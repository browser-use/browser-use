"""Regression tests for explicitly empty accessibility names (issue #5041)."""

from browser_use.dom.views import (
	DOMInteractedElement,
	EnhancedAXNode,
	EnhancedDOMTreeNode,
	EnhancedSnapshotNode,
	NodeType,
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


def _make_node(ax_node: EnhancedAXNode | None) -> EnhancedDOMTreeNode:
	return EnhancedDOMTreeNode(
		node_id=1,
		backend_node_id=1,
		node_type=NodeType.ELEMENT_NODE,
		node_name='BUTTON',
		node_value='',
		attributes={'id': 'btn'},
		is_scrollable=None,
		is_visible=None,
		absolute_position=None,
		target_id='test-target',
		frame_id=None,
		session_id=None,
		content_document=None,
		shadow_root_type=None,
		shadow_roots=None,
		parent_node=None,
		children_nodes=None,
		ax_node=ax_node,
		snapshot_node=EnhancedSnapshotNode(
			is_clickable=None,
			cursor_style=None,
			bounds=None,
			clientRects=None,
			scrollRects=None,
			computed_styles={},
			paint_order=None,
			stacking_contexts=None,
		),
	)


def test_load_from_enhanced_dom_tree_preserves_empty_ax_name() -> None:
	node = _make_node(_make_ax_node(''))
	element = DOMInteractedElement.load_from_enhanced_dom_tree(node)
	assert element.ax_name == ''


def test_load_from_enhanced_dom_tree_none_ax_name_stays_none() -> None:
	node = _make_node(_make_ax_node(None))
	element = DOMInteractedElement.load_from_enhanced_dom_tree(node)
	assert element.ax_name is None


def test_explicit_empty_ax_name_affects_stable_hash() -> None:
	with_name = _make_node(_make_ax_node(''))
	without_name = _make_node(_make_ax_node(None))

	assert with_name.compute_stable_hash() != without_name.compute_stable_hash()
