"""Tests for inline task planning feature.

Covers: plan generation, step advancement, replanning, rendering,
disabled planning, replan nudge, flash mode schema, and edge cases.
"""

import json

from browser_use.agent.views import (
	ActionResult,
	AgentOutput,
	AgentStepInfo,
	PlanItem,
)
from browser_use.tools.service import Tools

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agent_output(**overrides) -> AgentOutput:
	"""Build a minimal AgentOutput with plan fields."""
	tools = Tools()
	ActionModel = tools.registry.create_action_model()
	OutputType = AgentOutput.type_with_custom_actions(ActionModel)
	action_json = json.dumps(
		{
			'evaluation_previous_goal': 'Success',
			'memory': 'mem',
			'next_goal': 'goal',
			**{k: v for k, v in overrides.items() if k in ('current_plan_item', 'plan_update')},
			'action': [{'done': {'text': 'ok', 'success': True}}],
		}
	)
	return OutputType.model_validate_json(action_json)


def _make_agent(browser_session, mock_llm, **kwargs):
	"""Create an Agent with defaults suitable for unit tests."""
	from browser_use import Agent

	task = kwargs.pop('task', 'Test task')
	return Agent(task=task, llm=mock_llm, browser_session=browser_session, **kwargs)


# ---------------------------------------------------------------------------
# 1. Plan generation from plan_update on step 1
# ---------------------------------------------------------------------------


async def test_plan_generation_from_plan_update(browser_session, mock_llm):
	agent = _make_agent(browser_session, mock_llm)
	output = _make_agent_output(plan_update=['Navigate to page', 'Search for item', 'Extract price'])

	agent._update_plan_from_model_output(output)

	assert agent.state.plan is not None
	assert len(agent.state.plan) == 3
	assert agent.state.plan[0].status == 'current'
	assert agent.state.plan[1].status == 'pending'
	assert agent.state.plan[2].status == 'pending'
	assert agent.state.current_plan_item_index == 0
	assert agent.state.plan_generation_step == agent.state.n_steps


# ---------------------------------------------------------------------------
# 2. Plan step advancement via current_plan_item
# ---------------------------------------------------------------------------


async def test_plan_step_advancement(browser_session, mock_llm):
	agent = _make_agent(browser_session, mock_llm)
	# Seed a plan
	agent.state.plan = [
		PlanItem(text='Step A', status='current'),
		PlanItem(text='Step B'),
		PlanItem(text='Step C'),
	]
	agent.state.current_plan_item_index = 0

	output = _make_agent_output(current_plan_item=2)
	agent._update_plan_from_model_output(output)

	assert agent.state.plan[0].status == 'done'
	assert agent.state.plan[1].status == 'done'
	assert agent.state.plan[2].status == 'current'
	assert agent.state.current_plan_item_index == 2


# ---------------------------------------------------------------------------
# 3. Replanning replaces old plan
# ---------------------------------------------------------------------------


async def test_replanning_replaces_old_plan(browser_session, mock_llm):
	agent = _make_agent(browser_session, mock_llm)
	agent.state.plan = [
		PlanItem(text='Old step 1', status='done'),
		PlanItem(text='Old step 2', status='current'),
	]
	agent.state.current_plan_item_index = 1
	agent.state.plan_generation_step = 1

	output = _make_agent_output(plan_update=['New step A', 'New step B', 'New step C'])
	agent._update_plan_from_model_output(output)

	assert len(agent.state.plan) == 3
	assert agent.state.plan[0].text == 'New step A'
	assert agent.state.plan[0].status == 'current'
	assert agent.state.current_plan_item_index == 0


# ---------------------------------------------------------------------------
# 4. _render_plan_description output format
# ---------------------------------------------------------------------------


async def test_render_plan_description(browser_session, mock_llm):
	agent = _make_agent(browser_session, mock_llm)
	agent.state.plan = [
		PlanItem(text='Navigate to search page', status='done'),
		PlanItem(text='Search for "laptop"', status='current'),
		PlanItem(text='Extract price from results', status='pending'),
		PlanItem(text='Skipped step', status='skipped'),
	]

	result = agent._render_plan_description()
	assert result is not None
	lines = result.split('\n')
	assert lines[0] == '[x] 0: Navigate to search page'
	assert lines[1] == '[>] 1: Search for "laptop"'
	assert lines[2] == '[ ] 2: Extract price from results'
	assert lines[3] == '[-] 3: Skipped step'


# ---------------------------------------------------------------------------
# 5. Planning disabled returns None
# ---------------------------------------------------------------------------


async def test_planning_disabled_returns_none(browser_session, mock_llm):
	agent = _make_agent(browser_session, mock_llm, enable_planning=False)
	agent.state.plan = [PlanItem(text='Should not render')]

	assert agent._render_plan_description() is None

	# Also verify update is a no-op
	output = _make_agent_output(plan_update=['New plan'])
	agent._update_plan_from_model_output(output)
	# Plan should remain unchanged (the method returns early)
	assert agent.state.plan[0].text == 'Should not render'


# ---------------------------------------------------------------------------
# 6. Replan nudge injection at threshold
# ---------------------------------------------------------------------------


async def test_replan_nudge_injected_at_threshold(browser_session, mock_llm):
	agent = _make_agent(browser_session, mock_llm, planning_replan_on_stall=3)
	agent.state.plan = [PlanItem(text='Step 1', status='current')]
	agent.state.consecutive_failures = 3

	# Track context messages
	initial_count = len(agent._message_manager.state.history.context_messages)
	agent._inject_replan_nudge()
	after_count = len(agent._message_manager.state.history.context_messages)

	assert after_count == initial_count + 1
	msg = agent._message_manager.state.history.context_messages[-1]
	assert isinstance(msg.content, str) and 'REPLAN SUGGESTED' in msg.content


# ---------------------------------------------------------------------------
# 7. No nudge below threshold
# ---------------------------------------------------------------------------


async def test_no_replan_nudge_below_threshold(browser_session, mock_llm):
	agent = _make_agent(browser_session, mock_llm, planning_replan_on_stall=3)
	agent.state.plan = [PlanItem(text='Step 1', status='current')]
	agent.state.consecutive_failures = 2

	initial_count = len(agent._message_manager.state.history.context_messages)
	agent._inject_replan_nudge()
	after_count = len(agent._message_manager.state.history.context_messages)

	assert after_count == initial_count


# ---------------------------------------------------------------------------
# 8. Flash mode schema excludes plan fields
# ---------------------------------------------------------------------------


async def test_flash_mode_schema_excludes_plan_fields():
	tools = Tools()
	ActionModel = tools.registry.create_action_model()
	FlashOutput = AgentOutput.type_with_custom_actions_flash_mode(ActionModel)

	schema = FlashOutput.model_json_schema()
	assert 'current_plan_item' not in schema['properties']
	assert 'plan_update' not in schema['properties']
	assert 'thinking' not in schema['properties']


async def test_flash_mode_can_include_compact_thinking():
	tools = Tools()
	ActionModel = tools.registry.create_action_model()
	FlashOutput = AgentOutput.type_with_custom_actions_flash_mode(ActionModel, include_thinking=True)

	schema = FlashOutput.model_json_schema()
	assert list(schema['properties'])[:2] == ['thinking', 'action']
	assert schema['required'] == ['thinking', 'action']
	assert 'evaluation_previous_goal' not in schema['properties']
	assert 'memory' not in schema['properties']
	assert 'next_goal' not in schema['properties']
	assert 'current_plan_item' not in schema['properties']
	assert 'plan_update' not in schema['properties']


# ---------------------------------------------------------------------------
# 9. Full mode schema includes plan fields as optional
# ---------------------------------------------------------------------------


async def test_full_mode_schema_includes_plan_fields_optional():
	tools = Tools()
	ActionModel = tools.registry.create_action_model()
	FullOutput = AgentOutput.type_with_custom_actions(ActionModel)

	schema = FullOutput.model_json_schema()
	assert 'current_plan_item' in schema['properties']
	assert 'plan_update' in schema['properties']
	# They should NOT be in required
	assert 'current_plan_item' not in schema.get('required', [])
	assert 'plan_update' not in schema.get('required', [])


# ---------------------------------------------------------------------------
# 10. Out-of-bounds current_plan_item handled gracefully
# ---------------------------------------------------------------------------


async def test_out_of_bounds_plan_step_clamped(browser_session, mock_llm):
	agent = _make_agent(browser_session, mock_llm)
	agent.state.plan = [
		PlanItem(text='Step A', status='current'),
		PlanItem(text='Step B'),
	]
	agent.state.current_plan_item_index = 0

	# Way out of bounds high
	output = _make_agent_output(current_plan_item=999)
	agent._update_plan_from_model_output(output)
	assert agent.state.current_plan_item_index == 1  # clamped to last valid index
	assert agent.state.plan[0].status == 'done'
	assert agent.state.plan[1].status == 'current'

	# Negative index
	agent.state.plan = [
		PlanItem(text='Step X', status='current'),
		PlanItem(text='Step Y'),
	]
	agent.state.current_plan_item_index = 1
	output2 = _make_agent_output(current_plan_item=-5)
	agent._update_plan_from_model_output(output2)
	assert agent.state.current_plan_item_index == 0  # clamped to 0
	assert agent.state.plan[0].status == 'current'


# ---------------------------------------------------------------------------
# 11. No plan means render returns None
# ---------------------------------------------------------------------------


async def test_no_plan_render_returns_none(browser_session, mock_llm):
	agent = _make_agent(browser_session, mock_llm)
	assert agent.state.plan is None
	assert agent._render_plan_description() is None


# ---------------------------------------------------------------------------
# 12. Replan nudge disabled when planning_replan_on_stall=0
# ---------------------------------------------------------------------------


async def test_replan_nudge_disabled_when_zero(browser_session, mock_llm):
	agent = _make_agent(browser_session, mock_llm, planning_replan_on_stall=0)
	agent.state.plan = [PlanItem(text='Step 1', status='current')]
	agent.state.consecutive_failures = 100  # high but doesn't matter

	initial_count = len(agent._message_manager.state.history.context_messages)
	agent._inject_replan_nudge()
	after_count = len(agent._message_manager.state.history.context_messages)
	assert after_count == initial_count


# ---------------------------------------------------------------------------
# 13. No nudge when no plan exists
# ---------------------------------------------------------------------------


async def test_no_replan_nudge_without_plan(browser_session, mock_llm):
	agent = _make_agent(browser_session, mock_llm, planning_replan_on_stall=1)
	agent.state.consecutive_failures = 5  # above threshold

	initial_count = len(agent._message_manager.state.history.context_messages)
	agent._inject_replan_nudge()
	after_count = len(agent._message_manager.state.history.context_messages)
	assert after_count == initial_count


# ---------------------------------------------------------------------------
# 14. Exploration nudge fires when no plan exists after N steps
# ---------------------------------------------------------------------------


async def test_exploration_nudge_fires_after_limit(browser_session, mock_llm):
	agent = _make_agent(browser_session, mock_llm, planning_exploration_limit=3)
	agent.state.plan = None
	agent.state.n_steps = 3  # at the limit

	initial_count = len(agent._message_manager.state.history.context_messages)
	agent._inject_exploration_nudge()
	after_count = len(agent._message_manager.state.history.context_messages)

	assert after_count == initial_count + 1
	msg = agent._message_manager.state.history.context_messages[-1]
	assert isinstance(msg.content, str) and 'PLANNING NUDGE' in msg.content


# ---------------------------------------------------------------------------
# 15. No exploration nudge when plan already exists
# ---------------------------------------------------------------------------


async def test_no_exploration_nudge_when_plan_exists(browser_session, mock_llm):
	agent = _make_agent(browser_session, mock_llm, planning_exploration_limit=3)
	agent.state.plan = [PlanItem(text='Step 1', status='current')]
	agent.state.n_steps = 10  # well above limit

	initial_count = len(agent._message_manager.state.history.context_messages)
	agent._inject_exploration_nudge()
	after_count = len(agent._message_manager.state.history.context_messages)
	assert after_count == initial_count


# ---------------------------------------------------------------------------
# 16. No exploration nudge below the limit
# ---------------------------------------------------------------------------


async def test_no_exploration_nudge_below_limit(browser_session, mock_llm):
	agent = _make_agent(browser_session, mock_llm, planning_exploration_limit=5)
	agent.state.plan = None
	agent.state.n_steps = 4  # below the limit

	initial_count = len(agent._message_manager.state.history.context_messages)
	agent._inject_exploration_nudge()
	after_count = len(agent._message_manager.state.history.context_messages)
	assert after_count == initial_count


# ---------------------------------------------------------------------------
# 17. Exploration nudge disabled when planning_exploration_limit=0
# ---------------------------------------------------------------------------


async def test_exploration_nudge_disabled_when_zero(browser_session, mock_llm):
	agent = _make_agent(browser_session, mock_llm, planning_exploration_limit=0)
	agent.state.plan = None
	agent.state.n_steps = 100  # high but doesn't matter

	initial_count = len(agent._message_manager.state.history.context_messages)
	agent._inject_exploration_nudge()
	after_count = len(agent._message_manager.state.history.context_messages)
	assert after_count == initial_count


# ---------------------------------------------------------------------------
# 18. Exploration nudge disabled when enable_planning=False
# ---------------------------------------------------------------------------


async def test_exploration_nudge_disabled_when_planning_off(browser_session, mock_llm):
	agent = _make_agent(browser_session, mock_llm, enable_planning=False, planning_exploration_limit=3)
	agent.state.plan = None
	agent.state.n_steps = 10  # above limit

	initial_count = len(agent._message_manager.state.history.context_messages)
	agent._inject_exploration_nudge()
	after_count = len(agent._message_manager.state.history.context_messages)
	assert after_count == initial_count


# ---------------------------------------------------------------------------
# 19. Flash mode forces enable_planning=False
# ---------------------------------------------------------------------------


async def test_flash_mode_disables_planning(browser_session, mock_llm):
	agent = _make_agent(browser_session, mock_llm, flash_mode=True)
	assert agent.settings.enable_planning is False
	assert agent.settings.use_thinking is False


async def test_flash_mode_thinking_is_explicit_opt_in(browser_session, mock_llm):
	agent = _make_agent(browser_session, mock_llm, flash_mode=True, flash_mode_thinking=True)
	assert agent.settings.enable_planning is False
	assert agent.settings.use_thinking is True
	assert 'thinking' in agent.AgentOutput.model_json_schema()['required']


async def test_flash_mode_thinking_supports_synthetic_initial_navigation(browser_session, mock_llm, monkeypatch):
	agent = _make_agent(
		browser_session,
		mock_llm,
		task='Open https://example.com',
		flash_mode=True,
		flash_mode_thinking=True,
	)

	async def fake_multi_act(_actions):
		return [ActionResult(long_term_memory='Navigated')]

	monkeypatch.setattr(agent, 'multi_act', fake_multi_act)
	await agent._execute_initial_actions()

	initial_output = agent.history.history[0].model_output
	assert initial_output is not None
	assert initial_output.thinking == 'The initial URL was loaded automatically; inspect the resulting page.'


async def test_thinking_only_flash_output_is_retained_as_recent_history(browser_session, mock_llm):
	agent = _make_agent(browser_session, mock_llm, flash_mode=True, flash_mode_thinking=True)
	output = agent.AgentOutput.model_validate(
		{
			'thinking': 'Items 1 and 2 are confirmed; item 3 is next.',
			'action': [{'done': {'text': 'partial', 'success': False}}],
		}
	)

	agent._message_manager._update_agent_history_description(
		model_output=output,
		step_info=AgentStepInfo(step_number=1, max_steps=10),
	)

	assert agent._message_manager.state.agent_history_items[-1].memory == output.thinking
