"""Check provider usage using real clients with local HTTP transports."""

import json

import httpx
import pytest
from ollama import ChatResponse, Message
from openai.types.chat.chat_completion import ChatCompletion
from pydantic import BaseModel

from browser_use.llm.deepseek.chat import ChatDeepSeek
from browser_use.llm.messages import UserMessage
from browser_use.llm.ollama.chat import ChatOllama, _get_usage
from browser_use.llm.openai.usage import get_chat_usage


class Answer(BaseModel):
	"""A structured completion for the provider usage checks."""

	answer: str


@pytest.mark.parametrize('prompt,completion', [(None, None), (1, None), (None, 1)])
def test_ollama_partial_usage_is_unknown(prompt: int | None, completion: int | None):
	"""Avoid inventing a total when either of Ollama's token counts is missing."""
	response = ChatResponse(
		model='test', message=Message(role='assistant', content='ok'), prompt_eval_count=prompt, eval_count=completion
	)
	assert _get_usage(response) is None


def test_ollama_zero_token_counts_are_preserved():
	"""Zero is a reported count, not a missing count."""
	response = ChatResponse(model='test', message=Message(role='assistant', content='ok'), prompt_eval_count=0, eval_count=0)
	usage = _get_usage(response)
	assert usage is not None
	assert (usage.prompt_tokens, usage.completion_tokens, usage.total_tokens) == (0, 0, 0)


@pytest.mark.parametrize(
	'fields,expected',
	[
		({}, None),
		({'prompt_cache_hit_tokens': 6}, 6),
		({'prompt_tokens_details': {'cached_tokens': 0}, 'prompt_cache_hit_tokens': 6}, 0),
	],
)
def test_openai_compatible_cache_usage(fields: dict, expected: int | None):
	"""Use standard cached-token details first, with DeepSeek's cache field as a fallback."""
	response = ChatCompletion.model_validate(
		{
			'id': 'test',
			'object': 'chat.completion',
			'created': 1,
			'model': 'test',
			'choices': [],
			'usage': {'prompt_tokens': 10, 'completion_tokens': 4, 'total_tokens': 14, **fields},
		}
	)
	usage = get_chat_usage(response)
	assert usage is not None
	assert usage.prompt_cached_tokens == expected
	assert (usage.prompt_tokens, usage.completion_tokens, usage.total_tokens) == (10, 4, 14)


@pytest.mark.parametrize('structured', [False, True])
@pytest.mark.parametrize('include_usage', [False, True])
async def test_ollama_reports_usage_for_text_and_structured_output(structured: bool, include_usage: bool):
	"""Ollama counts propagate on both response paths; absent counts remain unknown."""

	def respond(request: httpx.Request) -> httpx.Response:
		"""Provide an Ollama chat response without starting a model server."""
		body = json.loads(request.content)
		content = '{"answer":"ok"}' if 'format' in body else 'ok'
		response = {
			'model': 'test',
			'created_at': '2026-01-01T00:00:00Z',
			'message': {'role': 'assistant', 'content': content},
			'done': True,
		}
		if include_usage:
			response.update({'prompt_eval_count': 10, 'eval_count': 4})
		return httpx.Response(200, json=response)

	model = ChatOllama(model='test', host='http://localhost:11434', client_params={'transport': httpx.MockTransport(respond)})
	result = await model.ainvoke([UserMessage(content='hi')], output_format=Answer if structured else None)
	if include_usage:
		assert result.usage is not None
		assert (result.usage.prompt_tokens, result.usage.completion_tokens, result.usage.total_tokens) == (10, 4, 14)
	else:
		assert result.usage is None


@pytest.mark.parametrize('structured', [False, True])
@pytest.mark.parametrize('include_usage', [False, True])
async def test_deepseek_reports_usage_for_text_and_structured_output(structured: bool, include_usage: bool):
	"""DeepSeek usage and cache hits propagate on both text and tool-call responses."""

	def respond(request: httpx.Request) -> httpx.Response:
		"""Return a DeepSeek-shaped OpenAI response from the HTTP boundary."""
		body = json.loads(request.content)
		message = {'role': 'assistant', 'content': 'ok'}
		if 'tools' in body:
			message = {
				'role': 'assistant',
				'content': None,
				'tool_calls': [
					{'id': 'call-1', 'type': 'function', 'function': {'name': 'Answer', 'arguments': '{"answer":"ok"}'}}
				],
			}
		response = {
			'id': 'test',
			'object': 'chat.completion',
			'created': 1,
			'model': 'test',
			'choices': [{'index': 0, 'finish_reason': 'stop', 'message': message}],
		}
		if include_usage:
			response['usage'] = {'prompt_tokens': 10, 'completion_tokens': 4, 'total_tokens': 14, 'prompt_cache_hit_tokens': 6}
		return httpx.Response(200, json=response)

	async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
		model = ChatDeepSeek(
			model='test', api_key='test', base_url='https://example.com/v1', client_params={'http_client': client}
		)
		result = await model.ainvoke([UserMessage(content='hi')], output_format=Answer if structured else None)
	if include_usage:
		assert result.usage is not None
		assert (result.usage.prompt_tokens, result.usage.completion_tokens, result.usage.total_tokens) == (10, 4, 14)
		assert result.usage.prompt_cached_tokens == 6
	else:
		assert result.usage is None
