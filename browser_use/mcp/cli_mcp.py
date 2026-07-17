"""MCP server exposing the CLI 3.0
Run with: browser-use --cli-mcp
"""

import asyncio
import base64
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from typing import Any

import mcp.server.stdio
import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions

from browser_use.utils import get_browser_use_version

_NAMESPACE_IMPORTS = (
	'from browser_harness.admin import ('
	'daemon_alive, ensure_daemon, restart_daemon, start_remote_daemon, stop_remote_daemon)\n'
	'from browser_harness.helpers import *\n'
)


def _harness_skill_text() -> str:
	from browser_use.skills.browser_use import skill_text

	return skill_text()


class CLIMCPServer:
	"""Stateful stdio MCP server wrapping the browser-harness exec model."""

	def __init__(self):
		self.server: Server = Server('browser-use')
		self._namespace: dict[str, Any] | None = None
		self._exec_lock = asyncio.Lock()
		self._register_handlers()

	def _tool_definitions(self) -> list[types.Tool]:
		return [
			types.Tool(
				name='browser_exec',
				description=(
					'Execute Python in the browser-harness session. Helpers like new_tab(url), '
					'goto_url(url), page_info(), click_at_xy(x, y), type_text(text), js(code), '
					'cdp(method, ...), wait_for_load(), list_tabs() are pre-imported. The namespace '
					'persists across calls. Returns whatever the code prints. First navigation '
					'should be new_tab(url).'
				),
				inputSchema={
					'type': 'object',
					'properties': {
						'code': {'type': 'string', 'description': 'Python code to execute'},
					},
					'required': ['code'],
				},
			),
			types.Tool(
				name='browser_screenshot',
				description='Capture the current page and return it as an image. Prefer this over capture_screenshot() in browser_exec.',
				inputSchema={
					'type': 'object',
					'properties': {
						'full': {'type': 'boolean', 'description': 'Capture beyond the viewport (full page)', 'default': False},
						'max_dim': {
							'type': 'integer',
							'minimum': 1,
							'description': 'Downscale so no side exceeds this many pixels (e.g. 1800 for 2x displays)',
						},
					},
				},
			),
		]

	def _register_handlers(self):
		@self.server.list_tools()
		async def handle_list_tools() -> list[types.Tool]:
			return self._tool_definitions()

		@self.server.call_tool()
		async def handle_call_tool(name: str, arguments: dict[str, Any] | None) -> list[types.TextContent | types.ImageContent]:
			arguments = arguments or {}
			if name == 'browser_exec':
				code = arguments.get('code')
				if not isinstance(code, str) or not code.strip():
					return [types.TextContent(type='text', text="Error: 'code' must be a non-empty string")]
				async with self._exec_lock:
					output = await asyncio.to_thread(self._execute, code)
				return [types.TextContent(type='text', text=output or '(no output)')]
			if name == 'browser_screenshot':
				max_dim = arguments.get('max_dim')
				if max_dim is not None and (isinstance(max_dim, bool) or not isinstance(max_dim, int) or max_dim < 1):
					return [types.TextContent(type='text', text="Error: 'max_dim' must be a positive integer")]
				async with self._exec_lock:
					png = await asyncio.to_thread(self._screenshot, bool(arguments.get('full', False)), max_dim)
				return [types.ImageContent(type='image', data=png, mimeType='image/png')]
			return [types.TextContent(type='text', text=f'Unknown tool: {name}')]

	def _ensure_namespace(self) -> dict[str, Any]:
		if self._namespace is None:
			ns: dict[str, Any] = {}
			exec(_NAMESPACE_IMPORTS, ns)
			self._namespace = ns
		return self._namespace

	def _ensure_daemon(self, code: str) -> None:
		"""Mirror run.py: daemon must be up before helpers run, except for cloud admin snippets."""
		ns = self._ensure_namespace()
		if code.lstrip().startswith(('start_remote_daemon(', 'stop_remote_daemon(')):
			return
		ns['ensure_daemon']()

	def _execute(self, code: str, connect: bool = True) -> str:
		"""Run code in the persistent namespace, capturing stdout/stderr.

		Runs in a worker thread: harness helpers are synchronous socket IPC. Output is
		captured because stdout carries the MCP protocol.
		"""
		buffer = StringIO()
		with redirect_stdout(buffer), redirect_stderr(buffer):
			try:
				ns = self._ensure_namespace()
				if connect:
					self._ensure_daemon(code)
				exec(code, ns)
			except BaseException:
				traceback.print_exc(file=buffer)
		return buffer.getvalue()

	def _screenshot(self, full: bool, max_dim: int | None) -> str:
		buffer = StringIO()
		with redirect_stdout(buffer), redirect_stderr(buffer):
			ns = self._ensure_namespace()
			ns['ensure_daemon']()
			path = ns['capture_screenshot'](full=full, max_dim=max_dim)
		with open(path, 'rb') as f:
			return base64.b64encode(f.read()).decode()

	def _instructions(self) -> str:
		return _harness_skill_text()

	async def run(self):
		if sys.stdin is None:
			raise RuntimeError('MCP stdio transport requires stdin, but this process was launched without one.')

		async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
			try:
				await self.server.run(
					read_stream,
					write_stream,
					InitializationOptions(
						server_name='browser-use',
						server_version=get_browser_use_version(),
						instructions=self._instructions(),
						capabilities=self.server.get_capabilities(
							notification_options=NotificationOptions(),
							experimental_capabilities={},
						),
					),
				)
			except BrokenPipeError:
				pass


async def main():
	import os

	os.environ.setdefault('BH_CLIENT', 'browser-use-mcp')
	server = CLIMCPServer()
	await server.run()


if __name__ == '__main__':
	asyncio.run(main())
