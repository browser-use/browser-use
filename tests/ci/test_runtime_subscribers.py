import pytest

from browser_use.agent.runtime import (
	AgentDoneCallbackSubscriber,
	AgentStepCallbackSubscriber,
	BrowserEventStream,
	BrowserRuntimeEventTypes,
	FilteredAsyncRuntimeEventCallback,
	FilteredRuntimeEventCallback,
	RuntimeEventRecorder,
)


class DoneHistory:
	def __init__(self, done: bool) -> None:
		self.done = done

	def is_done(self) -> bool:
		return self.done


def test_runtime_event_recorder_builds_failure_report() -> None:
	stream = BrowserEventStream()
	recorder = RuntimeEventRecorder()
	stream.subscribe(recorder)

	stream.emit(run_id='run-1', turn_id='turn-1', event_type=BrowserRuntimeEventTypes.TOOL_STARTED, payload={'tool': 'click'})
	stream.emit(
		run_id='run-1',
		turn_id='turn-1',
		event_type=BrowserRuntimeEventTypes.TOOL_FAILED,
		payload={'tool': 'click', 'error': 'stale index'},
	)
	stream.emit(run_id='run-1', turn_id='turn-1', event_type=BrowserRuntimeEventTypes.RUN_FAILED, payload={'error': 'failed'})

	report = recorder.failure_report()

	assert report['total_events'] == 3
	assert report['failure_count'] == 2
	assert report['last_tool_event']['payload']['error'] == 'stale index'
	assert report['last_event']['event_type'] == BrowserRuntimeEventTypes.RUN_FAILED


def test_filtered_runtime_event_callback_only_receives_selected_events() -> None:
	stream = BrowserEventStream()
	seen: list[str] = []
	callback = FilteredRuntimeEventCallback(
		callback=lambda event: seen.append(event.event_type),
		event_types={BrowserRuntimeEventTypes.TOOL_COMPLETED},
	)
	stream.subscribe(callback)

	stream.emit(run_id='run-1', event_type=BrowserRuntimeEventTypes.TOOL_STARTED)
	stream.emit(run_id='run-1', event_type=BrowserRuntimeEventTypes.TOOL_COMPLETED)

	assert seen == [BrowserRuntimeEventTypes.TOOL_COMPLETED]


@pytest.mark.asyncio
async def test_filtered_async_runtime_event_callback_only_receives_selected_events() -> None:
	stream = BrowserEventStream()
	seen: list[str] = []
	callback = FilteredAsyncRuntimeEventCallback(
		callback=lambda event: seen.append(event.event_type),
		event_types={BrowserRuntimeEventTypes.RUN_COMPLETED},
	)
	stream.subscribe_async(callback)

	await stream.emit_async(run_id='run-1', event_type=BrowserRuntimeEventTypes.RUN_STARTED)
	await stream.emit_async(run_id='run-1', event_type=BrowserRuntimeEventTypes.RUN_COMPLETED)

	assert seen == [BrowserRuntimeEventTypes.RUN_COMPLETED]


@pytest.mark.asyncio
async def test_agent_step_callback_subscriber_receives_model_delta_payload() -> None:
	stream = BrowserEventStream()
	seen: list[tuple[object, object, int]] = []
	stream.subscribe_async(AgentStepCallbackSubscriber(callback=lambda state, output, step: seen.append((state, output, step))))
	state = object()
	output = object()

	await stream.emit_async(
		run_id='run-1',
		event_type=BrowserRuntimeEventTypes.MODEL_DELTA,
		payload={'browser_state_summary': state, 'model_output': output, 'step': 3},
	)

	assert seen == [(state, output, 3)]


@pytest.mark.asyncio
async def test_agent_done_callback_subscriber_only_notifies_done_history() -> None:
	stream = BrowserEventStream()
	seen: list[DoneHistory] = []
	stream.subscribe_async(AgentDoneCallbackSubscriber(callback=seen.append))
	not_done = DoneHistory(done=False)
	done = DoneHistory(done=True)

	await stream.emit_async(
		run_id='run-1',
		event_type=BrowserRuntimeEventTypes.RUN_COMPLETED,
		payload={'history': not_done, 'notify_done_callback': True},
	)
	await stream.emit_async(
		run_id='run-1',
		event_type=BrowserRuntimeEventTypes.RUN_COMPLETED,
		payload={'history': done, 'notify_done_callback': True},
	)

	assert seen == [done]


def test_recorder_timeline_can_hide_payloads() -> None:
	recorder = RuntimeEventRecorder()
	stream = BrowserEventStream()
	stream.subscribe(recorder)
	stream.emit(run_id='run-1', event_type=BrowserRuntimeEventTypes.ARTIFACT_CREATED, payload={'path': '/tmp/file'})

	timeline = recorder.timeline(include_payload=False)

	assert timeline == [
		{
			'sequence': 1,
			'event_type': BrowserRuntimeEventTypes.ARTIFACT_CREATED,
			'run_id': 'run-1',
			'turn_id': None,
			'timestamp': timeline[0]['timestamp'],
		}
	]
