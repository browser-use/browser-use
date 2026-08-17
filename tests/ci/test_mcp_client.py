import asyncio
from unittest.mock import MagicMock

import pytest

from browser_use.mcp.client import MCPClient


@pytest.mark.asyncio
async def test_mcp_client_reconnects_after_disconnect() -> None:
	client = MCPClient(server_name='test-server', command='test-command')
	client._telemetry = MagicMock()

	async def fake_run_stdio_client(server_params) -> None:
		try:
			client.session = MagicMock()
			client._connected = True
			await client._disconnect_event.wait()
		finally:
			client._connected = False
			client.session = None

	client._run_stdio_client = fake_run_stdio_client

	await client.connect()
	await client.disconnect()
	assert client._disconnect_event.is_set()

	await asyncio.wait_for(client.connect(), timeout=1)
	assert client._connected
	assert not client._disconnect_event.is_set()

	await client.disconnect()
