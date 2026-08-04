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
from mcp.server import NotificationOptions, Server, ServerRequestContext
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
		self._namespace: dict[str, Any] | None = None
		self._exec_lock = asyncio.Lock()
		self.server: Server = self._build_server()

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
				input_schema={
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
				input_schema={
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

	def _build_server(self) -> Server:
		async def handle_list_tools(
			ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
		) -> types.ListToolsResult:
			return types.ListToolsResult(tools=self._tool_definitions())

		async def handle_call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> types.CallToolResult:
			name = params.name
			arguments = params.arguments or {}
			try:
				if name == 'browser_exec':
					code = arguments.get('code')
					if not isinstance(code, str) or not code.strip():
						return types.CallToolResult(
							content=[types.TextContent(type='text', text="Error: 'code' must be a non-empty string")],
							is_error=True,
						)
					async with self._exec_lock:
						output, is_error = await asyncio.to_thread(self._execute, code)
					# _execute reports failure structurally (see its return), so user code that
					# merely prints a traceback-like string is NOT misclassified as an error.
					if is_error:
						return types.CallToolResult(content=[types.TextContent(type='text', text=output)], is_error=True)
					return types.CallToolResult(content=[types.TextContent(type='text', text=output or '(no output)')])
				if name == 'browser_screenshot':
					max_dim = arguments.get('max_dim')
					if max_dim is not None and (isinstance(max_dim, bool) or not isinstance(max_dim, int) or max_dim < 1):
						return types.CallToolResult(
							content=[types.TextContent(type='text', text="Error: 'max_dim' must be a positive integer")],
							is_error=True,
						)
					async with self._exec_lock:
						png = await asyncio.to_thread(self._screenshot, bool(arguments.get('full', False)), max_dim)
					return types.CallToolResult(content=[types.ImageContent(type='image', data=png, mime_type='image/png')])
				return types.CallToolResult(content=[types.TextContent(type='text', text=f'Unknown tool: {name}')], is_error=True)
			except Exception as e:
				# _screenshot and other unexpected failures (daemon down, capture error,
				# missing file) must surface as tool errors, not escape the handler.
				return types.CallToolResult(
					content=[types.TextContent(type='text', text=f'Error: {e}')],
					is_error=True,
				)

		return Server('browser-use', on_list_tools=handle_list_tools, on_call_tool=handle_call_tool)

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

	def _execute(self, code: str, connect: bool = True) -> tuple[str, bool]:
		"""Run code in the persistent namespace, capturing stdout/stderr.

		Runs in a worker thread: harness helpers are synchronous socket IPC. Output is
		captured because stdout carries the MCP protocol.

		Returns ``(output, is_error)``. Failure is reported structurally via the boolean
		rather than by scanning the captured text, so user code that prints a
		traceback-looking string is not mistaken for a real exception.
		"""
		buffer = StringIO()
		is_error = False
		with redirect_stdout(buffer), redirect_stderr(buffer):
			try:
				ns = self._ensure_namespace()
				if connect:
					self._ensure_daemon(code)
				exec(code, ns)
			except BaseException:
				is_error = True
				traceback.print_exc(file=buffer)
		return buffer.getvalue(), is_error

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
