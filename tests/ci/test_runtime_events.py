from browser_use.agent.runtime import BrowserEventStream, BrowserRuntimeEventTypes


def test_event_stream_subscribers_receive_events_and_can_unsubscribe() -> None:
	stream = BrowserEventStream()
	received = []

	unsubscribe = stream.subscribe(received.append)
	first = stream.emit(run_id='run-1', event_type=BrowserRuntimeEventTypes.TURN_STARTED)
	unsubscribe()
	stream.emit(run_id='run-1', event_type=BrowserRuntimeEventTypes.TURN_COMPLETED)

	assert received == [first]
	assert [event.sequence for event in stream.events] == [1, 2]


def test_event_stream_replay_and_snapshot() -> None:
	stream = BrowserEventStream()
	stream.emit(run_id='run-1', event_type=BrowserRuntimeEventTypes.TURN_STARTED)
	stream.emit(run_id='run-1', event_type=BrowserRuntimeEventTypes.CONTEXT_BUILT)
	replayed = []

	stream.subscribe(replayed.append, replay=True)
	later = stream.emit(run_id='run-1', event_type=BrowserRuntimeEventTypes.RUN_COMPLETED)

	assert [event.event_type for event in replayed] == [
		BrowserRuntimeEventTypes.TURN_STARTED,
		BrowserRuntimeEventTypes.CONTEXT_BUILT,
		BrowserRuntimeEventTypes.RUN_COMPLETED,
	]
	assert stream.snapshot(after_sequence=2) == [later]


def test_event_stream_subscriber_failures_do_not_break_emit() -> None:
	stream = BrowserEventStream()

	def broken(_event):
		raise RuntimeError('subscriber failed')

	stream.subscribe(broken)
	event = stream.emit(run_id='run-1', event_type=BrowserRuntimeEventTypes.TOOL_FAILED)

	assert event.event_type == BrowserRuntimeEventTypes.TOOL_FAILED
	assert len(stream.subscriber_errors) == 1
	assert 'subscriber failed' in stream.subscriber_errors[0]


def test_runtime_event_type_catalog_contains_expected_events() -> None:
	assert BrowserRuntimeEventTypes.TURN_STARTED in BrowserRuntimeEventTypes.ALL
	assert BrowserRuntimeEventTypes.MODEL_DELTA in BrowserRuntimeEventTypes.ALL
	assert BrowserRuntimeEventTypes.DOWNLOAD_COMPLETED in BrowserRuntimeEventTypes.ALL
	assert BrowserRuntimeEventTypes.CONTEXT_COMPACTED in BrowserRuntimeEventTypes.ALL
