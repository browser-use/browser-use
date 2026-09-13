"""Tests for AnthropicMessageSerializer.serialize_messages with multiple system messages."""

from browser_use.llm.anthropic.serializer import AnthropicMessageSerializer
from browser_use.llm.messages import SystemMessage, UserMessage


def test_multiple_system_messages_preserved_in_order():
	"""All system messages should be preserved in their original order."""
	messages = [
		SystemMessage(content="Follow the base system rule."),
		SystemMessage(content="Also follow the additional system rule."),
		UserMessage(content="Continue the task."),
	]

	serialized_messages, system_prompt = AnthropicMessageSerializer.serialize_messages(messages)

	# Both system messages should be present
	assert system_prompt is not None
	assert isinstance(system_prompt, list)
	assert len(system_prompt) == 2
	assert system_prompt[0]['text'] == "Follow the base system rule."
	assert system_prompt[1]['text'] == "Also follow the additional system rule."

	# Only the user message should be in the regular messages
	assert len(serialized_messages) == 1


def test_single_system_message_returns_string():
	"""A single system message should return a plain string for efficiency."""
	messages = [
		SystemMessage(content="Base rule."),
		UserMessage(content="Do something."),
	]

	_, system_prompt = AnthropicMessageSerializer.serialize_messages(messages)

	assert isinstance(system_prompt, str)
	assert system_prompt == "Base rule."


def test_no_system_message_returns_none():
	"""No system messages should return None for system_prompt."""
	messages = [
		UserMessage(content="Hello."),
	]

	_, system_prompt = AnthropicMessageSerializer.serialize_messages(messages)

	assert system_prompt is None


def test_three_system_messages_all_preserved():
	"""Three system messages should all appear in order."""
	messages = [
		SystemMessage(content="First system instruction."),
		SystemMessage(content="Second system instruction."),
		SystemMessage(content="Third system instruction."),
		UserMessage(content="Execute."),
	]

	_, system_prompt = AnthropicMessageSerializer.serialize_messages(messages)

	assert system_prompt is not None
	assert isinstance(system_prompt, list)
	assert len(system_prompt) == 3
	assert system_prompt[0]['text'] == "First system instruction."
	assert system_prompt[1]['text'] == "Second system instruction."
	assert system_prompt[2]['text'] == "Third system instruction."
