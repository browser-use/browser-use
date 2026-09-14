"""A follow-up task (add_new_task + run) must not inherit the previous run's failure count or done step."""

import asyncio
from typing import cast
from unittest.mock import AsyncMock

from browser_use import Agent
from browser_use.llm.exceptions import ModelProviderError
from tests.ci.conftest import create_mock_llm


async def test_follow_up_task_runs_after_previous_run_stopped_on_failures(browser_session):
	llm = create_mock_llm()  # answers with a done action
	ainvoke = cast(AsyncMock, llm.ainvoke)
	answer = ainvoke.side_effect
	calls = 0

	async def fail_first_call(*args, **kwargs):
		nonlocal calls
		calls += 1
		if calls == 1:
			raise ModelProviderError('provider unavailable', status_code=400, model='mock-llm')
		return await answer(*args, **kwargs)

	ainvoke.side_effect = fail_first_call
	agent = Agent(
		task='First task',
		llm=llm,
		browser_session=browser_session,
		max_failures=1,
		final_response_after_failure=False,
		use_judge=False,
	)

	first = await agent.run(max_steps=3)
	assert not first.is_done()
	assert calls == 1

	agent.add_new_task('Follow-up task')
	second = await agent.run(max_steps=3)

	assert calls == 2
	assert second.is_done()


async def test_follow_up_step_that_times_out_is_not_reported_done(browser_session):
	llm = create_mock_llm()  # answers with a done action
	ainvoke = cast(AsyncMock, llm.ainvoke)
	answer = ainvoke.side_effect
	slow = False

	async def answer_or_hang(*args, **kwargs):
		if slow:
			await asyncio.sleep(10)
		return await answer(*args, **kwargs)

	ainvoke.side_effect = answer_or_hang
	done_calls = 0

	def on_done(history):
		nonlocal done_calls
		done_calls += 1

	agent = Agent(
		task='First task',
		llm=llm,
		browser_session=browser_session,
		max_failures=1,
		final_response_after_failure=False,
		use_judge=False,
		register_done_callback=on_done,
	)

	first = await agent.run(max_steps=3)
	assert first.is_done()
	done_calls = 0

	slow = True
	agent.settings.step_timeout = 1
	agent.add_new_task('Follow-up task')
	await agent.run(max_steps=3)

	# The follow-up step timed out without an answer, so the first task's done step must not complete it.
	assert done_calls == 0
	assert agent.state.consecutive_failures == 1
