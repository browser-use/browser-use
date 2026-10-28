"""Regression tests for action-executor rerun and recovery safety."""

import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from browser_use.agent.action_executor import ActionExecutor
from browser_use.agent.views import ActionResult, AgentHistoryList
from browser_use.tools.registry.views import ActionModel


class _ClickAction(ActionModel):
	click: dict[str, Any] | None = None


def _make_executor() -> tuple[ActionExecutor, MagicMock]:
	agent = MagicMock()
	agent.logger = logging.getLogger('test_action_executor')
	agent.settings.auto_recovery_max_attempts = 3
	agent.close = AsyncMock()
	agent.state.session_initialized = False
	return ActionExecutor(agent, MagicMock()), agent


@pytest.mark.asyncio
async def test_execute_history_step_handles_missing_interacted_element():
	executor, agent = _make_executor()
	agent.browser_session = MagicMock()
	agent.browser_session.get_browser_state_summary = AsyncMock(return_value=MagicMock())
	executor.multi_act = AsyncMock(return_value=[ActionResult(extracted_content='ok')])  # type: ignore[method-assign]

	history_item = MagicMock()
	history_item.model_output.action = [_ClickAction(click={'index': 5})]
	history_item.state.interacted_element = None

	results = await executor._execute_history_step(history_item, delay=0)

	assert results[0].extracted_content == 'ok'
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

	result = await executor._update_action_indices(historical, _ClickAction(click={'index': 5}), state)

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
async def test_rerun_treats_returned_action_error_as_failure(mock_sleep):
	executor, agent = _make_executor()
	agent.browser_session = MagicMock()
	agent.browser_session.start = AsyncMock()
	agent.task = 'task'
	executor._generate_rerun_summary = AsyncMock(return_value=ActionResult(extracted_content='summary'))  # type: ignore[method-assign]
	executor._execute_history_step = AsyncMock(return_value=[ActionResult(error='click failed')])  # type: ignore[method-assign]

	history_item = MagicMock()
	history_item.metadata = None
	history_item.result = []
	history_item.model_output.current_state.next_goal = 'goal'
	history = AgentHistoryList.model_construct(history=[history_item])

	results = await executor.rerun_history(history, max_retries=2, skip_failures=True, delay_between_actions=0)

	assert executor._execute_history_step.await_count == 2
	assert any(r.error and 'click failed' in r.error for r in results)
	assert results[-1].extracted_content == 'summary'
	agent.close.assert_awaited_once()
