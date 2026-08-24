"""Step counter accounting when a step is cancelled by `step_timeout`.

A timed-out step must consume exactly one unit of the `max_steps` budget. The
cancelled `step()` may or may not have reached `_finalize()`'s `n_steps += 1`
(`_finalize()` early-returns when `last_result` is empty), so `_execute_step`
compensates by comparing against the counter captured at step start.
"""

import asyncio

import pytest

from browser_use import Agent
from browser_use.agent.views import AgentStepInfo

STEP_TIMEOUT = 1


class _CountingTimeoutAgent(Agent):
	"""Times out with the counter already advanced — cancellation unwinds through
	`step()`'s `finally`, where `_finalize()` runs its increment."""

	async def step(self, step_info: AgentStepInfo | None = None) -> None:
		try:
			await asyncio.sleep(STEP_TIMEOUT + 1)
		finally:
			self.state.n_steps += 1


class _SkippingTimeoutAgent(Agent):
	"""Times out with the counter untouched — `_finalize()` early-returns because
	`step()` cleared `last_result` before the LLM call."""

	async def step(self, step_info: AgentStepInfo | None = None) -> None:
		await asyncio.sleep(STEP_TIMEOUT + 1)


TIMEOUT_AGENTS = [_CountingTimeoutAgent, _SkippingTimeoutAgent]


def _make_agent(agent_cls: type[Agent], mock_llm) -> Agent:
	return agent_cls(task='probe', llm=mock_llm, directly_open_url=False, step_timeout=STEP_TIMEOUT)


@pytest.mark.parametrize('agent_cls', TIMEOUT_AGENTS)
async def test_step_timeout_consumes_exactly_one_step(agent_cls: type[Agent], mock_llm):
	"""`run()` always passes `step == n_steps - 1`; a timeout there advances the counter by exactly one."""
	agent = _make_agent(agent_cls, mock_llm)
	agent.state.n_steps = 3
	step = agent.state.n_steps - 1

	await agent._execute_step(step=step, max_steps=5, step_info=AgentStepInfo(step_number=step, max_steps=5))

	assert agent.state.n_steps == 4
	assert agent.state.consecutive_failures == 1  # only the TimeoutError handler sets this


@pytest.mark.parametrize('agent_cls', TIMEOUT_AGENTS)
async def test_step_timeout_accounting_ignores_caller_step_index(agent_cls: type[Agent], mock_llm):
	"""Compensation keys off the counter at step start, not the caller's 0-indexed step number."""
	agent = _make_agent(agent_cls, mock_llm)
	agent.state.n_steps = 1

	await agent._execute_step(step=7, max_steps=99, step_info=AgentStepInfo(step_number=7, max_steps=99))

	assert agent.state.n_steps == 2
	assert agent.state.consecutive_failures == 1
