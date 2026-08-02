"""Tests for inline task planning feature.

Covers: plan generation, step advancement, replanning, rendering,
disabled planning, replan nudge, flash mode schema, and edge cases.
"""

import json

from browser_use.agent.views import (
	AgentOutput,
	PlanNodeStatus,
	PlanState,
	PlanStep,
	PlanUpdateStep,
)
from browser_use.tools.service import Tools

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_plan_state(descriptions: list[str], completed_up_to: int = -1) -> PlanState:
	"""Create a PlanState with linear steps (no alternatives) for testing."""
	steps = []
	for i, text in enumerate(descriptions):
		if i < completed_up_to:
			status = PlanNodeStatus.COMPLETED
		elif i == completed_up_to or (completed_up_to == -1 and i == 0):
			status = PlanNodeStatus.CURRENT
		else:
			status = PlanNodeStatus.PENDING
		steps.append(
			PlanStep(
				description=text,
				step_number=i,
				status=status,
			)
		)
	return PlanState(
		steps=steps,
		current_step_index=max(0, completed_up_to) if completed_up_to >= 0 else 0,
		created_at_step=0,
	)


def _make_agent_output(**overrides) -> AgentOutput:
	"""Build a minimal AgentOutput with plan fields."""
	tools = Tools()
	ActionModel = tools.registry.create_action_model()
	OutputType = AgentOutput.type_with_custom_actions(ActionModel)
	# Convert plan_update strings to PlanUpdateStep objects
	po = overrides.get('plan_update')
	if po is not None and po and isinstance(po[0], str):
		overrides['plan_update'] = [PlanUpdateStep(description=s) for s in po]
	action_json = json.dumps(
		{
			'evaluation_previous_goal': 'Success',
			'memory': 'mem',
			'next_goal': 'goal',
			**{
				k: [s.model_dump() for s in v] if k == 'plan_update' and v and isinstance(v[0], PlanUpdateStep) else v
				for k, v in overrides.items()
				if k in ('plan_update',)
			},
			'action': [{'done': {'text': 'ok', 'success': True}}],
		}
	)
	return OutputType.model_validate_json(action_json)


def _make_agent(browser_session, mock_llm, **kwargs):
	"""Create an Agent with defaults suitable for unit tests."""
	from browser_use import Agent

	return Agent(task='Test task', llm=mock_llm, browser_session=browser_session, **kwargs)


# ---------------------------------------------------------------------------
# 1. Plan generation from plan_update on step 1
# ---------------------------------------------------------------------------


async def test_plan_generation_from_plan_update(browser_session, mock_llm):
	agent = _make_agent(browser_session, mock_llm)
	output = _make_agent_output(plan_update=['Navigate to page', 'Search for item', 'Extract price'])

	agent._update_plan_from_model_output(output)

	ps = agent.state.plan_state
	assert ps is not None
	assert len(ps.steps) == 3
	assert ps.steps[0].status == PlanNodeStatus.CURRENT
	assert ps.steps[1].status == PlanNodeStatus.PENDING
	assert ps.steps[2].status == PlanNodeStatus.PENDING
	assert ps.current_step_index == 0
	assert ps.created_at_step == agent.state.n_steps


# ---------------------------------------------------------------------------
# 2. Plan step advancement via current_plan_item
# ---------------------------------------------------------------------------


async def test_step_advancement_via_completed(browser_session, mock_llm):
	agent = _make_agent(browser_session, mock_llm)
	agent.state.plan_state = _make_plan_state(['Step A', 'Step B', 'Step C'], completed_up_to=0)

	# Simulate step completion
	ps = agent.state.plan_state
	assert ps.advance_step() is True

	assert ps.steps[0].status == PlanNodeStatus.COMPLETED
	assert ps.steps[1].status == PlanNodeStatus.CURRENT
	assert ps.steps[2].status == PlanNodeStatus.PENDING
	assert ps.current_step_index == 1


# ---------------------------------------------------------------------------
# 3. Replanning replaces old plan
# ---------------------------------------------------------------------------


async def test_replanning_replaces_old_plan(browser_session, mock_llm):
	agent = _make_agent(browser_session, mock_llm)
	agent.state.plan_state = _make_plan_state(['Old step 1', 'Old step 2'], completed_up_to=0)

	output = _make_agent_output(plan_update=['New step A', 'New step B', 'New step C'])
	agent._update_plan_from_model_output(output)

	ps = agent.state.plan_state
	assert ps is not None
	assert len(ps.steps) == 3
	assert ps.steps[0].description == 'New step A'
	# first step of new plan marked as current, rest pending
	assert ps.steps[0].status == PlanNodeStatus.CURRENT
	assert ps.steps[1].status == PlanNodeStatus.PENDING
	assert ps.steps[2].status == PlanNodeStatus.PENDING
	assert ps.current_step_index == 0


# ---------------------------------------------------------------------------
# 4. _render_plan_description output format
# ---------------------------------------------------------------------------


async def test_render_plan_description(browser_session, mock_llm):
	agent = _make_agent(browser_session, mock_llm)
	agent.state.plan_state = PlanState(
		steps=[
			PlanStep(description='Navigate to search page', step_number=0, status=PlanNodeStatus.COMPLETED),
			PlanStep(description='Search for "laptop"', step_number=1, status=PlanNodeStatus.CURRENT),
			PlanStep(description='Extract price from results', step_number=2, status=PlanNodeStatus.PENDING),
			PlanStep(description='Skipped step', step_number=3, status=PlanNodeStatus.SKIPPED),
		],
		current_step_index=1,
		created_at_step=0,
	)

	result = agent._render_plan_description()
	assert result is not None
	lines = result.split('\n')
	assert '[✓]' in lines[0] and 'Navigate to search page' in lines[0]
	assert '[→]' in lines[1] and 'Search for' in lines[1] and 'laptop' in lines[1]
	assert '[ ]' in lines[2] and 'Extract' in lines[2]
	assert '[-]' in lines[3] and 'Skipped' in lines[3]


# ---------------------------------------------------------------------------
# 5. Planning disabled returns None
# ---------------------------------------------------------------------------


async def test_planning_disabled_returns_none(browser_session, mock_llm):
	agent = _make_agent(browser_session, mock_llm, enable_planning=False)
	agent.state.plan_state = _make_plan_state(['Should not render'])

	assert agent._render_plan_description() is None

	# Also verify update is a no-op
	output = _make_agent_output(plan_update=['New plan'])
	agent._update_plan_from_model_output(output)
	# Plan should remain unchanged (the method returns early)
	assert agent.state.plan_state.steps[0].description == 'Should not render'


# ---------------------------------------------------------------------------
# 6. Replan nudge injection at threshold
# ---------------------------------------------------------------------------


async def test_replan_nudge_injected_at_threshold(browser_session, mock_llm):
	agent = _make_agent(browser_session, mock_llm, planning_replan_on_stall=3)
	agent.state.plan_state = _make_plan_state(['Step 1'], completed_up_to=0)
	agent.state.plan_state.consecutive_failures = 3

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
	agent.state.plan_state = _make_plan_state(['Step 1'], completed_up_to=0)
	agent.state.plan_state.consecutive_failures = 2

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
	# current_plan_item field removed in hierarchical planning refactor
	assert 'plan_update' not in schema['properties']
	assert 'thinking' not in schema['properties']


# ---------------------------------------------------------------------------
# 9. Full mode schema includes plan fields as optional
# ---------------------------------------------------------------------------


async def test_full_mode_schema_includes_plan_fields_optional():
	tools = Tools()
	ActionModel = tools.registry.create_action_model()
	FullOutput = AgentOutput.type_with_custom_actions(ActionModel)

	schema = FullOutput.model_json_schema()
	# current_plan_item field removed in hierarchical planning refactor
	assert 'plan_update' in schema['properties']
	# They should NOT be in required
	# current_plan_item field removed
	assert 'plan_update' not in schema.get('required', [])


# ---------------------------------------------------------------------------
# 10. Out-of-bounds current_plan_item handled gracefully
# ---------------------------------------------------------------------------


async def test_plan_state_not_initialized_returns_none(browser_session, mock_llm):
	agent = _make_agent(browser_session, mock_llm)
	assert agent.state.plan_state is None
	assert agent._render_plan_description() is None
	initial_count = len(agent._message_manager.state.history.context_messages)
	agent._inject_replan_nudge()
	after_count = len(agent._message_manager.state.history.context_messages)
	assert after_count == initial_count


# ---------------------------------------------------------------------------
# 11. No plan means render returns None
# ---------------------------------------------------------------------------


async def test_no_plan_state_render_returns_none(browser_session, mock_llm):
	agent = _make_agent(browser_session, mock_llm)
	assert agent.state.plan_state is None
	assert agent._render_plan_description() is None


# ---------------------------------------------------------------------------
# 12. Replan nudge disabled when planning_replan_on_stall=0
# ---------------------------------------------------------------------------


async def test_replan_nudge_disabled_when_zero(browser_session, mock_llm):
	agent = _make_agent(browser_session, mock_llm, planning_replan_on_stall=0)
	agent.state.plan_state = _make_plan_state(['Step 1'], completed_up_to=0)
	agent.state.plan_state.consecutive_failures = 100  # high but doesn't matter

	initial_count = len(agent._message_manager.state.history.context_messages)
	agent._inject_replan_nudge()
	after_count = len(agent._message_manager.state.history.context_messages)
	assert after_count == initial_count


# ---------------------------------------------------------------------------
# 13. No nudge when no plan exists
# ---------------------------------------------------------------------------


async def test_no_replan_nudge_without_plan(browser_session, mock_llm):
	agent = _make_agent(browser_session, mock_llm, planning_replan_on_stall=1)
	# plan_state is None → _inject_replan_nudge returns immediately

	initial_count = len(agent._message_manager.state.history.context_messages)
	agent._inject_replan_nudge()
	after_count = len(agent._message_manager.state.history.context_messages)
	assert after_count == initial_count


# ---------------------------------------------------------------------------
# 14. Exploration nudge fires when no plan exists after N steps
# ---------------------------------------------------------------------------


async def test_exploration_nudge_fires_after_limit(browser_session, mock_llm):
	agent = _make_agent(browser_session, mock_llm, planning_exploration_limit=3)
	agent.state.plan_state = None
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
	agent.state.plan_state = _make_plan_state(['Step 1'], completed_up_to=0)
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
	agent.state.plan_state = None
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
	agent.state.plan_state = None
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
	agent.state.plan_state = None
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
