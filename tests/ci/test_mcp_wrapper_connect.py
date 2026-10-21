"""Regression tests for the MCPToolWrapper connection lifecycle.

`MCPToolWrapper.connect()` used to end with `await self._keep_session_alive()`,
which blocks until shutdown. Both context managers (the stdio transport and the
ClientSession) lived in connect()'s own frame, so awaiting connect() — exactly
what `register_mcp_tools()` and its docstring example do — deadlocked
permanently: the MCP server started and the tools were registered, but the
caller never regained control and the agent never ran.

Note on the timing assertions below: `_keep_session_alive` swallowed
CancelledError, so an outer `asyncio.wait_for` timeout did surface a "return"
from connect() — but only after the cancellation had already torn down the
session via the context-manager unwinding. A prompt return with a still-open
session is therefore the discriminating signal for the fix.
"""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast

from mcp.types import Tool

import browser_use.mcp.controller as mcp_controller
from browser_use import Tools
from browser_use.mcp.controller import MCPToolWrapper, register_mcp_tools


class FakeClientSession:
	"""Stand-in for mcp.ClientSession that records its lifecycle."""

	def __init__(self, read, write):
		self.read = read
		self.write = write
		self.initialized = False
		self.closed = False

	async def __aenter__(self):
		return self

	async def __aexit__(self, *exc_info):
		self.closed = True
		return False

	async def initialize(self):
		self.initialized = True

	async def list_tools(self):
		return SimpleNamespace(
			tools=[
				Tool(
					name='echo',
					description='Echo a message',
					input_schema={
						'type': 'object',
						'properties': {'message': {'type': 'string'}},
						'required': ['message'],
					},
				)
			]
		)


@asynccontextmanager
async def fake_stdio_client(server_params):
	yield object(), object()


def install_fake_transport(monkeypatch):
	monkeypatch.setattr(mcp_controller, 'ClientSession', FakeClientSession)
	monkeypatch.setattr(mcp_controller, 'stdio_client', fake_stdio_client)


async def _connect_promptly(wrapper: MCPToolWrapper) -> None:
	"""Await connect() and assert it returns on its own with a live session."""
	loop = asyncio.get_running_loop()
	start = loop.time()
	await asyncio.wait_for(wrapper.connect(), timeout=2.0)
	elapsed = loop.time() - start
	assert elapsed < 1.0, (
		f'connect() blocked for {elapsed:.2f}s — it must return after registering tools, not wait on a keep-alive event'
	)
	live = cast(FakeClientSession, wrapper.session)
	assert live is not None
	assert not live.closed, 'session must stay open after connect() returns (until disconnect())'


async def test_connect_returns_after_registering_tools(monkeypatch):
	install_fake_transport(monkeypatch)
	tools = Tools()
	wrapper = MCPToolWrapper(tools.registry, 'fake-mcp-server')

	await _connect_promptly(wrapper)

	assert cast(FakeClientSession, wrapper.session).initialized
	assert 'echo' in wrapper._tools
	assert 'echo' in wrapper._registered_actions


async def test_disconnect_closes_transport_and_session(monkeypatch):
	install_fake_transport(monkeypatch)
	tools = Tools()
	wrapper = MCPToolWrapper(tools.registry, 'fake-mcp-server')
	await _connect_promptly(wrapper)
	session = cast(FakeClientSession, wrapper.session)
	assert session is not None

	await wrapper.disconnect()

	assert wrapper.session is None
	assert session.closed, 'disconnect() must close the ClientSession'


async def test_connect_failure_releases_transport(monkeypatch):
	"""A server that fails during initialize() must not leave a half-open stack."""

	class FailingSession(FakeClientSession):
		async def initialize(self):
			raise RuntimeError('server refused connection')

	monkeypatch.setattr(mcp_controller, 'ClientSession', FailingSession)
	monkeypatch.setattr(mcp_controller, 'stdio_client', fake_stdio_client)
	tools = Tools()
	wrapper = MCPToolWrapper(tools.registry, 'fake-mcp-server')

	try:
		await asyncio.wait_for(wrapper.connect(), timeout=2.0)
		raise AssertionError('expected connect() to propagate the initialization failure')
	except RuntimeError as e:
		assert 'server refused connection' in str(e)

	assert wrapper.session is None, 'a failed connect() must not leave a dangling session reference'


async def test_register_mcp_tools_returns_connected_wrapper(monkeypatch):
	install_fake_transport(monkeypatch)
	tools = Tools()

	wrapper = await asyncio.wait_for(register_mcp_tools(tools.registry, 'fake-mcp-server'), timeout=2.0)

	assert 'echo' in wrapper._tools
	await _connect_promptly(wrapper)  # second connect is a no-op
