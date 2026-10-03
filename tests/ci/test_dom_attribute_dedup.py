"""Attribute de-duplication must not delete an attribute because it collided with itself."""

from browser_use.dom.serializer.serializer import DOMTreeSerializer
from browser_use.dom.views import DEFAULT_INCLUDE_ATTRIBUTES, EnhancedDOMTreeNode, NodeType


def _node(attributes: dict[str, str]) -> EnhancedDOMTreeNode:
	return EnhancedDOMTreeNode(
		node_id=1,
		backend_node_id=1,
		node_type=NodeType.ELEMENT_NODE,
		node_name='MY-TOGGLE',
		node_value='',
		attributes=attributes,
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
		ax_node=None,
		snapshot_node=None,
	)


def test_default_include_attributes_has_no_duplicates():
	assert len(DEFAULT_INCLUDE_ATTRIBUTES) == len(set(DEFAULT_INCLUDE_ATTRIBUTES))


def test_repeated_include_attribute_keeps_the_attribute():
	node = _node({'name': 'newsletter', 'checked': 'checked'})
	attrs = DOMTreeSerializer._build_attributes_string(node, ['name', 'checked', 'checked'], '')
	assert attrs == 'name=newsletter checked=checked'


def test_distinct_attributes_with_the_same_value_are_still_deduplicated():
	node = _node({'id': 'newsletter-optin', 'name': 'newsletter-optin'})
	attrs = DOMTreeSerializer._build_attributes_string(node, ['id', 'name'], '')
	assert attrs == 'id=newsletter-optin'
