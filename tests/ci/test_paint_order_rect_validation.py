"""Regression test: `Rect` must reject inverted bounds and collapsed nodes must not join occlusion math.

`__post_init__` returned `False`, which dataclasses ignore, so `Rect(x1=100, y1=50, x2=20, y2=10)` silently
produced negative-area rectangles. `calculate_paint_order` also passed zero-width/zero-height bounds into
`Rect`, so collapsed nodes could flag each other as occluded.
"""

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


@pytest.mark.parametrize(
	'corners',
	[
		(100.0, 50.0, 20.0, 10.0),
		(100.0, 10.0, 20.0, 50.0),
		(0.0, 50.0, 10.0, 10.0),
		(0.0, 10.0, 0.0, 5.0),
	],
	ids=['both-axes', 'x-only', 'y-only', 'y-only-flush-x'],
)
def test_inverted_rect_raises(corners: tuple[float, float, float, float]) -> None:
	with pytest.raises(ValueError, match='Invalid rect'):
		Rect(*corners)


def test_valid_rect_area_is_unchanged() -> None:
	rect = Rect(0.0, 0.0, 10.0, 5.0)

	assert rect.area() == 50.0


@pytest.mark.parametrize(
	'collapsed_bounds',
	[DOMRect(x=10, y=0, width=0, height=20), DOMRect(x=10, y=0, width=20, height=0)],
	ids=['zero-width', 'zero-height'],
)
def test_collapsed_nodes_do_not_occlude_each_other(collapsed_bounds: DOMRect) -> None:
	lower = SimplifiedNode(
		original_node=_make_node(NodeType.TEXT_NODE, 'LOWER', _make_snapshot(paint_order=1, bounds=collapsed_bounds)),
		children=[],
	)
	upper = SimplifiedNode(
		original_node=_make_node(NodeType.TEXT_NODE, 'UPPER', _make_snapshot(paint_order=2, bounds=collapsed_bounds)),
		children=[],
	)
	wrapper = SimplifiedNode(
		original_node=_make_node(NodeType.ELEMENT_NODE, '', None),
		children=[lower, upper],
		should_display=False,
	)

	PaintOrderRemover(wrapper).calculate_paint_order()

	assert lower.ignored_by_paint_order is False
	assert upper.ignored_by_paint_order is False


def test_collapsed_node_covered_by_a_real_element_is_still_marked_ignored() -> None:
	"""Keeping collapsed rects out of the union must not disable occlusion detection for them.

	A zero-area node under a real element is genuinely invisible, so it still has to be reported as
	`ignored_by_paint_order`; only its own rect has to stay out of the union.
	"""
	covered = SimplifiedNode(
		original_node=_make_node(
			NodeType.TEXT_NODE, 'COVERED', _make_snapshot(paint_order=1, bounds=DOMRect(x=10, y=5, width=0, height=20))
		),
		children=[],
	)
	on_top = SimplifiedNode(
		original_node=_make_node(
			NodeType.ELEMENT_NODE, 'ON_TOP', _make_snapshot(paint_order=2, bounds=DOMRect(x=0, y=0, width=100, height=100))
		),
		children=[],
	)
	wrapper = SimplifiedNode(
		original_node=_make_node(NodeType.ELEMENT_NODE, '', None),
		children=[covered, on_top],
		should_display=False,
	)

	PaintOrderRemover(wrapper).calculate_paint_order()

	assert covered.ignored_by_paint_order is True
	assert on_top.ignored_by_paint_order is False
