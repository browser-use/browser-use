import pytest

from browser_use import Agent
from browser_use.agent.runtime import BrowserRuntimeEventTypes


@pytest.mark.asyncio
async def test_agent_callbacks_are_routed_through_runtime_event_subscribers(browser_session, mock_llm) -> None:
	step_events: list[tuple[str, int, int]] = []
	done_events: list[bool] = []

	async def on_step(browser_state_summary, model_output, step: int) -> None:
		step_events.append((browser_state_summary.url, step, len(model_output.action)))

	def on_done(history) -> None:
		done_events.append(history.is_done())

	agent = Agent(
		task='Finish immediately',
		llm=mock_llm,
		browser_session=browser_session,
		register_new_step_callback=on_step,
		register_done_callback=on_done,
		use_judge=False,
		enable_signal_handler=False,
	)

	history = await agent.run(max_steps=2)

	assert history.is_done()
	assert len(step_events) == 1
	assert step_events[0][1:] == (1, 1)
	assert done_events == [True]
	event_types = [event.event_type for event in agent.runtime_session.event_stream.events]
	assert BrowserRuntimeEventTypes.RUN_STARTED in event_types
	assert BrowserRuntimeEventTypes.MODEL_DELTA in event_types
	assert BrowserRuntimeEventTypes.TURN_COMPLETED in event_types
	assert BrowserRuntimeEventTypes.RUN_COMPLETED in event_types
