"""Regression tests for paint-order rectangle validation (#5987)."""

import pytest

from browser_use.dom.serializer.paint_order import PaintOrderRemover, Rect
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


def _make_node(snapshot_node: EnhancedSnapshotNode) -> EnhancedDOMTreeNode:
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


class TestRectValidation:
	def test_rect_rejects_inverted_x_bounds(self) -> None:
		with pytest.raises(ValueError):
			Rect(x1=100.0, y1=0.0, x2=20.0, y2=10.0)

	def test_rect_rejects_inverted_y_bounds(self) -> None:
		with pytest.raises(ValueError):
			Rect(x1=0.0, y1=50.0, x2=100.0, y2=10.0)

	def test_rect_allows_zero_width_and_height(self) -> None:
		# x1 == x2 (or y1 == y2) is degenerate but not inverted; allowed here.
		assert Rect(x1=10.0, y1=0.0, x2=10.0, y2=20.0).area() == 0.0
		assert Rect(x1=0.0, y1=10.0, x2=20.0, y2=10.0).area() == 0.0


class TestPaintOrderSkipsNonPositiveDimensions:
	@pytest.mark.parametrize(
		("width", "height"),
		[(0, 10), (10, 0), (-5, 10), (10, -5), (0, 0)],
		ids=["zero-width", "zero-height", "negative-width", "negative-height", "zero-both"],
	)
	def test_non_positive_dimension_node_does_not_enter_occlusion(self, width: float, height: float) -> None:
		"""A collapsed/negative-size element must be skipped, not fed to Rect."""
		node = _make_node(_make_snapshot(paint_order=1, bounds=DOMRect(x=0, y=0, width=width, height=height)))
		simplified = SimplifiedNode(original_node=node, children=[])
		wrapper = SimplifiedNode(
			original_node=_make_node(_make_snapshot(paint_order=2, bounds=DOMRect(x=0, y=0, width=100, height=100))),
			children=[simplified],
		)

		# Should not raise and must not mark the collapsed node as occluded.
		PaintOrderRemover(wrapper).calculate_paint_order()

		assert simplified.ignored_by_paint_order is False

