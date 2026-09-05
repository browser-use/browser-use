"""Exercise MCP clients against real local HTTP and stdio servers."""

import asyncio
import os
import socket
import sys
import threading
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import pytest
import uvicorn
from mcp.server.mcpserver import MCPServer
from starlette.datastructures import Headers
from starlette.responses import Response
from starlette.types import Receive, Scope, Send

from browser_use import Tools
from browser_use.mcp.client import MCPClient


@dataclass
class LocalMCPServer:
	url: str
	request_auth: list[str | None] = field(default_factory=list)
	calls: list[int] = field(default_factory=list)
	allow_requests: threading.Event = field(default_factory=threading.Event)
	request_started: threading.Event = field(default_factory=threading.Event)


@pytest.fixture(params=[True, False], ids=['json', 'sse'])
async def local_mcp_server(request: pytest.FixtureRequest) -> AsyncIterator[LocalMCPServer]:
	mcp = MCPServer('local-http')
	state = LocalMCPServer(url='')
	state.allow_requests.set()

	@mcp.tool()
	def double(value: int) -> int:
		"""Double a number."""
		state.calls.append(value)
		return value * 2

	app = mcp.streamable_http_app(json_response=request.param)

	async def authenticated_app(scope: Scope, receive: Receive, send: Send) -> None:
		if scope['type'] == 'http':
			authorization = Headers(scope=scope).get('authorization')
			state.request_auth.append(authorization)
			state.request_started.set()
			await asyncio.to_thread(state.allow_requests.wait)
			if authorization != 'Bearer local-test-token':
				await Response(status_code=401)(scope, receive, send)
				return
		await app(scope, receive, send)

	original_no_proxy = os.environ.get('NO_PROXY')
	os.environ['NO_PROXY'] = '127.0.0.1,localhost'
	with socket.socket() as listener:
		listener.bind(('127.0.0.1', 0))
		listener.listen()
		state.url = f'http://127.0.0.1:{listener.getsockname()[1]}/mcp'
		server = uvicorn.Server(uvicorn.Config(authenticated_app, log_level='error', lifespan='on'))
		serving = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
		serving.start()
		try:
			async with asyncio.timeout(10):
				while not server.started:
					if not serving.is_alive():
						raise RuntimeError('Local MCP server exited before startup')
					await asyncio.sleep(0.01)
			yield state
		finally:
			state.allow_requests.set()
			server.should_exit = True
			try:
				await asyncio.to_thread(serving.join, 10)
				assert not serving.is_alive()
			finally:
				if original_no_proxy is None:
					os.environ.pop('NO_PROXY', None)
				else:
					os.environ['NO_PROXY'] = original_no_proxy


async def test_http_tools_register_call_and_disconnect(
	local_mcp_server: LocalMCPServer, caplog: pytest.LogCaptureFixture
) -> None:
	client = MCPClient(
		server_name='remote-tools',
		url=local_mcp_server.url,
		headers={'Authorization': 'Bearer local-test-token'},
	)
	tools = Tools()
	try:
		await client.register_to_tools(tools, prefix='remote_')
		assert client.session is not None
		result = await tools.registry.execute_action('remote_double', {'value': 7})
		assert result.error is None
		assert result.extracted_content == '14'
		assert local_mcp_server.calls == [7]
	finally:
		await client.disconnect()

	assert client.session is None
	assert not client._connected
	assert client._connection_task is not None and client._connection_task.done()
	assert local_mcp_server.request_auth
	assert set(local_mcp_server.request_auth) == {'Bearer local-test-token'}
	assert 'local-test-token' not in caplog.text


@pytest.mark.parametrize(
	'options',
	[
		{},
		{'command': 'python', 'url': 'http://127.0.0.1/mcp'},
		{'url': 'http://127.0.0.1/mcp', 'args': ['server.py']},
		{'url': 'http://127.0.0.1/mcp', 'env': {'TEST': 'value'}},
		{'command': 'python', 'headers': {'Authorization': 'test'}},
		{'url': 'file:///tmp/mcp'},
		{'url': 'http:///mcp'},
	],
)
def test_invalid_transport_configuration(options: dict[str, Any]) -> None:
	with pytest.raises(ValueError):
		MCPClient(server_name='invalid', **options)


async def test_stdio_client_still_registers_and_calls_tools() -> None:
	server_code = """
from mcp.server.mcpserver import MCPServer
server = MCPServer('local-stdio')
@server.tool()
def greet(name: str) -> str:
	return f'Hello {name}'
server.run()
"""
	client = MCPClient('stdio-tools', sys.executable, ['-c', server_code])
	tools = Tools()
	try:
		await client.register_to_tools(tools)
		result = await tools.registry.execute_action('greet', {'name': 'Ada'})
		assert result.error is None
		assert result.extracted_content == 'Hello Ada'
	finally:
		await client.disconnect()
	assert client.session is None


@pytest.mark.parametrize('failure_mode', ['unauthorized', 'timeout'])
async def test_http_transport_failure_exits_session(local_mcp_server: LocalMCPServer, failure_mode: str) -> None:
	if failure_mode == 'timeout':
		local_mcp_server.allow_requests.clear()
	client = MCPClient(server_name='connection-failure', url=local_mcp_server.url)
	try:
		with pytest.raises(RuntimeError, match='Failed to connect'):
			await client.connect()
	finally:
		local_mcp_server.allow_requests.set()
	assert client._connection_task is not None and client._connection_task.done()
	assert local_mcp_server.request_auth
	assert client.session is None
	assert not client._connected


async def test_http_transport_cancellation_exits_session(local_mcp_server: LocalMCPServer) -> None:
	client = MCPClient(
		server_name='cancelled',
		url=local_mcp_server.url,
		headers={'Authorization': 'Bearer local-test-token'},
	)
	await client.connect()
	connection_task = client._connection_task
	assert connection_task is not None
	connection_task.cancel()
	with pytest.raises(asyncio.CancelledError):
		await connection_task
	assert client.session is None
	assert not client._connected


async def test_cancel_connect_drains_http_initialization(local_mcp_server: LocalMCPServer) -> None:
	local_mcp_server.allow_requests.clear()
	client = MCPClient(
		server_name='cancel-initialization',
		url=local_mcp_server.url,
		headers={'Authorization': 'Bearer local-test-token'},
	)
	connecting = asyncio.create_task(client.connect())
	try:
		assert await asyncio.to_thread(local_mcp_server.request_started.wait, 5)
		connecting.cancel()
		with pytest.raises(asyncio.CancelledError):
			await connecting
		assert client._connection_task is not None and client._connection_task.done()
		assert client.session is None
		assert not client._connected
	finally:
		local_mcp_server.allow_requests.set()
		if client._connection_task is not None and not client._connection_task.done():
			client._connection_task.cancel()
			await asyncio.gather(client._connection_task, return_exceptions=True)
