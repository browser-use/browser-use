import asyncio

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
