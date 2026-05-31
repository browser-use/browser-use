from browser_use.agent.runtime import (
	BrowserAgentSession,
	BrowserContext,
	BrowserContextCompactor,
	BrowserRuntimeEventTypes,
	BrowserStateItem,
	ContextCompactionPolicy,
	DownloadItem,
	FileArtifactItem,
	SkillItem,
	TaskItem,
	ToolCallItem,
	ToolResultItem,
	WarningItem,
)


def test_compactor_preserves_active_state_and_runtime_handles() -> None:
	active_state = BrowserStateItem(
		url='https://example.com/current',
		text='[42]<button>Current</button>',
		runtime_handles={'targetId': 'full-target', 'sessionId': 'full-session', 'backendNodeId': 42},
	)
	context = BrowserContext(
		items=[
			TaskItem(text='Finish checkout'),
			BrowserStateItem(url='https://example.com/old', text='[1]<a>Old</a>'),
			ToolCallItem(tool_name='browser.click', arguments={'index': 1}),
			ToolResultItem(tool_name='browser.click', content='Clicked old link'),
			active_state,
			ToolResultItem(tool_name='browser.get_state', content='Current state refreshed'),
		]
	)
	compactor = BrowserContextCompactor(policy=ContextCompactionPolicy(max_items_before_compaction=4, keep_recent_items=1))

	result = compactor.compact(context)
	compacted_state = result.context.latest_browser_state()

	assert result.compacted is True
	assert compacted_state == active_state
	assert compacted_state is not None
	assert compacted_state.runtime_handles['targetId'] == 'full-target'
	assert '<compacted_memory>' in result.context.render()
	assert 'browser_state' in (result.summary or '')
	assert result.reasons == ['item_count']


def test_compactor_preserves_artifacts_warnings_and_skills() -> None:
	context = BrowserContext(
		items=[
			TaskItem(text='Download and inspect report'),
			SkillItem(name='downloads', title='Downloads', content='Use file tools after download.'),
			DownloadItem(file_name='report.pdf', path='/tmp/report.pdf'),
			FileArtifactItem(path='/tmp/report.pdf', description='Downloaded report'),
			WarningItem(code='retry', message='First click failed.'),
			*[ToolResultItem(tool_name='browser.wait', content=f'wait {index}') for index in range(8)],
			BrowserStateItem(url='https://example.com/report', text='[9]<button>Download</button>'),
		]
	)
	compactor = BrowserContextCompactor(policy=ContextCompactionPolicy(max_items_before_compaction=6, keep_recent_items=2))

	result = compactor.compact(context)
	kinds = [item.kind for item in result.context.items]
	rendered = result.context.render()

	assert result.compacted is True
	assert 'skill' in kinds
	assert 'download' in kinds
	assert 'file_artifact' in kinds
	assert 'warning' in kinds
	assert '[9]<button>Download</button>' in rendered
	assert 'wait 0' in rendered


def test_compactor_noops_below_threshold() -> None:
	context = BrowserContext(items=[TaskItem(text='Small task'), BrowserStateItem(text='[1]<button>Go</button>')])
	compactor = BrowserContextCompactor(policy=ContextCompactionPolicy(max_items_before_compaction=5))

	result = compactor.compact(context)

	assert result.compacted is False
	assert result.context == context


def test_compactor_triggers_from_rendered_context_pressure() -> None:
	active_state = BrowserStateItem(
		url='https://example.com/current',
		text='[7]<button>Continue</button>',
		runtime_handles={'targetId': 'full-target', 'backendNodeId': 7},
	)
	context = BrowserContext(
		items=[
			TaskItem(text='Finish a long research task'),
			*[
				ToolResultItem(tool_name='browser.extract', content=f'old extraction {index} ' + ('x' * 700))
				for index in range(5)
			],
			active_state,
			ToolResultItem(tool_name='browser.get_state', content='Current state refreshed'),
		]
	)
	compactor = BrowserContextCompactor(
		policy=ContextCompactionPolicy(
			max_items_before_compaction=100,
			max_rendered_chars_before_compaction=1800,
			keep_recent_items=1,
		)
	)

	result = compactor.compact(context)

	assert result.compacted is True
	assert result.reasons == ['context_pressure']
	assert result.before_rendered_chars is not None
	assert result.after_rendered_chars is not None
	assert result.after_rendered_chars < result.before_rendered_chars
	compacted_state = result.context.latest_browser_state()
	assert compacted_state == active_state
	assert compacted_state is not None
	assert compacted_state.runtime_handles['targetId'] == 'full-target'

	result.context.append(ToolCallItem(tool_name='browser.click', arguments={'index': 7}))
	result.context.append(ToolResultItem(tool_name='browser.click', content='Clicked Continue after compaction'))
	rendered = result.context.render()
	assert '<compacted_memory>' in rendered
	assert 'Clicked Continue after compaction' in rendered


def test_compactor_noops_when_pressure_only_affects_active_state() -> None:
	context = BrowserContext(
		items=[
			TaskItem(text='Inspect a huge current page'),
			BrowserStateItem(text='[1]<button>Keep</button>\n' + ('visible current page ' * 200)),
		]
	)
	compactor = BrowserContextCompactor(
		policy=ContextCompactionPolicy(
			max_items_before_compaction=100,
			max_rendered_chars_before_compaction=1200,
		)
	)

	result = compactor.compact(context)

	assert result.compacted is False
	assert result.reasons == ['context_pressure']
	assert result.context == context


def test_session_emits_compaction_event_for_compacted_context() -> None:
	session = BrowserAgentSession.create(task='Keep a long run small')
	turn = session.start_turn(step_index=9)
	context = BrowserContext(
		items=[
			TaskItem(text='Keep a long run small'),
			*[ToolResultItem(tool_name='browser.wait', content=f'older result {index}') for index in range(6)],
			BrowserStateItem(text='[3]<button>Next</button>', runtime_handles={'backendNodeId': 3}),
		]
	)
	compactor = BrowserContextCompactor(
		policy=ContextCompactionPolicy(
			max_items_before_compaction=4,
			max_rendered_chars_before_compaction=None,
			keep_recent_items=2,
		)
	)

	result = session.compact_context(context, compactor=compactor, turn=turn)

	assert result.compacted is True
	events = [event for event in session.event_stream.events if event.event_type == BrowserRuntimeEventTypes.CONTEXT_COMPACTED]
	assert len(events) == 1
	assert events[0].turn_id == turn.turn_id
	assert events[0].payload['reasons'] == ['item_count']
	assert events[0].payload['source_item_count'] == len(result.source_item_ids)
