import pytest

from browser_use.dom.serializer.paint_order import PaintOrderRemover, Rect
from browser_use.dom.views import DOMRect, EnhancedDOMTreeNode, EnhancedSnapshotNode, NodeType, SimplifiedNode


class TestRectValidation:
	def test_valid_rect_initialization_and_area(self):
		r = Rect(x1=10.0, y1=20.0, x2=50.0, y2=70.0)
		assert r.x1 == 10.0
		assert r.y1 == 20.0
		assert r.x2 == 50.0
		assert r.y2 == 70.0
		assert r.area() == 2000.0

	def test_zero_dimension_rect_is_valid(self):
		# Point or line rect (x1 == x2 or y1 == y2) is valid axis-aligned boundary
		r = Rect(x1=10.0, y1=20.0, x2=10.0, y2=20.0)
		assert r.area() == 0.0

	def test_inverted_x_raises_value_error(self):
		with pytest.raises(ValueError, match=r'Invalid rectangle bounds: x1 \(100\.0\) <= x2 \(20\.0\)'):
			Rect(x1=100.0, y1=20.0, x2=20.0, y2=50.0)

	def test_inverted_y_raises_value_error(self):
		with pytest.raises(ValueError, match=r'Invalid rectangle bounds.*y1 \(80\.0\) <= y2 \(30\.0\)'):
			Rect(x1=10.0, y1=80.0, x2=50.0, y2=30.0)

	def test_both_inverted_raises_value_error(self):
		with pytest.raises(ValueError, match=r'Invalid rectangle bounds'):
			Rect(x1=100.0, y1=50.0, x2=20.0, y2=10.0)


def _make_snapshot_node(paint_order: int, bounds: DOMRect) -> EnhancedSnapshotNode:
	return EnhancedSnapshotNode(
		is_clickable=None,
		cursor_style=None,
		bounds=bounds,
		clientRects=None,
		scrollRects=None,
		computed_styles={'opacity': '1.0', 'background-color': 'rgb(255, 255, 255)'},
		paint_order=paint_order,
		stacking_contexts=None,
	)


def _make_tree_node(snapshot_node: EnhancedSnapshotNode | None) -> EnhancedDOMTreeNode:
	return EnhancedDOMTreeNode(
		node_id=1,
		backend_node_id=1,
		node_type=NodeType.ELEMENT_NODE,
		node_name='DIV',
		node_value='',
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


class TestPaintOrderNonPositiveBounds:
	def test_zero_and_negative_dimension_nodes_do_not_corrupt_occlusion(self):
		"""
		Nodes with zero width/height (or negative dimensions) should be safely skipped
		in paint order calculation without crashing or corrupting occlusion sets.
		"""
		# A zero-width element at paint_order 2
		zero_width_node = SimplifiedNode(
			original_node=_make_tree_node(_make_snapshot_node(paint_order=2, bounds=DOMRect(x=0, y=0, width=0, height=50))),
			children=[],
		)

		# A negative-dimension node (which would invert bounds) at paint_order 2
		negative_dim_node = SimplifiedNode(
			original_node=_make_tree_node(_make_snapshot_node(paint_order=2, bounds=DOMRect(x=10, y=10, width=-20, height=-10))),
			children=[],
		)

		# A normal node at paint_order 1 underneath them
		underneath_node = SimplifiedNode(
			original_node=_make_tree_node(_make_snapshot_node(paint_order=1, bounds=DOMRect(x=0, y=0, width=100, height=100))),
			children=[],
		)

		root = SimplifiedNode(
			original_node=_make_tree_node(None),
			children=[underneath_node, zero_width_node, negative_dim_node],
		)

		# Should execute cleanly without raising ValueError on inverted rect
		remover = PaintOrderRemover(root)
		remover.calculate_paint_order()

		# Underneath node must NOT be marked ignored because the zero/negative nodes have no surface area
		assert underneath_node.ignored_by_paint_order is False
