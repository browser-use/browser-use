import asyncio
from unittest.mock import AsyncMock

import pytest

from browser_use import Agent
from browser_use.agent.views import AgentStepInfo


@pytest.mark.asyncio
async def test_execute_step_excludes_paused_time_from_timeout(mock_llm, monkeypatch):
	agent = Agent(task='Test pause-aware step timeout.', llm=mock_llm, directly_open_url=False)
	agent.settings.step_timeout = 1
	step_completed = False

	async def pause_during_step(_step_info):
		nonlocal step_completed
		await asyncio.sleep(0.05)
		agent.pause()
		await asyncio.sleep(1.1)
		agent.resume()
		await asyncio.sleep(0.05)
		step_completed = True

	monkeypatch.setattr(agent, 'step', pause_during_step)
	step_info = AgentStepInfo(step_number=0, max_steps=1)

	await agent._execute_step(0, 1, step_info)

	assert step_completed
	assert agent.state.consecutive_failures == 0


@pytest.mark.asyncio
async def test_execute_step_still_times_out_active_work(mock_llm, monkeypatch):
	agent = Agent(task='Test active step timeout.', llm=mock_llm, directly_open_url=False)
	agent.settings.step_timeout = 1
	step_cancelled = False

	async def slow_active_step(_step_info):
		nonlocal step_cancelled
		try:
			await asyncio.sleep(2)
		except asyncio.CancelledError:
			step_cancelled = True
			raise

	monkeypatch.setattr(agent, 'step', slow_active_step)
	step_info = AgentStepInfo(step_number=0, max_steps=1)

	await agent._execute_step(0, 1, step_info)

	assert step_cancelled
	assert agent.state.consecutive_failures == 1
	assert agent.state.last_result is not None
	assert agent.state.last_result[0].error == 'Step 1 timed out after 1 seconds'


@pytest.mark.asyncio
async def test_stop_cancels_a_paused_in_flight_step(mock_llm, monkeypatch):
	agent = Agent(task='Test stopping a paused step.', llm=mock_llm, directly_open_url=False)
	agent.settings.step_timeout = 1
	step_paused = asyncio.Event()
	step_cancelled = False

	async def paused_step(_step_info):
		nonlocal step_cancelled
		agent.pause()
		step_paused.set()
		try:
			await asyncio.Event().wait()
		except asyncio.CancelledError:
			step_cancelled = True
			raise

	monkeypatch.setattr(agent, 'step', paused_step)
	step_info = AgentStepInfo(step_number=0, max_steps=1)
	execute_task = asyncio.create_task(agent._execute_step(0, 1, step_info))
	await asyncio.wait_for(step_paused.wait(), timeout=1)

	agent.stop()
	await asyncio.wait_for(execute_task, timeout=1)

	assert step_cancelled
	assert agent.state.consecutive_failures == 0


@pytest.mark.asyncio
async def test_stop_on_last_step_is_not_reported_as_max_steps_failure(mock_llm, monkeypatch):
	agent = Agent(
		task='Test stopping on the final allowed step.',
		llm=mock_llm,
		directly_open_url=False,
		enable_signal_handler=False,
	)
	monkeypatch.setattr(type(agent.browser_session), 'start', AsyncMock())
	monkeypatch.setattr(agent, 'close', AsyncMock())

	async def stop_on_last_step(_step, max_steps, _step_info, _on_step_start, _on_step_end):
		agent.state.n_steps = max_steps + 1
		agent.stop()
		return False

	monkeypatch.setattr(agent, '_execute_step', stop_on_last_step)

	history = await agent.run(max_steps=1)

	assert 'Failed to complete task in maximum steps' not in history.errors()
