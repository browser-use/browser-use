from browser_use.agent.message_manager.service import MessageManager
from browser_use.agent.message_manager.views import HistoryItem
from browser_use.agent.views import AgentStepInfo
from browser_use.browser.views import BrowserStateSummary, PageInfo, TabInfo
from browser_use.dom.views import SerializedDOMState
from browser_use.filesystem.file_system import FileSystem
from browser_use.llm.messages import SystemMessage


def _browser_state() -> BrowserStateSummary:
	return BrowserStateSummary(
		url='https://example.test/page',
		title='Example',
		tabs=[TabInfo(target_id='abcd1234', url='https://example.test/page', title='Example')],
		page_info=PageInfo(
			viewport_width=1280,
			viewport_height=720,
			page_width=1280,
			page_height=1440,
			scroll_x=0,
			scroll_y=0,
			pixels_above=0,
			pixels_below=720,
			pixels_left=0,
			pixels_right=0,
		),
		dom_state=SerializedDOMState(_root=None, selector_map={}),
		screenshot=None,
	)


def test_message_manager_builds_typed_context_mirror(tmp_path) -> None:
	manager = MessageManager(
		task='Find the answer',
		system_message=SystemMessage(content='system'),
		file_system=FileSystem(tmp_path / 'files', create_default_files=False),
	)
	manager.state.compacted_memory = 'Earlier search found candidate pages.'
	manager.state.agent_history_items.append(
		HistoryItem(
			step_number=1,
			evaluation_previous_goal='Opened page',
			memory='Need the answer',
			next_goal='Read result',
			action_results='Result\nNavigated to example.com',
		)
	)
	manager.add_new_task('Prefer official sources')
	manager.state.read_state_description = '<read_state_0>Downloaded text</read_state_0>'

	context = manager.build_typed_context(
		available_file_paths=['/tmp/result.csv'],
		page_filtered_actions='special_action: available',
		unavailable_skills_info='<unavailable_skills>shadow-dom pending</unavailable_skills>',
		plan_description='1. Read official source',
		step_info=AgentStepInfo(step_number=2, max_steps=10),
	)
	rendered = context.render()

	assert [item.kind for item in context.items] == [
		'task',
		'compaction',
		'warning',
		'tool_result',
		'user_steer',
		'agent_state',
		'extraction_artifact',
		'page_actions',
		'warning',
		'step_info',
	]
	assert '<user_request>' in rendered
	assert '<compacted_memory>' in rendered
	assert '<tool_result name="legacy.step">' in rendered
	assert '<follow_up_user_request>' in rendered
	assert '<agent_state>' in rendered
	assert '<available_file_paths>/tmp/result.csv' in rendered
	assert '<plan>' in rendered
	assert 'Downloaded text' in rendered
	assert '<page_specific_actions>' in rendered
	assert 'shadow-dom pending' in rendered
	assert '<step_info>Step3 maximum:10' in rendered


def test_create_state_messages_stores_typed_context_snapshot(tmp_path) -> None:
	manager = MessageManager(
		task='Find the answer',
		system_message=SystemMessage(content='system'),
		file_system=FileSystem(tmp_path / 'files', create_default_files=False),
	)

	manager.create_state_messages(
		_browser_state(),
		page_filtered_actions='special_action: available',
		available_file_paths=['/tmp/result.csv'],
		plan_description='1. Read official source',
		step_info=AgentStepInfo(step_number=0, max_steps=5),
	)

	assert manager.last_typed_context is not None
	rendered = manager.last_typed_context.render()
	assert '<browser_state>' in rendered
	assert 'https://example.test/page' in rendered
	assert '<page_specific_actions>' in rendered
	assert '<available_file_paths>/tmp/result.csv' in rendered
	assert '<step_info>Step1 maximum:5' in rendered
