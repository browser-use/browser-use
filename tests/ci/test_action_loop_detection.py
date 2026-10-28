"""Tests for action loop detection — behavioral cycle breaking (PR #4)."""

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from pytest_httpserver import HTTPServer

from browser_use.agent.service import Agent
from browser_use.agent.views import (
	ActionLoopDetector,
	ActionResult,
	PageFingerprint,
	compute_action_hash,
)
from browser_use.browser import BrowserSession
from browser_use.browser.profile import BrowserProfile
from browser_use.llm.messages import UserMessage
from browser_use.tools.service import Tools
from browser_use.tools.views import NavigateAction
from tests.ci.conftest import create_mock_llm


def _get_context_messages(agent: Agent) -> list[str]:
	"""Extract text content from the agent's context messages."""
	msgs = agent._message_manager.state.history.context_messages
	return [m.content for m in msgs if isinstance(m, UserMessage) and isinstance(m.content, str)]


# ─── Action hash normalization tests ─────────────────────────────────────────


def test_search_normalization_ignores_keyword_order():
	"""Two searches with the same keywords in different order should produce the same hash."""
	h1 = compute_action_hash('search', {'query': 'site:example.com answers votes'})
	h2 = compute_action_hash('search', {'query': 'votes answers site:example.com'})
	assert h1 == h2


def test_search_normalization_ignores_case():
	"""Search normalization is case-insensitive."""
	h1 = compute_action_hash('search', {'query': 'Python Tutorial'})
	h2 = compute_action_hash('search', {'query': 'python tutorial'})
	assert h1 == h2


def test_search_normalization_ignores_punctuation():
	"""Search normalization strips punctuation."""
	h1 = compute_action_hash('search', {'query': 'site:hinative.com "answers" votes'})
	h2 = compute_action_hash('search', {'query': 'site:hinative.com answers, votes'})
	assert h1 == h2


def test_search_normalization_deduplicates_tokens():
	"""Duplicate tokens in a search query produce the same hash as single tokens."""
	h1 = compute_action_hash('search', {'query': 'python python tutorial'})
	h2 = compute_action_hash('search', {'query': 'python tutorial'})
	assert h1 == h2


def test_search_different_queries_produce_different_hashes():
	"""Fundamentally different search queries should NOT match."""
	h1 = compute_action_hash('search', {'query': 'python web scraping'})
	h2 = compute_action_hash('search', {'query': 'javascript testing framework'})
	assert h1 != h2


def test_click_same_index_same_hash():
	"""Clicking the same element index produces the same hash."""
	h1 = compute_action_hash('click', {'index': 5})
	h2 = compute_action_hash('click', {'index': 5})
	assert h1 == h2


def test_click_different_index_different_hash():
	"""Clicking different element indices produces different hashes."""
	h1 = compute_action_hash('click', {'index': 5})
	h2 = compute_action_hash('click', {'index': 12})
	assert h1 != h2


def test_input_same_element_same_text():
	"""Same element + same text = same hash."""
	h1 = compute_action_hash('input', {'index': 3, 'text': 'hello world', 'clear': True})
	h2 = compute_action_hash('input', {'index': 3, 'text': 'hello world', 'clear': False})
	assert h1 == h2  # clear flag doesn't affect hash


def test_input_different_text_different_hash():
	"""Same element but different text = different hash."""
	h1 = compute_action_hash('input', {'index': 3, 'text': 'hello'})
	h2 = compute_action_hash('input', {'index': 3, 'text': 'goodbye'})
	assert h1 != h2


def test_navigate_same_url_same_hash():
	"""Navigating to the exact same URL produces the same hash."""
	h1 = compute_action_hash('navigate', {'url': 'https://example.com/page1'})
	h2 = compute_action_hash('navigate', {'url': 'https://example.com/page1'})
	assert h1 == h2


def test_navigate_different_paths_different_hash():
	"""Navigating to different paths on the same domain produces different hashes — this is genuine exploration."""
	h1 = compute_action_hash('navigate', {'url': 'https://example.com/page1'})
	h2 = compute_action_hash('navigate', {'url': 'https://example.com/page2'})
	assert h1 != h2


def test_navigate_different_domain_different_hash():
	"""Navigate to different domains produces different hashes."""
	h1 = compute_action_hash('navigate', {'url': 'https://example.com/page1'})
	h2 = compute_action_hash('navigate', {'url': 'https://other.com/page1'})
	assert h1 != h2


def test_scroll_direction_matters():
	"""Scroll up and scroll down are different actions."""
	h1 = compute_action_hash('scroll', {'down': True, 'index': None})
	h2 = compute_action_hash('scroll', {'down': False, 'index': None})
	assert h1 != h2


def test_scroll_different_elements_different_hash():
	"""Scrolling different elements produces different hashes."""
	h1 = compute_action_hash('scroll', {'down': True, 'index': 5})
	h2 = compute_action_hash('scroll', {'down': True, 'index': 10})
	assert h1 != h2


def test_scroll_same_element_same_hash():
	"""Scrolling the same element in the same direction produces the same hash."""
	h1 = compute_action_hash('scroll', {'down': True, 'index': 5})
	h2 = compute_action_hash('scroll', {'down': True, 'index': 5})
	assert h1 == h2


def test_different_action_types_different_hashes():
	"""Different action types always produce different hashes."""
	h1 = compute_action_hash('click', {'index': 5})
	h2 = compute_action_hash('scroll', {'down': True, 'index': None})
	h3 = compute_action_hash('search', {'query': 'test'})
	assert len({h1, h2, h3}) == 3


# ─── ActionLoopDetector unit tests ───────────────────────────────────────────


def test_detector_no_nudge_for_diverse_actions():
	"""No nudge when actions are all different."""
	detector = ActionLoopDetector(window_size=20)
	detector.record_action('click', {'index': 1})
	detector.record_action('scroll', {'down': True, 'index': None})
	detector.record_action('click', {'index': 2})
	detector.record_action('search', {'query': 'something'})
	detector.record_action('navigate', {'url': 'https://example.com'})
	assert detector.get_nudge_message() is None


def test_detector_nudge_at_5_repeats():
	"""Nudge triggers at 5 repetitions of the same action."""
	detector = ActionLoopDetector(window_size=20)
	for _ in range(5):
		detector.record_action('search', {'query': 'site:hinative.com answers votes'})
	msg = detector.get_nudge_message()
	assert msg is not None
	assert 'repeated a similar action' in msg
	assert '5 times' in msg


def test_detector_no_nudge_at_4_repeats():
	"""No nudge at only 4 repetitions (below threshold)."""
	detector = ActionLoopDetector(window_size=20)
	for _ in range(4):
		detector.record_action('search', {'query': 'site:hinative.com answers votes'})
	assert detector.get_nudge_message() is None


def test_detector_nudge_escalates_at_8_repeats():
	"""Stronger nudge at 8 repetitions."""
	detector = ActionLoopDetector(window_size=20)
	for _ in range(8):
		detector.record_action('search', {'query': 'site:hinative.com answers votes'})
	msg = detector.get_nudge_message()
	assert msg is not None
	assert 'still making progress' in msg
	assert '8 times' in msg


def test_detector_nudge_escalates_at_12_repeats():
	"""Most urgent nudge at 12 repetitions."""
	detector = ActionLoopDetector(window_size=20)
	for _ in range(12):
		detector.record_action('search', {'query': 'site:hinative.com answers votes'})
	msg = detector.get_nudge_message()
	assert msg is not None
	assert 'making progress with each repetition' in msg
	assert '12 times' in msg


def test_detector_critical_message_no_done_directive():
	"""Critical nudge should NOT tell the agent to call done — just a gentle heads up."""
	detector = ActionLoopDetector(window_size=20)
	for _ in range(12):
		detector.record_action('search', {'query': 'site:hinative.com answers votes'})
	msg = detector.get_nudge_message()
	assert msg is not None
	assert 'done action' not in msg
	assert 'different approach' in msg


def test_detector_first_nudge_no_cannot_complete():
	"""First nudge should NOT say task 'cannot be completed' — just raise awareness."""
	detector = ActionLoopDetector(window_size=20)
	for _ in range(5):
		detector.record_action('search', {'query': 'site:hinative.com answers votes'})
	msg = detector.get_nudge_message()
	assert msg is not None
	assert 'cannot be completed' not in msg
	assert 'reconsidering your approach' in msg


def test_detector_window_slides():
	"""Old actions fall out of the window."""
	detector = ActionLoopDetector(window_size=10)
	# Fill window with repeated actions
	for _ in range(5):
		detector.record_action('click', {'index': 7})
	assert detector.max_repetition_count == 5

	# Push them out with diverse actions
	for i in range(10):
		detector.record_action('click', {'index': 100 + i})
	# The 5 old repeated actions should have been pushed out
	assert detector.max_repetition_count < 5
	assert detector.get_nudge_message() is None


def test_detector_search_variations_detected_as_same():
	"""Minor variations of the same search (the hinative pattern) are detected as repetition."""
	detector = ActionLoopDetector(window_size=20)
	# These are the kind of variations the agent produces
	queries = [
		'site:hinative.com answers votes questions',
		'site:hinative.com questions answers votes',
		'site:hinative.com votes answers questions',
		'site:hinative.com questions votes answers',
		'site:hinative.com answers questions votes',
	]
	for q in queries:
		detector.record_action('search', {'query': q})
	assert detector.max_repetition_count == 5
	assert detector.get_nudge_message() is not None


# ─── Page stagnation detection tests ─────────────────────────────────────────


def test_page_stagnation_no_nudge_when_pages_change():
	"""No stagnation nudge when page content changes each step."""
	detector = ActionLoopDetector(window_size=20)
	detector.record_page_state('https://example.com', 'page content 1', 50)
	detector.record_page_state('https://example.com', 'page content 2', 55)
	detector.record_page_state('https://example.com', 'page content 3', 60)
	assert detector.consecutive_stagnant_pages == 0
	assert detector.get_nudge_message() is None


def test_page_stagnation_nudge_at_5_identical_pages():
	"""Stagnation nudge fires after 5 consecutive identical page states."""
	detector = ActionLoopDetector(window_size=20)
	# First recording establishes baseline (doesn't count as stagnant)
	for _ in range(6):
		detector.record_page_state('https://example.com', 'same content', 50)
	assert detector.consecutive_stagnant_pages >= 5
	msg = detector.get_nudge_message()
	assert msg is not None
	assert 'page content has not changed' in msg


def test_page_stagnation_no_nudge_at_4_identical_pages():
	"""No stagnation nudge at only 4 consecutive identical pages (below threshold)."""
	detector = ActionLoopDetector(window_size=20)
	# First recording establishes baseline, then 4 stagnant = 5 total recordings
	for _ in range(5):
		detector.record_page_state('https://example.com', 'same content', 50)
	assert detector.consecutive_stagnant_pages == 4
	assert detector.get_nudge_message() is None


def test_page_stagnation_resets_on_change():
	"""Stagnation counter resets when page content changes."""
	detector = ActionLoopDetector(window_size=20)
	detector.record_page_state('https://example.com', 'same content', 50)
	detector.record_page_state('https://example.com', 'same content', 50)
	detector.record_page_state('https://example.com', 'same content', 50)
	assert detector.consecutive_stagnant_pages == 2
	# Page changes
	detector.record_page_state('https://example.com', 'different content', 55)
	assert detector.consecutive_stagnant_pages == 0


def test_combined_loop_and_stagnation():
	"""Both action loop and page stagnation messages appear together."""
	detector = ActionLoopDetector(window_size=20)
	# Create action repetition (8 for STRONG LOOP WARNING)
	for _ in range(8):
		detector.record_action('click', {'index': 7})
	# Create page stagnation (need 5 consecutive stagnant)
	detector.record_page_state('https://example.com', 'same', 50)
	for _ in range(5):
		detector.record_page_state('https://example.com', 'same', 50)
	msg = detector.get_nudge_message()
	assert msg is not None
	assert 'still making progress' in msg
	assert 'page content has not changed' in msg


# ─── PageFingerprint tests ───────────────────────────────────────────────────


def test_page_fingerprint_same_content_equal():
	"""Same content produces equal fingerprints."""
	fp1 = PageFingerprint.from_browser_state('https://example.com', 'hello world', 50)
	fp2 = PageFingerprint.from_browser_state('https://example.com', 'hello world', 50)
	assert fp1 == fp2


def test_page_fingerprint_different_content_not_equal():
	"""Different content produces different fingerprints."""
	fp1 = PageFingerprint.from_browser_state('https://example.com', 'hello world', 50)
	fp2 = PageFingerprint.from_browser_state('https://example.com', 'goodbye world', 50)
	assert fp1 != fp2


def test_page_fingerprint_different_url_not_equal():
	"""Different URL produces different fingerprint even with same content."""
	fp1 = PageFingerprint.from_browser_state('https://example.com', 'hello world', 50)
	fp2 = PageFingerprint.from_browser_state('https://other.com', 'hello world', 50)
	assert fp1 != fp2


def test_page_fingerprint_different_element_count_not_equal():
	"""Different element count produces different fingerprint."""
	fp1 = PageFingerprint.from_browser_state('https://example.com', 'hello world', 50)
	fp2 = PageFingerprint.from_browser_state('https://example.com', 'hello world', 51)
	assert fp1 != fp2


# ─── Agent integration tests ─────────────────────────────────────────────────


async def test_loop_nudge_injected_into_context():
	"""Loop detection nudge is injected as a context message in the agent."""
	llm = create_mock_llm()
	agent = Agent(task='Test task', llm=llm)

	# Simulate 5 repeated actions (new threshold)
	for _ in range(5):
		agent.state.loop_detector.record_action('search', {'query': 'site:example.com answers'})

	agent._inject_loop_detection_nudge()

	messages = _get_context_messages(agent)
	assert len(messages) == 1
	assert 'repeated a similar action' in messages[0]


async def test_no_loop_nudge_when_disabled():
	"""No loop nudge when loop_detection_enabled is False."""
	llm = create_mock_llm()
	agent = Agent(
		task='Test task',
		llm=llm,
		loop_detection_enabled=False,
	)

	# Simulate 8 repeated actions
	for _ in range(8):
		agent.state.loop_detector.record_action('search', {'query': 'site:example.com answers'})

	agent._inject_loop_detection_nudge()

	messages = _get_context_messages(agent)
	assert len(messages) == 0


async def test_no_loop_nudge_for_diverse_actions():
	"""No loop nudge when actions are diverse."""
	llm = create_mock_llm()
	agent = Agent(task='Test task', llm=llm)

	agent.state.loop_detector.record_action('click', {'index': 1})
	agent.state.loop_detector.record_action('scroll', {'down': True, 'index': None})
	agent.state.loop_detector.record_action('click', {'index': 2})

	agent._inject_loop_detection_nudge()

	messages = _get_context_messages(agent)
	assert len(messages) == 0


async def test_loop_detector_initialized_from_settings():
	"""Loop detector window size is set from agent settings."""
	llm = create_mock_llm()
	agent = Agent(task='Test task', llm=llm, loop_detection_window=30)
	assert agent.state.loop_detector.window_size == 30


async def test_loop_detector_default_window_size():
	"""Loop detection default window size is 20."""
	llm = create_mock_llm()
	agent = Agent(task='Test task', llm=llm)
	assert agent.settings.loop_detection_enabled is True
	assert agent.state.loop_detector.window_size == 20


@pytest.fixture(scope='module')
async def loop_browser_session() -> AsyncIterator[BrowserSession]:
	"""Run the batch regressions against Chromium, with no browser or tool mocks."""
	session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			user_data_dir=None,
			keep_alive=True,
			enable_default_extensions=False,
			wait_between_actions=0,
		)
	)
	await session.start()
	try:
		yield session
	finally:
		await session.kill()
		await session.event_bus.stop(clear=True, timeout=5)


async def _record_browser_marker(browser_session: BrowserSession, label: str) -> None:
	"""Leave execution evidence in the real page that survives same-origin navigation."""
	session = await browser_session.get_or_create_cdp_session()
	result = await session.cdp_client.send.Runtime.evaluate(
		params={
			'expression': (
				'(() => {const markers = JSON.parse(localStorage.getItem("loop_markers") || "[]");'
				f'markers.push({json.dumps(label)}); localStorage.setItem("loop_markers", JSON.stringify(markers));}})()'
			),
			'returnByValue': True,
		},
		session_id=session.session_id,
	)
	assert not result.get('exceptionDetails')


async def _read_browser_markers(browser_session: BrowserSession) -> list[str]:
	"""Read actual side effects independently of ActionResult and loop-detector state."""
	session = await browser_session.get_or_create_cdp_session()
	result = await session.cdp_client.send.Runtime.evaluate(
		params={'expression': 'JSON.parse(localStorage.getItem("loop_markers") || "[]")', 'returnByValue': True},
		session_id=session.session_id,
	)
	assert not result.get('exceptionDetails')
	markers = result['result'].get('value')
	assert isinstance(markers, list)
	return markers


@pytest.fixture
async def loop_recording_agent(loop_browser_session: BrowserSession, httpserver: HTTPServer) -> Agent:
	"""Use registered actions, a local HTTP form, and the real Tools dispatcher."""
	page = '<html><body><label>Required value<input id="required" required></label><button>Submit</button></body></html>'
	for path in ('/form', '/next'):
		httpserver.expect_request(path).respond_with_data(page, content_type='text/html')
	httpserver.expect_request('/favicon.ico').respond_with_data('', status=204)
	await loop_browser_session.navigate_to(httpserver.url_for('/form'))
	session = await loop_browser_session.get_or_create_cdp_session()
	await session.cdp_client.send.Runtime.evaluate(
		params={'expression': 'localStorage.removeItem("loop_markers")'}, session_id=session.session_id
	)
	tools = Tools()

	@tools.action('Record that this action ran on the current page')
	async def record_marker(label: str, browser_session: BrowserSession) -> ActionResult:
		await _record_browser_marker(browser_session, label)
		return ActionResult(extracted_content=f'Recorded {label}')

	@tools.action('Navigate using the browser event API without a static sequence flag', param_model=NavigateAction)
	async def change_page(params: NavigateAction, browser_session: BrowserSession) -> ActionResult:
		await browser_session.navigate_to(params.url, new_tab=params.new_tab)
		return ActionResult(extracted_content=f'Opened {params.url}')

	@tools.action('Validate the required field, reporting or raising an error when empty')
	async def validate_required_field(raise_exception: bool, browser_session: BrowserSession) -> ActionResult:
		await _record_browser_marker(browser_session, 'validation')
		session = await browser_session.get_or_create_cdp_session()
		result = await session.cdp_client.send.Runtime.evaluate(
			params={'expression': 'document.getElementById("required").value', 'returnByValue': True},
			session_id=session.session_id,
		)
		assert not result.get('exceptionDetails')
		field_value = result['result'].get('value')
		assert isinstance(field_value, str)
		if not field_value:
			if raise_exception:
				raise ValueError('Required field is empty')
			return ActionResult(error='Required field is empty')
		return ActionResult(extracted_content='Required field is filled')

	@tools.action('Exercise invalid return-type handling after a custom action executes')
	async def invalid_result(browser_session: BrowserSession) -> int:
		await _record_browser_marker(browser_session, 'invalid_result')
		return 1

	return Agent(task='Test executed-action accounting', llm=create_mock_llm(), browser_session=loop_browser_session, tools=tools)


@pytest.mark.parametrize('results', [None, []])
async def test_loop_recording_ignores_plans_without_results(results: list[ActionResult] | None):
	"""Planning an action without executing it must not advance repetition statistics."""
	agent = Agent(task='Test an unexecuted plan', llm=create_mock_llm())
	agent.state.last_model_output = agent.AgentOutput.model_validate({'action': [{'click': {'index': 1}}]})
	agent.state.last_result = results
	agent._update_loop_detector_actions()
	assert agent.state.loop_detector.recent_action_hashes == []


@pytest.mark.parametrize('stop_reason', ['static', 'url', 'focus', 'error', 'exception', 'invalid_result', 'done', 'later_done'])
async def test_loop_recording_excludes_unexecuted_batch_tail(
	loop_recording_agent: Agent, httpserver: HTTPServer, stop_reason: str
):
	"""A real multi_act early exit must not count queued tools that were never called."""
	agent = loop_recording_agent
	first_action: dict[str, dict[str, Any]] = {'record_marker': {'label': 'first'}}
	expected_markers = ['first']
	initial_focus = agent.browser_session.agent_focus_target_id
	if stop_reason == 'static':
		first_action = {'navigate': {'url': httpserver.url_for('/next')}}
		expected_markers = []
	elif stop_reason in {'url', 'focus'}:
		first_action = {
			'change_page': {
				'url': httpserver.url_for('/form' if stop_reason == 'focus' else '/next'),
				'new_tab': stop_reason == 'focus',
			}
		}
		expected_markers = []
	elif stop_reason in {'error', 'exception'}:
		first_action = {'validate_required_field': {'raise_exception': stop_reason == 'exception'}}
		expected_markers = ['validation']
	elif stop_reason == 'invalid_result':
		first_action = {'invalid_result': {}}
		expected_markers = ['invalid_result']
	elif stop_reason == 'done':
		first_action = {'done': {'text': 'Finished', 'success': True}}
		expected_markers = []

	planned_actions = [first_action]
	if stop_reason == 'later_done':
		planned_actions.append({'done': {'text': 'Finished', 'success': True}})
	planned_actions.append({'record_marker': {'label': 'skipped'}})
	agent.state.last_model_output = agent.AgentOutput.model_validate({'action': planned_actions})
	# One more false count for the skipped marker would trigger the first repetition nudge.
	for _ in range(4):
		agent.state.loop_detector.record_action('record_marker', {'label': 'skipped'})
	prior_hashes = list(agent.state.loop_detector.recent_action_hashes)

	await agent._execute_actions()
	agent._update_loop_detector_actions()

	assert await _read_browser_markers(agent.browser_session) == expected_markers
	assert agent.state.last_result is not None and len(agent.state.last_result) == 1
	if stop_reason in {'error', 'exception', 'invalid_result'}:
		assert agent.state.last_result[0].error is not None
	else:
		assert agent.state.last_result[0].error is None
	if stop_reason in {'static', 'url'}:
		assert await agent.browser_session.get_current_page_url() == httpserver.url_for('/next')
	if stop_reason == 'focus':
		assert await agent.browser_session.get_current_page_url() == httpserver.url_for('/form')
		assert agent.browser_session.agent_focus_target_id != initial_focus
	expected_hashes = list(prior_hashes)
	if stop_reason != 'done':
		action_name, params = next(iter(first_action.items()))
		expected_hashes.append(compute_action_hash(action_name, params))
	assert agent.state.loop_detector.recent_action_hashes == expected_hashes
	assert agent.state.loop_detector.get_nudge_message() is None


@pytest.mark.parametrize('successful_actions', [0, 1])
async def test_loop_recording_ignores_pre_dispatch_callback_errors(loop_recording_agent: Agent, successful_actions: int):
	"""A real stop-check callback can fail before dispatch without creating another tool attempt."""
	agent = loop_recording_agent
	agent.state.last_model_output = agent.AgentOutput.model_validate(
		{'action': [{'record_marker': {'label': label}} for label in ('first', 'second', 'skipped')]}
	)
	callback_calls = 0

	async def failing_stop_check() -> bool:
		nonlocal callback_calls
		callback_calls += 1
		if callback_calls > successful_actions:
			raise ValueError('External stop check failed')
		return False

	agent.register_should_stop_callback = failing_stop_check

	await agent._execute_actions()
	agent._update_loop_detector_actions()

	assert await _read_browser_markers(agent.browser_session) == (['first'] if successful_actions else [])
	assert callback_calls == successful_actions + 1
	assert agent.state.last_result is not None and len(agent.state.last_result) == successful_actions + 1
	assert agent.state.last_result[-1].error == 'ValueError: External stop check failed'
	assert (agent.state.last_result[-1].metadata or {}).get('action_skipped') is True
	expected_hashes = [compute_action_hash('record_marker', {'label': 'first'})] if successful_actions else []
	assert agent.state.loop_detector.recent_action_hashes == expected_hashes


async def test_loop_recording_ignores_error_after_an_already_recorded_result():
	"""A synthetic post-action error must not be attributed to the next planned action."""
	agent = Agent(task='Test a post-action error result', llm=create_mock_llm())
	agent.state.last_model_output = agent.AgentOutput.model_validate(
		{'action': [{'click': {'index': index}} for index in (1, 2)]}
	)
	agent.state.last_result = [
		ActionResult(extracted_content='First action completed'),
		ActionResult(error='Post-action page check failed', metadata={'action_skipped': True}),
	]
	agent._update_loop_detector_actions()
	assert agent.state.loop_detector.recent_action_hashes == [compute_action_hash('click', {'index': 1})]


async def test_loop_recording_keeps_all_executed_repetitions(loop_recording_agent: Agent):
	"""Successful repeated tool calls still produce the existing advisory nudge."""
	agent = loop_recording_agent
	agent.state.last_model_output = agent.AgentOutput.model_validate({'action': [{'record_marker': {'label': 'same'}}] * 5})

	await agent._execute_actions()
	agent._update_loop_detector_actions()

	assert await _read_browser_markers(agent.browser_session) == ['same'] * 5
	assert agent.state.last_result is not None and len(agent.state.last_result) == 5
	assert all(result.error is None for result in agent.state.last_result)
	assert agent.state.loop_detector.recent_action_hashes == [compute_action_hash('record_marker', {'label': 'same'})] * 5
	assert agent.state.loop_detector.get_nudge_message() is not None
