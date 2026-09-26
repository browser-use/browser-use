"""Regression tests for the Mistral chat client: timeout defaults, request payload, schema sanitization, and error mapping."""

import json

import httpx
import pytest
from pydantic import BaseModel, Field

from browser_use.llm.exceptions import ModelProviderError, ModelRateLimitError
from browser_use.llm.messages import UserMessage
from browser_use.llm.mistral.chat import ChatMistral


class Answer(BaseModel):
	answer: str


class Constrained(BaseModel):
	name: str = Field(..., min_length=2, max_length=10, pattern='[a-z]+')


def _mistral_response(*, content: str = 'ok', choices: bool = True) -> dict:
	return {
		'id': 'cmpl-test',
		'object': 'chat.completion',
		'created': 0,
		'model': 'mistral-medium-latest',
		'choices': [
			{
				'index': 0,
				'finish_reason': 'stop',
				'message': {'role': 'assistant', 'content': content},
			}
		]
		if choices
		else [],
		'usage': {'prompt_tokens': 5, 'completion_tokens': 2, 'total_tokens': 7},
	}


def _mock_llm(handler, **kwargs) -> ChatMistral:
	requests: list[httpx.Request] = []

	def wrapped_handler(request: httpx.Request) -> httpx.Response:
		requests.append(request)
		return handler(request)

	client = httpx.AsyncClient(transport=httpx.MockTransport(wrapped_handler))
	llm = ChatMistral(model='mistral-medium-latest', api_key='test-key', http_client=client, **kwargs)
	llm._captured_requests = requests  # type: ignore[attr-defined]
	return llm


def test_default_timeout_matches_openai_sdk_default():
	"""httpx's own library default is 5s, which times out most real LLM calls.

	Every AsyncOpenAI-based provider in this repo defaults to 600s; ChatMistral
	must fall back to the same value instead of the httpx default.
	"""
	llm = ChatMistral(model='mistral-medium-latest', api_key='test-key')
	assert llm._client().timeout == httpx.Timeout(timeout=600.0, connect=5.0)


def test_explicit_timeout_is_honored():
	llm = ChatMistral(model='mistral-medium-latest', api_key='test-key', timeout=httpx.Timeout(42.0))
	assert llm._client().timeout == httpx.Timeout(42.0)


def test_http_client_takes_precedence():
	def handler(request: httpx.Request) -> httpx.Response:
		return httpx.Response(200, json=_mistral_response())

	outer = httpx.AsyncClient(transport=httpx.MockTransport(handler))
	llm = ChatMistral(model='mistral-medium-latest', api_key='test-key', http_client=outer)
	assert llm._client() is outer


async def test_invoke_sends_expected_payload():
	llm = _mock_llm(lambda request: httpx.Response(200, json=_mistral_response()))

	result = await llm.ainvoke([UserMessage(content='question')])

	assert result.completion == 'ok'
	assert result.usage is not None and result.usage.total_tokens == 7
	body = json.loads(llm._captured_requests[0].content)  # type: ignore[attr-defined]
	assert body['model'] == 'mistral-medium-latest'
	assert body['messages'] == [{'role': 'user', 'content': 'question'}]
	assert body['temperature'] == 0.2
	assert body['max_tokens'] == 4096
	assert 'response_format' not in body
	assert llm._captured_requests[0].headers['authorization'] == 'Bearer test-key'  # type: ignore[attr-defined]


async def test_structured_output_strips_unsupported_keywords():
	llm = _mock_llm(lambda request: httpx.Response(200, json=_mistral_response(content='{"answer":"ok"}')))

	await llm.ainvoke([UserMessage(content='question')], Answer)

	body = json.loads(llm._captured_requests[0].content)  # type: ignore[attr-defined]
	assert body['response_format']['type'] == 'json_schema'
	assert body['response_format']['json_schema']['strict'] is True

	# Constrained fields must survive schema sanitization without the keywords Mistral rejects
	llm2 = _mock_llm(lambda request: httpx.Response(200, json=_mistral_response(content='{"name":"ok"}')))
	await llm2.ainvoke([UserMessage(content='question')], Constrained)
	body2 = json.loads(llm2._captured_requests[0].content)  # type: ignore[attr-defined]
	name_schema = body2['response_format']['json_schema']['schema']['properties']['name']
	for keyword in ('minLength', 'maxLength', 'pattern'):
		assert keyword not in name_schema


async def test_rate_limit_maps_to_model_rate_limit_error():
	llm = _mock_llm(lambda request: httpx.Response(429, json={'message': 'Rate limit exceeded'}))

	with pytest.raises(ModelRateLimitError) as exc_info:
		await llm.ainvoke([UserMessage(content='question')])
	assert exc_info.value.status_code == 429


async def test_provider_error_keeps_status_code():
	llm = _mock_llm(lambda request: httpx.Response(500, json={'message': 'Internal error'}))

	with pytest.raises(ModelProviderError) as exc_info:
		await llm.ainvoke([UserMessage(content='question')])
	assert exc_info.value.status_code == 500


async def test_empty_choices_raise_provider_error():
	llm = _mock_llm(lambda request: httpx.Response(200, json=_mistral_response(choices=False)))

	with pytest.raises(ModelProviderError, match='no choices'):
		await llm.ainvoke([UserMessage(content='question')])
