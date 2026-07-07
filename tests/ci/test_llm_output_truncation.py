"""Regression test: structured output cut off at the completion-token cap must raise a
clear truncation error, not a misleading JSON parse error ('Unterminated string...')."""

import pytest
from pydantic import BaseModel

from browser_use.llm.exceptions import ModelProviderError
from browser_use.llm.messages import UserMessage
from browser_use.llm.openai.chat import ChatOpenAI


class AnswerFormat(BaseModel):
	answer: str


async def test_openai_truncated_structured_output_raises_clear_error(httpserver):
	"""finish_reason='length' with JSON cut mid-string must surface the token cap, not a parse error."""
	httpserver.expect_request('/v1/chat/completions', method='POST').respond_with_json(
		{
			'id': 'chatcmpl-test',
			'object': 'chat.completion',
			'created': 0,
			'model': 'gpt-4o',
			'choices': [
				{
					'index': 0,
					'message': {'role': 'assistant', 'content': '{"answer": "this output was cut off mid-sent'},
					'finish_reason': 'length',
				}
			],
			'usage': {'prompt_tokens': 10, 'completion_tokens': 4096, 'total_tokens': 4106},
		}
	)

	llm = ChatOpenAI(model='gpt-4o', api_key='test-key', base_url=httpserver.url_for('/v1'))

	with pytest.raises(ModelProviderError) as exc_info:
		await llm.ainvoke([UserMessage(content='answer at length')], output_format=AnswerFormat)

	assert 'truncated' in str(exc_info.value), f'expected a truncation error, got: {exc_info.value}'
	assert 'max_completion_tokens' in str(exc_info.value)


async def test_openai_normal_structured_output_still_parses(httpserver):
	httpserver.expect_request('/v1/chat/completions', method='POST').respond_with_json(
		{
			'id': 'chatcmpl-test',
			'object': 'chat.completion',
			'created': 0,
			'model': 'gpt-4o',
			'choices': [
				{
					'index': 0,
					'message': {'role': 'assistant', 'content': '{"answer": "complete answer"}'},
					'finish_reason': 'stop',
				}
			],
			'usage': {'prompt_tokens': 10, 'completion_tokens': 8, 'total_tokens': 18},
		}
	)

	llm = ChatOpenAI(model='gpt-4o', api_key='test-key', base_url=httpserver.url_for('/v1'))

	result = await llm.ainvoke([UserMessage(content='answer briefly')], output_format=AnswerFormat)
	assert result.completion.answer == 'complete answer'


async def test_truncation_error_readable_when_cap_unset(httpserver):
	"""With max_completion_tokens=None, the error must describe the limit without printing 'None'."""
	httpserver.expect_request('/v1/chat/completions', method='POST').respond_with_json(
		{
			'id': 'chatcmpl-test',
			'object': 'chat.completion',
			'created': 0,
			'model': 'gpt-4o',
			'choices': [
				{
					'index': 0,
					'message': {'role': 'assistant', 'content': '{"answer": "cut off mid'},
					'finish_reason': 'length',
				}
			],
			'usage': {'prompt_tokens': 10, 'completion_tokens': 16384, 'total_tokens': 16394},
		}
	)

	llm = ChatOpenAI(model='gpt-4o', api_key='test-key', base_url=httpserver.url_for('/v1'), max_completion_tokens=None)

	with pytest.raises(ModelProviderError) as exc_info:
		await llm.ainvoke([UserMessage(content='answer at length')], output_format=AnswerFormat)

	assert 'truncated' in str(exc_info.value)
	assert 'None' not in str(exc_info.value), f'error message leaks None: {exc_info.value}'


def test_truncation_error_triggers_fallback_llm_switch(tmp_path):
	"""A truncation error must allow switching to a configured fallback LLM — a
	fallback with a different output cap can succeed where the primary truncated."""
	from browser_use.agent.service import Agent
	from browser_use.llm.exceptions import ModelOutputTruncatedError
	from tests.ci.conftest import create_mock_llm

	agent = Agent(
		task='test fallback on truncation',
		llm=create_mock_llm(),
		fallback_llm=create_mock_llm(),
		file_system_path=str(tmp_path / 'agent-files'),
	)

	error = ModelOutputTruncatedError(message='Model output was truncated at max_completion_tokens=4096', model='gpt-4o')
	assert agent._try_switch_to_fallback_llm(error) is True
	assert agent._using_fallback_llm is True


async def test_truncation_detected_when_content_is_null(httpserver):
	"""Reasoning models can spend the whole completion budget on hidden reasoning:
	finish_reason='length' with content=null. That must surface as truncation, not
	the generic 'Failed to parse structured output'."""
	httpserver.expect_request('/v1/chat/completions', method='POST').respond_with_json(
		{
			'id': 'chatcmpl-test',
			'object': 'chat.completion',
			'created': 0,
			'model': 'o3',
			'choices': [
				{
					'index': 0,
					'message': {'role': 'assistant', 'content': None},
					'finish_reason': 'length',
				}
			],
			'usage': {'prompt_tokens': 10, 'completion_tokens': 4096, 'total_tokens': 4106},
		}
	)

	llm = ChatOpenAI(model='o3', api_key='test-key', base_url=httpserver.url_for('/v1'))

	with pytest.raises(ModelProviderError) as exc_info:
		await llm.ainvoke([UserMessage(content='think hard')], output_format=AnswerFormat)

	assert 'truncated' in str(exc_info.value), f'expected truncation signal, got: {exc_info.value}'
