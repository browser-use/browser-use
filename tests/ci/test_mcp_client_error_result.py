"""Regression test for MCP tool calls that fail at the application level.

Per the MCP spec, `CallToolResult.isError` signals that the tool itself
reported a failure (e.g. "File not found") even though the RPC call
succeeded. `MCPClient` must surface that as a failed `ActionResult`
instead of silently treating `result.content` as a successful result.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp import types

from browser_use import Tools
from browser_use.mcp.client import MCPClient


def _make_connected_client() -> MCPClient:
	client = MCPClient(server_name='test-server', command='test-command')
	client._telemetry = MagicMock()
	client._connected = True
	client.session = MagicMock()
	return client


@pytest.mark.asyncio
async def test_mcp_tool_isError_true_is_surfaced_as_action_result_error():
	"""An MCP tool that reports isError=True must not look like a success."""
	client = _make_connected_client()
	client.session.call_tool = AsyncMock(  # type: ignore[union-attr]
		return_value=types.CallToolResult(
			content=[types.TextContent(type='text', text='File not found: /tmp/does-not-exist.txt')],
			isError=True,
		)
	)

	tools = Tools()
	tool = types.Tool(name='read_file', description='Read a file', inputSchema={'type': 'object', 'properties': {}})
	client._register_tool_as_action(tools.registry, 'read_file', tool)

	result = await tools.registry.execute_action('read_file', {})

	assert result.success is False, f'expected success=False for a failed MCP tool call, got {result!r}'
	assert result.error, f'expected result.error to be set for a failed MCP tool call, got {result!r}'
	assert 'File not found' in result.error


@pytest.mark.asyncio
async def test_mcp_tool_isError_false_still_succeeds():
	"""Sanity check: a normal successful MCP tool call is unaffected by the fix."""
	client = _make_connected_client()
	client.session.call_tool = AsyncMock(  # type: ignore[union-attr]
		return_value=types.CallToolResult(
			content=[types.TextContent(type='text', text='ok')],
			isError=False,
		)
	)

	tools = Tools()
	tool = types.Tool(name='read_file', description='Read a file', inputSchema={'type': 'object', 'properties': {}})
	client._register_tool_as_action(tools.registry, 'read_file', tool)

	result = await tools.registry.execute_action('read_file', {})

	assert result.error is None
	assert result.extracted_content == 'ok'
