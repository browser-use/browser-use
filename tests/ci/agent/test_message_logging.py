from types import SimpleNamespace

from pydantic import ConfigDict

from browser_use.agent.message_manager.service import (
	_log_format_message_line,
	_log_get_token_display,
)
from browser_use.llm.messages import UserMessage


class UserMessageWithMetadata(UserMessage):
	metadata: SimpleNamespace

	model_config = ConfigDict(arbitrary_types_allowed=True)


def test_log_token_display_uses_metadata_tokens():
	message = UserMessageWithMetadata(content='hello', metadata=SimpleNamespace(tokens=42))

	assert _log_get_token_display(message) == '  42'


def test_log_token_display_falls_back_without_metadata():
	message = UserMessage(content='hello')

	assert _log_get_token_display(message) == '   ?'


def test_log_format_message_line_does_not_emit_todo_placeholder():
	message = UserMessageWithMetadata(content='hello', metadata=SimpleNamespace(tokens=7))

	lines = _log_format_message_line(
		message,
		content='hello',
		is_last_message=False,
		terminal_width=80,
	)

	assert lines == ['💬[   7]: hello']
	assert 'TODO' not in lines[0]
