"""Regression test for DOMTreeSerializer leaking paint-order-occluded text.

PaintOrderRemover.calculate_paint_order() correctly computes which nodes are
fully covered by another element painted on top of them (e.g. content
underneath an open modal/dropdown) and marks them `ignored_by_paint_order`.
DOMTreeSerializer.serialize_tree() must respect that flag for TEXT_NODEs, or
covered text still ends up in the DOM string sent to the LLM every step.
"""

import pytest

from browser_use.dom.serializer.paint_order import PaintOrderRemover, Rect
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
		assert top_simplified.ignored_by_paint_order is False

		output = DOMTreeSerializer.serialize_tree(wrapper, [])

		assert 'TOP LAYER TEXT' in output
		assert 'HIDDEN BEHIND MODAL' not in output


class TestRectValidation:
	"""`Rect.__post_init__` used to `return False`, which `@dataclass` discards, so
	inverted corners were accepted and every area/intersection/occlusion computation
	downstream ran on a negative-area rectangle."""

	def test_rejects_inverted_horizontal_bounds(self):
		with pytest.raises(ValueError):
			Rect(x1=100.0, y1=10.0, x2=20.0, y2=10.0)

	def test_rejects_inverted_vertical_bounds(self):
		with pytest.raises(ValueError):
			Rect(x1=10.0, y1=50.0, x2=10.0, y2=5.0)

	def test_rejects_bounds_inverted_on_both_axes(self):
		# The exact reproducer from the issue report.
		with pytest.raises(ValueError):
			Rect(x1=100.0, y1=50.0, x2=20.0, y2=10.0)

	def test_keeps_zero_area_rectangles_valid(self):
		"""Closed rectangles may legitimately have zero width/height (a point or a
		line); only reversed corners are invalid."""
		point = Rect(x1=5.0, y1=5.0, x2=5.0, y2=5.0)
		line = Rect(x1=0.0, y1=7.0, x2=100.0, y2=7.0)

		assert point.area() == 0.0
		assert line.area() == 0.0


class TestPaintOrderNonPositiveBounds:
	"""Nodes whose snapshot reports zero or negative width/height must be filtered out
	before `Rect(...)`, otherwise the validated constructor raises for the negative case
	and collapsed wrappers still enter the occlusion union for the zero case."""

	def _remover(self, nodes):
		wrapper = SimplifiedNode(
			original_node=_make_node(NodeType.ELEMENT_NODE, '', None),
			children=[SimplifiedNode(original_node=n, children=[]) for n in nodes],
			should_display=False,
		)
		return wrapper, [child for child in wrapper.children]

	def test_collapsed_zero_size_node_is_ignored_as_an_occluder(self):
		hidden = _make_node(
			NodeType.TEXT_NODE,
			'UNDER A COLLAPSED WRAPPER',
			_make_snapshot(paint_order=1, bounds=DOMRect(x=0, y=0, width=100, height=20)),
		)
		collapsed = _make_node(
			NodeType.ELEMENT_NODE, '', _make_snapshot(paint_order=5, bounds=DOMRect(x=0, y=0, width=0, height=0))
		)

		wrapper, (hidden_simplified, _collapsed_simplified) = self._remover([hidden, collapsed])
		PaintOrderRemover(wrapper).calculate_paint_order()

		assert hidden_simplified.ignored_by_paint_order is False

	def test_inverted_bounds_do_not_raise(self):
		"""Negative width/height gives x2 < x1; the node must be skipped rather than
		handed to the now-strict `Rect` constructor."""
		node = _make_node(
			NodeType.ELEMENT_NODE, '', _make_snapshot(paint_order=2, bounds=DOMRect(x=100.0, y=50.0, width=-80.0, height=-40.0))
		)
		normal = _make_node(
			NodeType.TEXT_NODE, 'STILL VISIBLE', _make_snapshot(paint_order=3, bounds=DOMRect(x=0, y=0, width=10, height=10))
		)

		wrapper, (_node_simplified, normal_simplified) = self._remover([node, normal])

		PaintOrderRemover(wrapper).calculate_paint_order()  # must not raise ValueError

		assert normal_simplified.ignored_by_paint_order is False
