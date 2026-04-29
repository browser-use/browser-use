from browser_use.agent.message_manager.service import MessageManager, _log_format_message_line
from browser_use.agent.message_manager.views import MessageHistory, MessageManagerState
from browser_use.filesystem.file_system import FileSystem
from browser_use.llm.messages import SystemMessage, UserMessage


def test_log_format_message_line_uses_estimated_tokens():
	lines = _log_format_message_line(
		UserMessage(content='hello world'),
		'hello world',
		is_last_message=False,
		terminal_width=80,
	)

	assert len(lines) == 1
	assert '??? (TODO)' not in lines[0]
	assert '💬[   ~2]:' in lines[0]


def test_log_history_lines_includes_message_history(tmp_path):
	system_message = SystemMessage(content='system prompt')
	state = MessageManagerState(
		history=MessageHistory(
			system_message=system_message,
			state_message=UserMessage(content='current page state'),
			context_messages=[UserMessage(content='previous action result')],
		)
	)
	manager = MessageManager(
		task='test task',
		system_message=system_message,
		file_system=FileSystem(tmp_path),
		state=state,
	)

	log_output = manager._log_history_lines()

	assert 'LLM Message history (3 messages, ~' in log_output
	assert 'system prompt' in log_output
	assert 'current page state' in log_output
	assert 'previous action result' in log_output
	assert '??? (TODO)' not in log_output
