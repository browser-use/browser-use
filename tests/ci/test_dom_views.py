from browser_use.dom.views import DOMInteractedElement, EnhancedAXNode, EnhancedDOMTreeNode, NodeType


def _make_node(ax_name: str | None) -> EnhancedDOMTreeNode:
	ax_node = (
		EnhancedAXNode(
			ax_node_id='ax-1',
			ignored=False,
			role='button',
			name=ax_name,
			description=None,
			properties=None,
			child_ids=None,
		)
		if ax_name is not None
		else None
	)

	return EnhancedDOMTreeNode(
		node_id=1,
		backend_node_id=1,
		node_type=NodeType.ELEMENT_NODE,
		node_name='BUTTON',
		node_value='',
		attributes={'id': 'empty-name-button'},
		is_scrollable=None,
		is_visible=True,
		absolute_position=None,
		target_id='target-1',
		frame_id=None,
		session_id=None,
		content_document=None,
		shadow_root_type=None,
		shadow_roots=None,
		parent_node=None,
		children_nodes=None,
		ax_node=ax_node,
		snapshot_node=None,
	)


def test_empty_accessibility_name_is_preserved() -> None:
	node = _make_node('')

	interacted = DOMInteractedElement.load_from_enhanced_dom_tree(node)

	assert interacted.ax_name == ''


def test_empty_accessibility_name_affects_hashes() -> None:
	node_without_ax_name = _make_node(None)
	node_with_empty_ax_name = _make_node('')

	assert hash(node_with_empty_ax_name) != hash(node_without_ax_name)
	assert node_with_empty_ax_name.compute_stable_hash() != node_without_ax_name.compute_stable_hash()
