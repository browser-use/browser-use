from browser_use.agent.runtime import (
	BrowserEventStream,
	BrowserRuntimeEventTypes,
	FilteredRuntimeEventCallback,
	RuntimeEventRecorder,
)


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
