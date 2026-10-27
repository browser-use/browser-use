"""Regression test: when Claude calls the tool but writes the whole call out as text inside a
single string argument, the arguments must be recovered instead of failing validation with a
misleading 'Field required' error for the fields that were never populated."""

import json

import pytest
from pydantic import BaseModel

from browser_use.llm.anthropic.chat import ChatAnthropic
from browser_use.llm.exceptions import ModelProviderError
from browser_use.llm.messages import UserMessage


class StepOutput(BaseModel):
	thinking: str
	action: list[dict]


def _tool_use_response(tool_input: dict | str) -> dict:
	return {
		'id': 'msg_test',
		'type': 'message',
		'role': 'assistant',
		'model': 'claude-sonnet-5',
		'content': [{'type': 'tool_use', 'id': 'toolu_test', 'name': 'StepOutput', 'input': tool_input}],
		'stop_reason': 'tool_use',
		'stop_sequence': None,
		'usage': {'input_tokens': 10, 'output_tokens': 20},
	}


def _chat(httpserver) -> ChatAnthropic:
	return ChatAnthropic(model='claude-sonnet-5', api_key='test-key', base_url=httpserver.url_for('/'))


async def test_tool_call_rendered_as_xml_in_string_field_is_recovered(httpserver):
	"""The model fills only `thinking`, with the complete call as `<parameter name=...>` markup."""
	actions = [{'click_element_by_index': {'index': 5}}]
	serialized = (
		'<invoke name="StepOutput">\n'
		'<parameter name="thinking">The submit button is at index 5.</parameter>\n'
		f'<parameter name="action">{json.dumps(actions)}</action>\n'
		'</invoke>\n'
	)
	httpserver.expect_request('/v1/messages', method='POST').respond_with_json(_tool_use_response({'thinking': serialized}))

	result = await _chat(httpserver).ainvoke([UserMessage(content='next step')], output_format=StepOutput)

	assert result.completion.thinking == 'The submit button is at index 5.'
	assert result.completion.action == actions


async def test_tool_call_rendered_as_json_in_string_field_is_recovered(httpserver):
	"""Same failure mode, but the model writes JSON into the string field instead of markup."""
	payload = {'thinking': 'Clicking submit.', 'action': [{'click_element_by_index': {'index': 5}}]}
	httpserver.expect_request('/v1/messages', method='POST').respond_with_json(
		_tool_use_response({'thinking': f'Here is my response:\n{json.dumps(payload)}'})
	)

	result = await _chat(httpserver).ainvoke([UserMessage(content='next step')], output_format=StepOutput)

	assert result.completion.action == payload['action']


async def test_double_serialized_field_still_repaired(httpserver):
	"""The pre-existing repair for a single JSON-string field must keep working."""
	actions = [{'click_element_by_index': {'index': 5}}]
	httpserver.expect_request('/v1/messages', method='POST').respond_with_json(
		_tool_use_response({'thinking': 'Clicking submit.', 'action': json.dumps(actions)})
	)

	result = await _chat(httpserver).ainvoke([UserMessage(content='next step')], output_format=StepOutput)

	assert result.completion.action == actions


async def test_valid_tool_input_is_untouched(httpserver):
	actions = [{'click_element_by_index': {'index': 5}}]
	httpserver.expect_request('/v1/messages', method='POST').respond_with_json(
		_tool_use_response({'thinking': 'Clicking submit.', 'action': actions})
	)

	result = await _chat(httpserver).ainvoke([UserMessage(content='next step')], output_format=StepOutput)

	assert result.completion.action == actions


async def test_valid_tool_input_wins_over_conflicting_serialized_thinking(httpserver):
	"""A valid real action must take priority over a serialized action in thinking."""
	real_actions = [{'click_element_by_index': {'index': 5}}]
	serialized_actions = [{'click_element_by_index': {'index': 99}}]
	serialized = json.dumps({'thinking': 'Conflicting fallback.', 'action': serialized_actions})
	httpserver.expect_request('/v1/messages', method='POST').respond_with_json(
		_tool_use_response({'thinking': serialized, 'action': real_actions})
	)

	result = await _chat(httpserver).ainvoke([UserMessage(content='next step')], output_format=StepOutput)

	assert result.completion.action == real_actions
	assert result.completion.thinking == serialized


async def test_serialized_tool_call_outside_thinking_is_not_recovered(httpserver):
	"""Only the known malformed `thinking` path may be promoted to structured output."""
	payload = {'thinking': 'Clicking submit.', 'action': [{'click_element_by_index': {'index': 5}}]}
	httpserver.expect_request('/v1/messages', method='POST').respond_with_json(
		_tool_use_response({'thinking': 'No structured action was produced.', 'other': json.dumps(payload)})
	)

	with pytest.raises(ModelProviderError) as exc_info:
		await _chat(httpserver).ainvoke([UserMessage(content='next step')], output_format=StepOutput)

	assert 'action' in str(exc_info.value)


async def test_unrecoverable_tool_input_still_raises(httpserver):
	"""Recovery must not mask genuinely malformed output."""
	httpserver.expect_request('/v1/messages', method='POST').respond_with_json(
		_tool_use_response({'thinking': 'I could not decide what to do next.'})
	)

	with pytest.raises(ModelProviderError) as exc_info:
		await _chat(httpserver).ainvoke([UserMessage(content='next step')], output_format=StepOutput)

	assert 'action' in str(exc_info.value)
