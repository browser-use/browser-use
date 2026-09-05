"""Discover complete MCP catalogs through real stdio sessions and action execution."""

import asyncio
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent
from typing import Any

import psutil
import pytest

from browser_use import BrowserSession, Tools
from browser_use.mcp.client import MCPClient

SERVER = dedent("""
import asyncio
import json
import os
from pathlib import Path
import sys

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

config = json.loads(Path(sys.argv[1]).read_text())
events = Path(sys.argv[2])
page_index = 0

def record(event):
    with events.open('a') as output:
        output.write(json.dumps(event) + '\\n')

async def list_tools(ctx, params):
    global page_index
    cursor = params.cursor if params else None
    record({'cursor': cursor})
    if config.get('endless'):
        await asyncio.sleep(0.02)
        page_index += 1
        return types.ListToolsResult(tools=[], next_cursor=str(page_index))
    page = config['pages'][page_index]
    page_index += 1
    assert cursor == page.get('cursor'), (cursor, page.get('cursor'))
    if page.get('error'):
        raise ValueError('second page unavailable')
    if page.get('wait'):
        await asyncio.Event().wait()
    tools = [types.Tool(name=name, description=name,
                       input_schema={'type': 'object', 'properties': {}})
             for name in page.get('tools', [])]
    return types.ListToolsResult(tools=tools, next_cursor=page.get('next_cursor'))

async def call_tool(ctx, params):
    record({'call': params.name})
    return types.CallToolResult(content=[types.TextContent(type='text', text='called ' + params.name)])

async def main():
    record({'pid': os.getpid()})
    server = Server('paginated-tools', on_list_tools=list_tools, on_call_tool=call_tool)
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())

asyncio.run(main())
""")


@dataclass
class CatalogServer:
	client: MCPClient
	events_path: Path

	def events(self) -> list[dict[str, Any]]:
		if not self.events_path.exists():
			return []
		return [json.loads(line) for line in self.events_path.read_text().splitlines()]

	async def cleanup(self) -> None:
		await self.client.disconnect()
		if self.client._stdio_task is not None and not self.client._stdio_task.done():
			self.client._stdio_task.cancel()
			await asyncio.gather(self.client._stdio_task, return_exceptions=True)

	def assert_closed(self) -> None:
		assert self.client.session is None
		assert not self.client._connected
		assert self.client._stdio_task is not None and self.client._stdio_task.done()
		pid = next(event['pid'] for event in self.events() if 'pid' in event)
		assert not psutil.pid_exists(pid)


@pytest.fixture
def catalog_server(tmp_path: Path) -> Callable[..., CatalogServer]:
	def create(pages: list[dict[str, Any]], *, endless: bool = False) -> CatalogServer:
		server = tmp_path / 'server.py'
		server.write_text(SERVER)
		config = tmp_path / 'config.json'
		config.write_text(json.dumps({'pages': pages, 'endless': endless}))
		events = tmp_path / 'events.jsonl'
		client = MCPClient('paginated-tools', sys.executable, [str(server), str(config), str(events)])
		return CatalogServer(client, events)

	return create


@pytest.fixture(scope='module')
async def mcp_browser(tmp_path_factory):
	browser = BrowserSession(
		user_data_dir=str(tmp_path_factory.mktemp('mcp-browser-profile')),
		headless=True,
		enable_default_extensions=False,
	)
	await browser.start()
	try:
		yield browser
	finally:
		await browser.kill()
		await browser.event_bus.stop(clear=True, timeout=5)


@pytest.mark.parametrize(
	('pages', 'tool_filter', 'expected'),
	[
		([{'tools': ['first']}], None, ['first']),
		(
			[{'tools': ['first'], 'next_cursor': 'opaque/+=='}, {'cursor': 'opaque/+==', 'tools': ['second']}],
			None,
			['first', 'second'],
		),
		(
			[{'tools': ['first'], 'next_cursor': 'opaque/+=='}, {'cursor': 'opaque/+==', 'tools': ['second']}],
			['second'],
			['second'],
		),
		(
			[
				{'tools': ['first'], 'next_cursor': ''},
				{'cursor': '', 'tools': [], 'next_cursor': 'opaque-next'},
				{'cursor': 'opaque-next', 'tools': ['second']},
			],
			None,
			['first', 'second'],
		),
	],
	ids=['single-page', 'all-pages', 'filter-second-page', 'empty-cursor-and-page'],
)
async def test_catalog_tools_register_and_execute(catalog_server, mcp_browser, pages, tool_filter, expected):
	server = catalog_server(pages)
	tools = Tools()
	try:
		await server.client.register_to_tools(tools, tool_filter=tool_filter, prefix='catalog_')
		registered = [name for name in tools.registry.registry.actions if name.startswith('catalog_')]
		assert registered == [f'catalog_{name}' for name in expected]
		assert [event['cursor'] for event in server.events() if 'cursor' in event] == [page.get('cursor') for page in pages]
		action_name = f'catalog_{expected[-1]}'
		action = tools.registry.create_action_model()(**{action_name: {}})
		result = await tools.act(action, browser_session=mcp_browser)
		assert result.error is None
		assert result.extracted_content == f'called {expected[-1]}'
		assert [event['call'] for event in server.events() if 'call' in event] == [expected[-1]]
	finally:
		await server.cleanup()
	server.assert_closed()


def exception_messages(error: BaseException) -> str:
	if isinstance(error, BaseExceptionGroup):
		return '\n'.join(exception_messages(child) for child in error.exceptions)
	return str(error)


@pytest.mark.parametrize(
	('following_pages', 'message'),
	[
		([{'cursor': 'next', 'tools': ['second'], 'next_cursor': 'next'}], 'repeated tools/list cursor'),
		(
			[
				{'cursor': 'next', 'tools': ['second'], 'next_cursor': 'later'},
				{'cursor': 'later', 'tools': [], 'next_cursor': 'next'},
			],
			'repeated tools/list cursor',
		),
		([{'cursor': 'next', 'error': True}], 'second page unavailable'),
	],
	ids=['repeated-cursor', 'cursor-cycle', 'second-page-error'],
)
async def test_invalid_catalog_is_not_partially_registered(catalog_server, following_pages, message):
	server = catalog_server([{'tools': ['first'], 'next_cursor': 'next'}, *following_pages])
	tools = Tools()
	try:
		with pytest.raises(Exception) as caught:
			await server.client.register_to_tools(tools, prefix='catalog_')
		assert message in exception_messages(caught.value)
		assert not any(name.startswith('catalog_') for name in tools.registry.registry.actions)
		assert not server.client._tools
		server.assert_closed()
	finally:
		await server.cleanup()


async def test_cancelled_discovery_closes_session_and_server(catalog_server):
	server = catalog_server([{'tools': ['first'], 'next_cursor': 'next'}, {'cursor': 'next', 'wait': True}])
	tools = Tools()
	registration = asyncio.create_task(server.client.register_to_tools(tools, prefix='catalog_'))
	try:
		async with asyncio.timeout(5):
			# Readiness is reported by a separate stdio subprocess, not an in-loop event.
			while len([event for event in server.events() if 'cursor' in event]) < 2:  # noqa: ASYNC110
				await asyncio.sleep(0.01)
		registration.cancel()
		with pytest.raises(asyncio.CancelledError):
			await registration
		assert not any(name.startswith('catalog_') for name in tools.registry.registry.actions)
		assert not server.client._tools
		server.assert_closed()
	finally:
		registration.cancel()
		await asyncio.gather(registration, return_exceptions=True)
		await server.cleanup()


async def test_existing_connection_deadline_bounds_endless_new_cursors(catalog_server):
	server = catalog_server([], endless=True)
	try:
		with pytest.raises(RuntimeError, match='Failed to connect'):
			await server.client.connect()
		assert len([event for event in server.events() if 'cursor' in event]) > 1
		assert not server.client._tools
		server.assert_closed()
	finally:
		await server.cleanup()
