"""Regression test for the "... N more options..." indicator on <select> elements.

`DOMTreeSerializer._extract_select_options()` renders at most 4 option labels and,
when the select has more than 4 options, appends a trailing
`"... N more options..."` entry so the LLM knows the list is truncated.

`serialize_tree()` used to re-slice that list with `[:4]`, which cut off exactly
the indicator it was meant to preserve — the model saw `count=6` alongside four
labels and no signal that the remaining options existed.
"""

from browser_use.dom.serializer.serializer import DOMTreeSerializer
from browser_use.dom.views import EnhancedAXNode, EnhancedDOMTreeNode, NodeType, SimplifiedNode


def _make_node(
	node_id: int,
	node_name: str,
	node_type: NodeType = NodeType.ELEMENT_NODE,
	node_value: str = '',
	attributes: dict[str, str] | None = None,
	ax_node: EnhancedAXNode | None = None,
) -> EnhancedDOMTreeNode:
	return EnhancedDOMTreeNode(
		node_id=node_id,
		backend_node_id=node_id,
		node_type=node_type,
		node_name=node_name,
		node_value=node_value,
		attributes=attributes or {},
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
		ax_node=ax_node,
		snapshot_node=None,
	)


def _make_select(option_labels: list[str]) -> EnhancedDOMTreeNode:
	"""Build a <select> whose AX node advertises children, as a real select would."""
	select = _make_node(
		node_id=1,
		node_name='SELECT',
		attributes={'id': 'fruit'},
		ax_node=EnhancedAXNode(
			ax_node_id='ax-1',
			ignored=False,
			role='combobox',
			name='fruit',
			description=None,
			properties=None,
			child_ids=['ax-2'],
		),
	)

	children = []
	for offset, label in enumerate(option_labels):
		option = _make_node(node_id=10 + offset * 2, node_name='OPTION', attributes={'value': label.lower()})
		text = _make_node(node_id=11 + offset * 2, node_name='#text', node_type=NodeType.TEXT_NODE, node_value=label)
		text.parent_node = option
		option.children_nodes = [text]
		option.parent_node = select
		children.append(option)

	select.children_nodes = children
	return select


def _serialize_select(option_labels: list[str]) -> str:
	select = _make_select(option_labels)
	# A <select> always lands in the selector map, so it is serialized as an
	# interactive element with a selector index.
	simplified = SimplifiedNode(original_node=select, children=[], is_interactive=True, selector_index=5)

	serializer = DOMTreeSerializer(root_node=select)
	serializer._add_compound_components(simplified, select)

	return DOMTreeSerializer.serialize_tree(simplified, [])


class TestSelectOptionsSerialization:
	def test_more_options_indicator_survives_serialization(self):
		"""A select with 6 options must tell the LLM that 2 options are not shown."""
		output = _serialize_select(['Apple', 'Banana', 'Cherry', 'Date', 'Elderberry', 'Fig'])

		assert 'count=6' in output
		assert 'options=Apple|Banana|Cherry|Date|... 2 more options...' in output

	def test_all_options_shown_when_not_truncated(self):
		"""Four or fewer options are listed in full, with no truncation indicator."""
		output = _serialize_select(['Apple', 'Banana', 'Cherry', 'Date'])

		assert 'count=4' in output
		assert 'options=Apple|Banana|Cherry|Date' in output
		assert 'more options' not in output
