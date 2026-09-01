"""Regression tests for enhanced DOM HTML serialization."""

import pytest

from browser_use.dom.markdown_extractor import convert_html_to_markdown
from browser_use.dom.serializer.html_serializer import HTMLSerializer
from browser_use.dom.views import EnhancedDOMTreeNode, NodeType


def _make_node(
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


def _serialize_code(element_id: str, *, style: str = 'display: inline') -> tuple[str, str]:
	text = _make_node(NodeType.TEXT_NODE, '#text', node_value='visible code content')
	code = _make_node(
		NodeType.ELEMENT_NODE,
		'CODE',
		attributes={'id': element_id, 'style': style},
		children=[text],
	)
	document = _make_node(NodeType.DOCUMENT_NODE, '#document', children=[code])

	html = HTMLSerializer().serialize(document)
	markdown, _, _ = convert_html_to_markdown(html)
	return html, markdown


@pytest.mark.parametrize('element_id', ['user-data', 'workflow-state', 'snippet-1'])
def test_visible_code_with_ordinary_id_is_preserved(element_id: str):
	html, markdown = _serialize_code(element_id)

	assert 'visible code content' in html
	assert 'visible code content' in markdown


def test_code_with_display_none_is_filtered():
	html, markdown = _serialize_code('user-data', style='display: none')

	assert html == ''
	assert markdown == ''


def test_linkedin_application_state_code_is_filtered():
	html, markdown = _serialize_code('bpr-guid-123')

	assert html == ''
	assert markdown == ''
