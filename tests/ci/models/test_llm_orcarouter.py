"""Regression tests for OrcaRouter client setup and response handling."""

import json

import httpx
import pytest
from openai.types.chat import ChatCompletion, ChatCompletionMessage
from openai.types.chat.chat_completion import Choice
from pydantic import BaseModel

from browser_use.llm.messages import UserMessage
from browser_use.llm.orcarouter.chat import ChatOrcaRouter


class Answer(BaseModel):
	answer: str


def _completion(*, content: str | None = 'ok') -> ChatCompletion:
	return ChatCompletion(
		id='chatcmpl-test',
		choices=[Choice(finish_reason='stop', index=0, message=ChatCompletionMessage(role='assistant', content=content))],
		created=0,
		model='openai/gpt-4o',
		object='chat.completion',
	)


@pytest.mark.parametrize('structured', [False, True])
@pytest.mark.parametrize('extra_body', [None, {}, {'provider': {'order': ['test-provider']}, 'transforms': ['middle-out']}])
async def test_extra_body_reaches_http_request(structured: bool, extra_body: dict | None):
	"""Send provider-specific fields through the real SDK into the JSON request body."""
	requests: list[httpx.Request] = []

	def handle_request(request: httpx.Request) -> httpx.Response:
		requests.append(request)
		return httpx.Response(200, json=_completion(content='{"answer":"ok"}' if structured else 'ok').model_dump())

	async with httpx.AsyncClient(transport=httpx.MockTransport(handle_request)) as client:
		llm = ChatOrcaRouter(model='openai/gpt-4o', api_key='test-key', http_client=client, extra_body=extra_body)
		result = await llm.ainvoke([UserMessage(content='question')], output_format=Answer if structured else None)

	assert result.completion == (Answer(answer='ok') if structured else 'ok')
	assert len(requests) == 1
	body = json.loads(requests[0].content)
	assert body['model'] == 'openai/gpt-4o'
	assert body['messages'] == [{'role': 'user', 'content': 'question'}]
	assert 'extra_body' not in body
	if extra_body:
		assert body['provider'] == {'order': ['test-provider']}
		assert body['transforms'] == ['middle-out']
	else:
		assert 'provider' not in body
		assert 'transforms' not in body
	if structured:
		assert body['response_format']['type'] == 'json_schema'
