"""Tests for OpenAI HTTP Responses and the full-context WebSocket transport."""

import asyncio
from typing import Any

import pytest
from aiohttp import WSMsgType, web
from openai.types.responses import Response
from pydantic import BaseModel

from browser_use.llm.exceptions import ModelOutputTruncatedError, ModelProviderError, ModelRateLimitError
from browser_use.llm.messages import SystemMessage, UserMessage
from browser_use.llm.openai.chat import ChatOpenAI


def _response(response_id: str, text: str, *, status: str = 'completed') -> dict[str, Any]:
	response: dict[str, Any] = {
		'id': response_id,
		'created_at': 1.0,
		'model': 'gpt-5.6',
		'object': 'response',
		'parallel_tool_calls': True,
		'tool_choice': 'auto',
		'tools': [],
		'status': status,
		'output': [],
		'usage': {
			'input_tokens': 10,
			'input_tokens_details': {'cached_tokens': 2},
			'output_tokens': 3,
			'output_tokens_details': {'reasoning_tokens': 0},
			'total_tokens': 13,
		},
	}
	if status == 'completed':
		response['output'] = [
			{
				'id': f'msg_{response_id}',
				'type': 'message',
				'status': 'completed',
				'role': 'assistant',
				'content': [{'type': 'output_text', 'text': text, 'annotations': [], 'logprobs': []}],
			}
		]
	elif status == 'failed':
		response['error'] = {'code': 'server_error', 'message': 'request failed'}
	elif status == 'incomplete':
		response['incomplete_details'] = {'reason': 'max_output_tokens'}
	return response


def _event(response_id: str, text: str = 'ok', *, status: str = 'completed') -> dict[str, Any]:
	return {
		'type': f'response.{status}',
		'sequence_number': 1,
		'response': _response(response_id, text, status=status),
	}


@pytest.fixture
async def responses_websocket_server():
	state: dict[str, Any] = {
		'connections': 0,
		'requests': [],
		'headers': [],
		'queries': [],
		'response_texts': ['first', 'second', 'third'],
		'malformed_once': False,
		'hang_once': False,
		'rate_limit_once': False,
		'connection_limit_once': False,
		'nested_error_once': False,
		'failed_once': False,
		'incomplete_once': False,
		'handshake_status_once': None,
	}

	async def websocket_handler(request: web.Request) -> web.StreamResponse:
		state['connections'] += 1
		state['headers'].append(dict(request.headers))
		state['queries'].append(dict(request.query))
		if state['handshake_status_once'] is not None:
			status = state['handshake_status_once']
			state['handshake_status_once'] = None
			return web.Response(status=status, text='handshake rejected')
		websocket = web.WebSocketResponse()
		await websocket.prepare(request)
		async for message in websocket:
			if message.type != WSMsgType.TEXT:
				continue
			payload = message.json()
			state['requests'].append(payload)
			if state['malformed_once']:
				state['malformed_once'] = False
				await websocket.send_str('{not-json')
				continue
			if state['hang_once']:
				state['hang_once'] = False
				await asyncio.sleep(1)
				continue
			if state['rate_limit_once']:
				state['rate_limit_once'] = False
				await websocket.send_json(
					{
						'type': 'error',
						'code': 'rate_limit_exceeded',
						'message': 'slow down',
						'param': None,
						'sequence_number': 1,
					}
				)
				continue
			if state['connection_limit_once']:
				state['connection_limit_once'] = False
				await websocket.send_json(
					{
						'type': 'error',
						'code': 'websocket_connection_limit_reached',
						'message': 'connection reached its lifetime limit',
						'param': None,
						'sequence_number': 1,
					}
				)
				continue
			if state['nested_error_once']:
				state['nested_error_once'] = False
				await websocket.send_json(
					{
						'type': 'error',
						'status': 400,
						'error': {'message': 'nested gateway error', 'type': 'invalid_request_error', 'code': 'bad'},
					}
				)
				continue
			if state['failed_once']:
				state['failed_once'] = False
				await websocket.send_json(_event(f'resp_{len(state["requests"])}', status='failed'))
				continue
			if state['incomplete_once']:
				state['incomplete_once'] = False
				await websocket.send_json(_event(f'resp_{len(state["requests"])}', status='incomplete'))
				continue
			index = len(state['requests'])
			texts = state['response_texts']
			await websocket.send_json(_event(f'resp_{index}', texts[min(index - 1, len(texts) - 1)]))
		return websocket

	app = web.Application()
	app.router.add_get('/v1/responses', websocket_handler)
	runner = web.AppRunner(app)
	await runner.setup()
	site = web.TCPSite(runner, '127.0.0.1', 0)
	await site.start()
	server = site._server
	assert server is not None
	port = getattr(server, 'sockets')[0].getsockname()[1]
	try:
		yield state, f'http://127.0.0.1:{port}/v1'
	finally:
		await runner.cleanup()


async def test_reuses_connection_and_resends_full_context(responses_websocket_server):
	state, websocket_base_url = responses_websocket_server
	llm = ChatOpenAI(
		model='gpt-5.6',
		api_key='test-key',
		transport='responses_websocket',
		websocket_base_url=websocket_base_url,
		default_headers={'X-Test': 'yes'},
		default_query={'region': 'test'},
		max_completion_tokens=123,
	)
	messages = [SystemMessage(content='system'), UserMessage(content='full state')]
	try:
		first = await llm.ainvoke(messages, session_id='agent-1')
		second = await llm.ainvoke(messages, session_id='agent-1')
	finally:
		await llm.aclose()

	assert first.completion == 'first'
	assert first.usage is not None and first.usage.prompt_cached_tokens == 2
	assert second.completion == 'second'
	assert state['connections'] == 1
	assert state['headers'][0]['Authorization'] == 'Bearer test-key'
	assert state['headers'][0]['X-Test'] == 'yes'
	assert state['queries'][0] == {'region': 'test'}
	assert len(state['requests']) == 2
	assert all(request['type'] == 'response.create' for request in state['requests'])
	assert all(request['store'] is True for request in state['requests'])
	assert all('previous_response_id' not in request for request in state['requests'])
	assert state['requests'][1]['input'][1]['content'] == 'full state'
	assert state['requests'][1]['max_output_tokens'] == 123
	assert state['requests'][1]['reasoning'] == {'effort': 'low'}


async def test_store_false_reaches_websocket_request(responses_websocket_server):
	state, websocket_base_url = responses_websocket_server
	llm = ChatOpenAI(
		model='gpt-5.6', transport='responses_websocket', websocket_base_url=websocket_base_url,
		responses_store=False, default_headers={'Authorization': 'Bearer gateway-key'},
	)
	try:
		await llm.ainvoke([UserMessage(content='hello')], session_id='agent-1')
	finally:
		await llm.aclose()
	assert state['requests'][0]['store'] is False
	assert state['headers'][0]['Authorization'] == 'Bearer gateway-key'


async def test_malformed_frame_closes_socket_before_next_request(responses_websocket_server):
	state, websocket_base_url = responses_websocket_server
	llm = ChatOpenAI(
		model='gpt-5.6', api_key='test-key', transport='responses_websocket', websocket_base_url=websocket_base_url
	)
	try:
		state['malformed_once'] = True
		with pytest.raises(ModelProviderError, match='Invalid JSON frame'):
			await llm.ainvoke([UserMessage(content='first')], session_id='agent-1')
		result = await llm.ainvoke([UserMessage(content='second')], session_id='agent-1')
	finally:
		await llm.aclose()
	assert result.completion == 'second'
	assert state['connections'] == 2


async def test_timeout_reconnects_and_retries_full_context(responses_websocket_server):
	state, websocket_base_url = responses_websocket_server
	state['hang_once'] = True
	llm = ChatOpenAI(
		model='gpt-5.6', api_key='test-key', transport='responses_websocket',
		websocket_base_url=websocket_base_url, timeout=0.05,
	)
	try:
		result = await llm.ainvoke([UserMessage(content='full')], session_id='agent-1')
	finally:
		await llm.aclose()
	assert result.completion == 'second'
	assert state['connections'] == 2
	assert all('previous_response_id' not in request for request in state['requests'])


async def test_connection_lifetime_error_reconnects_and_retries(responses_websocket_server):
	state, websocket_base_url = responses_websocket_server
	state['connection_limit_once'] = True
	llm = ChatOpenAI(
		model='gpt-5.6', api_key='test-key', transport='responses_websocket', websocket_base_url=websocket_base_url
	)
	try:
		result = await llm.ainvoke([UserMessage(content='full')], session_id='agent-1')
	finally:
		await llm.aclose()
	assert result.completion == 'second'
	assert state['connections'] == 2
	assert len(state['requests']) == 2
	assert all('previous_response_id' not in request for request in state['requests'])


async def test_handshake_rate_limit_preserves_rate_limit_error(responses_websocket_server):
	state, websocket_base_url = responses_websocket_server
	state['handshake_status_once'] = 429
	llm = ChatOpenAI(
		model='gpt-5.6', api_key='test-key', transport='responses_websocket', websocket_base_url=websocket_base_url
	)
	try:
		with pytest.raises(ModelRateLimitError):
			await llm.ainvoke([UserMessage(content='full')], session_id='agent-1')
	finally:
		await llm.aclose()
	assert state['connections'] == 1


async def test_sessions_and_invocation_scopes_are_isolated(responses_websocket_server):
	state, websocket_base_url = responses_websocket_server
	llm = ChatOpenAI(
		model='gpt-5.6', api_key='test-key', transport='responses_websocket', websocket_base_url=websocket_base_url
	)
	messages = [UserMessage(content='hello')]
	try:
		await llm.ainvoke(messages, session_id='shared', invocation_scope='agent')
		await llm.ainvoke(messages, session_id='shared', invocation_scope='judge')
		await llm.ainvoke(messages, session_id='other', invocation_scope='agent')
		await llm.close_session('shared')
		await llm.ainvoke(messages, session_id='other', invocation_scope='agent')
	finally:
		await llm.aclose()
	assert state['connections'] == 3


async def test_error_and_terminal_failures_map_to_model_errors(responses_websocket_server):
	state, websocket_base_url = responses_websocket_server
	llm = ChatOpenAI(
		model='gpt-5.6', api_key='test-key', transport='responses_websocket', websocket_base_url=websocket_base_url
	)
	try:
		state['rate_limit_once'] = True
		with pytest.raises(ModelRateLimitError, match='slow down'):
			await llm.ainvoke([UserMessage(content='rate')], session_id='rate')
		state['nested_error_once'] = True
		with pytest.raises(ModelProviderError, match='nested gateway error'):
			await llm.ainvoke([UserMessage(content='nested')], session_id='nested')
		state['failed_once'] = True
		with pytest.raises(ModelProviderError, match='request failed'):
			await llm.ainvoke([UserMessage(content='failed')], session_id='failed')
		state['incomplete_once'] = True
		with pytest.raises(ModelOutputTruncatedError):
			await llm.ainvoke([UserMessage(content='incomplete')], session_id='incomplete')
	finally:
		await llm.aclose()


class StructuredResult(BaseModel):
	answer: str


async def test_structured_output_uses_responses_schema(responses_websocket_server):
	state, websocket_base_url = responses_websocket_server
	state['response_texts'] = ['{"answer":"ok"}']
	llm = ChatOpenAI(
		model='gpt-5.6', api_key='test-key', transport='responses_websocket', websocket_base_url=websocket_base_url
	)
	try:
		result = await llm.ainvoke(
			[UserMessage(content='return json')], output_format=StructuredResult, session_id='agent-1'
		)
	finally:
		await llm.aclose()
	assert result.completion == StructuredResult(answer='ok')
	assert state['requests'][0]['text']['format']['type'] == 'json_schema'
	assert state['requests'][0]['text']['format']['strict'] is True


def test_default_transport_remains_chat_completions():
	assert ChatOpenAI(model='gpt-4.1-mini').transport == 'chat_completions'


def test_websocket_transport_resolves_openai_environment(monkeypatch):
	monkeypatch.setenv('OPENAI_API_KEY', 'env-key')
	monkeypatch.setenv('OPENAI_BASE_URL', 'https://gateway.example.test/v1')
	monkeypatch.setenv('OPENAI_ORG_ID', 'org-test')
	monkeypatch.setenv('OPENAI_PROJECT_ID', 'project-test')
	transport = ChatOpenAI(model='gpt-5.6', transport='responses_websocket')._get_responses_websocket_transport()
	assert transport.url == 'wss://gateway.example.test/v1/responses'
	assert transport.api_key == 'env-key'
	assert transport.organization == 'org-test'
	assert transport.project == 'project-test'
	assert transport.timeout == 600.0


async def test_http_responses_transport_uses_shared_request_parser(monkeypatch):
	captured_request: dict[str, Any] = {}

	class FakeResponses:
		async def create(self, **kwargs):
			captured_request.update(kwargs)
			return Response.model_validate(_response('resp_http', 'http result'))

	class FakeClient:
		responses = FakeResponses()

	llm = ChatOpenAI(model='gpt-5.6', api_key='test-key', transport='responses')
	monkeypatch.setattr(llm, 'get_client', lambda: FakeClient())
	result = await llm.ainvoke([UserMessage(content='hello')])
	assert result.completion == 'http result'
	assert captured_request['model'] == 'gpt-5.6'
	assert captured_request['store'] is True
	assert captured_request['input'][0]['content'] == 'hello'
	assert captured_request['reasoning'] == {'effort': 'low'}
