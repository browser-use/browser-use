"""Regression coverage for MCP tool exceptions reported as isError=false (issue #5252).

`handle_call_tool` caught exceptions from `_execute_tool` and returned a plain
`list[TextContent]` describing the error. The low-level MCP SDK wraps a
returned content list into `CallToolResult(..., isError=False)` unconditionally,
so callers (and MCP hosts like Codex, which key off `isError` to classify a
tool call as failed) saw exceptions -- including CDP connection failures -- as
successful tool calls with error text embedded in the content.
"""

from mcp import types

from browser_use.mcp.server import BrowserUseServer


async def _call_tool(server: BrowserUseServer, name: str, arguments: dict) -> types.CallToolResult:
	handler = server.server.request_handlers[types.CallToolRequest]
	request = types.CallToolRequest(
		method='tools/call',
		params=types.CallToolRequestParams(name=name, arguments=arguments),
	)
	result = await handler(request)
	assert isinstance(result.root, types.CallToolResult)
	return result.root


async def test_tool_execution_exception_sets_iserror_true():
	server = BrowserUseServer()

	async def boom(name: str, arguments: dict) -> str:
		raise RuntimeError('Failed to establish CDP connection to browser: no close frame received or sent')

	server._execute_tool = boom  # type: ignore[method-assign]

	result = await _call_tool(server, 'browser_type', {'index': 999999, 'text': 'x'})

	assert result.isError is True
	assert len(result.content) == 1
	assert isinstance(result.content[0], types.TextContent)
	assert 'Failed to establish CDP connection' in result.content[0].text


async def test_successful_tool_execution_keeps_iserror_false():
	server = BrowserUseServer()

	async def ok(name: str, arguments: dict) -> str:
		return 'done'

	server._execute_tool = ok  # type: ignore[method-assign]

	result = await _call_tool(server, 'browser_get_state', {})

	assert result.isError is False
	assert result.content[0].text == 'done'  # type: ignore[union-attr]
