"""Tests for HTMLSerializer preserving visible code elements with ordinary IDs."""

import pytest

from browser_use.dom.markdown_extractor import convert_html_to_markdown
from browser_use.dom.serializer.html_serializer import HTMLSerializer
from browser_use.dom.views import EnhancedDOMTreeNode, NodeType


def make_node(
	node_type: NodeType,
	node_name: str,
	*,
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
		children_nodes=children,
		ax_node=None,
		snapshot_node=None,
	)

	for child in children or []:
		child.parent_node = node

	return node


@pytest.mark.parametrize(
	'element_id',
	[
		'user-data',
		'workflow-state',
	],
)
def test_visible_code_with_ordinary_id_is_preserved(element_id):
	"""Visible code elements with ordinary IDs containing 'data' or 'state' should not be dropped."""
	text = make_node(NodeType.TEXT_NODE, '#text', node_value='visible code content')
	code = make_node(
		NodeType.ELEMENT_NODE,
		'CODE',
		attributes={
			'id': element_id,
			'style': 'display: inline',
		},
		children=[text],
	)
	document = make_node(NodeType.DOCUMENT_NODE, '#document', children=[code])

	html = HTMLSerializer().serialize(document)
	markdown, _, _ = convert_html_to_markdown(html)

	assert 'visible code content' in html
	assert 'visible code content' in markdown


def test_visible_code_with_unrelated_id_is_preserved():
	"""Visible code elements with unrelated IDs should still be preserved (regression guard)."""
	text = make_node(NodeType.TEXT_NODE, '#text', node_value='visible code content')
	code = make_node(
		NodeType.ELEMENT_NODE,
		'CODE',
		attributes={
			'id': 'snippet-1',
			'style': 'display: inline',
		},
		children=[text],
	)
	document = make_node(NodeType.DOCUMENT_NODE, '#document', children=[code])

	html = HTMLSerializer().serialize(document)
	markdown, _, _ = convert_html_to_markdown(html)

	assert 'visible code content' in html
	assert 'visible code content' in markdown


def test_hidden_code_with_display_none_is_still_dropped():
	"""Code elements with display:none should still be dropped regardless of ID."""
	text = make_node(NodeType.TEXT_NODE, '#text', node_value='hidden content')
	code = make_node(
		NodeType.ELEMENT_NODE,
		'CODE',
		attributes={
			'id': 'snippet-1',
			'style': 'display: none',
		},
		children=[text],
	)
	document = make_node(NodeType.DOCUMENT_NODE, '#document', children=[code])

	html = HTMLSerializer().serialize(document)

	assert 'hidden content' not in html


def test_bpr_guid_code_is_still_dropped():
	"""Code elements with bpr-guid IDs should still be dropped (LinkedIn pattern)."""
	text = make_node(NodeType.TEXT_NODE, '#text', node_value='linkedin state')
	code = make_node(
		NodeType.ELEMENT_NODE,
		'CODE',
		attributes={
			'id': 'bpr-guid-12345',
		},
		children=[text],
	)
	document = make_node(NodeType.DOCUMENT_NODE, '#document', children=[code])

	html = HTMLSerializer().serialize(document)

	assert 'linkedin state' not in html
