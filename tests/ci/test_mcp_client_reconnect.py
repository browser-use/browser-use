"""Regression tests for MCPClient reconnect after disconnect.

`MCPClient._disconnect_event` is created once in `__init__` and set by
`disconnect()`, but was never cleared again. On a subsequent `connect()` the
background task's keep-alive `await self._disconnect_event.wait()` returned
immediately, so the freshly started server process and session were torn down
right after `connect()` reported success — leaving tool calls aimed at a dead
session.
"""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock

from mcp.types import Tool

import browser_use.mcp.client as mcp_client_module
from browser_use.mcp.client import MCPClient


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
					input_schema={'type': 'object', 'properties': {}},
				)
			]
		)


@asynccontextmanager
async def fake_stdio_client(server_params):
	yield object(), object()


def install_fake_transport(monkeypatch):
	monkeypatch.setattr(mcp_client_module, 'ClientSession', FakeClientSession)
	monkeypatch.setattr(mcp_client_module, 'stdio_client', fake_stdio_client)


def _make_client() -> MCPClient:
	client = MCPClient(server_name='test-server', command='test-command')
	client._telemetry = MagicMock()
	return client


async def test_reconnect_after_disconnect_stays_alive(monkeypatch):
	install_fake_transport(monkeypatch)
	client = _make_client()

	await asyncio.wait_for(client.connect(), timeout=5.0)
	assert client._connected
	first_session = cast(FakeClientSession, client.session)
	assert first_session is not None and not first_session.closed

	await client.disconnect()
	assert not client._connected
	assert first_session.closed

	# Reconnect on the same instance: connect() must yield a live session,
	# not one that tears itself down because the old disconnect event is
	# still set.
	await asyncio.wait_for(client.connect(), timeout=5.0)

	# Give a misbehaving background task a moment to tear itself down
	await asyncio.sleep(0.3)

	assert client._connected, 'reconnected client must stay connected'
	reconnected = cast(FakeClientSession, client.session)
	assert reconnected is not None, 'reconnected client must keep its session'
	assert not reconnected.closed, 'reconnected session was torn down right after connect()'


async def test_reconnect_rediscovers_tools(monkeypatch):
	install_fake_transport(monkeypatch)
	client = _make_client()

	await asyncio.wait_for(client.connect(), timeout=5.0)
	await client.disconnect()

	await asyncio.wait_for(client.connect(), timeout=5.0)
	await asyncio.sleep(0.3)

	assert 'echo' in client._tools, 'tools must be rediscovered on reconnect'
