"""Tests for step budget warning injection (IMP-7a)."""

from browser_use.agent.service import Agent
from browser_use.agent.views import AgentStepInfo
from browser_use.llm.messages import UserMessage
from tests.ci.conftest import create_mock_llm


def _get_context_messages(agent: Agent) -> list[str]:
	"""Extract text content from the agent's context messages."""
	msgs = agent._message_manager.state.history.context_messages
	return [m.content for m in msgs if isinstance(m, UserMessage) and isinstance(m.content, str)]


async def test_budget_warning_injected_at_75_percent():
	"""Budget warning should be injected when step >= 75% of max_steps."""
	llm = create_mock_llm()
	agent = Agent(task='Test task', llm=llm)

	step_info = AgentStepInfo(step_number=74, max_steps=100)  # step 75/100 = 75%
	await agent._inject_budget_warning(step_info)

	messages = _get_context_messages(agent)
	assert len(messages) == 1
	assert 'BUDGET WARNING' in messages[0]
	assert '75/100' in messages[0]
	assert '25 steps remaining' in messages[0]


async def test_budget_warning_injected_at_90_percent():
	"""Budget warning should fire at 90% too."""
	llm = create_mock_llm()
	agent = Agent(task='Test task', llm=llm)

	step_info = AgentStepInfo(step_number=89, max_steps=100)  # step 90/100 = 90%
	await agent._inject_budget_warning(step_info)

	messages = _get_context_messages(agent)
	assert len(messages) == 1
	assert 'BUDGET WARNING' in messages[0]
	assert '90/100' in messages[0]
	assert '10 steps remaining' in messages[0]


async def test_no_budget_warning_below_75_percent():
	"""No warning should be injected when step < 75% of max_steps."""
	llm = create_mock_llm()
	agent = Agent(task='Test task', llm=llm)

	step_info = AgentStepInfo(step_number=73, max_steps=100)  # step 74/100 = 74%
	await agent._inject_budget_warning(step_info)

	messages = _get_context_messages(agent)
	assert len(messages) == 0


async def test_no_budget_warning_on_last_step():
	"""No budget warning on the last step — _force_done_after_last_step handles that."""
	llm = create_mock_llm()
	agent = Agent(task='Test task', llm=llm)

	step_info = AgentStepInfo(step_number=99, max_steps=100)  # last step
	assert step_info.is_last_step()
	await agent._inject_budget_warning(step_info)

	messages = _get_context_messages(agent)
	assert len(messages) == 0


async def test_no_budget_warning_when_step_info_is_none():
	"""No warning when step_info is None."""
	llm = create_mock_llm()
	agent = Agent(task='Test task', llm=llm)

	await agent._inject_budget_warning(None)

	messages = _get_context_messages(agent)
	assert len(messages) == 0


async def test_budget_warning_exact_threshold():
	"""The warning should fire at exactly 75% (step 15/20)."""
	llm = create_mock_llm()
	agent = Agent(task='Test task', llm=llm)

	# step_number=14 means step 15 (1-indexed), 15/20 = 75%
	step_info = AgentStepInfo(step_number=14, max_steps=20)
	await agent._inject_budget_warning(step_info)

	messages = _get_context_messages(agent)
	assert len(messages) == 1
	assert '15/20' in messages[0]
	assert '5 steps remaining' in messages[0]


async def test_budget_warning_just_below_threshold():
	"""No warning at 74% — just below threshold."""
	llm = create_mock_llm()
	agent = Agent(task='Test task', llm=llm)

	# step_number=13 means step 14 (1-indexed), 14/20 = 70%
	step_info = AgentStepInfo(step_number=13, max_steps=20)
	await agent._inject_budget_warning(step_info)

	messages = _get_context_messages(agent)
	assert len(messages) == 0


async def test_budget_warning_small_max_steps():
	"""Budget warning works correctly with small max_steps values."""
	llm = create_mock_llm()
	agent = Agent(task='Test task', llm=llm)

	# step_number=3 means step 4 (1-indexed), 4/4 = 100% but is_last_step
	step_info = AgentStepInfo(step_number=3, max_steps=4)
	assert step_info.is_last_step()
	await agent._inject_budget_warning(step_info)
	messages = _get_context_messages(agent)
	assert len(messages) == 0  # last step, no warning

	# step_number=2 means step 3 (1-indexed), 3/4 = 75%
	step_info = AgentStepInfo(step_number=2, max_steps=4)
	await agent._inject_budget_warning(step_info)
	messages = _get_context_messages(agent)
	assert len(messages) == 1
	assert '3/4' in messages[0]


async def test_budget_warning_percentage_display():
	"""The percentage in the warning should be integer (no decimals)."""
	llm = create_mock_llm()
	agent = Agent(task='Test task', llm=llm)

	# step 76/100 = 76%
	step_info = AgentStepInfo(step_number=75, max_steps=100)
	await agent._inject_budget_warning(step_info)

	messages = _get_context_messages(agent)
	assert '76%' in messages[0]
	# Should not have decimal
	assert '76.0%' not in messages[0]


async def test_budget_warning_contains_actionable_guidance():
	"""The warning message should include actionable guidance for the agent."""
	llm = create_mock_llm()
	agent = Agent(task='Test task', llm=llm)

	step_info = AgentStepInfo(step_number=74, max_steps=100)
	await agent._inject_budget_warning(step_info)

	messages = _get_context_messages(agent)
	msg = messages[0]
	assert 'consolidate your results' in msg.lower()
	assert 'done' in msg.lower()
	assert 'partial results' in msg.lower()
