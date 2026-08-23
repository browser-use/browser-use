import asyncio

import pytest

from browser_use import Agent


class _FakeLLM:
	model = 'fake'
	provider = 'fake'

	async def ainvoke(self, *_args, **_kwargs):
		return None


@pytest.mark.asyncio
async def test_step_timeout_does_not_double_count_after_finalization():
	agent = Agent(task='probe', llm=_FakeLLM(), directly_open_url=False)
	agent.settings.step_timeout = 0.01
	agent.state.n_steps = 1

	async def timed_step(_step_info):
		try:
			await asyncio.sleep(1)
		finally:
			agent.state.n_steps += 1

	agent.step = timed_step
	await agent._execute_step(step=1, max_steps=5, step_info=None)

	assert agent.state.n_steps == 2


@pytest.mark.asyncio
async def test_step_timeout_advances_when_finalization_does_not_count():
	agent = Agent(task='probe', llm=_FakeLLM(), directly_open_url=False)
	agent.settings.step_timeout = 0.01
	agent.state.n_steps = 1

	async def timed_step(_step_info):
		await asyncio.sleep(1)

	agent.step = timed_step
	await agent._execute_step(step=1, max_steps=5, step_info=None)

	assert agent.state.n_steps == 2
