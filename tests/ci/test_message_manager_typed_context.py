from browser_use.agent.message_manager.service import MessageManager
from browser_use.agent.message_manager.views import HistoryItem
from browser_use.filesystem.file_system import FileSystem
from browser_use.llm.messages import SystemMessage


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

	context = manager.build_typed_context()
	rendered = context.render()

	assert [item.kind for item in context.items] == [
		'task',
		'compaction',
		'warning',
		'tool_result',
		'user_steer',
		'extraction_artifact',
	]
	assert '<user_request>' in rendered
	assert '<compacted_memory>' in rendered
	assert '<tool_result name="legacy.step">' in rendered
	assert '<follow_up_user_request>' in rendered
	assert 'Downloaded text' in rendered
