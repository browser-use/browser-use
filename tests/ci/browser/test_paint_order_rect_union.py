"""Focused coverage for the float-quad RectUnionPure and paint-order scoping.

Guards the #5159 allocation optimization (tuple-backed union with
contains_quad/add_quad) against behaviour drift: containment, partial overlap,
split coverage, degenerate rectangles, add-order independence, the Rect/quad
API parity, the safety cap, repeated invocation, and per-iframe-document
scoping of occlusion.
"""

from browser_use.dom.serializer.paint_order import PaintOrderRemover, Rect, RectUnionPure
from browser_use.dom.views import DOMRect, EnhancedDOMTreeNode, EnhancedSnapshotNode, NodeType, SimplifiedNode


# --------------------------------------------------------------------------- #
# RectUnionPure                                                               #
# --------------------------------------------------------------------------- #
def test_empty_union_contains_nothing():
	u = RectUnionPure()
	assert u.contains_quad(0, 0, 10, 10) is False
	assert u.contains(Rect(0, 0, 10, 10)) is False


def test_full_containment():
	u = RectUnionPure()
	assert u.add_quad(0, 0, 100, 100) is True
	assert u.contains_quad(10, 10, 40, 40) is True
	# an already-covered rectangle is not re-added
	assert u.add_quad(10, 10, 40, 40) is False


def test_partial_overlap_not_contained():
	u = RectUnionPure()
	u.add_quad(0, 0, 10, 10)
	# extends past the covered region on x -> not fully covered
	assert u.contains_quad(5, 5, 15, 8) is False


def test_split_coverage_from_two_disjoint_rects():
	u = RectUnionPure()
	u.add_quad(0, 0, 10, 10)
	u.add_quad(10, 0, 20, 10)  # adjacent, shares the x=10 edge
	# the spanning rectangle is covered by the union of the two halves
	assert u.contains_quad(0, 0, 20, 10) is True
	assert u.contains_quad(2, 2, 18, 8) is True


def test_degenerate_zero_area_rectangle():
	u = RectUnionPure()
	u.add_quad(0, 0, 10, 10)
	# a zero-width probe fully inside the covered area is contained
	assert u.contains_quad(5, 0, 5, 10) is True
	# adding a degenerate rectangle does not crash and reports growth honestly
	u2 = RectUnionPure()
	assert u2.add_quad(3, 3, 3, 8) is True


def test_add_order_independence():
	rects = [(0, 0, 10, 10), (5, 5, 15, 15), (12, 0, 20, 8), (0, 12, 8, 20)]
	probes = [
		(1, 1, 4, 4),
		(6, 6, 9, 9),
		(13, 1, 19, 7),
		(0, 5, 15, 10),  # covered only by combining the first two rectangles
		(0, 0, 20, 20),
	]
	a = RectUnionPure()
	for r in rects:
		a.add_quad(*r)
	b = RectUnionPure()
	for r in reversed(rects):
		b.add_quad(*r)
	assert [a.contains_quad(*p) for p in probes] == [b.contains_quad(*p) for p in probes]


def test_rect_api_matches_quad_api():
	u_rect = RectUnionPure()
	u_quad = RectUnionPure()
	seq = [(0, 0, 10, 10), (5, 5, 20, 20), (30, 30, 40, 40), (5, 5, 20, 20)]
	for x1, y1, x2, y2 in seq:
		assert u_rect.add(Rect(x1, y1, x2, y2)) == u_quad.add_quad(x1, y1, x2, y2)
		assert u_rect.contains(Rect(x1, y1, x2, y2)) == u_quad.contains_quad(x1, y1, x2, y2)


def test_max_rects_cap_stops_growth():
	u = RectUnionPure()
	# pre-fill to the cap with disjoint dummy rects, then confirm add is refused
	u._rects = [(float(i), 0.0, float(i) + 0.5, 1.0) for i in range(RectUnionPure._MAX_RECTS)]
	assert len(u._rects) == RectUnionPure._MAX_RECTS
	assert u.add_quad(10_000, 10_000, 10_010, 10_010) is False
	assert len(u._rects) == RectUnionPure._MAX_RECTS


# --------------------------------------------------------------------------- #
# PaintOrderRemover                                                           #
# --------------------------------------------------------------------------- #
def _enh(tag, *, session_id, frame_id=None, parent=None, paint_order=None, bg='rgb(255, 255, 255)'):
	bounds = DOMRect(x=0, y=0, width=100, height=30)
	return EnhancedDOMTreeNode(
		node_id=1,
		backend_node_id=1,
		node_type=NodeType.ELEMENT_NODE,
		node_name=tag.upper(),
		node_value='',
		attributes={},
		is_scrollable=False,
		is_visible=True,
		absolute_position=bounds,
		target_id=f'target-{session_id}',
		frame_id=frame_id,
		session_id=session_id,
		content_document=None,
		shadow_root_type=None,
		shadow_roots=None,
		parent_node=parent,
		children_nodes=[],
		ax_node=None,
		snapshot_node=EnhancedSnapshotNode(
			is_clickable=None,
			cursor_style='auto',
			bounds=bounds,
			clientRects=bounds,
			scrollRects=None,
			computed_styles={'display': 'block', 'visibility': 'visible', 'opacity': '1', 'background-color': bg},
			paint_order=paint_order,
			stacking_contexts=None,
		),
	)


def _two_input_tree(card_parent, cvv_parent):
	lower = _enh('input', session_id='wrapper', parent=card_parent, paint_order=1)
	upper = _enh('input', session_id='wrapper', parent=cvv_parent, paint_order=2)
	root = SimplifiedNode(
		original_node=_enh('html', session_id='main'),
		children=[SimplifiedNode(original_node=lower, children=[]), SimplifiedNode(original_node=upper, children=[])],
	)
	return root


def test_scoping_isolated_between_iframe_documents():
	card = _enh('iframe', session_id='wrapper', frame_id='card')
	cvv = _enh('iframe', session_id='wrapper', frame_id='cvv')
	root = _two_input_tree(card, cvv)
	PaintOrderRemover(root).calculate_paint_order()
	# different documents -> the higher-paint-order rect cannot occlude the other
	assert root.children[0].ignored_by_paint_order is False
	assert root.children[1].ignored_by_paint_order is False


def test_occlusion_within_single_document():
	root = _two_input_tree(None, None)  # both live in the main document
	PaintOrderRemover(root).calculate_paint_order()
	assert root.children[0].ignored_by_paint_order is True  # lower, occluded
	assert root.children[1].ignored_by_paint_order is False  # upper blocker


def test_repeated_invocation_is_idempotent():
	root = _two_input_tree(None, None)
	PaintOrderRemover(root).calculate_paint_order()
	first = [c.ignored_by_paint_order for c in root.children]
	PaintOrderRemover(root).calculate_paint_order()
	second = [c.ignored_by_paint_order for c in root.children]
	assert first == second == [True, False]
