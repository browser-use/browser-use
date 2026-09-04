"""Regression tests for <select> option serialization in the DOM serializer.

`_extract_select_options` builds `first_options` as up to 4 option labels *plus* a
trailing "... N more options..." indicator when a select has more than 4 options.
`DOMTreeSerializer.serialize_tree` used to slice that list to 4 entries, which silently
dropped the indicator — the LLM was told `count=N` but shown only 4 option labels with
no signal that more options existed. These tests pin the intended behaviour.
"""

from browser_use.dom.serializer.serializer import DOMTreeSerializer
from browser_use.dom.views import EnhancedDOMTreeNode, NodeType, SimplifiedNode


def _make_select_node(first_options: list[str], options_count: int) -> SimplifiedNode:
	"""Build a minimal interactive <select> node carrying compound-component info."""
	select = EnhancedDOMTreeNode(
		node_id=1,
		backend_node_id=42,
		node_type=NodeType.ELEMENT_NODE,
		node_name='SELECT',
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
		children_nodes=None,
		ax_node=None,
		snapshot_node=None,
	)
	select._compound_children = [
		{
			'name': 'Choose a fruit',
			'role': 'combobox',
			'valuemin': None,
			'valuemax': None,
			'valuenow': None,
			'options_count': options_count,
			'first_options': first_options,
			'format_hint': None,
		}
	]
	return SimplifiedNode(original_node=select, children=[], should_display=True, is_interactive=True)


def test_more_options_indicator_is_preserved():
	"""A select with more than 4 options must keep the '... N more options...' indicator."""
	node = _make_select_node(
		first_options=['Apple', 'Banana', 'Cherry', 'Date', '... 2 more options...'],
		options_count=6,
	)

	out = DOMTreeSerializer.serialize_tree(node, ['id'])

	assert 'count=6' in out
	# All four visible labels are present...
	for label in ('Apple', 'Banana', 'Cherry', 'Date'):
		assert label in out
	# ...and crucially the "more options" indicator is not dropped.
	assert '... 2 more options...' in out


def test_all_options_shown_when_four_or_fewer():
	"""A select with <= 4 options renders every label and adds no indicator."""
	node = _make_select_node(
		first_options=['Yes', 'No', 'Maybe'],
		options_count=3,
	)

	out = DOMTreeSerializer.serialize_tree(node, ['id'])

	assert 'options=Yes|No|Maybe' in out
	assert 'more options' not in out
