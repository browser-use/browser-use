"""Regression tests for browser_use.dom.serializer.html_serializer."""

import pytest

from browser_use.dom.serializer.html_serializer import HTMLSerializer
from browser_use.dom.views import EnhancedDOMTreeNode, NodeType


def _make_node(node_type, node_name='#node', **overrides):
	defaults = {
		'node_id': 1,
		'backend_node_id': 1,
		'node_type': node_type,
		'node_name': node_name,
		'node_value': '',
		'attributes': {},
		'is_scrollable': False,
		'is_visible': True,
		'absolute_position': None,
		'target_id': None,
		'frame_id': None,
		'session_id': None,
		'content_document': None,
		'shadow_root_type': None,
		'shadow_roots': None,
		'parent_node': None,
		'children_nodes': None,
		'ax_node': None,
		'snapshot_node': None,
	}
	defaults.update(overrides)
	return EnhancedDOMTreeNode(**defaults)


@pytest.mark.parametrize('shadow_root_type', ['open', 'closed'])
def test_shadow_root_uses_shadowrootmode_attribute(shadow_root_type):
	"""Declarative shadow DOM requires `shadowrootmode`, not bare `shadowroot`.

	The WHATWG/HTML spec defines `<template shadowrootmode="open|closed">` as the
	declarative shadow DOM signal. A bare `shadowroot` attribute is unknown to
	spec-compliant parsers, so the shadow tree would be dropped on round-trip.
	"""
	shadow_root = _make_node(
		NodeType.DOCUMENT_FRAGMENT_NODE,
		node_name='#document-fragment',
		shadow_root_type=shadow_root_type,
	)
	host = _make_node(NodeType.ELEMENT_NODE, node_name='DIV', shadow_roots=[shadow_root])

	html = HTMLSerializer().serialize(host)

	assert f'<template shadowrootmode="{shadow_root_type}">' in html
	assert 'shadowroot="' not in html.replace('shadowrootmode="', '')
