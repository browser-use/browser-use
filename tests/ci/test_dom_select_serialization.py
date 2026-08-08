"""Regression coverage for the select "N more options" indicator (issue #5195).

`_extract_select_options` builds `first_options` as up to 4 option labels
*plus* a trailing "... N more options..." indicator when there are more than
4 options, so the list can have 5 elements. The consumer in `serialize_tree`
used to re-slice that list to `[:4]`, which silently dropped the indicator
(the 5th element) whenever a <select> had more than 4 options.
"""

from browser_use.dom.serializer.serializer import DOMTreeSerializer
from browser_use.dom.views import DOMRect, EnhancedAXNode, EnhancedDOMTreeNode, EnhancedSnapshotNode, NodeType


def _node(
	tag_name: str,
	*,
	node_id: int,
	attributes: dict[str, str] | None = None,
	node_value: str = '',
	node_type: NodeType = NodeType.ELEMENT_NODE,
) -> EnhancedDOMTreeNode:
	return EnhancedDOMTreeNode(
		node_id=node_id,
		backend_node_id=node_id,
		node_type=node_type,
		node_name=tag_name.upper() if node_type == NodeType.ELEMENT_NODE else '#text',
		node_value=node_value,
		attributes=attributes or {},
		is_scrollable=False,
		is_visible=True,
		absolute_position=DOMRect(x=0, y=0, width=100, height=30),
		target_id='target-main',
		frame_id=None,
		session_id='main',
		content_document=None,
		shadow_root_type=None,
		shadow_roots=None,
		parent_node=None,
		children_nodes=[],
		ax_node=None,
		snapshot_node=EnhancedSnapshotNode(
			is_clickable=None,
			cursor_style='auto',
			bounds=DOMRect(x=0, y=0, width=100, height=30),
			clientRects=DOMRect(x=0, y=0, width=100, height=30),
			scrollRects=None,
			computed_styles={
				'display': 'block',
				'visibility': 'visible',
				'opacity': '1',
				'background-color': 'rgba(0, 0, 0, 0)',
			},
			paint_order=None,
			stacking_contexts=None,
		),
	)


def _option(node_id: int, label: str) -> EnhancedDOMTreeNode:
	option = _node('option', node_id=node_id, attributes={'value': label})
	text = _node(f'#text-{node_id}', node_id=1000 + node_id, node_value=label, node_type=NodeType.TEXT_NODE)
	option.children_nodes = [text]
	text.parent_node = option
	return option


def _select_with_options(labels: list[str]) -> EnhancedDOMTreeNode:
	root = _node('html', node_id=1)
	select = _node('select', node_id=2, attributes={'id': 'fruit'})
	select.ax_node = EnhancedAXNode(
		ax_node_id='2',
		ignored=False,
		role='combobox',
		name='fruit',
		description=None,
		properties=None,
		child_ids=['ax-2-1'],
	)
	options = [_option(10 + i, label) for i, label in enumerate(labels)]
	select.children_nodes = options
	for option in options:
		option.parent_node = select
	root.children_nodes = [select]
	select.parent_node = root
	return root


def test_select_serialization_keeps_more_options_indicator():
	root = _select_with_options(['Apple', 'Banana', 'Cherry', 'Date', 'Elderberry', 'Fig'])

	serialized_state = DOMTreeSerializer(
		root,
		enable_bbox_filtering=False,
		paint_order_filtering=False,
	).serialize_accessible_elements()[0]

	llm_repr = serialized_state.llm_representation()
	assert 'count=6' in llm_repr
	assert '... 2 more options...' in llm_repr, f'expected "more options" indicator in: {llm_repr}'
	assert 'Apple|Banana|Cherry|Date|... 2 more options...' in llm_repr


def test_select_serialization_omits_indicator_when_four_or_fewer_options():
	root = _select_with_options(['Apple', 'Banana', 'Cherry', 'Date'])

	serialized_state = DOMTreeSerializer(
		root,
		enable_bbox_filtering=False,
		paint_order_filtering=False,
	).serialize_accessible_elements()[0]

	llm_repr = serialized_state.llm_representation()
	assert 'count=4' in llm_repr
	assert 'more options' not in llm_repr
