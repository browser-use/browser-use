"""Regression test: the visibility predicate must not mutate the node's stored bounds.

DomService.is_element_visible_according_to_all_parents() is a pure -> bool
predicate, but it used to bind current_bounds directly to the shared, mutable
node.snapshot_node.bounds (absolute page coordinates set at construction) and
then apply iframe/scroll offsets in place. On any scrolled or iframe page that
permanently corrupted the node's stored geometry, which downstream consumers
(paint-order occlusion, bbox containment) then read as wrong rectangles. The fix
computes on a DOMRect copy, mirroring the deliberate copy in
_construct_enhanced_node.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from browser_use.dom.service import DomService
from browser_use.dom.views import DOMRect, EnhancedDOMTreeNode, NodeType


def _snap(*, bounds=None, scroll_rects=None, client_rects=None, computed_styles=None):
	return SimpleNamespace(
		bounds=bounds,
		scrollRects=scroll_rects,
		clientRects=client_rects,
		computed_styles=computed_styles or {},
	)


def test_visibility_check_does_not_mutate_bounds_on_scrolled_page():
	node_bounds = DOMRect(x=100.0, y=200.0, width=10.0, height=10.0)
	node = SimpleNamespace(snapshot_node=_snap(bounds=node_bounds))
	# Root HTML frame scrolled down 50px.
	html_frame = SimpleNamespace(
		node_type=NodeType.ELEMENT_NODE,
		node_name='HTML',
		snapshot_node=_snap(
			bounds=DOMRect(0.0, 0.0, 800.0, 600.0),
			scroll_rects=DOMRect(0.0, 50.0, 800.0, 2000.0),
			client_rects=DOMRect(0.0, 0.0, 800.0, 600.0),
		),
	)

	# node/html_frame are SimpleNamespace duck-typed stand-ins for EnhancedDOMTreeNode
	# (the predicate only reads .snapshot_node / .node_type / .node_name).
	visible = DomService.is_element_visible_according_to_all_parents(
		cast(EnhancedDOMTreeNode, node), cast(list[EnhancedDOMTreeNode], [html_frame])
	)

	assert visible is True
	# Before the fix the scroll offset was applied in place, leaving y at 150.
	assert (node_bounds.x, node_bounds.y) == (100.0, 200.0)
	assert node.snapshot_node.bounds is node_bounds  # same object, untouched


def test_visibility_check_does_not_mutate_bounds_inside_iframe():
	node_bounds = DOMRect(x=10.0, y=20.0, width=10.0, height=10.0)
	node = SimpleNamespace(snapshot_node=_snap(bounds=node_bounds))
	# Element nested in an iframe offset by (300, 400).
	iframe = SimpleNamespace(
		node_type=NodeType.ELEMENT_NODE,
		node_name='IFRAME',
		snapshot_node=_snap(bounds=DOMRect(300.0, 400.0, 200.0, 200.0)),
	)

	DomService.is_element_visible_according_to_all_parents(
		cast(EnhancedDOMTreeNode, node), cast(list[EnhancedDOMTreeNode], [iframe])
	)

	# Before the fix the iframe offset was added in place, leaving (310, 420).
	assert (node_bounds.x, node_bounds.y) == (10.0, 20.0)
