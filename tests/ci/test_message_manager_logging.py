from browser_use.agent.message_manager.service import (
	MessageManager,
	_log_estimate_token_count,
	_log_format_message_line,
)
from browser_use.agent.views import MessageManagerState
from browser_use.filesystem.file_system import FileSystem
from browser_use.llm.messages import SystemMessage, UserMessage


def test_log_format_message_line_with_numeric_token_count():
	message = UserMessage(content='hello world')
	lines = _log_format_message_line(
		message=message,
		content=message.text,
		token_count=42,
		is_last_message=True,
		terminal_width=120,
	)

	assert lines
	assert '[  42]:' in lines[0]
	assert '??? (TODO)' not in lines[0]


def test_log_format_message_line_with_missing_token_count():
	message = UserMessage(content='hello world')
	lines = _log_format_message_line(
		message=message,
		content=message.text,
		token_count=None,
		is_last_message=True,
		terminal_width=120,
	)

	assert lines
	assert '[   ?]:' in lines[0]
	assert '??? (TODO)' not in lines[0]


def test_log_estimate_token_count_empty_message_returns_none():
	message = UserMessage(content='   ')
	assert _log_estimate_token_count(message) is None


def test_log_history_lines_does_not_include_todo_placeholder(tmp_path):
	file_system = FileSystem(tmp_path)
	message_manager = MessageManager(
		task='Test task',
		system_message=SystemMessage(content='System message'),
		state=MessageManagerState(),
		file_system=file_system,
	)
	message_manager._add_context_message(UserMessage(content='A short contextual message'))

	history_log = message_manager._log_history_lines()

	assert history_log
	assert '??? (TODO)' not in history_log
	assert '📜 LLM Message history' in history_log
