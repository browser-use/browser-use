import asyncio
import logging
import time
from typing import Any
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from browser_use.agent.service import Agent, PendingToolPause
from browser_use.agent.views import ActionModel, ActionResult, AgentHistory, AgentHistoryList, AgentStepInfo, PauseResult
from browser_use.browser.views import BrowserStateHistory, BrowserStateSummary
from browser_use.dom.views import SerializedDOMState
from browser_use.llm.base import BaseChatModel
from browser_use.llm.views import ChatInvokeCompletion
from browser_use.tools.service import Tools
from tests.ci.conftest import create_mock_llm


@pytest.fixture(autouse=True)
def _suppress_expected_agent_logs():
	"""Keep HITL pause unit tests focused on assertions, not lifecycle logs.

	The code paths under test intentionally emit pause_resumed/pause_cancelled and
	browser cleanup logs. Those logs are useful in production, but noisy in this
	unit test file because pytest log_cli prints them even when tests pass.
	"""

	previous_disable_level = logging.root.manager.disable
	logging.disable(logging.INFO)
	try:
		yield
	finally:
		logging.disable(previous_disable_level)


def _make_test_agent() -> Agent:
	return Agent(task='Test HITL pause', llm=create_mock_llm(actions=None))


def _install_pending_pause(agent: Agent, *, token: str = 'secret-token') -> PendingToolPause:
	loop = asyncio.get_running_loop()
	pause = PendingToolPause(
		token=token,
		pause_id='public-pause-id',
		step=1,
		action_index=0,
		tool_name='ask_approval',
		prompt='Approve?',
		reason='approval',
		created_at=time.time(),
		timeout=10.0,
		timeout_behavior='continue',
		metadata={'request_id': 'abc123'},
		loop=loop,
		future=loop.create_future(),
	)
	agent._pending_tool_pause = pause
	return pause


class _PauseActionModel(ActionModel):
	"""Minimal ActionModel slot for exercising Agent.multi_act() plumbing."""

	pause_action: dict[str, Any] | None = None
	followup_action: dict[str, Any] | None = None
	done: dict[str, Any] | None = None


def _make_recording_llm(actions: list[str], seen_messages: list[list[Any]]) -> BaseChatModel:
	"""Create a mock LLM that records each prompt and returns scripted JSON actions."""

	llm = AsyncMock(spec=BaseChatModel)
	llm.model = 'mock-llm'
	llm.provider = 'mock'
	llm.name = 'mock-llm'
	llm.model_name = 'mock-llm'
	llm._verified_api_keys = True
	action_index = 0

	async def _ainvoke(*args, **kwargs):
		nonlocal action_index
		messages = list(args[0]) if args else []
		seen_messages.append(messages)
		output_format = args[1] if len(args) >= 2 else kwargs.get('output_format')
		action_json = actions[min(action_index, len(actions) - 1)]
		action_index += 1
		if output_format is None:
			return ChatInvokeCompletion(completion=action_json, usage=None)
		return ChatInvokeCompletion(completion=output_format.model_validate_json(action_json), usage=None)

	llm.ainvoke.side_effect = _ainvoke
	return llm


def _empty_browser_state() -> BrowserStateSummary:
	return BrowserStateSummary(
		dom_state=SerializedDOMState(_root=None, selector_map={}),
		url='about:blank',
		title='Test page',
		tabs=[],
	)


def test_pause_result_is_importable_from_top_level_package():
	"""PauseResult should be part of the public browser_use API."""
	from browser_use import PauseResult, ToolPauseState

	pause = PauseResult(
		prompt='Approve payment?', reason='approval', timeout=300, timeout_behavior='stop', metadata={'request_id': 'abc123'}
	)
	state = ToolPauseState(
		token='secret-token',
		pause_id='public-pause-id',
		step=1,
		action_index=0,
		tool_name='ask_approval',
		prompt=pause.prompt,
		reason=pause.reason,
		created_at=123.0,
		timeout=pause.timeout,
		timeout_behavior=pause.timeout_behavior,
		metadata=pause.metadata,
	)

	assert pause.prompt == 'Approve payment?'
	assert pause.reason == 'approval'
	assert pause.timeout == 300
	assert pause.timeout_behavior == 'stop'
	assert state.token == 'secret-token'
	assert state.pause_id == 'public-pause-id'
	assert state.action_index == 0
	assert state.timeout_behavior == 'stop'


def test_pause_result_rejects_non_positive_timeout():
	"""PauseResult timeout must be positive when provided."""
	from browser_use.agent.views import PauseResult

	for timeout in (0, -1):
		with pytest.raises(ValidationError, match='PauseResult.timeout must be greater than 0 seconds'):
			PauseResult(prompt='Approve?', timeout=timeout)

	assert PauseResult(prompt='Approve?', timeout=None).timeout is None
	assert PauseResult(prompt='Approve?', timeout=0.1).timeout == 0.1


@pytest.mark.asyncio
async def test_tool_pause_query_resume_and_late_resume():
	"""External integrations can query a pending pause and resume it once with its secret token."""
	agent = _make_test_agent()
	try:
		assert agent.get_pending_tool_pause() is None
		assert await agent.resume_tool_pause('missing-token', 'ignored') is False

		pause = _install_pending_pause(agent)
		state = agent.get_pending_tool_pause()

		assert state is not None
		assert state.token == 'secret-token'
		assert state.pause_id == 'public-pause-id'
		assert state.step == 1
		assert state.action_index == 0
		assert state.tool_name == 'ask_approval'
		assert state.prompt == 'Approve?'
		assert state.reason == 'approval'
		assert state.timeout == 10.0
		assert state.timeout_behavior == 'continue'
		assert state.metadata == {'request_id': 'abc123'}

		assert await agent.resume_tool_pause('wrong-token', 'ignored') is False
		assert await agent.resume_tool_pause('secret-token', 'approved', source='unit-test') is True
		assert agent.get_pending_tool_pause() is None
		assert await agent.resume_tool_pause('secret-token', 'late answer') is False

		resolved = await pause.future
		assert isinstance(resolved, ActionResult)
		assert resolved.extracted_content == 'approved'
		assert resolved.include_extracted_content_only_once is True
		assert resolved.long_term_memory == 'External input received for tool ask_approval.'
		assert 'approved' not in resolved.long_term_memory
		assert resolved.metadata == {
			'tool_pause_resolved': True,
			'tool_pause_id': 'public-pause-id',
			'tool_name': 'ask_approval',
			'reason': 'approval',
		}
	finally:
		await agent.close()


@pytest.mark.asyncio
async def test_tool_pause_cancel_and_stop_reject_late_resume():
	"""Cancelled/stopped pauses complete with an error and cannot be resumed later."""
	agent = _make_test_agent()
	try:
		pause = _install_pending_pause(agent)

		assert await agent.cancel_tool_pause('wrong-token', 'ignored') is False
		assert await agent.cancel_tool_pause('secret-token', 'test cancel') is True
		assert agent.get_pending_tool_pause() is None
		assert await agent.resume_tool_pause('secret-token', 'late answer') is False

		cancelled = await pause.future
		assert isinstance(cancelled, ActionResult)
		assert cancelled.error == 'Tool pause cancelled: test cancel'

		stop_pause = _install_pending_pause(agent, token='stop-token')
		agent.stop()
		assert agent.get_pending_tool_pause() is None
		assert await agent.resume_tool_pause('stop-token', 'late answer') is False

		stopped = await stop_pause.future
		assert isinstance(stopped, ActionResult)
		assert stopped.error == 'Tool pause cancelled because agent stopped'
	finally:
		await agent.close()


@pytest.mark.asyncio
async def test_request_tool_pause_uses_secret_token_and_returns_no_action_placeholder():
	"""Requesting a pause should register runtime state without returning an ActionResult."""
	agent = _make_test_agent()
	try:
		registration_result = agent._request_tool_pause(
			PauseResult(prompt='Approve?', reason='approval', timeout=1.0, metadata={'request_id': 'abc123'}),
			'ask_approval',
			action_index=0,
		)
		state = agent.get_pending_tool_pause()

		assert registration_result is None
		assert state is not None
		assert state.tool_name == 'ask_approval'
		assert state.action_index == 0
		assert state.token != state.pause_id
		assert len(state.token) >= 32
		assert state.metadata == {'request_id': 'abc123'}
	finally:
		await agent.close()


@pytest.mark.asyncio
async def test_final_step_pause_resolves_as_current_action_result(monkeypatch: pytest.MonkeyPatch):
	"""A final-step pause is still the current action result and does not require a follow-up step."""
	agent = _make_test_agent()
	try:
		assert agent.browser_session is not None

		async def _current_url(_browser_session):
			return 'about:blank'

		monkeypatch.setattr(type(agent.browser_session), 'get_current_page_url', _current_url)

		async def _pause_act(**_kwargs):
			return PauseResult(prompt='Approve on final step?', timeout=2.0)

		agent.tools.act = _pause_act  # type: ignore[method-assign]

		async def _resume_when_pending():
			while True:
				pause = agent.get_pending_tool_pause()
				if pause is not None:
					break
				await asyncio.sleep(0.01)
			assert await agent.resume_tool_pause(pause.token, 'approved on final step') is True

		resume_task = asyncio.create_task(_resume_when_pending())
		results = await agent.multi_act([_PauseActionModel(pause_action={'x': 1})])
		await resume_task

		assert len(results) == 1
		assert results[0].extracted_content == 'approved on final step'
		assert agent.get_pending_tool_pause() is None
		assert agent._pending_tool_pause is None
	finally:
		await agent.close()


@pytest.mark.asyncio
async def test_resolved_tool_pause_history_does_not_expose_secret_token(tmp_path):
	"""Resolved action history may contain pause_id, but must not contain the secret resume token."""
	agent = _make_test_agent()
	try:
		registration_result = agent._request_tool_pause(PauseResult(prompt='Approve?', reason='approval'), 'ask_approval')
		state = agent.get_pending_tool_pause()
		assert registration_result is None
		assert state is not None
		assert agent._pending_tool_pause is not None
		pause = agent._pending_tool_pause

		assert await agent.resume_tool_pause(state.token, 'approved') is True
		resolved = await pause.future

		assert state.pause_id in str(resolved.model_dump())
		assert state.token not in str(resolved.model_dump())

		history = AgentHistoryList(
			history=[
				AgentHistory(
					model_output=None,
					result=[resolved],
					state=BrowserStateHistory(url='about:blank', title='Test page', tabs=[], interacted_element=[]),
				)
			]
		)
		serialized_history = str(history.model_dump())

		assert state.pause_id in serialized_history
		assert state.token not in serialized_history
		assert state.pause_id != state.token

		history_path = tmp_path / 'history.json'
		history.save_to_file(history_path)
		saved_history = history_path.read_text(encoding='utf-8')
		assert state.pause_id in saved_history
		assert state.token not in saved_history
	finally:
		await agent.close()


@pytest.mark.asyncio
async def test_request_tool_pause_rejects_second_pending_pause():
	"""Only one external tool pause may be pending because Phase 1 has a single resume token slot."""
	agent = _make_test_agent()
	try:
		first = _install_pending_pause(agent)

		second = agent._request_tool_pause(
			PauseResult(prompt='Second approval?', reason='approval'),
			'ask_second_approval',
		)

		assert second is not None
		assert second.error == 'Another tool pause is already pending'
		assert agent._pending_tool_pause is first
		state = agent.get_pending_tool_pause()
		assert state is not None
		assert state.token == 'secret-token'
		assert state.tool_name == 'ask_approval'
	finally:
		await agent.close()


@pytest.mark.asyncio
async def test_resume_tool_pause_merges_custom_action_result_metadata():
	"""Custom ActionResult resumes preserve caller data while adding pause correlation metadata."""
	agent = _make_test_agent()
	try:
		pause = _install_pending_pause(agent)
		custom_result = ActionResult(
			extracted_content='custom approved',
			include_extracted_content_only_once=True,
			long_term_memory='Custom resume summary without raw secret data.',
			metadata={'request_id': 'abc123', 'tool_pause_id': 'caller-cannot-spoof-pause-id'},
		)

		assert await agent.resume_tool_pause('secret-token', custom_result, source='unit-test') is True
		resolved = await pause.future

		assert resolved.extracted_content == 'custom approved'
		assert resolved.include_extracted_content_only_once is True
		assert resolved.long_term_memory == 'Custom resume summary without raw secret data.'
		assert resolved.metadata == {
			'request_id': 'abc123',
			'tool_pause_id': 'public-pause-id',
			'tool_pause_resolved': True,
			'tool_name': 'ask_approval',
			'reason': 'approval',
		}
		assert resolved is not custom_result
		assert custom_result.metadata == {'request_id': 'abc123', 'tool_pause_id': 'caller-cannot-spoof-pause-id'}
	finally:
		await agent.close()


@pytest.mark.asyncio
async def test_pause_lifecycle_logs_do_not_expose_token_or_raw_human_input(monkeypatch: pytest.MonkeyPatch):
	"""Lifecycle logs should expose only privacy-safe correlation fields."""
	agent = _make_test_agent()
	try:
		captured_logs: list[str] = []

		def _capture_info(message: str, *args, **_kwargs):
			captured_logs.append(message % args if args else message)

		monkeypatch.setattr(agent.logger, 'info', _capture_info)

		registration_result = agent._request_tool_pause(
			PauseResult(prompt='Approve?', reason='approval', timeout=1.0),
			'ask_approval',
		)
		state = agent.get_pending_tool_pause()
		assert state is not None
		assert registration_result is None

		raw_human_input = 'raw-human-secret-approval-text'
		raw_source_input = 'source-contains-raw-human-secret-approval-text'
		assert await agent.resume_tool_pause(state.token, raw_human_input, source=raw_source_input) is True

		log_text = '\n'.join(captured_logs)
		assert 'pause_requested' in log_text
		assert 'pause_resumed' in log_text
		assert state.pause_id in log_text
		assert state.token not in log_text
		assert raw_human_input not in log_text
		assert raw_source_input not in log_text
		assert 'source=provided' in log_text
	finally:
		await agent.close()


@pytest.mark.asyncio
async def test_close_cancels_pending_tool_pause():
	"""Closing an agent directly should resolve any pending tool pause future."""
	agent = _make_test_agent()
	pause = _install_pending_pause(agent)

	await agent.close()

	assert agent.get_pending_tool_pause() is None
	assert pause.future.done() is True
	closed = pause.future.result()
	assert closed.error == 'Tool pause cancelled because agent closed'


@pytest.mark.asyncio
async def test_resume_tool_pause_rejects_done_action_result_and_allows_cancel_cleanup():
	"""Phase 1 resumes cannot turn a pending pause into a run-terminating done action."""
	agent = _make_test_agent()
	try:
		pause = _install_pending_pause(agent)
		done_result = ActionResult(is_done=True, success=True, extracted_content='approved and done')

		assert await agent.resume_tool_pause('secret-token', done_result, source='unit-test') is False
		state = agent.get_pending_tool_pause()
		assert state is not None
		assert state.token == 'secret-token'
		assert pause.future.done() is False

		assert await agent.cancel_tool_pause('secret-token', 'cleanup after rejected done result') is True
		cancelled = await pause.future
		assert cancelled.error == 'Tool pause cancelled: cleanup after rejected done result'
	finally:
		await agent.close()


@pytest.mark.asyncio
async def test_take_step_waits_for_tool_pause_after_step(monkeypatch: pytest.MonkeyPatch):
	"""Manual take_step() should support the same in-step HITL pause flow as run()."""
	agent = _make_test_agent()
	try:
		assert agent.browser_session is not None

		async def _current_url(_browser_session):
			return 'about:blank'

		monkeypatch.setattr(type(agent.browser_session), 'get_current_page_url', _current_url)

		async def _pause_act(**_kwargs):
			return PauseResult(prompt='Approve during take_step?', timeout=2.0)

		agent.tools.act = _pause_act  # type: ignore[method-assign]

		async def _fake_step(_step_info=None):
			agent.state.last_result = await agent.multi_act([_PauseActionModel(pause_action={'x': 1})])

		monkeypatch.setattr(agent, 'step', _fake_step)

		async def _resume_after_pause_is_visible():
			while True:
				state = agent.get_pending_tool_pause()
				if state is not None:
					break
				await asyncio.sleep(0.01)
			assert await agent.resume_tool_pause(state.token, 'approved during take_step') is True

		resume_task = asyncio.create_task(_resume_after_pause_is_visible())
		done, valid = await agent.take_step(AgentStepInfo(step_number=1, max_steps=3))
		await asyncio.wait_for(resume_task, timeout=1)

		assert (done, valid) == (False, False)
		assert agent.get_pending_tool_pause() is None
		assert agent._pending_tool_pause is None
		assert agent.state.last_result is not None
		assert agent.state.last_result[0].extracted_content == 'approved during take_step'
	finally:
		await agent.close()


@pytest.mark.asyncio
async def test_multi_act_rejects_pause_result_when_tool_pause_not_allowed(monkeypatch: pytest.MonkeyPatch):
	"""Initial actions should not create pending tool pauses in Phase 1."""
	agent = _make_test_agent()
	try:
		assert agent.browser_session is not None

		async def _current_url(_browser_session):
			return 'about:blank'

		monkeypatch.setattr(type(agent.browser_session), 'get_current_page_url', _current_url)

		async def _pause_act(**_kwargs):
			return PauseResult(prompt='Approve initial action?')

		agent.tools.act = _pause_act  # type: ignore[method-assign]

		results = await agent.multi_act(
			[_PauseActionModel(pause_action={'x': 1})],
			allow_tool_pause=False,
			tool_pause_unsupported_error='Tool pause is not supported in initial_actions in Phase 1',
		)

		assert len(results) == 1
		assert results[0].error == 'Tool pause is not supported in initial_actions in Phase 1'
		assert agent.get_pending_tool_pause() is None
		assert agent._pending_tool_pause is None
	finally:
		await agent.close()


@pytest.mark.asyncio
async def test_history_rerun_rejects_pause_result_without_pending_pause(monkeypatch: pytest.MonkeyPatch):
	"""History replay should return a clear unsupported error instead of hanging on HITL pause."""
	agent = _make_test_agent()
	try:
		assert agent.browser_session is not None

		async def _browser_state(_browser_session, **_kwargs):
			return _empty_browser_state()

		monkeypatch.setattr(type(agent.browser_session), 'get_browser_state_summary', _browser_state)

		async def _pause_act(**_kwargs):
			return PauseResult(prompt='Approve replayed action?')

		agent.tools.act = _pause_act  # type: ignore[method-assign]

		history_item = AgentHistory(
			model_output=agent.AgentOutput(
				evaluation_previous_goal='Replay',
				memory=None,
				next_goal='Replay pause action',
				action=[{'navigate': {'url': 'https://example.com'}}],  # type: ignore[list-item]
			),
			result=[ActionResult()],
			state=BrowserStateHistory(url='about:blank', title='Replay', tabs=[], interacted_element=[None]),
		)

		results = await agent._execute_history_step(history_item, delay=0)

		assert len(results) == 1
		assert results[0].error == 'Tool pause is not supported during history rerun in Phase 1'
		assert agent.get_pending_tool_pause() is None
		assert agent._pending_tool_pause is None
	finally:
		await agent.close()


@pytest.mark.asyncio
async def test_multi_act_resolves_pause_result_in_current_action_and_continues(monkeypatch: pytest.MonkeyPatch):
	"""A PauseResult resolves to the current action result and does not break the remaining action sequence."""
	agent = _make_test_agent()
	try:
		assert agent.browser_session is not None

		async def _current_url(_browser_session):
			return 'about:blank'

		monkeypatch.setattr(type(agent.browser_session), 'get_current_page_url', _current_url)

		calls = 0

		async def _act(action: ActionModel, **_kwargs):
			nonlocal calls
			calls += 1
			action_data = action.model_dump(exclude_unset=True)
			if calls == 1:
				assert action_data.get('pause_action') is not None
				return PauseResult(prompt='Approve first action?', reason='approval', timeout=2.0)
			assert action_data.get('followup_action') is not None
			return ActionResult(extracted_content='second action executed')

		agent.tools.act = _act  # type: ignore[method-assign]

		async def _resume_when_pending():
			while True:
				pause = agent.get_pending_tool_pause()
				if pause is not None:
					break
				await asyncio.sleep(0.01)
			assert pause.action_index == 0
			assert await agent.resume_tool_pause(pause.token, 'approved first action') is True

		resume_task = asyncio.create_task(_resume_when_pending())
		results = await agent.multi_act(
			[
				_PauseActionModel(pause_action={'x': 1}),
				_PauseActionModel(followup_action={'x': 2}),
			],
		)
		await resume_task

		assert calls == 2
		assert len(results) == 2
		assert results[0].extracted_content == 'approved first action'
		assert results[1].extracted_content == 'second action executed'
		assert agent.get_pending_tool_pause() is None
		assert agent._pending_tool_pause is None
	finally:
		await agent.close()


@pytest.mark.asyncio
async def test_multi_act_resolves_two_pause_results_serially(monkeypatch: pytest.MonkeyPatch):
	"""Two pause actions in one multi_act() should resolve one-by-one without concurrent pending pauses."""
	agent = _make_test_agent()
	try:
		assert agent.browser_session is not None

		async def _current_url(_browser_session):
			return 'about:blank'

		monkeypatch.setattr(type(agent.browser_session), 'get_current_page_url', _current_url)

		calls = 0

		async def _act(action: ActionModel, **_kwargs):
			nonlocal calls
			calls += 1
			action_data = action.model_dump(exclude_unset=True)
			assert action_data.get('pause_action') is not None
			return PauseResult(prompt=f'Approve action {calls}?', reason='approval', timeout=2.0)

		agent.tools.act = _act  # type: ignore[method-assign]
		seen_pause_ids: list[str] = []

		async def _resume_two_pauses():
			for expected_index, response in enumerate(['approved first pause', 'approved second pause']):
				while True:
					pause = agent.get_pending_tool_pause()
					if pause is not None and pause.pause_id not in seen_pause_ids:
						break
					await asyncio.sleep(0.01)
				assert pause.action_index == expected_index
				seen_pause_ids.append(pause.pause_id)
				assert await agent.resume_tool_pause(pause.token, response, source='unit-test') is True

		resume_task = asyncio.create_task(_resume_two_pauses())
		results = await agent.multi_act(
			[
				_PauseActionModel(pause_action={'x': 1}),
				_PauseActionModel(pause_action={'x': 2}),
			],
		)
		await resume_task

		assert calls == 2
		assert len(results) == 2
		assert results[0].extracted_content == 'approved first pause'
		assert results[1].extracted_content == 'approved second pause'
		assert len(set(seen_pause_ids)) == 2
		assert agent.get_pending_tool_pause() is None
		assert agent._pending_tool_pause is None
	finally:
		await agent.close()


@pytest.mark.asyncio
async def test_multi_act_stops_before_later_pause_when_prior_action_changes_page(monkeypatch: pytest.MonkeyPatch):
	"""A normal ActionResult that changes page state must prevent later queued pause/actions from running."""
	agent = _make_test_agent()
	try:
		assert agent.browser_session is not None
		current_url = 'about:blank'

		async def _current_url(_browser_session):
			return current_url

		monkeypatch.setattr(type(agent.browser_session), 'get_current_page_url', _current_url)

		calls = 0

		async def _act(action: ActionModel, **_kwargs):
			nonlocal calls, current_url
			calls += 1
			if calls == 1:
				current_url = 'https://example.com/changed'
				return ActionResult(extracted_content='first action changed page')
			return PauseResult(prompt='This pause should not be requested')

		agent.tools.act = _act  # type: ignore[method-assign]

		results = await agent.multi_act(
			[
				_PauseActionModel(followup_action={'x': 1}),
				_PauseActionModel(pause_action={'x': 2}),
			],
		)

		assert calls == 1
		assert len(results) == 1
		assert results[0].extracted_content == 'first action changed page'
		assert agent.get_pending_tool_pause() is None
		assert agent._pending_tool_pause is None
	finally:
		await agent.close()


@pytest.mark.asyncio
async def test_multi_act_stops_after_pause_when_page_changes_during_external_wait(monkeypatch: pytest.MonkeyPatch):
	"""A resolved PauseResult should still run the normal post-action page-change guard."""
	agent = _make_test_agent()
	try:
		assert agent.browser_session is not None
		current_url = 'about:blank'

		async def _current_url(_browser_session):
			return current_url

		monkeypatch.setattr(type(agent.browser_session), 'get_current_page_url', _current_url)

		calls = 0

		async def _act(action: ActionModel, **_kwargs):
			nonlocal calls
			calls += 1
			if calls == 1:
				return PauseResult(prompt='Approve first action?', timeout=2.0)
			return ActionResult(extracted_content='second action should not execute')

		agent.tools.act = _act  # type: ignore[method-assign]

		async def _resume_after_page_change():
			nonlocal current_url
			while True:
				pause = agent.get_pending_tool_pause()
				if pause is not None:
					break
				await asyncio.sleep(0.01)
			current_url = 'https://example.com/changed-during-pause'
			assert await agent.resume_tool_pause(pause.token, 'approved after page changed') is True

		resume_task = asyncio.create_task(_resume_after_page_change())
		results = await agent.multi_act(
			[
				_PauseActionModel(pause_action={'x': 1}),
				_PauseActionModel(followup_action={'x': 2}),
			],
		)
		await resume_task

		assert calls == 1
		assert len(results) == 1
		assert results[0].extracted_content == 'approved after page changed'
		assert agent.get_pending_tool_pause() is None
		assert agent._pending_tool_pause is None
	finally:
		await agent.close()


@pytest.mark.asyncio
async def test_multi_act_stops_after_pause_resumes_with_action_result_error(monkeypatch: pytest.MonkeyPatch):
	"""A PauseResult resumed as an ActionResult(error=...) should inherit ActionResult short-circuit behavior."""
	agent = _make_test_agent()
	try:
		assert agent.browser_session is not None

		async def _current_url(_browser_session):
			return 'about:blank'

		monkeypatch.setattr(type(agent.browser_session), 'get_current_page_url', _current_url)

		calls = 0

		async def _act(action: ActionModel, **_kwargs):
			nonlocal calls
			calls += 1
			if calls == 1:
				return PauseResult(prompt='Approve first action?', timeout=2.0)
			return ActionResult(extracted_content='second action should not execute')

		agent.tools.act = _act  # type: ignore[method-assign]

		async def _resume_with_error():
			while True:
				pause = agent.get_pending_tool_pause()
				if pause is not None:
					break
				await asyncio.sleep(0.01)
			assert await agent.resume_tool_pause(pause.token, ActionResult(error='human rejected action')) is True

		resume_task = asyncio.create_task(_resume_with_error())
		results = await agent.multi_act(
			[
				_PauseActionModel(pause_action={'x': 1}),
				_PauseActionModel(followup_action={'x': 2}),
			],
		)
		await resume_task

		assert calls == 1
		assert len(results) == 1
		assert results[0].error == 'human rejected action'
		assert agent.get_pending_tool_pause() is None
		assert agent._pending_tool_pause is None
	finally:
		await agent.close()


@pytest.mark.asyncio
async def test_multi_act_pause_timeout_behavior_stop_stops_agent(monkeypatch: pytest.MonkeyPatch):
	"""timeout_behavior='stop' should stop the agent and prevent follow-up actions from running."""
	agent = _make_test_agent()
	try:
		assert agent.browser_session is not None

		async def _current_url(_browser_session):
			return 'about:blank'

		monkeypatch.setattr(type(agent.browser_session), 'get_current_page_url', _current_url)

		calls = 0

		async def _act(action: ActionModel, **_kwargs):
			nonlocal calls
			calls += 1
			action_data = action.model_dump(exclude_unset=True)
			assert action_data.get('pause_action') is not None
			return PauseResult(prompt='Approve?', timeout=0.01, timeout_behavior='stop')

		agent.tools.act = _act  # type: ignore[method-assign]

		results = await agent.multi_act(
			[
				_PauseActionModel(pause_action={'x': 1}),
				_PauseActionModel(followup_action={'x': 2}),
			],
		)

		assert calls == 1
		assert len(results) == 1
		assert results[0].error == 'Tool pause timed out after 0.01 seconds'
		assert agent.state.stopped is True
		assert agent.get_pending_tool_pause() is None
		assert agent._pending_tool_pause is None
		assert await agent.resume_tool_pause('missing-or-late-token', 'late answer') is False
	finally:
		await agent.close()


@pytest.mark.asyncio
async def test_run_stops_after_pause_timeout_behavior_stop_without_next_llm_turn(monkeypatch: pytest.MonkeyPatch):
	"""timeout_behavior='stop' should stop the run loop, not merely return an action error."""
	tools = Tools()

	@tools.action('Ask a human to approve before continuing')
	async def ask_approval() -> PauseResult:
		return PauseResult(prompt='Approve?', reason='approval', timeout=0.01, timeout_behavior='stop')

	seen_messages: list[list[Any]] = []
	llm = _make_recording_llm(
		[
			"""
			{
				"thinking": "Need approval",
				"evaluation_previous_goal": "Starting",
				"memory": "Need external approval",
				"next_goal": "Ask for approval",
				"action": [{"ask_approval": {}}]
			}
			""",
			"""
			{
				"thinking": "Should not run",
				"evaluation_previous_goal": "Bypassed approval",
				"memory": "This turn should not happen",
				"next_goal": "Finish",
				"action": [{"done": {"text": "Should not happen", "success": true}}]
			}
			""",
		],
		seen_messages,
	)
	agent = Agent(task='Test HITL pause stop timeout', llm=llm, tools=tools, step_timeout=1, use_judge=False)
	try:
		assert agent.browser_session is not None

		async def _start(_browser_session):
			return None

		async def _current_url(_browser_session):
			return 'about:blank'

		async def _browser_state(_browser_session, **_kwargs):
			return _empty_browser_state()

		async def _close():
			return None

		monkeypatch.setattr(type(agent.browser_session), 'start', _start)
		monkeypatch.setattr(type(agent.browser_session), 'get_current_page_url', _current_url)
		monkeypatch.setattr(type(agent.browser_session), 'get_browser_state_summary', _browser_state)
		monkeypatch.setattr(agent, 'close', _close)

		async def _pause_act(action: ActionModel, **_kwargs):
			action_data = action.model_dump(exclude_unset=True)
			if action_data.get('ask_approval') is not None:
				return PauseResult(prompt='Approve?', reason='approval', timeout=0.01, timeout_behavior='stop')
			return ActionResult(is_done=True, success=True, extracted_content='Should not happen')

		agent.tools.act = _pause_act  # type: ignore[method-assign]

		history = await agent.run(max_steps=3)

		assert agent.state.stopped is True
		assert len(seen_messages) == 1
		assert history.is_done() is False
		assert history.errors()[-1] == 'Tool pause timed out after 0.01 seconds'
		assert agent.get_pending_tool_pause() is None
		assert agent._pending_tool_pause is None
	finally:
		await agent.close()


@pytest.mark.asyncio
async def test_step_timeout_counts_active_time_before_pause(monkeypatch: pytest.MonkeyPatch):
	"""A tool cannot exceed active step_timeout before returning PauseResult and then hide in pause wait."""
	agent = Agent(task='Test active timeout before HITL pause', llm=create_mock_llm(actions=None), step_timeout=1)
	try:

		async def _fake_step(_step_info=None):
			# Simulate a synchronous/blocking tool that only requests HITL after the
			# active step budget has already been consumed.
			time.sleep(1.1)  # noqa: ASYNC251 - intentionally blocks to exercise active timeout accounting
			_install_pending_pause(agent)
			assert agent._pending_tool_pause is not None
			await agent._pending_tool_pause.future

		monkeypatch.setattr(agent, 'step', _fake_step)

		with pytest.raises(TimeoutError):
			await asyncio.wait_for(
				agent._run_step_with_suspendable_timeout(AgentStepInfo(step_number=0, max_steps=3)),
				timeout=2,
			)

		assert agent.get_pending_tool_pause() is None
		assert agent._pending_tool_pause is None
	finally:
		await agent.close()


@pytest.mark.asyncio
async def test_cancelled_suspendable_step_cleans_pending_pause(monkeypatch: pytest.MonkeyPatch):
	"""Cancelling the outer step runner must not leave the inner step task or pending pause alive."""
	agent = _make_test_agent()
	try:
		pause_started = asyncio.Event()

		async def _fake_step(_step_info=None):
			_install_pending_pause(agent)
			assert agent._pending_tool_pause is not None
			pause_started.set()
			await agent._pending_tool_pause.future

		monkeypatch.setattr(agent, 'step', _fake_step)

		step_task = asyncio.create_task(agent._run_step_with_suspendable_timeout(AgentStepInfo(step_number=0, max_steps=3)))
		await asyncio.wait_for(pause_started.wait(), timeout=1)

		step_task.cancel()
		with pytest.raises(asyncio.CancelledError):
			await step_task

		assert agent.get_pending_tool_pause() is None
		assert agent._pending_tool_pause is None
		assert await agent.resume_tool_pause('secret-token', 'late answer') is False
	finally:
		await agent.close()


@pytest.mark.asyncio
async def test_run_resumes_tool_pause_and_next_llm_turn_sees_human_response(monkeypatch: pytest.MonkeyPatch):
	"""A tool PauseResult is resumed and injected into the next LLM turn."""
	tools = Tools()

	@tools.action('Ask a human to approve the operation')
	async def ask_approval() -> PauseResult:
		return PauseResult(prompt='Approve?', reason='approval', timeout=2.0)

	seen_messages: list[list[Any]] = []
	llm = _make_recording_llm(
		[
			"""
			{
				"thinking": "Need approval",
				"evaluation_previous_goal": "Starting",
				"memory": "Need external approval",
				"next_goal": "Ask for approval",
				"action": [{"ask_approval": {}}]
			}
			""",
			"""
			{
				"thinking": "Approval received",
				"evaluation_previous_goal": "Approval was received",
				"memory": "Human approved the operation",
				"next_goal": "Finish",
				"action": [{"done": {"text": "Saw approval", "success": true}}]
			}
			""",
		],
		seen_messages,
	)
	agent = Agent(task='Test HITL pause e2e', llm=llm, tools=tools, step_timeout=1, use_judge=False)
	try:
		assert agent.browser_session is not None

		async def _start(_browser_session):
			return None

		async def _current_url(_browser_session):
			return 'about:blank'

		async def _browser_state(_browser_session, **_kwargs):
			return _empty_browser_state()

		async def _close():
			return None

		monkeypatch.setattr(type(agent.browser_session), 'start', _start)
		monkeypatch.setattr(type(agent.browser_session), 'get_current_page_url', _current_url)
		monkeypatch.setattr(type(agent.browser_session), 'get_browser_state_summary', _browser_state)
		monkeypatch.setattr(agent, 'close', _close)

		async def _pause_act(action: ActionModel, **_kwargs):
			action_data = action.model_dump(exclude_unset=True)
			if action_data.get('ask_approval') is not None:
				return PauseResult(prompt='Approve?', reason='approval', timeout=2.0)
			return ActionResult(is_done=True, success=True, extracted_content='Saw approval')

		agent.tools.act = _pause_act  # type: ignore[method-assign]

		async def _resume_after_step_timeout_budget():
			while True:
				pause = agent.get_pending_tool_pause()
				if pause is not None:
					break
				await asyncio.sleep(0.01)
			await asyncio.sleep(1.1)
			assert await agent.resume_tool_pause(pause.token, 'approved by human') is True

		resume_task = asyncio.create_task(_resume_after_step_timeout_budget())
		history = await agent.run(max_steps=3)
		await resume_task

		assert all(error is None for error in history.errors())
		assert history.is_done()
		assert len(seen_messages) >= 2
		second_turn_text = '\n'.join(str(message) for message in seen_messages[1])
		assert 'approved by human' in second_turn_text
		assert 'Step 1 timed out after 1 seconds' not in '\n'.join(str(error) for error in history.errors() if error)
	finally:
		await agent.close()
