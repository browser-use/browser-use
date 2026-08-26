"""Regression coverage for select option metadata serialization."""

from browser_use.dom.serializer.serializer import DOMTreeSerializer
from browser_use.dom.views import EnhancedDOMTreeNode, NodeType


def _node(
	node_name: str,
	*,
	node_type: NodeType = NodeType.ELEMENT_NODE,
	node_value: str = '',
	attributes: dict[str, str] | None = None,
	children: list[EnhancedDOMTreeNode] | None = None,
) -> EnhancedDOMTreeNode:
	node = EnhancedDOMTreeNode(
		node_id=1,
		backend_node_id=1,
		node_type=node_type,
		node_name=node_name,
		node_value=node_value,
		attributes=attributes or {},
		is_scrollable=False,
		is_visible=True,
		absolute_position=None,
		target_id='target',
		frame_id=None,
		session_id=None,
		content_document=None,
		shadow_root_type=None,
		shadow_roots=None,
		parent_node=None,
		children_nodes=children or [],
		ax_node=None,
		snapshot_node=None,
	)
	for child in node.children:
		child.parent_node = node
	return node


def _option(text: str, value: str | None = None) -> EnhancedDOMTreeNode:
	attributes = {} if value is None else {'value': value}
	return _node(
		'OPTION',
		attributes=attributes,
		children=[_node('#text', node_type=NodeType.TEXT_NODE, node_value=text)],
	)


def test_explicit_empty_placeholder_does_not_hide_numeric_option_format() -> None:
	select = _node('SELECT', children=[_option('Choose a quantity', ''), _option('One', '1'), _option('Two', '2')])

	options = DOMTreeSerializer(select)._extract_select_options(select)

	assert options is not None
	assert options['format_hint'] == 'numeric'


def test_multiple_explicit_empty_values_do_not_infer_a_format() -> None:
	select = _node('SELECT', children=[_option('Choose one', ''), _option('Not applicable', '')])

	options = DOMTreeSerializer(select)._extract_select_options(select)

	assert options is not None
	assert options['format_hint'] is None


def test_missing_value_attributes_still_fall_back_to_option_text() -> None:
	select = _node('SELECT', children=[_option('1'), _option('2')])

	options = DOMTreeSerializer(select)._extract_select_options(select)

	assert options is not None
	assert options['format_hint'] == 'numeric'
