"""Unit tests for DOM view models that don't need a live browser.

Covers pure data transformations in browser_use/dom/views.py, notably
DOMInteractedElement.load_from_enhanced_dom_tree preserving explicitly
empty accessibility names (regression for #5271).
"""

from browser_use.dom.views import (
	DOMInteractedElement,
	EnhancedAXNode,
	EnhancedDOMTreeNode,
	NodeType,
)


def _make_tree_node(ax_node: EnhancedAXNode | None) -> EnhancedDOMTreeNode:
	"""Build a minimal EnhancedDOMTreeNode with only the fields the loader touches."""
	return EnhancedDOMTreeNode(
		node_id=1,
		backend_node_id=100,
		node_type=NodeType.ELEMENT_NODE,
		node_name='button',
		node_value='',
		attributes={'aria-label': ''},
		is_scrollable=None,
		is_visible=True,
		absolute_position=None,
		target_id='target-1',
		frame_id='frame-1',
		session_id='session-1',
		content_document=None,
		shadow_root_type=None,
		shadow_roots=None,
		parent_node=None,
		children_nodes=None,
		ax_node=ax_node,
		snapshot_node=None,
	)


def _make_ax_node(name: str | None) -> EnhancedAXNode:
	return EnhancedAXNode(
		ax_node_id='ax-1',
		ignored=False,
		role='button',
		name=name,
		description=None,
		properties=None,
		child_ids=None,
	)


def test_load_preserves_explicitly_empty_ax_name():
	"""An explicitly empty accessibility name ("") must survive the round-trip.

	Regression for #5271: the old truthiness check collapsed "" to None,
	conflating "attribute missing" with "attribute intentionally empty".
	"""
	node = _make_tree_node(ax_node=_make_ax_node(name=''))
	interacted = DOMInteractedElement.load_from_enhanced_dom_tree(node)

	assert interacted.ax_name == ''


def test_load_keeps_none_when_ax_name_missing():
	"""When the AX node has no name attribute, ax_name stays None."""
	node = _make_tree_node(ax_node=_make_ax_node(name=None))
	interacted = DOMInteractedElement.load_from_enhanced_dom_tree(node)

	assert interacted.ax_name is None


def test_load_keeps_real_ax_name():
	"""A populated accessibility name is preserved."""
	node = _make_tree_node(ax_node=_make_ax_node(name='Submit order'))
	interacted = DOMInteractedElement.load_from_enhanced_dom_tree(node)

	assert interacted.ax_name == 'Submit order'


def test_load_without_ax_node():
	"""No AX node at all -> ax_name is None."""
	node = _make_tree_node(ax_node=None)
	interacted = DOMInteractedElement.load_from_enhanced_dom_tree(node)

	assert interacted.ax_name is None
