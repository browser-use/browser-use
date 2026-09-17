"""Regression tests for AnthropicMessageSerializer's handling of system messages."""

from browser_use.llm.anthropic.serializer import AnthropicMessageSerializer
from browser_use.llm.messages import BaseMessage, SystemMessage, UserMessage


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
		# Separated by a blank line, so one instruction does not run into the next.
		'Follow the base system rule.\n\n',
		'Also follow the additional system rule.',
	]
	assert len(messages) == 1


def test_empty_system_message_is_dropped_rather_than_sent_as_an_empty_block():
	"""Anthropic rejects an empty text block, so an empty extend_system_message must not
	turn a working request into a 400."""
	_, system = AnthropicMessageSerializer.serialize_messages(
		[
			SystemMessage(content=''),
			SystemMessage(content='Follow the base system rule.'),
			UserMessage(content='Continue the task.'),
		]
	)

	assert system == 'Follow the base system rule.'


def test_system_messages_that_are_all_empty_leave_no_system_instruction():
	"""Nothing to say means no system field at all, rather than a list of empty blocks."""
	_, system = AnthropicMessageSerializer.serialize_messages(
		[SystemMessage(content=''), SystemMessage(content=''), UserMessage(content='Continue the task.')]
	)

	assert system is None


def test_dropping_an_empty_system_message_keeps_the_cache_breakpoint():
	"""The breakpoint must land on a message that still has text, not vanish with the empty one."""
	_, system = AnthropicMessageSerializer.serialize_messages(
		[
			SystemMessage(content='Follow the base system rule.', cache=True),
			SystemMessage(content='', cache=True),
			UserMessage(content='Continue the task.'),
		]
	)

	assert system == [{'text': 'Follow the base system rule.', 'type': 'text', 'cache_control': {'type': 'ephemeral'}}]


def test_a_single_empty_system_message_is_unchanged():
	"""The single-message path is untouched: it still serializes to a plain string."""
	_, system = AnthropicMessageSerializer.serialize_messages(
		[SystemMessage(content=''), UserMessage(content='Continue the task.')]
	)

	assert system == ''


def test_cache_control_marks_the_last_cached_system_message():
	"""The breakpoint lands on the last *cached* message, not simply the last one."""
	_, system = AnthropicMessageSerializer.serialize_messages(
		[
			SystemMessage(content='Follow the base system rule.', cache=True),
			SystemMessage(content='Also follow the additional system rule.'),
			UserMessage(content='Continue the task.'),
		]
	)

	assert isinstance(system, list)
	assert system[0].get('cache_control') == {'type': 'ephemeral'}
	assert system[1].get('cache_control') is None


def test_only_the_last_cached_system_message_keeps_a_breakpoint():
	"""Anthropic allows four cache_control breakpoints per request, and a breakpoint caches
	everything before it, so several cached system messages must collapse to a single marker."""
	messages: list[BaseMessage] = [SystemMessage(content=f'Rule {index}.', cache=True) for index in range(5)]
	messages.append(UserMessage(content='Continue the task.'))

	_, system = AnthropicMessageSerializer.serialize_messages(messages)

	assert isinstance(system, list)
	assert [block.get('cache_control') is not None for block in system] == [False, False, False, False, True]
