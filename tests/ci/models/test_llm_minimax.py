"""Exercise MiniMax at the SDK's serialized HTTP boundary, without inference."""

import json
from typing import Any, get_args

import httpx
import pytest
from pydantic import BaseModel

from browser_use import ChatMiniMax
from browser_use.llm.exceptions import ModelProviderError
from browser_use.llm.messages import (
	AssistantMessage,
	BaseMessage,
	ContentPartImageParam,
	ContentPartTextParam,
	Function,
	ImageURL,
	ToolCall,
	UserMessage,
)
from browser_use.llm.models import get_llm_by_name
from browser_use.llm.openai.chat import ChatOpenAI
from browser_use.llm.vercel.chat import ChatVercel, ChatVercelModel


class Answer(BaseModel):
	answer: str


def completion_response(request: httpx.Request) -> httpx.Response:
	return httpx.Response(
		200,
		json={
			'id': 'test-completion',
			'object': 'chat.completion',
			'created': 0,
			'model': json.loads(request.content)['model'],
			'choices': [
				{
					'index': 0,
					'message': {'role': 'assistant', 'content': '{"answer":"ok"}', 'reasoning_content': 'preserved reasoning'},
					'finish_reason': 'stop',
				}
			],
			'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15},
		},
	)


@pytest.mark.parametrize('region,host', [('global', 'api.minimax.io'), ('cn', 'api.minimaxi.com')])
@pytest.mark.parametrize('structured', [False, True])
async def test_default_sdk_request_preserves_images_history_and_reasoning(monkeypatch, region, host, structured):
	monkeypatch.delenv('MINIMAX_BASE_URL', raising=False)
	requests = []

	def handle(request):
		requests.append(request)
		return completion_response(request)

	messages: list[BaseMessage] = [
		AssistantMessage(
			content='<think>previous thought</think>previous answer',
			reasoning_content='previous separate reasoning',
			tool_calls=[ToolCall(id='call-1', function=Function(name='inspect', arguments='{}'))],
		),
		UserMessage(
			content=[
				ContentPartTextParam(text='Inspect this screenshot'),
				ContentPartImageParam(image_url=ImageURL(url='data:image/png;base64,dGVzdA==', detail='high')),
			]
		),
	]
	original = [message.model_dump() for message in messages]
	async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
		llm = ChatMiniMax(api_key='test-key', region=region, http_client=client, max_retries=0)
		result = await llm.ainvoke(messages, output_format=Answer if structured else None)

	assert len(requests) == 1
	request = requests[0]
	assert request.url.host == host
	assert request.url.path == '/v1/chat/completions'
	body = json.loads(request.content)
	assert body['model'] == 'MiniMax-M3.1-Flash'
	assert body['reasoning_effort'] == 'max'
	assert body['max_completion_tokens'] == 16384
	assert 'service_tier' not in body
	assert 'reasoning_split' not in body
	assert 'thinking' not in body  # The native API defaults to adaptive.
	assert body['messages'][0]['content'] == original[0]['content']
	assert body['messages'][0]['reasoning_content'] == 'previous separate reasoning'
	assert body['messages'][0]['tool_calls'][0]['id'] == 'call-1'
	assert body['messages'][1]['content'][1]['image_url'] == {'url': 'data:image/png;base64,dGVzdA==', 'detail': 'high'}
	assert [message.model_dump() for message in messages] == original
	assert result.thinking == 'preserved reasoning'
	assert result.usage is not None and result.usage.total_tokens == 15
	if structured:
		assert result.completion == Answer(answer='ok')
		assert body['response_format']['type'] == 'json_schema'
	else:
		assert result.completion == '{"answer":"ok"}'


@pytest.mark.parametrize('effort', ['low', 'medium', 'high', 'xhigh', 'max'])
async def test_flash_explicit_effort_and_adaptive_thinking(effort):
	def handle(request):
		body = json.loads(request.content)
		assert body['reasoning_effort'] == effort
		assert body['thinking'] == {'type': 'adaptive'}
		return completion_response(request)

	async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
		llm = ChatMiniMax(api_key='test-key', reasoning_effort=effort, thinking='adaptive', http_client=client)
		await llm.ainvoke([UserMessage(content='hello')])


@pytest.mark.parametrize(
	'options,error',
	[
		({'thinking': 'disabled'}, 'requires adaptive thinking'),
		({'reasoning_effort': 'none'}, 'reasoning_effort must be'),
		({'service_tier': 'priority'}, 'does not support service_tier'),
	],
)
async def test_flash_rejects_unsupported_parameters_before_http(options: dict[str, Any], error):
	def handle(request):
		pytest.fail('Invalid Flash options must not reach HTTP')

	async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
		llm = ChatMiniMax(api_key='test-key', http_client=client, **options)
		with pytest.raises(ModelProviderError, match=error):
			await llm.ainvoke([UserMessage(content='hello')])


@pytest.mark.parametrize(
	'alias,expected',
	[
		('minimax_m3_1_flash', 'MiniMax-M3.1-Flash'),
		('minimax_m3', 'MiniMax-M3'),
		('minimax_m2_7', 'MiniMax-M2.7'),
		('minimax_MiniMax-M2.5', 'MiniMax-M2.5'),
		('minimax_custom_deployment-v1', 'custom_deployment-v1'),
	],
)
async def test_factory_model_ids_reach_sdk_unchanged(monkeypatch, alias, expected):
	monkeypatch.setenv('MINIMAX_API_KEY', 'test-key')
	monkeypatch.setenv('MINIMAX_BASE_URL', 'https://custom.example/v1')

	def handle(request):
		body = json.loads(request.content)
		assert request.url.host == 'custom.example'
		assert body['model'] == expected
		assert ('reasoning_effort' in body) == (expected == 'MiniMax-M3.1-Flash')
		return completion_response(request)

	async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
		llm = get_llm_by_name(alias)
		assert isinstance(llm, ChatMiniMax)
		llm.http_client = client
		await llm.ainvoke([UserMessage(content='hello')])


async def test_m3_can_disable_thinking_and_explicit_endpoint_wins(monkeypatch):
	monkeypatch.setenv('MINIMAX_BASE_URL', 'https://unused.example/v1')

	def handle(request):
		body = json.loads(request.content)
		assert request.url.host == 'explicit.example'
		assert body['model'] == 'MiniMax-M3'
		assert body['thinking'] == {'type': 'disabled'}
		assert 'reasoning_effort' not in body
		return completion_response(request)

	async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
		llm = ChatMiniMax(
			model='MiniMax-M3',
			api_key='test-key',
			base_url='https://explicit.example/v1',
			thinking='disabled',
			http_client=client,
		)
		await llm.ainvoke([UserMessage(content='hello')])


def test_current_catalog_excludes_legacy_suggestions_but_keeps_factory_support():
	from browser_use.llm import models

	assert [name for name in models.__all__ if name.startswith('minimax_')] == ['minimax_m3_1_flash', 'minimax_m3']
	assert [name for name in get_args(ChatVercelModel) if name.startswith('minimax/')] == ['minimax/minimax-m3']


@pytest.mark.parametrize('model,reasoning', [('gpt-4.1', False), ('o3-mini', True)])
async def test_shared_request_options_preserve_openai_behavior(model, reasoning):
	def handle(request):
		body = json.loads(request.content)
		assert body['model'] == model
		assert body['max_completion_tokens'] == 4096
		assert body['top_p'] == 0.9
		assert body['seed'] == 7
		assert body['service_tier'] == 'auto'
		if reasoning:
			assert body['reasoning_effort'] == 'low'
			assert 'temperature' not in body
			assert 'frequency_penalty' not in body
		else:
			assert body['temperature'] == 0.2
			assert body['frequency_penalty'] == 0.3
			assert 'reasoning_effort' not in body
		return completion_response(request)

	async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
		llm = ChatOpenAI(model=model, api_key='test-key', top_p=0.9, seed=7, service_tier='auto', http_client=client)
		await llm.ainvoke([UserMessage(content='hello')])


@pytest.mark.parametrize('model', ['minimax/minimax-m3', 'minimax/minimax-m2', 'custom/deployment'])
async def test_vercel_current_and_saved_ids_reach_sdk(model):
	def handle(request):
		body = json.loads(request.content)
		assert request.url.host == 'ai-gateway.vercel.sh'
		assert body['model'] == model
		assert 'reasoning_effort' not in body
		return completion_response(request)

	async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
		llm = ChatVercel(model=model, api_key='test-key', http_client=client)
		await llm.ainvoke([UserMessage(content='hello')])
