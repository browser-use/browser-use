"""Tests for adaptive browser-state settling before an LLM turn."""

# These tests intentionally construct partial Agent/browser objects to exercise
# private settling helpers without launching Chromium.
# pyright: reportArgumentType=false, reportAttributeAccessIssue=false, reportOptionalSubscript=false, reportOperatorIssue=false

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from browser_use.agent.service import Agent
from browser_use.agent.views import ActionResult, AgentSettings, PageFingerprint
from browser_use.browser.views import BrowserStateSummary
from browser_use.tools.utils import get_click_target_fingerprint


class _FakeDOMState:
	def __init__(self, text: str, *, has_root: bool = True, selector_count: int = 0) -> None:
		self._text = text
		self._root = object() if has_root else None
		self.selector_map = {index: object() for index in range(selector_count)}

	def llm_representation(self) -> str:
		return self._text


def test_restores_legacy_fingerprint_without_text_length() -> None:
	fingerprint = PageFingerprint.model_validate({'url': 'https://example.com', 'element_count': 2, 'text_hash': 'legacy'})
	assert fingerprint.text_length == 0
	assert fingerprint.text_hash == 'legacy'


def _state(text: str, *, has_root: bool = True, state_error: str | None = None, selector_count: int = 0) -> BrowserStateSummary:
	return BrowserStateSummary(
		dom_state=_FakeDOMState(text, has_root=has_root, selector_count=selector_count),  # type: ignore[arg-type]
		url='https://example.com/products',
		title='Products',
		tabs=[],
		state_error=state_error,
	)


def test_detects_strong_loading_shell_signals() -> None:
	state = _state('<div>Loading screen</div><div>Loading content</div>')

	assert Agent._browser_state_is_loading_shell(state) is True


def test_does_not_delay_normal_page_that_mentions_loading_once() -> None:
	state = _state('<main><h1>Products</h1><p>Lazy loading improves image performance.</p></main>')

	assert Agent._browser_state_is_loading_shell(state) is False


def test_does_not_delay_rich_page_behind_persistent_loading_modal() -> None:
	state = _state(
		'<main><h1>Products</h1>'
		+ ('<button>Add to cart</button><p>Product details</p>' * 80)
		+ '</main><div>Loading screen</div>',
		selector_count=20,
	)

	assert Agent._browser_state_is_loading_shell(state) is False


def test_detects_repeated_loading_placeholders() -> None:
	state = _state('<div>Loading...</div><div>Loading...</div><div>Loading...</div>')

	assert Agent._browser_state_is_loading_shell(state) is True


def test_detects_repeated_loading_placeholders_inside_rich_page_shell() -> None:
	state = _state(
		'<header>' + ('<button>Navigation</button>' * 20) + '</header>' + ('<div>Loading...</div>' * 6),
		selector_count=20,
	)

	assert Agent._browser_state_is_loading_shell(state) is True


@pytest.mark.asyncio
async def test_loading_shell_is_refreshed_before_returning_state() -> None:
	loading_state = _state('<div>Loading...</div><div>Loading...</div><div>Loading...</div>')
	ready_state = _state('<main><h1>Products</h1><button>Add to cart</button></main>')
	browser_session = SimpleNamespace(
		get_browser_state_summary=AsyncMock(side_effect=[loading_state, ready_state]),
		id='browser-session-test',
		agent_focus_target_id=None,
	)
	agent = Agent.__new__(Agent)
	agent.browser_session = browser_session
	agent.include_recent_events = False
	agent.settings = AgentSettings(
		loading_shell_max_wait_seconds=0.8,
		loading_shell_poll_interval_seconds=0.15,
	)
	with patch('browser_use.agent.service.asyncio.sleep', new=AsyncMock()) as sleep_mock:
		result = await agent._get_browser_state_after_loading_settle()

	assert result is ready_state
	assert browser_session.get_browser_state_summary.await_count == 2
	browser_session.get_browser_state_summary.assert_awaited_with(
		include_screenshot=True,
		include_recent_events=False,
	)
	sleep_mock.assert_awaited_once_with(0.15)


def test_history_screenshot_sampling_uses_only_interval_steps() -> None:
	agent = Agent.__new__(Agent)
	agent.settings = AgentSettings(use_vision='auto', history_screenshot_interval=5)
	agent.state = SimpleNamespace(n_steps=1, last_result=[])

	assert agent._should_capture_history_screenshot() is False
	agent.state.n_steps = 2
	assert agent._should_capture_history_screenshot() is False
	agent.state.n_steps = 5
	assert agent._should_capture_history_screenshot() is True


def test_explicit_screenshot_request_overrides_history_sampling() -> None:
	agent = Agent.__new__(Agent)
	agent.settings = AgentSettings(use_vision='auto', history_screenshot_interval=10)
	agent.state = SimpleNamespace(
		n_steps=2,
		last_result=[SimpleNamespace(metadata={'include_screenshot': True})],
	)

	assert agent._should_capture_history_screenshot() is True


@pytest.mark.asyncio
async def test_loading_settle_can_skip_screenshots() -> None:
	ready_state = _state('<main><h1>Products</h1></main>')
	browser_session = SimpleNamespace(
		get_browser_state_summary=AsyncMock(return_value=ready_state),
		id='browser-session-test',
		agent_focus_target_id=None,
	)
	agent = Agent.__new__(Agent)
	agent.browser_session = browser_session
	agent.include_recent_events = False
	agent.settings = AgentSettings()

	result = await agent._get_browser_state_after_loading_settle(include_screenshot=False)

	assert result is ready_state
	browser_session.get_browser_state_summary.assert_awaited_once_with(
		include_screenshot=False,
		include_recent_events=False,
	)


@pytest.mark.asyncio
async def test_unchanged_state_after_click_is_refreshed_until_it_changes() -> None:
	previous_state = _state('<main><button>Add to cart</button></main>', selector_count=1)
	changed_state = _state('<dialog><p>Added to cart</p><button>Continue shopping</button></dialog>', selector_count=1)
	browser_session = SimpleNamespace(
		get_browser_state_summary=AsyncMock(side_effect=[previous_state, previous_state, changed_state]),
		id='browser-session-test',
		agent_focus_target_id=None,
	)
	click_action = SimpleNamespace(model_dump=lambda **_kwargs: {'click': {'index': 1}})
	agent = Agent.__new__(Agent)
	agent.browser_session = browser_session
	agent.include_recent_events = False
	agent.settings = AgentSettings(
		post_click_state_settle_max_wait_seconds=0.6,
		post_click_state_settle_poll_interval_seconds=0.1,
	)
	agent.state = SimpleNamespace(
		last_model_output=SimpleNamespace(action=[click_action]),
		last_result=[SimpleNamespace(error=None)],
	)
	agent._last_observed_page_fingerprint = Agent._page_fingerprint(previous_state)

	with patch('browser_use.agent.service.asyncio.sleep', new=AsyncMock()) as sleep_mock:
		result = await agent._get_browser_state_after_loading_settle(include_screenshot=False)

	assert result is changed_state
	assert browser_session.get_browser_state_summary.await_count == 3
	assert sleep_mock.await_count == 2
	assert len(agent.state.last_result) == 1


@pytest.mark.asyncio
async def test_unchanged_click_adds_one_shot_model_feedback() -> None:
	state = _state('<main><button>Save</button></main>', selector_count=1)
	browser_session = SimpleNamespace(
		get_browser_state_summary=AsyncMock(return_value=state),
		id='browser-session-test',
		agent_focus_target_id=None,
	)
	click_action = SimpleNamespace(model_dump=lambda **_kwargs: {'click': {'index': 1}})
	agent = Agent.__new__(Agent)
	agent.browser_session = browser_session
	agent.include_recent_events = False
	agent.settings = AgentSettings(
		post_click_state_settle_max_wait_seconds=0.6,
		post_click_state_settle_poll_interval_seconds=0.1,
	)
	agent.state = SimpleNamespace(
		last_model_output=SimpleNamespace(action=[click_action]),
		last_result=[SimpleNamespace(error=None, metadata=None)],
	)
	agent._last_observed_page_fingerprint = Agent._page_fingerprint(state)

	with (
		patch('browser_use.agent.service.asyncio.sleep', new=AsyncMock()),
		patch('browser_use.agent.service.time.monotonic', side_effect=[0.0, 0.0, 0.6]),
	):
		result = await agent._get_browser_state_after_loading_settle(include_screenshot=False)

	assert result is state
	assert len(agent.state.last_result) == 2
	feedback = agent.state.last_result[-1]
	assert feedback.include_extracted_content_only_once is True
	assert 'Do not repeat the identical click blindly' in feedback.extracted_content
	assert feedback.metadata == {'post_click_state_unchanged': True}


@pytest.mark.asyncio
async def test_commit_button_waits_through_small_incidental_dom_mutation() -> None:
	button = SimpleNamespace(
		backend_node_id=42,
		tag_name='button',
		attributes={'id': 'save', 'type': 'submit', 'aria-label': 'Save'},
		get_meaningful_text_for_llm=lambda: 'Save',
	)
	previous_state = _state('<main><button id="save">Save</button></main>', selector_count=1)
	incidental_state = _state('<main><button id="save">Save</button><span>...</span></main>', selector_count=1)
	incidental_state.dom_state.selector_map = {1: button}
	completed_state = _state('<main><p>Saved successfully</p></main>', selector_count=0)
	browser_session = SimpleNamespace(
		get_browser_state_summary=AsyncMock(side_effect=[incidental_state, completed_state]),
		id='browser-session-test',
		agent_focus_target_id=None,
	)
	click_action = SimpleNamespace(model_dump=lambda **_kwargs: {'click': {'index': 1}})
	agent = Agent.__new__(Agent)
	agent.browser_session = browser_session
	agent.include_recent_events = False
	agent.settings = AgentSettings(
		post_click_state_settle_max_wait_seconds=0.6,
		post_click_state_settle_poll_interval_seconds=0.1,
	)
	agent.state = SimpleNamespace(
		last_model_output=SimpleNamespace(action=[click_action]),
		last_result=[ActionResult(metadata={'click_target_fingerprint': get_click_target_fingerprint(button)})],
	)
	agent._last_observed_page_fingerprint = Agent._page_fingerprint(previous_state)

	with patch('browser_use.agent.service.asyncio.sleep', new=AsyncMock()) as sleep_mock:
		result = await agent._get_browser_state_after_loading_settle(include_screenshot=False)

	assert result is completed_state
	assert browser_session.get_browser_state_summary.await_count == 2
	sleep_mock.assert_awaited_once_with(0.1)


@pytest.mark.asyncio
async def test_commit_button_reports_large_unrelated_dom_mutation_without_waiting() -> None:
	button = SimpleNamespace(
		backend_node_id=42,
		tag_name='button',
		attributes={'id': 'add', 'aria-label': 'Add to cart'},
		get_meaningful_text_for_llm=lambda: 'Add to cart',
	)
	previous_state = _state('<main><button id="add">Add to cart</button></main>', selector_count=1)
	incidental_state = _state('<main>' + ('<aside>Rotating promotion</aside>' * 100) + '</main>', selector_count=30)
	incidental_state.dom_state.selector_map = {1: button, **{index: object() for index in range(2, 31)}}
	browser_session = SimpleNamespace(
		get_browser_state_summary=AsyncMock(return_value=incidental_state),
		id='browser-session-test',
		agent_focus_target_id=None,
	)
	click_action = SimpleNamespace(model_dump=lambda **_kwargs: {'click': {'index': 1}})
	agent = Agent.__new__(Agent)
	agent.browser_session = browser_session
	agent.include_recent_events = False
	agent.settings = AgentSettings(
		post_click_state_settle_max_wait_seconds=0.6,
		post_click_state_settle_poll_interval_seconds=0.1,
	)
	agent.state = SimpleNamespace(
		last_model_output=SimpleNamespace(action=[click_action]),
		last_result=[ActionResult(metadata={'click_target_fingerprint': get_click_target_fingerprint(button)})],
	)
	agent._last_observed_page_fingerprint = Agent._page_fingerprint(previous_state)

	with patch('browser_use.agent.service.asyncio.sleep', new=AsyncMock()) as sleep_mock:
		result = await agent._get_browser_state_after_loading_settle(include_screenshot=False)

	assert result is incidental_state
	browser_session.get_browser_state_summary.assert_awaited_once()
	sleep_mock.assert_not_awaited()
	assert len(agent.state.last_result) == 2
	assert agent.state.last_result[-1].metadata == {'post_click_state_unchanged': True}


def test_click_target_state_ignores_duplicate_html_ids() -> None:
	clicked_button = SimpleNamespace(
		backend_node_id=42,
		tag_name='button',
		attributes={'id': 'shared-add-button', 'aria-label': 'Add Product B to cart'},
		get_meaningful_text_for_llm=lambda: 'Add to cart',
	)
	unrelated_button = SimpleNamespace(
		backend_node_id=7,
		tag_name='button',
		attributes={'id': 'shared-add-button', 'aria-label': 'Add Product A to cart'},
		get_meaningful_text_for_llm=lambda: 'Add to cart',
	)
	rerendered_clicked_button = SimpleNamespace(
		backend_node_id=99,
		tag_name='button',
		attributes={'id': 'shared-add-button', 'aria-label': 'Add Product B to cart'},
		get_meaningful_text_for_llm=lambda: 'Add to cart',
	)
	state = _state('<main>Product cards rerendered</main>', selector_count=2)
	state.dom_state.selector_map = {1: unrelated_button, 2: rerendered_clicked_button}
	agent = Agent.__new__(Agent)
	agent.state = SimpleNamespace(
		last_result=[ActionResult(metadata={'click_target_fingerprint': get_click_target_fingerprint(clicked_button)})]
	)

	assert agent._last_click_target_state(state) == 'same'


@pytest.mark.asyncio
async def test_non_click_action_does_not_trigger_post_click_refresh() -> None:
	state = _state('<main><input value="query"></main>', selector_count=1)
	browser_session = SimpleNamespace(
		get_browser_state_summary=AsyncMock(return_value=state),
		id='browser-session-test',
		agent_focus_target_id=None,
	)
	input_action = SimpleNamespace(model_dump=lambda **_kwargs: {'input': {'index': 1, 'text': 'query'}})
	agent = Agent.__new__(Agent)
	agent.browser_session = browser_session
	agent.include_recent_events = False
	agent.settings = AgentSettings(post_click_state_settle_max_wait_seconds=0.6)
	agent.state = SimpleNamespace(
		last_model_output=SimpleNamespace(action=[input_action]),
		last_result=[SimpleNamespace(error=None)],
	)
	agent._last_observed_page_fingerprint = Agent._page_fingerprint(state)

	result = await agent._get_browser_state_after_loading_settle(include_screenshot=False)

	assert result is state
	browser_session.get_browser_state_summary.assert_awaited_once()
