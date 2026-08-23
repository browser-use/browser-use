import asyncio
from typing import cast

import pytest

from browser_use import Agent
from browser_use.agent.views import AgentStepInfo
from browser_use.llm.base import BaseChatModel


class _FakeLLM:
	model = 'fake'
	provider = 'fake'
	name = 'fake'
	_verified_api_keys = True

	async def ainvoke(self, *_args, **_kwargs):
		return None


class _FinalizingTimedAgent(Agent):
	async def step(self, step_info: AgentStepInfo | None = None) -> None:
		try:
			await asyncio.sleep(2)
		finally:
			self.state.n_steps += 1


class _NonFinalizingTimedAgent(Agent):
	async def step(self, step_info: AgentStepInfo | None = None) -> None:
		await asyncio.sleep(2)


@pytest.mark.asyncio
async def test_step_timeout_does_not_double_count_after_finalization():
	agent = _FinalizingTimedAgent(
		task='probe',
		llm=cast(BaseChatModel, _FakeLLM()),
		directly_open_url=False,
		step_timeout=1,
	)
	agent.state.n_steps = 1
	await agent._execute_step(step=1, max_steps=5, step_info=AgentStepInfo(step_number=1, max_steps=5))

	assert agent.state.n_steps == 2


@pytest.mark.asyncio
async def test_step_timeout_advances_when_finalization_does_not_count():
	agent = _NonFinalizingTimedAgent(
		task='probe',
		llm=cast(BaseChatModel, _FakeLLM()),
		directly_open_url=False,
		step_timeout=1,
	)
	agent.state.n_steps = 1
	await agent._execute_step(step=1, max_steps=5, step_info=AgentStepInfo(step_number=1, max_steps=5))

	assert agent.state.n_steps == 2
