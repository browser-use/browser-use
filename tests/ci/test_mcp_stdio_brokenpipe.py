"""Regression tests for clean MCP stdio shutdown after a client disconnect."""

from unittest.mock import AsyncMock

import mcp.server.stdio
import pytest

from browser_use.mcp.cli_mcp import CLIMCPServer
from browser_use.mcp.server import BrowserUseServer


class BrokenPipeStdioContext:
	async def __aenter__(self):
		return object(), object()

	async def __aexit__(self, exc_type, exc_value, traceback):
		return False


@pytest.mark.asyncio
async def test_browser_use_server_handles_broken_pipe(monkeypatch):
	"""The full MCP server should exit cleanly when its stdio client disconnects."""
	server = BrowserUseServer()
	server._start_cleanup_task = AsyncMock()
	server.server.run = AsyncMock(side_effect=BrokenPipeError())
	monkeypatch.setattr(mcp.server.stdio, 'stdio_server', BrokenPipeStdioContext)

	await server.run()

	server.server.run.assert_awaited_once()


@pytest.mark.asyncio
async def test_cli_mcp_server_handles_broken_pipe(monkeypatch):
	"""The CLI MCP server should exit cleanly when its stdio client disconnects."""
	server = CLIMCPServer()
	server.server.run = AsyncMock(side_effect=BrokenPipeError())
	monkeypatch.setattr(mcp.server.stdio, 'stdio_server', BrokenPipeStdioContext)

	await server.run()

	server.server.run.assert_awaited_once()
