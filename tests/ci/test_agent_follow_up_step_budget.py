from unittest.mock import AsyncMock, patch

from browser_use import Agent
from browser_use.agent.views import AgentStepInfo


async def test_follow_up_run_has_its_own_step_budget(browser_session, mock_llm):
	started_tasks = []

	async def record_started_task(agent):
		started_tasks.append(agent.task)

	agent = Agent(
		task='Complete the first task',
		llm=mock_llm,
		browser_session=browser_session,
	)

	await agent.run(max_steps=1, on_step_start=record_started_task)

	agent.add_new_task('Complete the follow-up task')
	await agent.run(max_steps=1, on_step_start=record_started_task)

	assert started_tasks == ['Complete the first task', 'Complete the follow-up task']


async def test_follow_up_timeout_advances_global_step_counter(browser_session, mock_llm):
	agent = Agent(
		task='Complete the follow-up task',
		llm=mock_llm,
		browser_session=browser_session,
	)
	agent.state.n_steps = 2

	with patch.object(agent, 'step', AsyncMock(side_effect=TimeoutError)):
		await agent._execute_step(
			step=0,
			max_steps=1,
			step_info=AgentStepInfo(step_number=0, max_steps=1),
		)

	assert agent.state.n_steps == 3
