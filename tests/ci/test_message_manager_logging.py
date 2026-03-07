import os

from browser_use.agent.message_manager import service as message_manager_service
from browser_use.agent.message_manager.service import MessageManager
from browser_use.agent.message_manager.views import MessageManagerState
from browser_use.filesystem.file_system import FileSystem
from browser_use.llm.messages import (
	AssistantMessage,
	ContentPartImageParam,
	ContentPartTextParam,
	Function,
	ImageURL,
	SystemMessage,
	ToolCall,
	UserMessage,
)


def _build_message_manager(tmp_path) -> MessageManager:
	return MessageManager(
		task='Test task',
		system_message=SystemMessage(content='System instructions'),
		state=MessageManagerState(),
		file_system=FileSystem(str(tmp_path)),
	)


def test_log_history_lines_formats_current_messages(tmp_path, monkeypatch):
	"""Debug history logging should render the current message history instead of returning an empty string."""
	monkeypatch.setattr(message_manager_service.shutil, 'get_terminal_size', lambda fallback: os.terminal_size((200, 20)))
	message_manager = _build_message_manager(tmp_path)
	message_manager._set_message_with_type(UserMessage(content='Current page state'), 'state')
	message_manager._add_context_message(UserMessage(content='Retry with a different selector'))

	log_output = message_manager._log_history_lines()

	assert '📜 LLM Message history (3 messages, token count unavailable):' in log_output
	assert 'System instructions' in log_output
	assert 'Current page state' in log_output
	assert 'Retry with a different selector' in log_output
	assert '💬[' in log_output
	assert '🧠[' in log_output


def test_log_history_lines_includes_rich_message_parts(tmp_path, monkeypatch):
	"""Debug history logging should include image and tool-call previews from the current message types."""
	monkeypatch.setattr(message_manager_service.shutil, 'get_terminal_size', lambda fallback: os.terminal_size((200, 20)))
	message_manager = _build_message_manager(tmp_path)
	message_manager._set_message_with_type(
		UserMessage(
			content=[
				ContentPartTextParam(text='State with screenshot'),
				ContentPartImageParam(image_url=ImageURL(url='data:image/png;base64,AAAA')),
			]
		),
		'state',
	)
	message_manager._add_context_message(
		AssistantMessage(
			content='Calling a tool',
			tool_calls=[
				ToolCall(
					id='call_1',
					function=Function(name='click', arguments='{"index": 1}'),
				)
			],
		)
	)

	log_output = message_manager._log_history_lines()

	assert 'State with screenshot' in log_output
	assert '<base64 image/png>' in log_output
	assert 'Calling a tool' in log_output
	assert 'click({"index": 1})' in log_output
