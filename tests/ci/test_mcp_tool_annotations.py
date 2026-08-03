"""Tests for MCP tool annotations on the `browser-use --mcp` surface (#5239).

The MCP tool catalogue used to ship without any `annotations`, so clients that
gate tool execution on MCP hints (e.g. Codex CLI with `approval_policy=never`)
auto-cancelled even clearly read-only calls like `browser_get_state`.

Read-only tools must advertise `readOnlyHint=True`; every state-changing tool
must NOT advertise it. `browser_extract_content` is deliberately excluded from
the read-only set: it dispatches the `extract` action through `Tools.act()`
with a FileSystem handle and can write extraction artifacts.
"""

import mcp.types as types
import pytest

from browser_use.mcp.server import BrowserUseServer

# Tools whose handlers only read state (see BrowserUseServer._get_browser_state,
# _get_html, _screenshot, _list_tabs, _list_sessions). Everything else mutates
# browser/session state and must never carry readOnlyHint=True.
EXPECTED_READ_ONLY_TOOLS = frozenset(
	{
		'browser_get_state',
		'browser_get_html',
		'browser_screenshot',
		'browser_list_tabs',
		'browser_list_sessions',
	}
)


@pytest.fixture
def server() -> BrowserUseServer:
	return BrowserUseServer()


def _is_read_only(tool: types.Tool) -> bool:
	return tool.annotations is not None and tool.annotations.readOnlyHint is True


async def _list_tools(server: BrowserUseServer) -> list[types.Tool]:
	handler = server.server.request_handlers[types.ListToolsRequest]
	result = await handler(types.ListToolsRequest(method='tools/list'))
	assert isinstance(result, types.ServerResult), f'expected ServerResult, got {type(result).__name__}'
	list_result = result.root
	assert isinstance(list_result, types.ListToolsResult), f'expected ListToolsResult, got {type(list_result).__name__}'
	assert len(list_result.tools) > 0, 'tools/list returned an empty catalogue'
	return list_result.tools


async def test_read_only_tools_advertise_read_only_hint(server: BrowserUseServer) -> None:
	"""Every genuinely read-only tool must carry annotations.readOnlyHint=True."""
	tools = await _list_tools(server)
	by_name = {tool.name: tool for tool in tools}

	missing_tools = EXPECTED_READ_ONLY_TOOLS - by_name.keys()
	assert not missing_tools, f'expected read-only tools missing from tools/list: {sorted(missing_tools)}'

	unannotated = sorted(name for name in EXPECTED_READ_ONLY_TOOLS if not _is_read_only(by_name[name]))
	assert not unannotated, (
		f'read-only tools missing readOnlyHint=True: {unannotated}. '
		f'Clients that gate on MCP annotations (e.g. Codex approval_policy=never) cancel unannotated calls.'
	)


async def test_mutating_tools_never_advertise_read_only_hint(server: BrowserUseServer) -> None:
	"""No state-changing tool may claim to be read-only.

	A new tool that carries readOnlyHint=True must be consciously added to
	EXPECTED_READ_ONLY_TOOLS after checking its handler really only reads.
	"""
	tools = await _list_tools(server)

	mislabeled = sorted(tool.name for tool in tools if tool.name not in EXPECTED_READ_ONLY_TOOLS and _is_read_only(tool))
	assert not mislabeled, f'state-changing tools wrongly advertise readOnlyHint=True: {mislabeled}'
