"""Regression tests for Mistral client setup and retry behaviour."""

import json

import httpx
import pytest
from pytest_httpserver import HTTPServer
from werkzeug import Request, Response

from browser_use.llm.exceptions import ModelProviderError, ModelRateLimitError
from browser_use.llm.messages import UserMessage
from browser_use.llm.mistral.chat import ChatMistral


def test_client_uses_llm_scale_timeout_by_default():
	# httpx's own default is Timeout(5.0), shorter than a typical agent step.
	# The SDK-backed adapters get read=600 from their vendor SDK.
	timeout = ChatMistral(model='mistral-medium-latest', api_key='k')._client().timeout
	assert timeout.read == 600.0
	assert timeout.connect == 5.0


def test_explicit_timeout_takes_precedence():
	explicit = httpx.Timeout(30.0)
	assert ChatMistral(model='mistral-medium-latest', api_key='k', timeout=explicit)._client().timeout == explicit


def _completion_body() -> dict:
	return {
		'choices': [{'message': {'content': 'hi'}}],
		'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2},
	}


async def test_retries_after_rate_limit_then_succeeds(httpserver: HTTPServer):
	calls: list[int] = []

	def handler(request: Request) -> Response:
		calls.append(1)
		if len(calls) == 1:
			return Response('{"message": "rate limited"}', status=429, content_type='application/json')
		return Response(json.dumps(_completion_body()), status=200, content_type='application/json')

	httpserver.expect_request('/chat/completions').respond_with_handler(handler)

	chat = ChatMistral(
		model='mistral-medium-latest',
		api_key='k',
		base_url=httpserver.url_for(''),
		max_retries=2,
	)
	result = await chat.ainvoke([UserMessage(content='hi')])

	assert result.completion == 'hi'
	assert len(calls) == 2


async def test_exhausted_retries_raise_rate_limit_error(httpserver: HTTPServer):
	calls: list[int] = []

	def handler(request: Request) -> Response:
		calls.append(1)
		return Response('{"message": "rate limited"}', status=429, content_type='application/json')

	httpserver.expect_request('/chat/completions').respond_with_handler(handler)

	chat = ChatMistral(model='mistral-medium-latest', api_key='k', base_url=httpserver.url_for(''), max_retries=2)
	with pytest.raises(ModelRateLimitError):
		await chat.ainvoke([UserMessage(content='hi')])

	assert len(calls) == 2


async def test_client_errors_are_not_retried(httpserver: HTTPServer):
	calls: list[int] = []

	def handler(request: Request) -> Response:
		calls.append(1)
		return Response('{"message": "Invalid model"}', status=400, content_type='application/json')

	httpserver.expect_request('/chat/completions').respond_with_handler(handler)

	chat = ChatMistral(model='bad-model', api_key='k', base_url=httpserver.url_for(''), max_retries=5)
	with pytest.raises(ModelProviderError):
		await chat.ainvoke([UserMessage(content='hi')])

	assert len(calls) == 1
