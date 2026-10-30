import pytest

from browser_use.dom.serializer.serializer import DOMTreeSerializer
from browser_use.dom.views import DOMRect, EnhancedAXNode, EnhancedDOMTreeNode, EnhancedSnapshotNode, NodeType


def _make_node(node_id: int, tag: str, children: list[EnhancedDOMTreeNode] | None = None) -> EnhancedDOMTreeNode:
	return EnhancedDOMTreeNode(
		node_id=node_id,
		backend_node_id=node_id,
		node_type=NodeType.ELEMENT_NODE,
		node_name=tag.upper(),
		node_value='',
		attributes={},
		is_scrollable=None,
		is_visible=True,
		absolute_position=None,
		target_id='test-target',
		frame_id=None,
		session_id=None,
		content_document=None,
		shadow_root_type=None,
		shadow_roots=None,
		parent_node=None,
		children_nodes=children,
		ax_node=None,
		snapshot_node=None,
	)


@pytest.mark.parametrize(('option_count', 'grouped'), [(4, False), (5, False), (6, False), (6, True)])
def test_select_option_preview_preserves_omission_hint(option_count: int, grouped: bool):
	"""Keep the bounded option preview and its omission count in the LLM-facing DOM."""
	labels = ['Apple', 'Banana', 'Cherry', 'Date', 'Elderberry', 'Fig'][:option_count]
	options = []
	for index, label in enumerate(labels, start=2):
		text = _make_node(index + 10, '#text')
		text.node_type = NodeType.TEXT_NODE
		text.node_value = label
		options.append(_make_node(index, 'option', [text]))

	children = [_make_node(20, 'optgroup', options)] if grouped else options
	select = _make_node(1, 'select', children)
	select.ax_node = EnhancedAXNode(
		ax_node_id='1', ignored=False, role='combobox', name='Fruit', description=None, properties=None, child_ids=['2']
	)
	select.snapshot_node = EnhancedSnapshotNode(
		is_clickable=True,
		cursor_style=None,
		bounds=DOMRect(x=0, y=0, width=100, height=20),
		clientRects=None,
		scrollRects=None,
		computed_styles={},
		paint_order=None,
		stacking_contexts=None,
	)
	state, _ = DOMTreeSerializer(select).serialize_accessible_elements()
	output = state.llm_representation()

	preview = 'Apple|Banana|Cherry|Date'
	if option_count > 4:
		preview += f'|... {option_count - 4} more options...'
	assert f'count={option_count},options={preview})' in output
	assert 'Elderberry' not in output
	assert 'Fig' not in output
	if option_count == 4:
		assert 'more options' not in output
