"""Handler-level regression tests for the mcp 2.x migration.

These tests drive the handlers registered on the underlying ``mcp.server.Server``
(``server.server.get_request_handler(...)``) rather than calling internal helpers
directly. They assert the contract the reviewer flagged on PR #5334: failed tool
calls must be returned as ``CallToolResult(..., is_error=True)`` instead of being
wrapped as successful results, and the list handlers must return typed results.

No real browser, daemon, or LLM is needed — internal helpers are stubbed out.
"""

from typing import Any

import mcp.types as types
import pytest

from browser_use.mcp.cli_mcp import CLIMCPServer
from browser_use.mcp.server import BrowserUseServer


def _call_tool_handler(server: Any) -> Any:
	return server.server.get_request_handler('tools/call').handler


def _list_tools_handler(server: Any) -> Any:
	return server.server.get_request_handler('tools/list').handler


def _list_resources_handler(server: Any) -> Any:
	return server.server.get_request_handler('resources/list').handler


def _list_prompts_handler(server: Any) -> Any:
	return server.server.get_request_handler('prompts/list').handler


def _text_of(result: types.CallToolResult) -> str:
	return ''.join(getattr(block, 'text', '') for block in result.content)


# ---------------------------------------------------------------------------
# BrowserUseServer
# ---------------------------------------------------------------------------


@pytest.fixture
def browser_use_server() -> BrowserUseServer:
	return BrowserUseServer()


async def test_browser_use_registers_call_and_list_handlers(browser_use_server: BrowserUseServer) -> None:
	handlers = browser_use_server.server._request_handlers
	assert 'tools/call' in handlers
	assert 'tools/list' in handlers


async def test_browser_use_list_tools_returns_typed_tools_with_schemas(browser_use_server: BrowserUseServer) -> None:
	handler = _list_tools_handler(browser_use_server)
	result = await handler(None, None)
	assert isinstance(result, types.ListToolsResult)
	assert len(result.tools) > 0
	for tool in result.tools:
		assert isinstance(tool, types.Tool)
		assert tool.input_schema, f'tool {tool.name!r} must have an input_schema populated'


async def test_browser_use_list_resources_returns_typed_empty(browser_use_server: BrowserUseServer) -> None:
	handler = _list_resources_handler(browser_use_server)
	result = await handler(None, None)
	assert isinstance(result, types.ListResourcesResult)
	assert result.resources == []


async def test_browser_use_list_prompts_returns_typed_empty(browser_use_server: BrowserUseServer) -> None:
	handler = _list_prompts_handler(browser_use_server)
	result = await handler(None, None)
	assert isinstance(result, types.ListPromptsResult)
	assert result.prompts == []


async def test_browser_use_call_unknown_tool_is_error(browser_use_server: BrowserUseServer) -> None:
	handler = _call_tool_handler(browser_use_server)
	params = types.CallToolRequestParams(name='no_such_tool', arguments={})
	result = await handler(None, params)
	assert isinstance(result, types.CallToolResult)
	assert result.is_error is True
	assert 'Unknown tool' in _text_of(result)


async def test_browser_use_call_tool_that_raises_is_error(browser_use_server: BrowserUseServer) -> None:
	async def raising_stub(tool_name: str, arguments: dict[str, Any]) -> str:
		raise RuntimeError('boom')

	browser_use_server._execute_tool = raising_stub  # type: ignore[method-assign]
	handler = _call_tool_handler(browser_use_server)
	params = types.CallToolRequestParams(name='browser_navigate', arguments={'url': 'https://example.test'})
	result = await handler(None, params)
	assert result.is_error is True
	assert 'boom' in _text_of(result)


async def test_browser_use_call_tool_success_is_not_error_and_preserves_text(browser_use_server: BrowserUseServer) -> None:
	async def ok_stub(task: str, **kwargs: Any) -> str:
		return f'did: {task}'

	browser_use_server._retry_with_browser_use_agent = ok_stub  # type: ignore[method-assign]
	handler = _call_tool_handler(browser_use_server)
	params = types.CallToolRequestParams(name='retry_with_browser_use_agent', arguments={'task': 'noop'})
	result = await handler(None, params)
	assert result.is_error is not True
	assert _text_of(result) == 'did: noop'


# ---------------------------------------------------------------------------
# CLIMCPServer
# ---------------------------------------------------------------------------


@pytest.fixture
def cli_server() -> CLIMCPServer:
	return CLIMCPServer()


async def test_cli_registers_call_and_list_handlers(cli_server: CLIMCPServer) -> None:
	handlers = cli_server.server._request_handlers
	assert 'tools/call' in handlers
	assert 'tools/list' in handlers


async def test_cli_list_tools_returns_both_schemas(cli_server: CLIMCPServer) -> None:
	handler = _list_tools_handler(cli_server)
	result = await handler(None, None)
	assert isinstance(result, types.ListToolsResult)
	names = {tool.name for tool in result.tools}
	assert names == {'browser_exec', 'browser_screenshot'}
	for tool in result.tools:
		assert tool.input_schema, f'tool {tool.name!r} must have an input_schema populated'


async def test_cli_exec_missing_code_is_error(cli_server: CLIMCPServer) -> None:
	handler = _call_tool_handler(cli_server)
	params = types.CallToolRequestParams(name='browser_exec', arguments={})
	result = await handler(None, params)
	assert result.is_error is True


async def test_cli_exec_empty_code_is_error(cli_server: CLIMCPServer) -> None:
	handler = _call_tool_handler(cli_server)
	params = types.CallToolRequestParams(name='browser_exec', arguments={'code': '   '})
	result = await handler(None, params)
	assert result.is_error is True


async def test_cli_exec_traceback_is_error(cli_server: CLIMCPServer) -> None:
	def fake_execute(code: str, connect: bool = True) -> str:
		return 'Traceback (most recent call last):\n  File "<stdin>", line 1\nZeroDivisionError: division by zero\n'

	cli_server._execute = fake_execute  # type: ignore[method-assign]
	handler = _call_tool_handler(cli_server)
	params = types.CallToolRequestParams(name='browser_exec', arguments={'code': '1/0'})
	result = await handler(None, params)
	assert result.is_error is True
	assert 'ZeroDivisionError' in _text_of(result)


async def test_cli_exec_success_is_not_error(cli_server: CLIMCPServer) -> None:
	def fake_execute(code: str, connect: bool = True) -> str:
		return 'hello from the page'

	cli_server._execute = fake_execute  # type: ignore[method-assign]
	handler = _call_tool_handler(cli_server)
	params = types.CallToolRequestParams(name='browser_exec', arguments={'code': 'print(1)'})
	result = await handler(None, params)
	assert result.is_error is not True
	assert _text_of(result) == 'hello from the page'


async def test_cli_screenshot_that_raises_is_error_not_propagated(cli_server: CLIMCPServer) -> None:
	def fake_screenshot(full: bool, max_dim: int | None) -> str:
		raise RuntimeError('daemon is down')

	cli_server._screenshot = fake_screenshot  # type: ignore[method-assign]
	handler = _call_tool_handler(cli_server)
	params = types.CallToolRequestParams(name='browser_screenshot', arguments={})
	result = await handler(None, params)
	assert isinstance(result, types.CallToolResult)
	assert result.is_error is True
	assert 'daemon is down' in _text_of(result)


async def test_cli_unknown_tool_is_error(cli_server: CLIMCPServer) -> None:
	handler = _call_tool_handler(cli_server)
	params = types.CallToolRequestParams(name='no_such_tool', arguments={})
	result = await handler(None, params)
	assert result.is_error is True
	assert 'Unknown tool' in _text_of(result)
