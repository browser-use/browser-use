"""Tests for MCP tool annotations on the `browser-use --mcp` surface (#5239).

The MCP tool catalogue used to ship without any `annotations`, so clients that
gate tool execution on MCP hints (e.g. Codex CLI with `approval_policy=never`)
auto-cancelled even clearly read-only calls like `browser_get_state`.

Read-only tools must advertise `readOnlyHint=True`; every state-changing tool
must NOT advertise it. `browser_extract_content` is deliberately excluded from
the read-only set: it dispatches the `extract` action through `Tools.act()`
with a FileSystem handle and can write extraction artifacts.
"""

import mcp.shared.memory
import mcp.types as types
import pytest

from browser_use.mcp._compat import MCP_SDK_V2
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
	if tool.annotations is None:
		return False
	# readOnlyHint (mcp 1.x attribute) was renamed to read_only_hint in mcp 2.x
	read_only = getattr(tool.annotations, 'read_only_hint', None)
	if read_only is None:
		read_only = getattr(tool.annotations, 'readOnlyHint', False)
	return read_only is True


async def _list_tools(server: BrowserUseServer) -> list[types.Tool]:
	"""Fetch the tools/list catalogue through a real client session (mcp 1.x and 2.x)."""
	from contextlib import asynccontextmanager

	from mcp import ClientSession

	@asynccontextmanager
	async def connected_session():
		if MCP_SDK_V2:
			# mcp 2.x: pair in-memory streams, run the server on a task, talk to it with a ClientSession
			import anyio
			from mcp.server import NotificationOptions
			from mcp.server.models import InitializationOptions

			create_streams = getattr(mcp.shared.memory, 'create_client_server_memory_streams')

			async with create_streams() as (client_streams, server_streams):
				client_read, client_write = client_streams
				server_read, server_write = server_streams
				async with anyio.create_task_group() as tg:
					tg.start_soon(
						server.server.run,
						server_read,
						server_write,
						InitializationOptions(
							server_name='browser-use',
							server_version='0.0.0-test',
							capabilities=server.server.get_capabilities(
								notification_options=NotificationOptions(),
								experimental_capabilities={},
							),
						),
					)
					try:
						async with ClientSession(client_read, client_write) as session:
							await session.initialize()
							yield session
					finally:
						tg.cancel_scope.cancel()
		else:
			create_connected = getattr(mcp.shared.memory, 'create_connected_server_and_client_session')

			async with create_connected(server.server) as session:
				yield session

	async with connected_session() as session:
		result = await session.list_tools()
		assert len(result.tools) > 0, 'tools/list returned an empty catalogue'
		return result.tools


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
