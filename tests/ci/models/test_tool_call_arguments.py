"""Tool call arguments must stay JSON strings in OpenAI-compatible requests."""

import json

import httpx
import pytest

from browser_use.llm.cerebras.chat import ChatCerebras
from browser_use.llm.deepseek.chat import ChatDeepSeek
from browser_use.llm.messages import AssistantMessage, Function, ToolCall


@pytest.mark.parametrize('chat_class', [ChatDeepSeek, ChatCerebras])
@pytest.mark.parametrize('arguments', ['{}', '{\n  "city": "北京", "options": {"units": ["celsius"]}\n}', '{"city":'])
async def test_tool_call_arguments_remain_strings_in_http_request(
	chat_class: type[ChatDeepSeek] | type[ChatCerebras], arguments: str
):
	"""Preserve the original argument text through serialization and the real SDK."""
	requests: list[httpx.Request] = []

	def handle_request(request: httpx.Request) -> httpx.Response:
		requests.append(request)
		return httpx.Response(
			200,
			json={
				'id': 'chatcmpl-test',
				'object': 'chat.completion',
				'created': 0,
				'model': 'test-model',
				'choices': [{'index': 0, 'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': 'ok'}}],
			},
		)

	message = AssistantMessage(
		content=None,
		tool_calls=[ToolCall(id='call-test', function=Function(name='lookup_weather', arguments=arguments))],
	)
	async with httpx.AsyncClient(transport=httpx.MockTransport(handle_request)) as client:
		llm = chat_class(api_key='test-key', client_params={'http_client': client})
		result = await llm.ainvoke([message])

	assert result.completion == 'ok'
	assert len(requests) == 1
	body = json.loads(requests[0].content)
	assert body['messages'][0]['tool_calls'] == [
		{
			'id': 'call-test',
			'type': 'function',
			'function': {'name': 'lookup_weather', 'arguments': arguments},
		}
	]
