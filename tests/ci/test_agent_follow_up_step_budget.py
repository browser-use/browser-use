from browser_use import Agent
from browser_use.agent.views import AgentStepInfo, MessageCompactionSettings


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
	assert agent.state.n_steps == 2

	agent.add_new_task('Complete the follow-up task')
	await agent.run(max_steps=1, on_step_start=record_started_task)

	assert started_tasks == ['Complete the first task', 'Complete the follow-up task']
	assert agent.state.n_steps == 3


async def test_follow_up_keeps_compaction_cadence(browser_session, mock_llm):
	agent = Agent(
		task='Complete the first task',
		llm=mock_llm,
		browser_session=browser_session,
		message_compaction=MessageCompactionSettings(compact_every_n_steps=1, trigger_char_count=0),
	)

	await agent.run(max_steps=1)
	assert agent.state.message_manager_state.compaction_count == 0

	agent.add_new_task('Complete the follow-up task')
	await agent.run(max_steps=1)

	assert agent.state.message_manager_state.compaction_count == 1
	assert agent.state.message_manager_state.last_compaction_step == 1

	agent.add_new_task('Complete another follow-up task')
	await agent.run(max_steps=1)

	assert agent.state.message_manager_state.compaction_count == 2
	assert agent.state.message_manager_state.last_compaction_step == 2


async def test_follow_up_timeout_advances_global_step_counter(browser_session, mock_llm):
	agent = Agent(
		task='Complete the follow-up task',
		llm=mock_llm,
		browser_session=browser_session,
		step_timeout=0,
	)
	agent.state.n_steps = 2

	await agent._execute_step(
		step=0,
		max_steps=1,
		step_info=AgentStepInfo(step_number=0, max_steps=1),
	)

	assert agent.state.n_steps == 3
	assert agent.state.last_result is not None
	assert 'timed out' in (agent.state.last_result[0].error or '')
