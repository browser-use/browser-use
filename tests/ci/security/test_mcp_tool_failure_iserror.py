"""Tests for MCP server tool-failure reporting (isError).

The native browser-use MCP server originally converted tool execution failures
into ordinary content lists, so the Python MCP SDK emitted a `CallToolResult`
with `isError=False`. A later fix classified failures by string-prefix sniffing,
which misclassified successful text that happened to start with ``"Error:"``
(e.g. `browser_extract_content` returning page text) and missed failure shapes
that didn't match any sentinel (e.g. ``Session <id> not found``).

The helpers now return a typed `ToolFailure` and the registered call-tool
handler maps it to `CallToolResult(isError=True)` at a single boundary, so
protocol status is independent of user- or page-supplied text.
"""

import pytest
from mcp import types

from browser_use.mcp.server import BrowserUseServer, ToolFailure


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> BrowserUseServer:
	# Keep the suite hermetic: telemetry / cloud sync would try network I/O.
	monkeypatch.setenv('ANONYMIZED_TELEMETRY', 'false')
	monkeypatch.setenv('BROWSER_USE_CLOUD_SYNC', 'false')
	return BrowserUseServer()


async def call_handler(server: BrowserUseServer, name: str, arguments: dict | None = None):
	"""Invoke the registered call-tool handler the way the MCP SDK would."""
	return await server._handle_call_tool(name, arguments or {})


def assert_error_result(result, needle: str) -> None:
	assert isinstance(result, types.CallToolResult), f'expected CallToolResult, got {type(result)}'
	assert result.isError is True, f'expected isError=True, got {result.isError}'
	content = result.content[0]
	assert isinstance(content, types.TextContent)
	assert needle in content.text, f'{needle!r} not in {content.text!r}'


class _StubSession:
	"""Minimal browser-session stand-in whose element lookups find nothing."""

	id = 'stub-session-id'

	async def get_dom_element_by_index(self, index: int):
		return None


async def test_unknown_tool_is_reported_as_error(server: BrowserUseServer) -> None:
	result = await call_handler(server, 'does_not_exist', {})
	assert_error_result(result, 'Unknown tool: does_not_exist')


async def test_missing_session_is_reported_as_error(server: BrowserUseServer) -> None:
	# _execute_tool lazily initialises a real browser session before dispatching
	# browser_* tools; simulate an init that yields no session.
	async def _no_session(*args, **kwargs):
		return None

	server._init_browser_session = _no_session  # type: ignore[method-assign]
	result = await call_handler(server, 'browser_list_tabs', {})
	assert_error_result(result, 'No browser session active')


async def test_missing_element_is_reported_as_error(server: BrowserUseServer) -> None:
	server.browser_session = _StubSession()  # type: ignore[assignment]
	result = await call_handler(server, 'browser_click', {'index': 5})
	assert_error_result(result, 'Element with index 5 not found')


async def test_missing_close_session_is_reported_as_error(server: BrowserUseServer) -> None:
	result = await call_handler(server, 'browser_close_session', {'session_id': 'abc123'})
	assert_error_result(result, 'Session abc123 not found')


async def test_raised_exception_is_reported_as_error(server: BrowserUseServer) -> None:
	async def _no_session(*args, **kwargs):
		return None

	server._init_browser_session = _no_session  # type: ignore[method-assign]

	async def _boom(*args, **kwargs):
		raise RuntimeError('kaboom')

	server._navigate = _boom  # type: ignore[method-assign]
	result = await call_handler(server, 'browser_navigate', {'url': 'https://example.com'})
	assert_error_result(result, 'kaboom')


async def test_successful_text_starting_with_error_is_not_flagged(server: BrowserUseServer) -> None:
	"""`browser_extract_content` returns arbitrary page text; a successful
	extraction that begins with ``Error:`` must stay a normal result."""

	async def _no_session(*args, **kwargs):
		return None

	server._init_browser_session = _no_session  # type: ignore[method-assign]

	async def _fake_extract(query: str, extract_links: bool = False) -> str:
		return 'Error: the page returned a validation notice'

	server._extract_content = _fake_extract  # type: ignore[method-assign]
	result = await call_handler(server, 'browser_extract_content', {'query': 'summary'})

	# Success path returns a plain content list; the SDK wraps it with isError=False.
	assert isinstance(result, list), f'expected content list, got {type(result)}'
	content = result[0]
	assert isinstance(content, types.TextContent)
	assert content.text.startswith('Error: the page returned a validation notice')


async def test_tool_failure_type_reaches_handler_boundary(server: BrowserUseServer) -> None:
	"""_execute_tool itself returns the typed failure, not a sniffed string."""
	result = await server._execute_tool('does_not_exist', {})
	assert isinstance(result, ToolFailure)
	assert result.message == 'Unknown tool: does_not_exist'
