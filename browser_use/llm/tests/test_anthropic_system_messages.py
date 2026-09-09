"""Regression coverage for preserving Anthropic system instructions."""

import pytest

from browser_use.llm.anthropic.serializer import AnthropicMessageSerializer
from browser_use.llm.messages import AssistantMessage, BaseMessage, ContentPartTextParam, SystemMessage, UserMessage


@pytest.mark.parametrize('use_blocks', [False, True])
def test_multiple_system_messages_preserve_order(use_blocks: bool):
	"""Keep every instruction, including system messages interleaved with conversation."""
	first = [ContentPartTextParam(text='Base rule'), ContentPartTextParam(text='Extra rule')] if use_blocks else 'Base rule'
	messages: list[BaseMessage] = [
		SystemMessage(content=first),
		UserMessage(content='Question'),
		SystemMessage(content='Final rule'),
		AssistantMessage(content='Answer'),
	]
	original = [message.model_dump() for message in messages]

	conversation, system = AnthropicMessageSerializer.serialize_messages(messages)

	assert conversation == [{'role': 'user', 'content': 'Question'}, {'role': 'assistant', 'content': 'Answer'}]
	assert isinstance(system, list)
	assert [block['text'] for block in system] == (
		['Base rule', 'Extra rule', 'Final rule'] if use_blocks else ['Base rule', 'Final rule']
	)
	assert all(not block.get('cache_control') for block in system)
	assert [message.model_dump() for message in messages] == original


@pytest.mark.parametrize('cached', [False, True])
@pytest.mark.parametrize('use_blocks', [False, True])
def test_single_system_message_shape_is_unchanged(cached: bool, use_blocks: bool):
	"""Retain the existing string and text-block representations for one instruction."""
	content = [ContentPartTextParam(text='Rule')] if use_blocks else 'Rule'
	_, system = AnthropicMessageSerializer.serialize_messages([SystemMessage(content=content, cache=cached)])
	if use_blocks or cached:
		assert system == [{'type': 'text', 'text': 'Rule', 'cache_control': {'type': 'ephemeral'} if cached else None}]
	else:
		assert system == 'Rule'


def test_no_system_messages():
	"""Keep the absent system instruction represented by None."""
	assert AnthropicMessageSerializer.serialize_messages([]) == ([], None)
	assert AnthropicMessageSerializer.serialize_messages([UserMessage(content='Hello')]) == (
		[{'role': 'user', 'content': 'Hello'}],
		None,
	)


def test_only_last_cached_system_message_has_breakpoint():
	"""Bound cache breakpoints while preserving the boundary before uncached instructions."""
	messages: list[BaseMessage] = [SystemMessage(content=f'Rule {i}', cache=True) for i in range(5)]
	messages.extend(
		[
			SystemMessage(content=[ContentPartTextParam(text='Part one'), ContentPartTextParam(text='Part two')], cache=True),
			SystemMessage(content='Uncached suffix'),
			UserMessage(content='Question', cache=True),
		]
	)
	original = [message.model_dump() for message in messages]
	conversation, system = AnthropicMessageSerializer.serialize_messages(messages)
	assert isinstance(system, list)
	assert [block['text'] for block in system] == [*(f'Rule {i}' for i in range(5)), 'Part one', 'Part two', 'Uncached suffix']
	assert [i for i, block in enumerate(system) if block.get('cache_control')] == [6]
	assert conversation == [
		{'role': 'user', 'content': [{'type': 'text', 'text': 'Question', 'cache_control': {'type': 'ephemeral'}}]}
	]
	assert [message.model_dump() for message in messages] == original
