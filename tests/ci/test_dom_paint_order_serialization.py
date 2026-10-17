"""Regression test for DOMTreeSerializer leaking paint-order-occluded text.

PaintOrderRemover.calculate_paint_order() correctly computes which nodes are
fully covered by another element painted on top of them (e.g. content
underneath an open modal/dropdown) and marks them `ignored_by_paint_order`.
DOMTreeSerializer.serialize_tree() must respect that flag for TEXT_NODEs, or
covered text still ends up in the DOM string sent to the LLM every step.
"""

from browser_use.dom.serializer.paint_order import PaintOrderRemover
from browser_use.dom.serializer.serializer import DOMTreeSerializer
from browser_use.dom.views import DOMRect, EnhancedDOMTreeNode, EnhancedSnapshotNode, NodeType, SimplifiedNode


def _make_snapshot(paint_order: int, bounds: DOMRect) -> EnhancedSnapshotNode:
	return EnhancedSnapshotNode(
		is_clickable=None,
		cursor_style=None,
		bounds=bounds,
		clientRects=None,
		scrollRects=None,
		computed_styles={},
		paint_order=paint_order,
		stacking_contexts=None,
	)


def _make_node(node_type: NodeType, node_value: str, snapshot_node: EnhancedSnapshotNode | None) -> EnhancedDOMTreeNode:
	return EnhancedDOMTreeNode(
		node_id=1,
		backend_node_id=1,
		node_type=node_type,
		node_name='#text' if node_type == NodeType.TEXT_NODE else 'DIV',
		node_value=node_value,
		attributes={},
		is_scrollable=None,
		is_visible=True,
		absolute_position=None,
		target_id='test-target',
		frame_id=None,
		session_id=None,
		content_document=None,
		shadow_root_type=None,
		shadow_roots=None,
		parent_node=None,
		children_nodes=None,
		ax_node=None,
		snapshot_node=snapshot_node,
	)


class TestPaintOrderTextExclusion:
	def test_text_fully_covered_by_another_element_is_not_serialized(self):
		"""Two text nodes at identical bounds: the lower paint-order one is fully
		covered by the higher paint-order one and must be excluded from the
		LLM-facing DOM string, even though both are individually `is_visible`."""
		bounds = DOMRect(x=0, y=0, width=100, height=20)
		hidden_node = _make_node(NodeType.TEXT_NODE, 'HIDDEN BEHIND MODAL', _make_snapshot(paint_order=1, bounds=bounds))
		top_node = _make_node(NodeType.TEXT_NODE, 'TOP LAYER TEXT', _make_snapshot(paint_order=2, bounds=bounds))

		hidden_simplified = SimplifiedNode(original_node=hidden_node, children=[])
		top_simplified = SimplifiedNode(original_node=top_node, children=[])

		# should_display=False on the wrapper so serialize_tree skips the element
		# line itself and just recurses straight into the two text-node children.
		wrapper = SimplifiedNode(
			original_node=_make_node(NodeType.ELEMENT_NODE, '', None),
			children=[hidden_simplified, top_simplified],
			should_display=False,
		)

		PaintOrderRemover(wrapper).calculate_paint_order()

		# Sanity check: paint-order calculation itself flagged the covered node.
		assert hidden_simplified.ignored_by_paint_order is True
		output = DOMTreeSerializer.serialize_tree(wrapper, [])

		assert 'TOP LAYER TEXT' in output
		assert 'HIDDEN BEHIND MODAL' not in output

	def test_rect_inverted_bounds_raises_value_error(self):
		"""Rect must raise ValueError when inverted coordinates (x1 > x2 or y1 > y2) are given."""
		import pytest

		from browser_use.dom.serializer.paint_order import Rect

		with pytest.raises(ValueError, match='Invalid rectangle bounds'):
			Rect(x1=100.0, y1=50.0, x2=20.0, y2=10.0)

		with pytest.raises(ValueError, match='Invalid rectangle bounds'):
			Rect(x1=10.0, y1=50.0, x2=20.0, y2=40.0)

		# Valid bounds should succeed
		valid_rect = Rect(x1=0.0, y1=0.0, x2=10.0, y2=10.0)
		assert valid_rect.area() == 100.0

	def test_calculate_paint_order_skips_zero_and_negative_dimensions(self):
		"""Nodes with width <= 0 or height <= 0 should be skipped from occlusion calculations."""
		zero_width = _make_node(NodeType.TEXT_NODE, 'ZERO WIDTH', _make_snapshot(paint_order=1, bounds=DOMRect(x=0, y=0, width=0, height=20)))
		zero_height = _make_node(NodeType.TEXT_NODE, 'ZERO HEIGHT', _make_snapshot(paint_order=1, bounds=DOMRect(x=0, y=0, width=20, height=0)))

		zero_w_simplified = SimplifiedNode(original_node=zero_width, children=[])
		zero_h_simplified = SimplifiedNode(original_node=zero_height, children=[])

		wrapper = SimplifiedNode(
			original_node=_make_node(NodeType.ELEMENT_NODE, '', None),
			children=[zero_w_simplified, zero_h_simplified],
			should_display=False,
		)

		PaintOrderRemover(wrapper).calculate_paint_order()
		assert zero_w_simplified.ignored_by_paint_order is False
		assert zero_h_simplified.ignored_by_paint_order is False

