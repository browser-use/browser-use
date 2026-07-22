"""Tests for MCP server error reporting (isError=True)."""

from typing import Any

import pytest
import mcp.types as types

from browser_use.mcp.server import BrowserUseServer


@pytest.fixture
def server() -> BrowserUseServer:
	return BrowserUseServer()


async def test_handle_call_tool_returns_is_error_true_on_exception(server: BrowserUseServer) -> None:
	"""Execution exception -> handle_call_tool must return CallToolResult with isError=True."""

	async def throwing_stub(**kwargs: Any) -> str:
		raise RuntimeError('Failed to establish CDP connection to browser')

	server._retry_with_browser_use_agent = throwing_stub  # type: ignore[method-assign]

	handler = server.server.request_handlers[types.CallToolRequest]
	request = types.CallToolRequest(
		params=types.CallToolRequestParams(name='retry_with_browser_use_agent', arguments={'task': 'noop'})
	)

	result = await handler(request)

	# The mcp server wraps the result in a ServerResult root
	assert hasattr(result, 'root') or isinstance(result, types.CallToolResult)
	tool_result = result.root if hasattr(result, 'root') else result

	assert isinstance(tool_result, types.CallToolResult)
	assert tool_result.isError is True
	assert len(tool_result.content) == 1
	assert tool_result.content[0].type == 'text'
	assert 'Failed to establish CDP connection' in tool_result.content[0].text
