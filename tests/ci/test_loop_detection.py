"""
Tests for the agent action loop detection feature.

Two-tier detection:
 - Tier 1 (exact): same (action_type, element_index) repeated ≥3 times in 5 steps.
 - Tier 2 (page-stuck): same (action_type, url) repeated ≥4 times in 6 steps,
   regardless of element index. Catches Cloudflare / dynamic-DOM loops.
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


def _make_history_entry(
	agent: Agent,
	action_type: str,
	*,
	page_url: str = 'http://localhost',
	page_title: str = 'Test',
	**params,
) -> AgentHistory:
	"""Create a minimal AgentHistory entry with one action.

	page_url / page_title set the BrowserStateHistory fields (the page the agent was on).
	All other **params are forwarded as action parameters (e.g. index=5, text='hello').
	"""
	action_json = _make_action_json(action_type, **params)
	model_output = agent.AgentOutput.model_validate_json(action_json)
	return AgentHistory(
		model_output=model_output,
		result=[ActionResult(extracted_content='ok')],
		state=BrowserStateHistory(
			url=page_url,
			title=page_title,
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
	agent.history.history.append(_make_history_entry(agent, 'navigate', url='http://localhost:8080/other'))

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


# ---------------------------------------------------------------------------
# Tier 2: page-stuck detection (same action_type + url, different indices)
# ---------------------------------------------------------------------------


async def test_page_stuck_detects_cloudflare_pattern():
	"""Clicking different indices on the same stuck page triggers tier-2 warning.

	Simulates the Cloudflare checkbox loop: the agent clicks "Verify you are human"
	at indices 87, 282, 480, 910 on the same URL. Each index is different, so tier-1
	won't fire, but tier-2 should.
	"""
	llm = create_mock_llm()
	agent = Agent(task='Test', llm=llm)

	cloudflare_url = 'http://localhost:8080/challenge'
	for idx in [87, 282, 480, 910]:
		agent.history.history.append(
			_make_history_entry(agent, 'click', page_url=cloudflare_url, page_title='Just a moment...', index=idx)
		)

	await agent._check_for_action_loop()

	msgs = _get_context_messages(agent)
	assert len(msgs) == 1
	content = msgs[0].content
	assert 'PAGE STUCK' in content
	assert 'click' in content
	assert cloudflare_url in content


async def test_page_stuck_no_trigger_across_different_urls():
	"""Clicks on different pages should NOT trigger page-stuck detection."""
	llm = create_mock_llm()
	agent = Agent(task='Test', llm=llm)

	for i in range(5):
		agent.history.history.append(_make_history_entry(agent, 'click', page_url=f'http://localhost/page{i}', index=i + 1))

	await agent._check_for_action_loop()

	msgs = _get_context_messages(agent)
	assert len(msgs) == 0


async def test_page_stuck_respects_threshold():
	"""Only 3 clicks on the same URL (below tier-2 threshold of 4) — no warning."""
	llm = create_mock_llm()
	agent = Agent(task='Test', llm=llm)

	for idx in [100, 200, 300]:
		agent.history.history.append(_make_history_entry(agent, 'click', page_url='http://localhost:8080/stuck', index=idx))

	await agent._check_for_action_loop()

	msgs = _get_context_messages(agent)
	assert len(msgs) == 0


async def test_page_stuck_ignores_wait_actions():
	"""Wait actions on the same URL should not trigger page-stuck detection."""
	llm = create_mock_llm()
	agent = Agent(task='Test', llm=llm)

	for _ in range(6):
		agent.history.history.append(_make_history_entry(agent, 'wait', page_url='http://localhost:8080/stuck', seconds=5))

	await agent._check_for_action_loop()

	msgs = _get_context_messages(agent)
	assert len(msgs) == 0


async def test_exact_match_takes_priority_over_page_stuck():
	"""When both tiers would fire, the exact-match (tier 1) warning is emitted."""
	llm = create_mock_llm()
	agent = Agent(task='Test', llm=llm)

	# 4 clicks on same index AND same url — both tiers qualify
	for _ in range(4):
		agent.history.history.append(_make_history_entry(agent, 'click', page_url='http://localhost:8080/stuck', index=5))

	await agent._check_for_action_loop()

	msgs = _get_context_messages(agent)
	assert len(msgs) == 1
	content = msgs[0].content
	# Tier 1 says "LOOP DETECTED", tier 2 says "PAGE STUCK LOOP DETECTED"
	# Only tier 1 should fire since it returns early
	assert 'LOOP DETECTED' in content
	assert 'PAGE STUCK' not in content
