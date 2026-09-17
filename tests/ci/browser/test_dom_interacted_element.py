from browser_use.dom.views import DOMInteractedElement, EnhancedAXNode, EnhancedDOMTreeNode, NodeType


def test_load_from_enhanced_dom_tree_preserves_empty_ax_name():
	# Setup node with explicit empty string ax_name
	ax_node = EnhancedAXNode(
		ax_node_id='1',
		ignored=False,
		role='button',
		name='',  # explicitly empty string
		description=None,
		properties=None,
		child_ids=None,
	)

	enhanced_node = EnhancedDOMTreeNode(
		node_id=1,
		backend_node_id=1,
		node_type=NodeType.ELEMENT_NODE,
		node_name='BUTTON',
		node_value='',
		attributes={},
		is_scrollable=False,
		is_visible=True,
		absolute_position=None,
		target_id='target1',
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

	interacted_element = DOMInteractedElement.load_from_enhanced_dom_tree(enhanced_node)

	# Assert ax_name is preserved as empty string, not None
	assert interacted_element.ax_name == ''


def test_load_from_enhanced_dom_tree_handles_none_ax_name():
	# Setup node with None ax_name
	ax_node = EnhancedAXNode(
		ax_node_id='1', ignored=False, role='button', name=None, description=None, properties=None, child_ids=None
	)

	enhanced_node = EnhancedDOMTreeNode(
		node_id=1,
		backend_node_id=1,
		node_type=NodeType.ELEMENT_NODE,
		node_name='BUTTON',
		node_value='',
		attributes={},
		is_scrollable=False,
		is_visible=True,
		absolute_position=None,
		target_id='target1',
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

	interacted_element = DOMInteractedElement.load_from_enhanced_dom_tree(enhanced_node)

	# Assert ax_name is None
	assert interacted_element.ax_name is None
