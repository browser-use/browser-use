import asyncio
import time

import pytest

from browser_use import ActionResult, Agent, Browser, Controller


@pytest.mark.asyncio
async def test_agent_pause_timeout(mock_llm):
	"""
	Test that an agent can be paused for longer than the step_timeout
	and successfully resume without raising a TimeoutError.
	"""
	controller = Controller()

	@controller.action('Wait and do something')
	async def custom_pause_action():
		agent.pause()
		await asyncio.sleep(4.0)
		agent.resume()
		return ActionResult(extracted_content='Success after pause')

	# Force the mock LLM to call the custom tool first, then done.
	from tests.ci.conftest import create_mock_llm

	custom_action_json = '{"action": [{"custom_pause_action": {}}]}'
	mock_llm_with_action = create_mock_llm(actions=[custom_action_json])

	# Extremely short step timeout (2.0s)
	agent = Agent(
		task='Test pause functionality. Call the custom tool once.',
		llm=mock_llm_with_action,
		controller=controller,
		browser=Browser(),
		# Injecting fake max_steps to ensure fast execution
		max_actions_per_step=1,
	)
	# Override timeout setting
	agent.settings.step_timeout = 2.0

	# Ensure it works without failing
	start_time = time.time()
	history = await agent.run(max_steps=2)
	elapsed = time.time() - start_time

	# We expect elapsed to be > 4 seconds because of the sleep
	assert elapsed >= 4.0

	# We expect the agent didn't fail due to TimeoutError
	assert agent.state.consecutive_failures == 0
	assert history.is_done() or not history.has_errors()
