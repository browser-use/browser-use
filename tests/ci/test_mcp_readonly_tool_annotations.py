"""Regression coverage for missing MCP tool annotations (issue #5239).

`tools/list` on the native Browser Use MCP server returned no annotations at
all, including for genuinely read-only operations like `browser_get_state`.
Some MCP hosts (e.g. Codex CLI running non-interactively with
`approval_policy=never`) require `readOnlyHint=true` before they'll auto-run
a tool call instead of cancelling it, so unannotated read-only tools could
never be used in those hosts.
"""

from mcp import types

from browser_use.mcp.server import BrowserUseServer

READ_ONLY_TOOLS = {
	'browser_get_state',
	'browser_extract_content',
	'browser_get_html',
	'browser_screenshot',
	'browser_list_tabs',
	'browser_list_sessions',
}

MUTATING_TOOLS = {
	'browser_navigate',
	'browser_click',
	'browser_type',
	'browser_scroll',
	'browser_go_back',
	'browser_switch_tab',
	'browser_close_tab',
	'retry_with_browser_use_agent',
	'browser_close_session',
	'browser_close_all',
}


async def _list_tools() -> dict[str, types.Tool]:
	server = BrowserUseServer()
	handler = server.server.request_handlers[types.ListToolsRequest]
	result = await handler(types.ListToolsRequest(method='tools/list'))
	tools = result.root.tools  # type: ignore[union-attr]
	return {tool.name: tool for tool in tools}


async def test_all_expected_tools_are_present():
	tools = await _list_tools()
	assert READ_ONLY_TOOLS | MUTATING_TOOLS <= tools.keys()


async def test_read_only_tools_have_read_only_hint():
	tools = await _list_tools()
	for name in READ_ONLY_TOOLS:
		annotations = tools[name].annotations
		assert annotations is not None, f'{name} is read-only but has no annotations at all'
		assert annotations.readOnlyHint is True, f'{name} is read-only but readOnlyHint is {annotations.readOnlyHint!r}'


async def test_mutating_tools_are_not_marked_read_only():
	tools = await _list_tools()
	for name in MUTATING_TOOLS:
		annotations = tools[name].annotations
		assert annotations is None or annotations.readOnlyHint is not True, (
			f'{name} mutates browser/session state and must not claim readOnlyHint=true'
		)
