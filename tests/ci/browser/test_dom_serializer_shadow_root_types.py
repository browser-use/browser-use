"""Regression coverage for model-visible shadow root type labels."""

import pytest
from cdp_use.cdp.dom.types import ShadowRootType

from browser_use.agent.prompts import AgentMessagePrompt
from browser_use.browser.views import BrowserStateSummary
from browser_use.dom.serializer.serializer import DOMTreeSerializer
from browser_use.dom.views import (
	DOMRect,
	EnhancedDOMTreeNode,
	EnhancedSnapshotNode,
	NodeType,
	SerializedDOMState,
	SimplifiedNode,
)
from browser_use.filesystem.file_system import FileSystem


def _enhanced_node(
	name: str,
	*,
	node_id: int,
	node_type: NodeType = NodeType.ELEMENT_NODE,
	shadow_root_type: ShadowRootType | None = None,
	has_snapshot: bool = True,
) -> EnhancedDOMTreeNode:
	return EnhancedDOMTreeNode(
		node_id=node_id,
		backend_node_id=node_id,
		node_type=node_type,
		node_name=name,
		node_value='',
		attributes={},
		is_scrollable=False,
		is_visible=True,
		absolute_position=DOMRect(x=0, y=0, width=100, height=30),
		target_id='target',
		frame_id=None,
		session_id='session',
		content_document=None,
		shadow_root_type=shadow_root_type,
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
			computed_styles={'display': 'block', 'visibility': 'visible', 'opacity': '1'},
			paint_order=None,
			stacking_contexts=None,
		)
		if has_snapshot
		else None,
	)


def _shadow_host(tag_name: str, shadow_root_type: ShadowRootType | None, node_id: int) -> SimplifiedNode:
	shadow_child = SimplifiedNode(
		original_node=_enhanced_node('BUTTON', node_id=node_id + 2),
		children=[],
		is_interactive=True,
		selector_index=node_id + 2,
	)
	shadow_root = SimplifiedNode(
		original_node=_enhanced_node(
			'#document-fragment',
			node_id=node_id + 1,
			node_type=NodeType.DOCUMENT_FRAGMENT_NODE,
			shadow_root_type=shadow_root_type,
		),
		children=[shadow_child],
	)
	return SimplifiedNode(
		original_node=_enhanced_node(tag_name.upper(), node_id=node_id),
		children=[shadow_root],
		is_interactive=True,
		selector_index=node_id,
		is_shadow_host=True,
	)


@pytest.mark.parametrize('tag_name', ['div', 'svg'])
@pytest.mark.parametrize(
	('shadow_root_type', 'host_marker', 'fragment_label'),
	[
		('open', '|SHADOW(open)|', 'Open Shadow'),
		('closed', '|SHADOW(closed)|', 'Closed Shadow'),
		('user-agent', '|SHADOW(user-agent)|', 'User-Agent Shadow'),
		(None, '|SHADOW|', 'Shadow'),
	],
)
def test_shadow_root_types_are_labeled_without_changing_content(
	tag_name: str,
	shadow_root_type: ShadowRootType | None,
	host_marker: str,
	fragment_label: str,
):
	"""Both host rendering paths must preserve and accurately label shadow content."""
	host = _shadow_host(tag_name, shadow_root_type, node_id=10)

	representation = SerializedDOMState(_root=host, selector_map={}).llm_representation()

	assert host_marker in representation
	if tag_name == 'div':
		assert fragment_label in representation
		assert '[12]<button' in representation
	else:
		assert 'SVG content collapsed' in representation


def test_page_stats_report_user_agent_roots_separately_from_author_roots(tmp_path):
	"""The complete browser-state message must not count native controls as open author roots."""
	root = SimplifiedNode(
		original_node=_enhanced_node('HTML', node_id=1),
		children=[
			_shadow_host('select', 'user-agent', node_id=10),
			_shadow_host('div', 'open', node_id=20),
			_shadow_host('div', 'closed', node_id=30),
		],
	)
	state = BrowserStateSummary(
		dom_state=SerializedDOMState(_root=root, selector_map={}),
		url='http://localhost/',
		title='Shadow root types',
		tabs=[],
	)
	prompt = AgentMessagePrompt(
		browser_state_summary=state,
		file_system=FileSystem(base_dir=tmp_path, create_default_files=False),
	)

	description = prompt._get_browser_state_description()

	assert '1 shadow(open), 1 shadow(closed), 1 shadow(user-agent)' in description
	assert '|SHADOW(user-agent)|[10]<select' in description
	assert 'User-Agent Shadow' in description
	assert '[12]<button' in description


@pytest.mark.parametrize('shadow_root_type', ['open', 'closed', 'user-agent'])
def test_full_serializer_retains_type_when_empty_fragment_is_optimized_out(
	shadow_root_type: ShadowRootType,
	tmp_path,
):
	"""A native host keeps its CDP type even when its empty fragment is removed."""
	root = _enhanced_node('HTML', node_id=1)
	host = _enhanced_node('INPUT', node_id=2)
	shadow_root = _enhanced_node(
		'#document-fragment',
		node_id=3,
		node_type=NodeType.DOCUMENT_FRAGMENT_NODE,
		shadow_root_type=shadow_root_type,
		has_snapshot=False,
	)
	root.children_nodes = [host]
	host.parent_node = root
	host.shadow_roots = [shadow_root]
	shadow_root.parent_node = host

	serialized_state = DOMTreeSerializer(
		root,
		enable_bbox_filtering=False,
		paint_order_filtering=False,
	).serialize_accessible_elements()[0]

	assert f'|SHADOW({shadow_root_type})|[2]<input' in serialized_state.llm_representation()
	assert serialized_state._root is not None
	assert serialized_state._root.children[0].children == []

	state = BrowserStateSummary(
		dom_state=serialized_state,
		url='http://localhost/',
		title='Optimized empty shadow root',
		tabs=[],
	)
	prompt = AgentMessagePrompt(
		browser_state_summary=state,
		file_system=FileSystem(base_dir=tmp_path, create_default_files=False),
	)
	stats = prompt._extract_page_statistics()

	assert stats['shadow_open'] == int(shadow_root_type == 'open')
	assert stats['shadow_closed'] == int(shadow_root_type == 'closed')
	assert stats['shadow_user_agent'] == int(shadow_root_type == 'user-agent')

	page_stats = prompt._get_browser_state_description().split('</page_stats>', 1)[0]
	if shadow_root_type == 'user-agent':
		assert '1 shadow(user-agent)' in page_stats
		assert 'shadow(open)' not in page_stats
		assert 'shadow(closed)' not in page_stats
	else:
		assert f'1 shadow({shadow_root_type})' in page_stats
		assert 'shadow(user-agent)' not in page_stats
