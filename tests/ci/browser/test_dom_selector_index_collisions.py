"""Regression coverage for selector identity across CDP sessions."""

from types import SimpleNamespace
from typing import Any, cast

import pytest

from browser_use.actor.page import Page
from browser_use.agent.service import Agent
from browser_use.browser import python_highlights
from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession
from browser_use.browser.views import BrowserStateSummary
from browser_use.dom.serializer.serializer import DOMTreeSerializer
from browser_use.dom.service import DomService
from browser_use.dom.views import DOMInteractedElement, DOMRect, EnhancedDOMTreeNode, EnhancedSnapshotNode, NodeType


def _node(
	tag_name: str,
	*,
	node_id: int,
	backend_node_id: int,
	session_id: str,
	frame_id: str | None = None,
) -> EnhancedDOMTreeNode:
	return EnhancedDOMTreeNode(
		node_id=node_id,
		backend_node_id=backend_node_id,
		node_type=NodeType.ELEMENT_NODE,
		node_name=tag_name.upper(),
		node_value='',
		attributes={},
		is_scrollable=False,
		is_visible=True,
		absolute_position=DOMRect(x=0, y=0, width=100, height=30),
		target_id=f'target-{session_id}',
		frame_id=frame_id,
		session_id=session_id,
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


def _serialize(children: list[EnhancedDOMTreeNode]):
	root = _node('html', node_id=100, backend_node_id=100, session_id='main')
	root.children_nodes = children
	for child in children:
		child.parent_node = root
	return DOMTreeSerializer(
		root,
		enable_bbox_filtering=False,
		paint_order_filtering=False,
	).serialize_accessible_elements()[0]


def test_backend_id_collisions_get_unique_selector_indices():
	"""Both controls remain addressable when separate sessions reuse a backend ID."""
	main_input = _node('input', node_id=1, backend_node_id=5, session_id='main')
	iframe_input = _node('input', node_id=2, backend_node_id=5, session_id='iframe')

	serialized_state = _serialize([main_input, iframe_input])

	assert list(serialized_state.selector_map) == [5, 101]
	assert list(serialized_state.selector_map.values()) == [main_input, iframe_input]
	assert '[5]<input' in serialized_state.llm_representation()
	assert '[101]<input' in serialized_state.llm_representation()
	assert '[i_5] <input' in serialized_state.eval_representation()
	assert '[i_101] <input' in serialized_state.eval_representation()


def test_session_lookup_keeps_selector_and_backend_identity_separate():
	"""Action messages and coordinate lookup resolve the intended session-local node."""
	main_input = _node('input', node_id=1, backend_node_id=5, session_id='main')
	iframe_input = _node('input', node_id=2, backend_node_id=5, session_id='iframe')
	session = BrowserSession(browser_profile=BrowserProfile(use_cloud=False))
	session.update_cached_selector_map({5: main_input, 101: iframe_input})

	assert session.get_selector_index(iframe_input) == 101
	assert session._get_cached_node_by_backend_id(5, 'main') is main_input
	assert session._get_cached_node_by_backend_id(5, 'iframe') is iframe_input


@pytest.mark.asyncio
async def test_history_remapping_prefers_the_original_frame():
	"""History replay must not choose an identical element from a different frame."""
	main_input = _node(
		'input',
		node_id=1,
		backend_node_id=5,
		session_id='main',
		frame_id='main-frame',
	)
	iframe_input = _node(
		'input',
		node_id=2,
		backend_node_id=5,
		session_id='iframe',
		frame_id='iframe-frame',
	)
	serialized_state = _serialize([main_input, iframe_input])
	historical_element = DOMInteractedElement.load_from_enhanced_dom_tree(iframe_input)

	class FakeAction:
		def __init__(self):
			self.index = 5

		def get_index(self):
			return self.index

		def set_index(self, index):
			self.index = index

	logger = SimpleNamespace(info=lambda *_args: None, debug=lambda *_args: None)
	agent = cast(Any, SimpleNamespace(logger=logger))
	action = FakeAction()
	state = BrowserStateSummary(dom_state=serialized_state, url='https://example.test', title='Test', tabs=[])

	updated_action = await Agent._update_action_indices(agent, historical_element, cast(Any, action), state)

	assert updated_action is action
	assert action.index == 101


def test_pagination_metadata_separates_selector_and_backend_ids():
	"""Public pagination metadata must not label a synthetic selector as a CDP backend ID."""
	iframe_button = _node('button', node_id=2, backend_node_id=5, session_id='iframe')
	assert iframe_button.snapshot_node is not None
	iframe_button.snapshot_node.is_clickable = True
	iframe_button.attributes['aria-label'] = 'Next'

	buttons = DomService.detect_pagination_buttons({101: iframe_button})

	assert buttons[0]['backend_node_id'] == 5
	assert buttons[0]['selector_index'] == 101


def test_screenshot_overlay_uses_selector_index(monkeypatch):
	"""Visual labels match the collision-free index shown in the DOM text."""
	iframe_input = _node('input', node_id=2, backend_node_id=5, session_id='iframe')
	captured_text: list[str | None] = []

	def capture_label(_draw, _bbox, _color, text, *_args):
		captured_text.append(text)

	monkeypatch.setattr(python_highlights, 'draw_enhanced_bounding_box_with_text', capture_label)
	python_highlights.process_element_highlight(
		101,
		iframe_input,
		draw=None,
		device_pixel_ratio=1,
		font=None,
		filter_highlight_ids=False,
		image_size=(1280, 900),
	)

	assert captured_text == ['101']


@pytest.mark.asyncio
async def test_interaction_highlight_uses_the_nodes_cdp_session(monkeypatch):
	"""The transient action highlight must resolve coordinates in the node's OOPIF session."""
	iframe_input = _node('input', node_id=2, backend_node_id=5, session_id='iframe')
	session = BrowserSession(browser_profile=BrowserProfile(use_cloud=False))
	iframe_cdp_session = SimpleNamespace(session_id='iframe')
	resolved_nodes: list[EnhancedDOMTreeNode] = []

	async def resolve_node_session(_session, node):
		resolved_nodes.append(node)
		return iframe_cdp_session

	async def no_coordinates(_session, backend_node_id, cdp_session):
		assert backend_node_id == 5
		assert cdp_session is iframe_cdp_session
		return None

	monkeypatch.setattr(BrowserSession, 'cdp_client_for_node', resolve_node_session)
	monkeypatch.setattr(BrowserSession, 'get_element_coordinates', no_coordinates)

	await session.highlight_interaction_element(iframe_input)

	assert resolved_nodes == [iframe_input]


@pytest.mark.asyncio
async def test_actor_prompt_element_uses_the_selected_nodes_session(monkeypatch):
	"""Actor prompt lookup must return an Element bound to the selected OOPIF session."""
	main_input = _node('input', node_id=1, backend_node_id=5, session_id='main')
	iframe_input = _node('input', node_id=2, backend_node_id=5, session_id='iframe')
	serialized_state = _serialize([main_input, iframe_input])
	root = _node('html', node_id=100, backend_node_id=100, session_id='main')
	session = BrowserSession(browser_profile=BrowserProfile(use_cloud=False))
	session._cdp_client_root = cast(Any, SimpleNamespace())

	class FakeSerializer:
		def __init__(self, *_args, **_kwargs):
			pass

		def serialize_accessible_elements(self):
			return serialized_state, {}

	class FakeLLM:
		async def ainvoke(self, *_args, **_kwargs):
			return SimpleNamespace(completion=SimpleNamespace(element_highlight_index=101))

	async def get_dom_tree(_service, **_kwargs):
		return root, {}

	async def resolve_node_session(_session, node):
		assert node is iframe_input
		return SimpleNamespace(session_id='iframe')

	monkeypatch.setattr('browser_use.actor.page.DOMTreeSerializer', FakeSerializer)
	monkeypatch.setattr(DomService, 'get_dom_tree', get_dom_tree)
	monkeypatch.setattr(BrowserSession, 'cdp_client_for_node', resolve_node_session)

	page = Page(session, target_id='target-main', session_id='main', llm=cast(Any, FakeLLM()))
	element = await page.get_element_by_prompt('card number')

	assert element is not None
	assert element._backend_node_id == 5
	assert element._session_id == 'iframe'
