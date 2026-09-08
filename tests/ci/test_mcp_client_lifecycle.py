import asyncio
from typing import Any

import pytest

from browser_use.mcp import client as client_module
from browser_use.mcp.client import MCPClient


@pytest.fixture
def mcp_client() -> MCPClient:
	return MCPClient(server_name='test-server', command='test-command')


async def test_connection_timeout_cancels_stdio_task(
	mcp_client: MCPClient,
	monkeypatch: pytest.MonkeyPatch,
) -> None:
	task_finished = asyncio.Event()

	async def stalled_stdio_client(_server_params: Any) -> None:
		try:
			await asyncio.Event().wait()
		finally:
			task_finished.set()

	monkeypatch.setattr(client_module, 'MCP_CONNECT_TIMEOUT_SECONDS', 0.01)
	monkeypatch.setattr(mcp_client, '_run_stdio_client', stalled_stdio_client)

	with pytest.raises(RuntimeError, match='Failed to connect'):
		await mcp_client.connect()

	assert task_finished.is_set()
	assert mcp_client._stdio_task is None
	assert mcp_client._connected is False


async def test_disconnect_cancels_connection_in_progress(
	mcp_client: MCPClient,
	monkeypatch: pytest.MonkeyPatch,
) -> None:
	task_started = asyncio.Event()
	task_finished = asyncio.Event()

	async def stalled_stdio_client(_server_params: Any) -> None:
		task_started.set()
		try:
			await asyncio.Event().wait()
		finally:
			task_finished.set()

	monkeypatch.setattr(mcp_client, '_run_stdio_client', stalled_stdio_client)

	connect_task = asyncio.create_task(mcp_client.connect())
	await task_started.wait()
	await mcp_client.disconnect()

	with pytest.raises(RuntimeError, match='Failed to connect'):
		await connect_task

	assert task_finished.is_set()
	assert mcp_client._stdio_task is None
	assert mcp_client._connected is False


async def test_cancelling_connect_cleans_up_stdio_task(
	mcp_client: MCPClient,
	monkeypatch: pytest.MonkeyPatch,
) -> None:
	task_started = asyncio.Event()
	task_finished = asyncio.Event()

	async def stalled_stdio_client(_server_params: Any) -> None:
		task_started.set()
		try:
			await asyncio.Event().wait()
		finally:
			task_finished.set()

	monkeypatch.setattr(mcp_client, '_run_stdio_client', stalled_stdio_client)

	connect_task = asyncio.create_task(mcp_client.connect())
	await task_started.wait()
	connect_task.cancel()

	with pytest.raises(asyncio.CancelledError):
		await connect_task

	assert task_finished.is_set()
	assert mcp_client._stdio_task is None
	assert mcp_client._connected is False


async def test_client_can_reconnect_after_disconnect(
	mcp_client: MCPClient,
	monkeypatch: pytest.MonkeyPatch,
) -> None:
	connection_attempts = 0

	async def connected_stdio_client(_server_params: Any) -> None:
		nonlocal connection_attempts
		connection_attempts += 1
		mcp_client._connected = True
		mcp_client._connection_ready_event.set()
		try:
			await mcp_client._disconnect_event.wait()
		finally:
			mcp_client._connected = False
			mcp_client._connection_ready_event.set()

	monkeypatch.setattr(mcp_client, '_run_stdio_client', connected_stdio_client)

	await asyncio.gather(mcp_client.connect(), mcp_client.connect())
	assert connection_attempts == 1
	assert mcp_client._connected is True

	await mcp_client.disconnect()
	assert mcp_client._stdio_task is None

	await mcp_client.connect()
	assert connection_attempts == 2
	assert mcp_client._connected is True
	assert mcp_client._disconnect_event.is_set() is False
	assert mcp_client._stdio_task is not None
	assert mcp_client._stdio_task.done() is False

	await mcp_client.disconnect()
