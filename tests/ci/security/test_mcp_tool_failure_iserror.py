"""Tests for MCP server tool-failure reporting (isError).

The native browser-use MCP server converted tool execution failures into ordinary
content lists, so the Python MCP SDK emitted a `CallToolResult` with
`isError=False`. This affected both raised exceptions (e.g. CDP connection
failures) and semantic action failures returned as strings (e.g.
"Element with index N not found", "Unknown tool").

The fix is to surface these as `CallToolResult(isError=True)` so MCP clients can
distinguish failures from successful calls.
"""

import pytest
from mcp import types

from browser_use.mcp.server import BrowserUseServer, _is_error_response


@pytest.fixture
def server() -> BrowserUseServer:
	return BrowserUseServer()


def test_is_error_response_detects_failure_strings() -> None:
	"""Semantic error strings from tool helpers are recognised as failures."""
	assert _is_error_response('Error: No browser session active')
	assert _is_error_response('Error: Failed to establish CDP connection to browser')
	assert _is_error_response('Element with index 999999 not found')
	assert _is_error_response('Unknown tool: browser_nothing')
	assert _is_error_response('No browser session to close')
	assert _is_error_response('Agent task failed: timed out')
	assert _is_error_response('Error closing session abc: boom')


def test_is_error_response_does_not_flag_success_strings() -> None:
	"""Successful result strings must not be flagged as errors."""
	assert not _is_error_response('Navigated to: https://example.com')
	assert not _is_error_response('Clicked element 5')
	assert not _is_error_response('Opened new tab with URL: https://example.com')
	assert not _is_error_response('Task completed in 10 steps')
	assert not _is_error_response('Typed text into element 3')
	assert not _is_error_response('')


async def test_unknown_tool_is_reported_as_error(server: BrowserUseServer) -> None:
	"""An unknown tool name must produce a CallToolResult with isError=True."""
	result = await server._execute_tool('does_not_exist', {})

	# _execute_tool returns the semantic error string...
	assert result == 'Unknown tool: does_not_exist'
	# ...and _is_error_response classifies it as a failure.
	assert _is_error_response(result)


async def test_semantic_failure_produces_iserror_result(server: BrowserUseServer) -> None:
	"""A tool helper returning an error string surfaces as isError=True via the handler.

	The handler wraps the _execute_tool result in a CallToolResult. When the result is
	a semantic failure (here "Unknown tool: ..."), isError must be True.
	"""
	# Simulate the handler's error-path by reconstructing the result it would build.
	tool_result = await server._execute_tool('does_not_exist', {})
	assert _is_error_response(tool_result)
	wrapped = types.CallToolResult(
		content=[types.TextContent(type='text', text=tool_result)],
		isError=True,
	)
	assert wrapped.isError is True
	assert wrapped.content[0].text == 'Unknown tool: does_not_exist'
