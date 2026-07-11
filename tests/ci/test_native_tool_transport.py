import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from browser_use.llm.anthropic.chat import ChatAnthropic
from browser_use.llm.azure.chat import ChatAzureOpenAI
from browser_use.llm.base import ToolDefinition
from browser_use.llm.browser_use.chat import ChatBrowserUse
from browser_use.llm.google.chat import ChatGoogle
from browser_use.llm.messages import UserMessage
from browser_use.llm.openai.chat import ChatOpenAI
from browser_use.llm.views import ChatInvokeCompletion

HOSTILE_CODE = '''import json
rows = await js("""
Array.from(document.querySelectorAll('a')).map(a => ({
  text: a.innerText,
  href: a.href,
  quote: `say "hello" and don't break`,
  regex: /\\w+\\/path/g.source
}))
""")
open("nested/\u2603.json", "w").write(json.dumps(rows, ensure_ascii=False))
print("```json\\n</tool_call>\\n", len(rows))
'''

HOSTILE_JAVASCRIPT = """() => {
  const pattern = /\\w+\\/path/g;
  return [...document.querySelectorAll('a')].map(a => ({
    text: a.innerText,
    href: a.href,
    quote: `say "hello" and don't break`,
    pattern: pattern.source
  }));
}"""


def _tool() -> ToolDefinition:
	return ToolDefinition(
		name='browser_use_step',
		description='Return one action.',
		parameters={
			'type': 'object',
			'properties': {'code': {'type': 'string'}},
			'required': ['code'],
			'additionalProperties': False,
		},
	)


@pytest.mark.asyncio
async def test_openai_native_tool_preserves_nested_code(httpserver):
	arguments = json.dumps({'code': HOSTILE_CODE}, ensure_ascii=False)
	httpserver.expect_request('/v1/chat/completions', method='POST').respond_with_json(
		{
			'id': 'chatcmpl-tools',
			'object': 'chat.completion',
			'created': 0,
			'model': 'gpt-test',
			'choices': [
				{
					'index': 0,
					'message': {
						'role': 'assistant',
						'content': None,
						'tool_calls': [
							{
								'id': 'call_1',
								'type': 'function',
								'function': {'name': 'browser_use_step', 'arguments': arguments},
							}
						],
					},
					'finish_reason': 'tool_calls',
				}
			],
			'usage': {'prompt_tokens': 10, 'completion_tokens': 20, 'total_tokens': 30},
		}
	)
	llm = ChatOpenAI(model='gpt-test', api_key='test', base_url=httpserver.url_for('/v1'))

	response = await llm.ainvoke([UserMessage(content='act')], tools=[_tool()], tool_choice='required')

	assert json.loads(response.tool_calls[0].function.arguments)['code'] == HOSTILE_CODE
	request = httpserver.log[0][0].json
	assert request['tool_choice'] == 'required'
	assert request['parallel_tool_calls'] is False
	assert request['tools'][0]['function']['parameters']['properties']['code']['type'] == 'string'


@pytest.mark.asyncio
async def test_openai_reasoning_tools_use_responses_api():
	arguments = json.dumps({'code': HOSTILE_CODE}, ensure_ascii=False)
	response = SimpleNamespace(
		id='resp_1',
		output=[SimpleNamespace(type='function_call', call_id='call_1', name='browser_use_step', arguments=arguments)],
		output_text='',
		usage=None,
		error=None,
		incomplete_details=None,
		status='completed',
	)
	client = MagicMock()
	client.responses.create = AsyncMock(return_value=response)
	llm = ChatOpenAI(model='gpt-5.5', api_key='test')
	llm.get_client = lambda: client  # type: ignore[method-assign]

	result = await llm.ainvoke([UserMessage(content='act')], tools=[_tool()], tool_choice='required')

	assert json.loads(result.tool_calls[0].function.arguments)['code'] == HOSTILE_CODE
	request_call = client.responses.create.await_args
	assert request_call is not None
	request = request_call.kwargs
	assert request['tool_choice'] == 'required'
	assert request['reasoning'] == {'effort': 'low'}
	assert request['parallel_tool_calls'] is False
	assert 'temperature' not in request


@pytest.mark.asyncio
async def test_azure_reasoning_tools_route_to_responses_api():
	llm = ChatAzureOpenAI(model='gpt-5.5', api_key='test', azure_endpoint='https://example.openai.azure.com')
	expected = ChatInvokeCompletion(completion='', usage=None)
	llm._ainvoke_responses_api = AsyncMock(return_value=expected)  # type: ignore[method-assign]

	result = await llm.ainvoke([UserMessage(content='act')], tools=[_tool()], tool_choice='required')

	assert result is expected
	assert llm._ainvoke_responses_api.await_count == 1


@pytest.mark.asyncio
async def test_anthropic_thinking_uses_auto_but_keeps_native_tool_channel():
	llm = ChatAnthropic(model='claude-test', api_key='test', thinking={'type': 'enabled', 'budget_tokens': 1024})
	captured: dict = {}

	async def create_message(**kwargs):
		captured.update(kwargs)
		return SimpleNamespace(
			content=[
				SimpleNamespace(
					type='tool_use',
					id='toolu_1',
					name='browser_use_step',
					input={'code': HOSTILE_CODE},
				)
			],
			usage=SimpleNamespace(
				input_tokens=10,
				output_tokens=20,
				cache_read_input_tokens=0,
				cache_creation_input_tokens=0,
				cache_creation=None,
			),
			stop_reason='tool_use',
			stop_details=None,
		)

	llm._create_message = create_message  # type: ignore[method-assign]
	response = await llm.ainvoke([UserMessage(content='act')], tools=[_tool()], tool_choice='required')

	assert captured['tool_choice'] == {'type': 'auto'}
	assert captured['tools'][0]['cache_control'] == {'type': 'ephemeral'}
	assert json.loads(response.tool_calls[0].function.arguments)['code'] == HOSTILE_CODE


@pytest.mark.asyncio
async def test_gemini_native_tool_preserves_code_and_thought_signature():
	function_call = SimpleNamespace(id='call_1', name='browser_use_step', args={'code': HOSTILE_JAVASCRIPT})
	part = SimpleNamespace(function_call=function_call, text=None, thought=False, thought_signature=b'signature')
	response = SimpleNamespace(
		text=None,
		candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]), finish_reason='STOP')],
		usage_metadata=SimpleNamespace(
			prompt_token_count=10,
			candidates_token_count=20,
			thoughts_token_count=5,
			total_token_count=35,
			cached_content_token_count=4,
			prompt_tokens_details=None,
		),
	)
	client = MagicMock()
	client.aio.models.generate_content = AsyncMock(return_value=response)
	llm = ChatGoogle(model='gemini-2.5-flash', api_key='test')
	llm._client = client

	result = await llm.ainvoke([UserMessage(content='act')], tools=[_tool()], tool_choice='required')

	assert json.loads(result.tool_calls[0].function.arguments)['code'] == HOSTILE_JAVASCRIPT
	assert result.tool_calls[0].thought_signature == b'signature'
	request_call = client.aio.models.generate_content.await_args
	assert request_call is not None
	config = request_call.kwargs['config']
	assert str(config['tool_config']['function_calling_config']['mode']).endswith('ANY')


@pytest.mark.asyncio
async def test_gemini_3_5_flash_defaults_to_medium_thinking_level():
	function_call = SimpleNamespace(id='call_1', name='browser_use_step', args={'code': HOSTILE_CODE})
	part = SimpleNamespace(function_call=function_call, text=None, thought=False, thought_signature=None)
	response = SimpleNamespace(
		text=None,
		candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]), finish_reason='STOP')],
		usage_metadata=SimpleNamespace(
			prompt_token_count=10,
			candidates_token_count=20,
			thoughts_token_count=5,
			total_token_count=35,
			cached_content_token_count=0,
			prompt_tokens_details=None,
		),
	)
	client = MagicMock()
	client.aio.models.generate_content = AsyncMock(return_value=response)
	llm = ChatGoogle(model='gemini-3.5-flash', api_key='test')
	llm._client = client

	await llm.ainvoke([UserMessage(content='act')], tools=[_tool()], tool_choice='required')

	request_call = client.aio.models.generate_content.await_args
	assert request_call is not None
	config = request_call.kwargs['config']
	assert str(config['thinking_config']['thinking_level']).endswith('MEDIUM')
	assert 'thinking_budget' not in config['thinking_config']


@pytest.mark.asyncio
async def test_chat_browser_use_uses_openai_compatible_gateway_for_tools(monkeypatch):
	monkeypatch.setenv('BROWSER_USE_API_KEY', 'test')
	captured: dict = {}
	arguments = json.dumps({'code': HOSTILE_CODE}, ensure_ascii=False)

	async def post(*args, **kwargs):
		captured.update(kwargs)
		response = MagicMock()
		response.raise_for_status = MagicMock()
		response.json.return_value = {
			'id': 'gateway_1',
			'choices': [
				{
					'message': {
						'content': '',
						'tool_calls': [
							{
								'id': 'call_1',
								'function': {'name': 'browser_use_step', 'arguments': arguments},
							}
						],
					},
					'finish_reason': 'tool_calls',
				}
			],
			'usage': {'prompt_tokens': 10, 'completion_tokens': 20, 'total_tokens': 30},
		}
		return response

	with patch('httpx.AsyncClient') as client_class:
		client = AsyncMock()
		client.post = post
		client.__aenter__ = AsyncMock(return_value=client)
		client.__aexit__ = AsyncMock(return_value=None)
		client_class.return_value = client
		llm = ChatBrowserUse(model='bu-2-0')
		result = await llm.ainvoke([UserMessage(content='act')], tools=[_tool()], tool_choice='required')

	assert captured['headers']['x-browser-use-request-type'] == 'rust_agent'
	assert captured['json']['tool_choice'] == 'required'
	assert json.loads(result.tool_calls[0].function.arguments)['code'] == HOSTILE_CODE
