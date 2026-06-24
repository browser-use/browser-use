from browser_use.dom.views import DOMInteractedElement, EnhancedAXNode, EnhancedDOMTreeNode, NodeType


def _make_enhanced_dom_node(*, ax_name: str | None) -> EnhancedDOMTreeNode:
	ax_node = None
	if ax_name is not None:
		ax_node = EnhancedAXNode(
			ax_node_id='ax-1',
			ignored=False,
			role='button',
			name=ax_name,
			description=None,
			properties=None,
			child_ids=None,
		)

	return EnhancedDOMTreeNode(
		node_id=1,
		backend_node_id=1,
		node_type=NodeType.ELEMENT_NODE,
		node_name='BUTTON',
		node_value='',
		attributes={'aria-label': ax_name or ''},
		is_scrollable=False,
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


def test_load_from_enhanced_dom_tree_preserves_empty_ax_name():
	element = DOMInteractedElement.load_from_enhanced_dom_tree(_make_enhanced_dom_node(ax_name=''))

	assert element.ax_name == ''


def test_load_from_enhanced_dom_tree_keeps_missing_ax_name_none():
	element = DOMInteractedElement.load_from_enhanced_dom_tree(_make_enhanced_dom_node(ax_name=None))

	assert element.ax_name is None
