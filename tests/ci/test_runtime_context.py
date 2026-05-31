from browser_use.agent.runtime import (
	BrowserContext,
	BrowserContextRenderer,
	BrowserStateItem,
	CompactionItem,
	DownloadItem,
	ExtractionArtifactItem,
	FileArtifactItem,
	TaskItem,
	ToolCallItem,
	ToolResultItem,
	UserSteerItem,
	WarningItem,
)


def test_typed_context_renders_deterministically() -> None:
	context = BrowserContext(
		items=[
			TaskItem(text='Find the install command'),
			ToolCallItem(
				tool_name='browser.navigate', call_id='call-1', arguments={'url': 'https://example.com', 'new_tab': False}
			),
			ToolResultItem(
				tool_name='browser.navigate',
				call_id='call-1',
				content='Navigated',
				structured_content={'url': 'https://example.com'},
			),
			BrowserStateItem(url='https://example.com', title='Example', text='Interactive elements:\n[12]<a>Docs</a>'),
		]
	)

	rendered_once = context.render()
	rendered_twice = BrowserContextRenderer().render(context.items)

	assert rendered_once == rendered_twice
	assert '<user_request>\nFind the install command\n</user_request>' in rendered_once
	assert '<tool_call id="call-1" name="browser.navigate">' in rendered_once
	assert '{"new_tab":false,"url":"https://example.com"}' in rendered_once
	assert '<browser_state>\nURL: https://example.com\nTitle: Example\nInteractive elements:' in rendered_once


def test_browser_state_keeps_runtime_handles_out_of_default_render() -> None:
	item = BrowserStateItem(
		url='https://example.com',
		text='[42]<button>Submit</button>',
		runtime_handles={
			'backendNodeId': 42,
			'targetId': 'full-target-id',
			'sessionId': 'full-session-id',
			'frameId': 'full-frame-id',
		},
	)

	rendered = item.render()
	dumped = item.model_dump()

	assert '[42]<button>Submit</button>' in rendered
	assert 'full-target-id' not in rendered
	assert 'runtime_handles' not in dumped
	assert item.runtime_handles['backendNodeId'] == 42


def test_context_keeps_active_browser_state_after_compaction() -> None:
	context = BrowserContext()
	context.append(TaskItem(text='Compare prices'))
	context.append(CompactionItem(summary='Earlier steps searched for two products.'))
	current_state = context.append(BrowserStateItem(url='https://shop.example/item', text='[77]<button>Add to cart</button>'))

	assert context.latest_browser_state() == current_state
	assert '<compacted_memory>' in context.render()
	assert '[77]<button>Add to cart</button>' in context.render()


def test_context_item_union_round_trips() -> None:
	context = BrowserContext(
		items=[
			UserSteerItem(text='Prefer official docs.'),
			DownloadItem(file_name='report.pdf', path='/tmp/report.pdf', media_type='application/pdf'),
			FileArtifactItem(path='/tmp/report.pdf', description='Downloaded report'),
			ExtractionArtifactItem(source='report.pdf', query='summary', content='Important extracted text'),
			WarningItem(code='stale_state', message='Browser state may be stale.'),
		]
	)

	round_tripped = BrowserContext.model_validate(context.model_dump(mode='json'))
	rendered = round_tripped.render()

	assert [item.kind for item in round_tripped.items] == [
		'user_steer',
		'download',
		'file_artifact',
		'extraction_artifact',
		'warning',
	]
	assert '<follow_up_user_request>' in rendered
	assert '<download>' in rendered
	assert '<file_artifact>' in rendered
	assert '<extraction_artifact metadata="' in rendered
	assert '<warning code="stale_state">' in rendered
