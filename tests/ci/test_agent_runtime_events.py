import json
import logging

import pytest

from browser_use import Agent
from browser_use.agent.llm_debug_trace import write_runtime_events_debug_snapshot
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
	assert BrowserRuntimeEventTypes.CONTEXT_BUILT in event_types
	assert BrowserRuntimeEventTypes.MODEL_DELTA in event_types
	assert BrowserRuntimeEventTypes.TURN_COMPLETED in event_types
	assert BrowserRuntimeEventTypes.RUN_COMPLETED in event_types
	context_event = next(
		event for event in agent.runtime_session.event_stream.events if event.event_type == BrowserRuntimeEventTypes.CONTEXT_BUILT
	)
	assert context_event.payload['item_count'] >= 2
	assert context_event.payload['rendered_chars'] > 0


@pytest.mark.asyncio
async def test_agent_runtime_skips_legacy_cloud_eventbus_without_cloud_sync(browser_session, mock_llm, monkeypatch) -> None:
	agent = Agent(
		task='Finish immediately',
		llm=mock_llm,
		browser_session=browser_session,
		use_judge=False,
		enable_signal_handler=False,
	)

	def fail_dispatch(*_args, **_kwargs) -> None:
		raise AssertionError('legacy cloud eventbus should not run without cloud_sync')

	monkeypatch.setattr(agent.eventbus, 'dispatch', fail_dispatch)

	history = await agent.run(max_steps=2)

	assert history.is_done()
	event_types = [event.event_type for event in agent.runtime_session.event_stream.events]
	assert BrowserRuntimeEventTypes.RUN_STARTED in event_types
	assert BrowserRuntimeEventTypes.RUN_COMPLETED in event_types


@pytest.mark.asyncio
async def test_runtime_event_debug_snapshot_summarizes_terminal_history(browser_session, mock_llm, tmp_path) -> None:
	agent = Agent(
		task='Finish immediately',
		llm=mock_llm,
		browser_session=browser_session,
		use_judge=False,
		enable_signal_handler=False,
	)
	agent.logger.setLevel(logging.DEBUG)

	history = await agent.run(max_steps=2)
	await write_runtime_events_debug_snapshot(
		agent_directory=tmp_path,
		logger=agent.logger,
		runtime_session=agent.runtime_session,
	)

	assert history.is_done()
	runtime_events_path = tmp_path / 'runtime_events.jsonl'
	events = [json.loads(line) for line in runtime_events_path.read_text(encoding='utf-8').splitlines()]
	terminal_event = next(event for event in reversed(events) if event['event_type'] == BrowserRuntimeEventTypes.RUN_COMPLETED)
	history_payload = terminal_event['payload']['history']
	assert history_payload['is_done'] is True
	assert history_payload['history_length'] == len(history.history)
	assert 'final_result' in history_payload
	assert 'screenshots' not in history_payload
	assert runtime_events_path.stat().st_size < 50_000
