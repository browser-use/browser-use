"""Regression tests for action-executor rerun and recovery safety."""

import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from browser_use.agent.action_executor import ActionExecutor, HistoryStepExecution
from browser_use.agent.views import ActionResult, AgentHistoryList
from browser_use.tools.registry.views import ActionModel
from browser_use.tools.views import ClickElementAction


class _ClickAction(ActionModel):
	click: ClickElementAction | None = None


class _GoBackAction(ActionModel):
	go_back: dict[str, Any] | None = None


def _make_executor() -> tuple[ActionExecutor, MagicMock]:
	agent = MagicMock()
	agent.logger = logging.getLogger('test_action_executor')
	agent.settings.auto_recovery_max_attempts = 3
	agent.close = AsyncMock()
	agent.state.session_initialized = False
	return ActionExecutor(agent, MagicMock()), agent


def _make_history_item(actions: list[ActionModel], interacted_element=None) -> MagicMock:
	history_item = MagicMock()
	history_item.metadata = None
	history_item.result = []
	history_item.model_output.current_state.next_goal = 'goal'
	history_item.model_output.action = actions
	history_item.state.interacted_element = interacted_element
	return history_item


@pytest.mark.asyncio
async def test_execute_history_step_rejects_missing_element_for_index_action():
	executor, agent = _make_executor()
	agent.browser_session = MagicMock()
	agent.browser_session.get_browser_state_summary = AsyncMock(return_value=MagicMock())
	executor.multi_act = AsyncMock(return_value=[ActionResult(extracted_content='ok')])  # type: ignore[method-assign]

	history_item = _make_history_item([_ClickAction(click=ClickElementAction(index=5))])

	outcome = await executor._execute_history_step(history_item, delay=0)

	assert outcome.error is not None
	assert outcome.failed_action_index == 0
	assert outcome.results == []
	executor.multi_act.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_history_step_allows_non_index_action_without_element():
	executor, agent = _make_executor()
	agent.browser_session = MagicMock()
	agent.browser_session.get_browser_state_summary = AsyncMock(return_value=MagicMock())
	executor.multi_act = AsyncMock(return_value=[ActionResult(extracted_content='ok')])  # type: ignore[method-assign]

	history_item = _make_history_item([_GoBackAction(go_back={})])

	outcome = await executor._execute_history_step(history_item, delay=0)

	assert outcome.error is None
	assert outcome.results[0].extracted_content == 'ok'
	executor.multi_act.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_action_indices_stays_within_recorded_frame():
	executor, _ = _make_executor()

	historical = MagicMock()
	historical.frame_id = 'frame-A'
	historical.element_hash = 1
	historical.stable_hash = None
	historical.x_path = '/html/body/button'
	historical.ax_name = None
	historical.attributes = {}
	historical.node_name = 'button'

	same_frame = MagicMock()
	same_frame.frame_id = 'frame-A'
	same_frame.element_hash = 2
	same_frame.xpath = '/html/body/other'
	same_frame.node_name = 'button'
	same_frame.attributes = {}

	# An identical control in a different iframe would match if cross-frame
	# entries were allowed.
	other_frame = MagicMock()
	other_frame.frame_id = 'frame-B'
	other_frame.element_hash = 1
	other_frame.xpath = historical.x_path
	other_frame.node_name = 'button'
	other_frame.attributes = {}

	state = MagicMock()
	state.dom_state.selector_map = {0: same_frame, 1: other_frame}

	result = await executor._update_action_indices(historical, _ClickAction(click=ClickElementAction(index=5)), state)

	assert result is None


@pytest.mark.asyncio
async def test_update_action_indices_remaps_changed_frame_id():
	executor, _ = _make_executor()

	historical = MagicMock()
	historical.frame_id = 'old-frame'
	historical.element_hash = 1
	historical.stable_hash = None
	historical.x_path = '/html/body/button'
	historical.ax_name = None
	historical.attributes = {}
	historical.node_name = 'button'

	new_frame = MagicMock()
	new_frame.frame_id = 'new-frame'
	new_frame.element_hash = 1
	new_frame.xpath = historical.x_path
	new_frame.node_name = 'button'
	new_frame.attributes = {}

	other_frame = MagicMock()
	other_frame.frame_id = 'other-frame'
	other_frame.element_hash = 2
	other_frame.xpath = '/html/body/other'
	other_frame.node_name = 'button'
	other_frame.attributes = {}

	state = MagicMock()
	state.dom_state.selector_map = {0: new_frame, 1: other_frame}

	result = await executor._update_action_indices(historical, _ClickAction(click=ClickElementAction(index=5)), state)

	assert result is not None
	assert result.get_index() == 0


@pytest.mark.asyncio
async def test_update_action_indices_ambiguous_frame_remap_returns_none():
	executor, _ = _make_executor()

	historical = MagicMock()
	historical.frame_id = 'old-frame'
	historical.element_hash = 1
	historical.stable_hash = None
	historical.x_path = '/html/body/button'
	historical.ax_name = None
	historical.attributes = {}
	historical.node_name = 'button'

	frame_a = MagicMock()
	frame_a.frame_id = 'frame-a'
	frame_a.element_hash = 1
	frame_a.xpath = historical.x_path
	frame_a.node_name = 'button'
	frame_a.attributes = {}

	frame_b = MagicMock()
	frame_b.frame_id = 'frame-b'
	frame_b.element_hash = 1
	frame_b.xpath = historical.x_path
	frame_b.node_name = 'button'
	frame_b.attributes = {}

	state = MagicMock()
	state.dom_state.selector_map = {0: frame_a, 1: frame_b}

	result = await executor._update_action_indices(historical, _ClickAction(click=ClickElementAction(index=5)), state)

	assert result is None


@pytest.mark.asyncio
async def test_rerun_history_closes_after_start_failure():
	executor, agent = _make_executor()
	agent.browser_session = MagicMock()
	agent.browser_session.start = AsyncMock(side_effect=RuntimeError('start failed'))

	with pytest.raises(RuntimeError, match='start failed'):
		await executor.rerun_history(AgentHistoryList(history=[]))

	agent.close.assert_awaited_once()


@pytest.mark.asyncio
@patch('browser_use.agent.action_executor.asyncio.sleep', new_callable=AsyncMock)
async def test_rerun_treats_returned_action_error_as_failure(_mock_sleep):
	executor, agent = _make_executor()
	agent.browser_session = MagicMock()
	agent.browser_session.start = AsyncMock()
	agent.task = 'task'
	executor._generate_rerun_summary = AsyncMock(return_value=ActionResult(extracted_content='summary'))  # type: ignore[method-assign]
	executor._execute_history_step = AsyncMock(  # type: ignore[method-assign]
		return_value=HistoryStepExecution(results=[], failed_action_index=0, error='click failed')
	)

	history = AgentHistoryList.model_construct(history=[_make_history_item([_GoBackAction(go_back={}), _GoBackAction(go_back={})])])

	results = await executor.rerun_history(history, max_retries=2, skip_failures=True, delay_between_actions=0)

	assert executor._execute_history_step.await_count == 2
	assert any(r.error and 'click failed' in r.error for r in results)
	assert results[-1].extracted_content == 'summary'
	agent.close.assert_awaited_once()


@pytest.mark.asyncio
@patch('browser_use.agent.action_executor.asyncio.sleep', new_callable=AsyncMock)
async def test_rerun_resumes_after_successful_prefix(_mock_sleep):
	executor, agent = _make_executor()
	agent.browser_session = MagicMock()
	agent.browser_session.start = AsyncMock()
	agent.task = 'task'
	executor._generate_rerun_summary = AsyncMock(return_value=ActionResult(extracted_content='summary'))  # type: ignore[method-assign]
	executor._execute_history_step = AsyncMock(  # type: ignore[method-assign]
		side_effect=[
			HistoryStepExecution(
				results=[ActionResult(extracted_content='add ok')],
				failed_action_index=1,
				error='checkout failed',
			),
			HistoryStepExecution(results=[ActionResult(extracted_content='checkout ok')]),
		]
	)

	history = AgentHistoryList.model_construct(
		history=[_make_history_item([_GoBackAction(go_back={}), _GoBackAction(go_back={})])]
	)

	results = await executor.rerun_history(history, max_retries=2, skip_failures=True, delay_between_actions=0)

	assert executor._execute_history_step.await_count == 2
	assert executor._execute_history_step.await_args_list[1].kwargs['start_index'] == 1
	assert [r.extracted_content for r in results if r.extracted_content] == ['add ok', 'checkout ok', 'summary']
	assert results[-1].extracted_content == 'summary'
	agent.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_count_expected_elements_skips_actions_before_start_index():
	executor, _ = _make_executor()
	history_item = _make_history_item(
		[
			_ClickAction(click=ClickElementAction(index=10)),
			_ClickAction(click=ClickElementAction(index=2)),
		]
	)

	assert executor._count_expected_elements_from_history(history_item) == 11
	assert executor._count_expected_elements_from_history(history_item, start_index=1) == 3
