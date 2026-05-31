import pytest

from browser_use.agent.runtime import BrowserAgentSession, BrowserEventStream, BrowserRuntimeEventTypes


@pytest.mark.asyncio
async def test_event_stream_async_subscribers_receive_events_and_failures() -> None:
	stream = BrowserEventStream()
	received = []

	async def collect(event):
		received.append(event.event_type)

	async def broken(_event):
		raise RuntimeError('async subscriber failed')

	stream.subscribe_async(collect)
	stream.subscribe_async(broken)

	event = await stream.emit_async(run_id='run-1', event_type=BrowserRuntimeEventTypes.RUN_STARTED)

	assert event.event_type == BrowserRuntimeEventTypes.RUN_STARTED
	assert received == [BrowserRuntimeEventTypes.RUN_STARTED]
	assert len(stream.subscriber_errors) == 1
	assert 'async subscriber failed' in stream.subscriber_errors[0]


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
	assert BrowserRuntimeEventTypes.RUN_STARTED in BrowserRuntimeEventTypes.ALL
	assert BrowserRuntimeEventTypes.TURN_STARTED in BrowserRuntimeEventTypes.ALL
	assert BrowserRuntimeEventTypes.MODEL_DELTA in BrowserRuntimeEventTypes.ALL
	assert BrowserRuntimeEventTypes.DOWNLOAD_COMPLETED in BrowserRuntimeEventTypes.ALL
	assert BrowserRuntimeEventTypes.CONTEXT_COMPACTED in BrowserRuntimeEventTypes.ALL


def test_agent_session_emits_context_model_download_and_run_events(tmp_path) -> None:
	session = BrowserAgentSession.create(task='Download report')
	turn = session.start_turn(step_index=4)

	session.emit_context_built(turn, item_count=5, rendered_chars=1200)
	session.emit_model_delta(turn, text='Need the CSV file.', tool_call_count=1)
	session.emit_download_started(file_name='report.csv', url='https://example.com/report.csv', turn=turn)
	artifact = session.record_download_completed(
		file_name='report.csv',
		path=tmp_path / 'report.csv',
		url='https://example.com/report.csv',
		turn=turn,
		metadata={'bytes': 12},
	)
	session.complete_run(metadata={'success': True})

	assert session.artifact_store.get(artifact.artifact_id) == artifact
	assert [event.event_type for event in session.event_stream.events] == [
		BrowserRuntimeEventTypes.TURN_STARTED,
		BrowserRuntimeEventTypes.CONTEXT_BUILT,
		BrowserRuntimeEventTypes.MODEL_DELTA,
		BrowserRuntimeEventTypes.DOWNLOAD_STARTED,
		BrowserRuntimeEventTypes.DOWNLOAD_COMPLETED,
		BrowserRuntimeEventTypes.ARTIFACT_CREATED,
		BrowserRuntimeEventTypes.RUN_COMPLETED,
	]
	assert session.event_stream.events[1].payload == {'step_index': 4, 'item_count': 5, 'rendered_chars': 1200}
	assert session.event_stream.events[2].payload['text_chars'] == len('Need the CSV file.')
	assert session.event_stream.events[4].payload['artifact_id'] == artifact.artifact_id
	assert session.event_stream.events[4].payload['media_type'] == 'text/csv'
	assert session.event_stream.events[-1].payload == {'success': True}


def test_agent_session_emits_run_failure_event() -> None:
	session = BrowserAgentSession.create(task='Fail clearly')

	event = session.fail_run('max failures reached', metadata={'step': 8})

	assert event.event_type == BrowserRuntimeEventTypes.RUN_FAILED
	assert event.payload == {'error': 'max failures reached', 'step': 8}
