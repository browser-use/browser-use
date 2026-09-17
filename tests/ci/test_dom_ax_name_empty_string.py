"""Regression coverage for empty-string accessibility names (issue #5041).

An element can have an explicit empty accessible name (e.g. aria-label=""),
which is a distinct, valid state from having no accessibility node at all.
`if ax_node.name:` treats both states the same because "" is falsy in
Python, silently collapsing them to None. This corrupts DOM identity hashing
and element matching, since two elements with different (but both empty)
accessible-name states would otherwise hash identically to elements that
have no ax_node whatsoever.
"""

from browser_use.dom.views import (
	DOMInteractedElement,
	DOMRect,
	EnhancedAXNode,
	EnhancedDOMTreeNode,
	EnhancedSnapshotNode,
	NodeType,
)


def _node(*, ax_name: str | None, node_id: int = 1, backend_node_id: int = 1) -> EnhancedDOMTreeNode:
	return EnhancedDOMTreeNode(
		node_id=node_id,
		backend_node_id=backend_node_id,
		node_type=NodeType.ELEMENT_NODE,
		node_name='BUTTON',
		node_value='',
		attributes={},
		is_scrollable=False,
		is_visible=True,
		absolute_position=DOMRect(x=0, y=0, width=100, height=30),
		target_id='target-1',
		frame_id=None,
		session_id='session-1',
		content_document=None,
		shadow_root_type=None,
		shadow_roots=None,
		parent_node=None,
		children_nodes=[],
		ax_node=EnhancedAXNode(
			ax_node_id='1',
			ignored=False,
			role='button',
			name=ax_name,
			description=None,
			properties=None,
			child_ids=None,
		)
		if ax_name is not None
		else None,
		snapshot_node=EnhancedSnapshotNode(
			is_clickable=None,
			cursor_style='auto',
			bounds=DOMRect(x=0, y=0, width=100, height=30),
			clientRects=DOMRect(x=0, y=0, width=100, height=30),
			scrollRects=None,
			computed_styles={},
			paint_order=None,
			stacking_contexts=None,
		),
	)


def test_load_from_enhanced_dom_tree_preserves_explicit_empty_ax_name():
	node_with_empty_name = _node(ax_name='')
	node_with_no_ax_node = _node(ax_name=None)

	interacted_empty = DOMInteractedElement.load_from_enhanced_dom_tree(node_with_empty_name)
	interacted_none = DOMInteractedElement.load_from_enhanced_dom_tree(node_with_no_ax_node)

	assert interacted_empty.ax_name == '', 'explicit empty accessible name must be preserved, not collapsed to None'
	assert interacted_none.ax_name is None


def test_stable_hash_distinguishes_empty_ax_name_from_missing_ax_node():
	node_with_empty_name = _node(ax_name='')
	node_with_no_ax_node = _node(ax_name=None)

	assert node_with_empty_name.compute_stable_hash() != node_with_no_ax_node.compute_stable_hash()


def test_element_hash_distinguishes_empty_ax_name_from_missing_ax_node():
	node_with_empty_name = _node(ax_name='')
	node_with_no_ax_node = _node(ax_name=None)

	assert hash(node_with_empty_name) != hash(node_with_no_ax_node)
