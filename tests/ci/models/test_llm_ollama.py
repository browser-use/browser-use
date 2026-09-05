"""Tests for ChatOllama option handling and structured-output parsing."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from ollama import ChatResponse
from ollama._types import Message
from pydantic import BaseModel

from browser_use.llm.exceptions import ModelProviderError
from browser_use.llm.messages import UserMessage
from browser_use.llm.ollama.chat import ChatOllama


class Answer(BaseModel):
	answer: str


def _client_returning(content: str) -> MagicMock:
	client = MagicMock()
	client.chat = AsyncMock(return_value=MagicMock(message=MagicMock(content=content)))
	return client


async def test_splits_top_level_chat_parameters_from_ollama_options():
	"""Top-level chat parameters must not be sent inside model options (#5017)."""
	client = _client_returning('{"answer": "ok"}')
	llm = ChatOllama(
		model='test-model',
		ollama_options={
			'think': False,
			'logprobs': True,
			'top_logprobs': 3,
			'keep_alive': '10m',
			'format': 'json',
			'stream': False,
			'num_ctx': 2048,
		},
	)

	with patch.object(ChatOllama, 'get_client', return_value=client):
		result = await llm.ainvoke([UserMessage(content='hi')], output_format=Answer)

	assert result.completion.answer == 'ok'
	kwargs = client.chat.await_args.kwargs
	assert kwargs['options'] == {'num_ctx': 2048}
	assert kwargs['think'] is False
	assert kwargs['logprobs'] is True
	assert kwargs['top_logprobs'] == 3
	assert kwargs['keep_alive'] == '10m'
	assert kwargs['format'] == Answer.model_json_schema()
	assert kwargs.get('stream') is None


@pytest.mark.parametrize('fence', ['```json', '```JSON', '``` json', '```'])
async def test_parses_json_wrapped_in_markdown_fences(fence: str):
	client = _client_returning(f'{fence}\n{{"answer": "ok"}}\n```')
	llm = ChatOllama(model='test-model')

	with patch.object(ChatOllama, 'get_client', return_value=client):
		result = await llm.ainvoke([UserMessage(content='hi')], output_format=Answer)

	assert result.completion.answer == 'ok'


async def test_truncated_json_raises_model_provider_error():
	client = _client_returning('{\n')
	llm = ChatOllama(model='test-model')

	with patch.object(ChatOllama, 'get_client', return_value=client), pytest.raises(ModelProviderError) as exc_info:
		await llm.ainvoke([UserMessage(content='hi')], output_format=Answer)

	assert 'Invalid JSON' in exc_info.value.message or 'invalid JSON' in exc_info.value.message.lower()


def test_usage_is_reported_from_eval_counts():
	"""Ollama returns the counts as prompt_eval_count / eval_count."""
	response = ChatResponse(
		model='qwen3',
		done=True,
		message=Message(role='assistant', content='hi'),
		prompt_eval_count=350,
		eval_count=120,
	)

	usage = ChatOllama(model='qwen3')._get_usage(response)

	assert usage is not None
	assert usage.prompt_tokens == 350
	assert usage.completion_tokens == 120
	assert usage.total_tokens == 470


def test_usage_is_none_when_the_response_carries_no_counts():
	"""Both fields are Optional; reporting nothing beats reporting zero."""
	response = ChatResponse(model='qwen3', done=True, message=Message(role='assistant', content='hi'))

	assert ChatOllama(model='qwen3')._get_usage(response) is None


def test_a_fully_cached_prompt_still_reports_its_completion():
	"""prompt_eval_count is 0 when the whole prompt was already in cache."""
	response = ChatResponse(
		model='qwen3',
		done=True,
		message=Message(role='assistant', content='hi'),
		prompt_eval_count=0,
		eval_count=120,
	)

	usage = ChatOllama(model='qwen3')._get_usage(response)

	assert usage is not None
	assert usage.prompt_tokens == 0
	assert usage.completion_tokens == 120
	assert usage.total_tokens == 120
