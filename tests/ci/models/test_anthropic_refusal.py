"""Refusal content must survive conversion to Anthropic's text blocks."""

import pytest

from browser_use.llm.anthropic.serializer import AnthropicMessageSerializer
from browser_use.llm.messages import AssistantMessage, ContentPartRefusalParam, ContentPartTextParam, Function, ToolCall


@pytest.mark.parametrize('cache', [False, True])
@pytest.mark.parametrize('with_tool', [False, True])
@pytest.mark.parametrize('parts', [('refusal',), ('text', 'refusal'), ('refusal', 'text'), ('refusal', 'text', 'refusal')])
def test_assistant_refusal_preserves_order_and_cache(parts, cache, with_tool):
	content = [
		ContentPartRefusalParam(refusal=f'Declined {index}.')
		if part == 'refusal'
		else ContentPartTextParam(text=f'Text {index}.')
		for index, part in enumerate(parts)
	]
	expected = [f'[Refusal] Declined {index}.' if part == 'refusal' else f'Text {index}.' for index, part in enumerate(parts)]
	tool_calls = (
		[ToolCall(id='tool_1', function=Function(name='lookup', arguments='{"query": "refusal context", "limit": 2}'))]
		if with_tool
		else []
	)
	message = AssistantMessage(content=content, cache=cache, tool_calls=tool_calls)
	original = message.model_dump()
	serialized, _ = AnthropicMessageSerializer.serialize_messages([message])
	result = serialized[0]['content']
	if isinstance(result, str):
		assert not cache and not with_tool and len(expected) == 1
		assert expected == [result]
	else:
		assert isinstance(result, list)
		assert [block['text'] for block in result if isinstance(block, dict) and block['type'] == 'text'] == expected
		assert len(result) == len(expected) + int(with_tool)
		for index, block in enumerate(result):
			assert isinstance(block, dict)
			assert block.get('cache_control') == ({'type': 'ephemeral'} if cache and index == len(result) - 1 else None)
		if with_tool:
			last = result[-1]
			assert isinstance(last, dict)
			assert last['type'] == 'tool_use'
			assert last['id'] == 'tool_1'
			assert last['name'] == 'lookup'
			assert last['input'] == {'query': 'refusal context', 'limit': 2}
	assert message.model_dump() == original


@pytest.mark.parametrize('cache', [False, True])
@pytest.mark.parametrize('with_tool', [False, True])
@pytest.mark.parametrize('content', [None, [], 'Explanation.', [ContentPartRefusalParam(refusal='Content refusal.')]])
def test_top_level_refusal_preserves_content_and_cache(
	content: str | list[ContentPartTextParam | ContentPartRefusalParam] | None, cache: bool, with_tool: bool
) -> None:
	tool_calls = (
		[ToolCall(id='tool_1', function=Function(name='lookup', arguments='{"query": "refusal context", "limit": 2}'))]
		if with_tool
		else []
	)
	message = AssistantMessage(content=content, refusal='Top-level refusal.', cache=cache, tool_calls=tool_calls)
	original = message.model_dump()
	serialized, system = AnthropicMessageSerializer.serialize_messages([message])
	result = serialized[0]['content']
	expected = []
	if isinstance(content, str):
		expected.append(content)
	elif content:
		expected.append('[Refusal] Content refusal.')
	expected.append('[Refusal] Top-level refusal.')
	if isinstance(result, str):
		assert not cache and not with_tool
		assert [result] == expected
	else:
		assert isinstance(result, list)
		assert [block['text'] for block in result if isinstance(block, dict) and block['type'] == 'text'] == expected
		assert len(result) == len(expected) + int(with_tool)
		for index, block in enumerate(result):
			assert isinstance(block, dict)
			assert block.get('cache_control') == ({'type': 'ephemeral'} if cache and index == len(result) - 1 else None)
		if with_tool:
			last = result[-1]
			assert isinstance(last, dict)
			assert last['type'] == 'tool_use'
			assert last['id'] == 'tool_1'
			assert last['name'] == 'lookup'
			assert last['input'] == {'query': 'refusal context', 'limit': 2}
	assert system is None
	assert message.model_dump() == original
