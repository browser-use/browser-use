from browser_use.agent.runtime import (
	BrowserContext,
	BrowserContextCompactor,
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
