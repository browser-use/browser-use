"""Regression test: every system message must survive Anthropic serialization.

`serialize_messages()` used a single `system_message` slot, so each `SystemMessage` overwrote the
previous one and only the last instruction was sent as the Anthropic system prompt.
"""

from browser_use.llm.anthropic.serializer import AnthropicMessageSerializer
from browser_use.llm.messages import SystemMessage, UserMessage


def _texts(system_message) -> list[str]:
	if isinstance(system_message, str):
		return [system_message]
	return [block['text'] for block in system_message]


def test_multiple_system_messages_are_preserved_in_order() -> None:
	messages = [
		SystemMessage(content='Follow the base system rule.'),
		SystemMessage(content='Also follow the additional system rule.'),
		UserMessage(content='Continue the task.'),
	]
	serialized_messages, system_message = AnthropicMessageSerializer.serialize_messages(messages)

	assert _texts(system_message) == ['Follow the base system rule.', 'Also follow the additional system rule.']
	assert len(serialized_messages) == 1
	assert serialized_messages[0]['role'] == 'user'


def test_single_plain_system_message_keeps_string_shape() -> None:
	messages = [SystemMessage(content='Only one instruction.'), UserMessage(content='Go.')]
	_, system_message = AnthropicMessageSerializer.serialize_messages(messages)

	assert system_message == 'Only one instruction.'


def test_multiple_system_messages_with_cache_keep_cache_on_last_block() -> None:
	messages = [
		SystemMessage(content='First instruction.'),
		SystemMessage(content='Second instruction.', cache=True),
		UserMessage(content='Go.'),
	]
	_, system_message = AnthropicMessageSerializer.serialize_messages(messages)

	assert isinstance(system_message, list)
	assert _texts(system_message) == ['First instruction.', 'Second instruction.']
	assert 'cache_control' not in system_message[0]
	assert system_message[1]['cache_control'] == {'type': 'ephemeral'}
