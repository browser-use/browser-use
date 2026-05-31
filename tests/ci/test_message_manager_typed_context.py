import base64

from browser_use.agent.message_manager.service import MessageManager
from browser_use.agent.runtime import BrowserSkillRegistry
from browser_use.agent.runtime.context import ToolResultItem
from browser_use.agent.views import ActionResult, AgentStepInfo
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
	manager.state.context_items.append(
		ToolResultItem(
			tool_name='browser.navigate',
			content='Result\nNavigated to example.com',
			structured_content={'step_number': 1, 'memory': 'Need the answer'},
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
	assert '<tool_result name="browser.navigate">' in rendered
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
	assert manager.last_state_message_text is not None
	assert manager.last_state_message_text == rendered
	assert '<runtime_skills>' not in manager.last_state_message_text


def test_create_state_messages_supports_prepared_step_state(tmp_path) -> None:
	manager = MessageManager(
		task='Find the answer',
		system_message=SystemMessage(content='system'),
		file_system=FileSystem(tmp_path / 'files', create_default_files=False),
	)
	browser_state = _browser_state()

	manager.prepare_step_state(browser_state)
	manager.create_state_messages(
		browser_state,
		page_filtered_actions='special_action: available',
		available_file_paths=['/tmp/result.csv'],
		step_info=AgentStepInfo(step_number=0, max_steps=5),
		skip_state_update=True,
	)

	assert manager.last_typed_context is not None
	assert manager.last_state_message_text is not None
	assert manager.last_state_message_text == manager.last_typed_context.render()
	assert '<page_specific_actions>' in manager.last_state_message_text
	assert '<available_file_paths>/tmp/result.csv' in manager.last_state_message_text


def test_create_state_messages_includes_selected_runtime_skills_only_when_relevant(tmp_path) -> None:
	manager = MessageManager(
		task='Download the receipt PDF',
		system_message=SystemMessage(content='system'),
		file_system=FileSystem(tmp_path / 'files', create_default_files=False),
	)
	selected_skills = BrowserSkillRegistry.default().select(task='Download the receipt PDF', max_skills=1)

	manager.create_state_messages(
		_browser_state(),
		selected_runtime_skills=selected_skills,
		step_info=AgentStepInfo(step_number=0, max_steps=5),
	)

	assert manager.last_typed_context is not None
	assert [item.kind for item in manager.last_typed_context.items].count('skill') == 1
	assert manager.last_state_message_text is not None
	assert manager.last_state_message_text == manager.last_typed_context.render()
	assert '<runtime_skills>' not in manager.last_state_message_text
	assert '<skill name="downloads" title="Downloads">' in manager.last_state_message_text


def test_typed_context_ledger_records_file_download_and_image_artifacts(tmp_path) -> None:
	manager = MessageManager(
		task='Collect artifacts',
		system_message=SystemMessage(content='system'),
		file_system=FileSystem(tmp_path / 'files', create_default_files=False),
	)
	download_path = str(tmp_path / 'receipt.pdf')
	manager.prepare_step_state(
		_browser_state(),
		result=[
			ActionResult(
				extracted_content='Saved artifacts',
				attachments=[download_path],
				images=[{'name': 'receipt.png', 'data': base64.b64encode(b'image-data').decode()}],
				metadata={
					'download': {
						'file_name': 'receipt.pdf',
						'path': download_path,
						'mime_type': 'application/pdf',
					}
				},
			)
		],
		step_info=AgentStepInfo(step_number=0, max_steps=5),
	)

	kinds = [item.kind for item in manager.state.context_items]
	assert 'file_artifact' in kinds
	assert 'download' in kinds
	assert 'screenshot' in kinds

	rendered = manager.build_typed_context(_browser_state()).render()
	assert '<file_artifact>' in rendered
	assert '<download>' in rendered
	assert '<screenshot>' in rendered
	assert 'receipt.pdf' in rendered
