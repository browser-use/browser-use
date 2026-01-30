"""
Tests for the agent action loop detection feature.

Verifies that _check_for_action_loop() correctly detects when the agent repeats
the same action on the same element multiple times and injects a warning message.
"""

import json

from browser_use.agent.service import Agent
from browser_use.agent.views import ActionResult, AgentHistory
from browser_use.browser.views import BrowserStateHistory
from tests.ci.conftest import create_mock_llm


def _make_action_json(action_type: str, **params) -> str:
	"""Build a JSON string for a mock LLM response with a single action."""
	return json.dumps(
		{
			'thinking': 'null',
			'evaluation_previous_goal': 'Attempting action',
			'memory': 'In progress',
			'next_goal': 'Continue',
			'action': [{action_type: params}],
		}
	)


def _make_history_entry(agent: Agent, action_type: str, **params) -> AgentHistory:
	"""Create a minimal AgentHistory entry with one action."""
	action_json = _make_action_json(action_type, **params)
	model_output = agent.AgentOutput.model_validate_json(action_json)
	return AgentHistory(
		model_output=model_output,
		result=[ActionResult(extracted_content='ok')],
		state=BrowserStateHistory(
			url='http://localhost',
			title='Test',
			tabs=[],
			interacted_element=[None],
		),
	)


def _get_context_messages(agent: Agent) -> list:
	"""Return the current context messages from the agent's message manager."""
	return agent._message_manager.state.history.context_messages


async def test_loop_detection_triggers_after_repeated_clicks():
	"""Loop detection fires when the same click action is repeated >= 3 times in 5 steps."""
	llm = create_mock_llm()
	agent = Agent(task='Test', llm=llm)

	# Populate history: click index 5 four times, then a different action
	for _ in range(4):
		agent.history.history.append(_make_history_entry(agent, 'click', index=5))
	agent.history.history.append(_make_history_entry(agent, 'scroll', direction='down', amount=3))

	await agent._check_for_action_loop()

	msgs = _get_context_messages(agent)
	assert len(msgs) == 1
	content = msgs[0].content
	assert 'LOOP DETECTED' in content
	assert 'click' in content
	assert '5' in content  # element index


async def test_no_loop_detection_for_varied_actions():
	"""No loop warning when each step performs a different action."""
	llm = create_mock_llm()
	agent = Agent(task='Test', llm=llm)

	agent.history.history.append(_make_history_entry(agent, 'click', index=1))
	agent.history.history.append(_make_history_entry(agent, 'click', index=2))
	agent.history.history.append(_make_history_entry(agent, 'input', index=3, text='hello'))
	agent.history.history.append(_make_history_entry(agent, 'scroll', direction='down', amount=3))
	agent.history.history.append(_make_history_entry(agent, 'navigate', url='http://example.com'))

	await agent._check_for_action_loop()

	msgs = _get_context_messages(agent)
	assert len(msgs) == 0


async def test_loop_detection_respects_threshold():
	"""No warning when the same action is repeated only 2 times (below threshold of 3)."""
	llm = create_mock_llm()
	agent = Agent(task='Test', llm=llm)

	agent.history.history.append(_make_history_entry(agent, 'click', index=7))
	agent.history.history.append(_make_history_entry(agent, 'click', index=7))
	agent.history.history.append(_make_history_entry(agent, 'scroll', direction='down', amount=3))

	await agent._check_for_action_loop()

	msgs = _get_context_messages(agent)
	assert len(msgs) == 0


async def test_loop_detection_ignores_wait_actions():
	"""Wait actions are excluded from loop detection — repeating wait is sometimes legitimate."""
	llm = create_mock_llm()
	agent = Agent(task='Test', llm=llm)

	for _ in range(5):
		agent.history.history.append(_make_history_entry(agent, 'wait', seconds=3))

	await agent._check_for_action_loop()

	msgs = _get_context_messages(agent)
	assert len(msgs) == 0


async def test_loop_detection_with_input_actions():
	"""Loop detection fires for repeated input actions on the same element."""
	llm = create_mock_llm()
	agent = Agent(task='Test', llm=llm)

	for _ in range(4):
		agent.history.history.append(_make_history_entry(agent, 'input', index=10, text='hello'))
	agent.history.history.append(_make_history_entry(agent, 'click', index=2))

	await agent._check_for_action_loop()

	msgs = _get_context_messages(agent)
	assert len(msgs) == 1
	content = msgs[0].content
	assert 'LOOP DETECTED' in content
	assert 'input' in content
	assert '10' in content  # element index
