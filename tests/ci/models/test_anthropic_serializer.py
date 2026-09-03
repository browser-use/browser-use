"""Regression tests for AnthropicMessageSerializer's handling of system messages."""

from browser_use.llm.anthropic.serializer import AnthropicMessageSerializer
from browser_use.llm.messages import SystemMessage, UserMessage


def test_single_system_message_is_returned_as_plain_string():
	"""The common case must keep returning a bare string, not a block list."""
	_, system = AnthropicMessageSerializer.serialize_messages(
		[SystemMessage(content='Follow the base system rule.'), UserMessage(content='Continue the task.')]
	)

	assert system == 'Follow the base system rule.'


def test_all_system_messages_are_preserved_in_order():
	"""Every SystemMessage must reach the request, in the order it was supplied."""
	messages, system = AnthropicMessageSerializer.serialize_messages(
		[
			SystemMessage(content='Follow the base system rule.'),
			SystemMessage(content='Also follow the additional system rule.'),
			UserMessage(content='Continue the task.'),
		]
	)

	assert isinstance(system, list)
	assert [block['text'] for block in system] == [
		'Follow the base system rule.',
		'Also follow the additional system rule.',
	]
	assert len(messages) == 1


def test_cache_control_is_kept_per_system_message():
	"""A cached system message keeps its cache_control when combined with an uncached one."""
	_, system = AnthropicMessageSerializer.serialize_messages(
		[
			SystemMessage(content='Follow the base system rule.', cache=True),
			SystemMessage(content='Also follow the additional system rule.'),
			UserMessage(content='Continue the task.'),
		]
	)

	assert isinstance(system, list)
	assert system[0]['cache_control'] == {'type': 'ephemeral'}
	assert system[1]['cache_control'] is None
