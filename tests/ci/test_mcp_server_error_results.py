from unittest.mock import AsyncMock, MagicMock

import pytest

from browser_use.mcp.server import BrowserUseServer


@pytest.fixture
def server() -> BrowserUseServer:
	return BrowserUseServer()


async def test_successful_tool_result_sets_is_error_false(server: BrowserUseServer) -> None:
	server._execute_tool = AsyncMock(return_value='ok')  # type: ignore[method-assign]

	result = await server._handle_call_tool('browser_list_tabs', {})

	assert result.isError is False
	assert result.content[0].type == 'text'
	assert result.content[0].text == 'ok'


async def test_unexpected_tool_exception_sets_is_error_true(server: BrowserUseServer) -> None:
	server._execute_tool = AsyncMock(side_effect=RuntimeError('CDP connection failed'))  # type: ignore[method-assign]

	result = await server._handle_call_tool('browser_type', {'index': 1, 'text': 'hello'})

	assert result.isError is True
	assert result.content[0].type == 'text'
	assert result.content[0].text == 'Error: CDP connection failed'


async def test_missing_element_sets_is_error_true(server: BrowserUseServer) -> None:
	server.browser_session = MagicMock()
	server.browser_session.get_dom_element_by_index = AsyncMock(return_value=None)

	result = await server._handle_call_tool('browser_type', {'index': 999999, 'text': 'hello'})

	assert result.isError is True
	assert result.content[0].type == 'text'
	assert result.content[0].text == 'Element with index 999999 not found'


async def test_unknown_tool_sets_is_error_true(server: BrowserUseServer) -> None:
	result = await server._handle_call_tool('unknown_tool', {})

	assert result.isError is True
	assert result.content[0].type == 'text'
	assert result.content[0].text == 'Unknown tool: unknown_tool'
