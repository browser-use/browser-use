"""MCP server exposing the CLI 3.0
Run with: browser-use --cli-mcp
"""

import asyncio
import base64
import os
import subprocess
import sys
import threading
import traceback
import webbrowser
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from typing import Any

import mcp.server.stdio
import mcp.types as types
from browser_harness import _ipc as ipc
from browser_harness import admin
from browser_harness.auth import CloudAuthRequired
from mcp.server import Server

from browser_use import harness_cloud
from browser_use.auth import harden_login_callback, set_aside_corrupt_store
from browser_use.harness_cloud import CloudBrowserError
from browser_use.utils import get_browser_use_version

_NAMESPACE_IMPORTS = (
	'from browser_harness.admin import ('
	'daemon_alive, ensure_daemon, restart_daemon, start_remote_daemon, stop_remote_daemon)\n'
	'from browser_harness.helpers import *\n'
)


LOGIN_HINT = 'Not signed in to Browser Use Cloud. Call the browser_login tool (it opens the browser to approve), then retry.'
LOGIN_WAIT_SECONDS = 45.0
LOGIN_NEXT = 'Start a cloud browser with start_remote_daemon("<name>") in browser_exec.'
CLOUD_TIMEOUT_MINUTES = 30  # default lifetime of a cloud browser this server starts; start_remote_daemon(timeout=) overrides

MCP_GUIDE = f"""# This MCP server

These rules override the skill below where they differ:
- Code runs in browser_exec; there is no shell, so ignore `BU_NAME=... browser-use <<'PY'` examples.
- Local: without a cloud browser, browser_exec drives the user's own Chrome (the default daemon).
- Cloud: `start_remote_daemon("work")` (call browser_login first if not signed in). Every later browser_exec and
  browser_screenshot drives that cloud browser; never pass BU_NAME. One cloud browser at a time per server.
- It lives {CLOUD_TIMEOUT_MINUTES} minutes unless you pass `timeout=<minutes>` (up to 240), and this server stops it when it
  exits. Once it ends, calls fail with an error: start a new one, never fall back to the local Chrome.
- The live view and CDP URLs grant control of the browser, so they are not shown. Only if the user asks to watch, run
  `os.environ["BH_OPEN_LIVE_URL"] = "1"` before start_remote_daemon: the live view then opens in their browser, and
  both are returned.

"""

# Runs detached for each cloud browser this server starts. Its stdin is a pipe only this server holds: the read
# returns at EOF, when the server exits however it ends (stdin closed, SIGTERM, SIGKILL), and it stops that browser.
_REAPER = (
	'import sys\n'
	'sys.stdin.buffer.read()\n'
	'from browser_use.harness_cloud import stop_cloud\n'
	'stop_cloud(sys.argv[1], sys.argv[2])\n'
)


def _open_url(url: str) -> bool:
	"""Open url in the user's browser without letting a child process write to stdout (the MCP channel)."""
	command = {'darwin': ['open', url], 'linux': ['xdg-open', url]}.get(sys.platform)
	if command is None:
		try:
			return bool(webbrowser.open(url))
		except Exception:
			return False
	try:
		subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
		return True
	except OSError:
		return False


class _Login:
	"""One browser OAuth login (browser-harness's flow and key store), finishing in a thread across tool calls."""

	def __init__(self):
		from browser_harness import auth

		os.environ.setdefault('BH_DEVICE_NAME', 'browser-use-mcp')
		harden_login_callback()
		set_aside_corrupt_store()  # a corrupt key store would make saving the new key fail after the user approved
		self.start = auth.start_browser_auth(open_url=False)
		self.opened = _open_url(self.start.auth_url)
		self.error: str | None = None
		self.thread = threading.Thread(target=self._finish, daemon=True, name='browser-use-login')
		self.thread.start()

	def _finish(self) -> None:
		from browser_harness import auth

		try:
			auth.complete_browser_auth(self.start)
		except Exception as e:  # AuthError: denied, timed out, exchange failed
			self.error = str(e)


def _harness_skill_text() -> str:
	from browser_use.skills.browser_use import skill_text

	return skill_text()


class CLIMCPServer:
	"""Stateful stdio MCP server wrapping the browser-harness exec model."""

	def __init__(self):
		self.server: Server = Server(
			'browser-use',
			version=get_browser_use_version(),
			instructions=self._instructions(),
		)
		self._namespace: dict[str, Any] | None = None
		self._exec_lock = asyncio.Lock()
		self._login: _Login | None = None
		self._login_lock = threading.Lock()
		self._remote: str | None = None  # the cloud daemon this server started; browser_exec drives it
		self._reapers: list[subprocess.Popen] = []  # held open so the pipes close only when this process exits
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
					'should be new_tab(url). Drives the local Chrome until start_remote_daemon("<name>") starts a '
					'cloud browser; then every call drives that one until it ends (stopped when this server exits).'
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
			types.Tool(
				name='browser_login',
				description=(
					"Sign in to Browser Use Cloud for cloud browsers (start_remote_daemon). Opens the user's browser "
					'to approve; the key is stored for browser-use, browser-harness and this server, never shown. '
					'Returns once signed in, or with the URL to approve: call it again to finish.'
				),
				input_schema={
					'type': 'object',
					'properties': {
						'force': {
							'type': 'boolean',
							'description': 'Sign in again even if a key is stored (the stored key was rejected)',
							'default': False,
						},
					},
				},
			),
		]

	def _register_handlers(self):
		async def handle_list_tools(_context: Any, _params: types.PaginatedRequestParams) -> types.ListToolsResult:
			return types.ListToolsResult(tools=self._tool_definitions())

		async def handle_call_tool(_context: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
			name = params.name
			arguments = params.arguments or {}
			if name == 'browser_exec':
				code = arguments.get('code')
				if not isinstance(code, str) or not code.strip():
					return types.CallToolResult(
						content=[types.TextContent(type='text', text="Error: 'code' must be a non-empty string")],
						is_error=True,
					)
				async with self._exec_lock:
					output = await asyncio.to_thread(self._execute, code)
				return types.CallToolResult(content=[types.TextContent(type='text', text=output or '(no output)')])
			if name == 'browser_screenshot':
				max_dim = arguments.get('max_dim')
				if max_dim is not None and (isinstance(max_dim, bool) or not isinstance(max_dim, int) or max_dim < 1):
					return types.CallToolResult(
						content=[types.TextContent(type='text', text="Error: 'max_dim' must be a positive integer")],
						is_error=True,
					)
				async with self._exec_lock:
					try:
						png = await asyncio.to_thread(self._screenshot, bool(arguments.get('full', False)), max_dim)
					except CloudBrowserError as e:
						return types.CallToolResult(content=[types.TextContent(type='text', text=f'Error: {e}')], is_error=True)
				content: list[types.ContentBlock] = [types.ImageContent(type='image', data=png, mime_type='image/png')]
				return types.CallToolResult(content=content)
			if name == 'browser_login':
				text = await asyncio.to_thread(self._sign_in, bool(arguments.get('force', False)))
				return types.CallToolResult(content=[types.TextContent(type='text', text=text)])
			return types.CallToolResult(
				content=[types.TextContent(type='text', text=f'Unknown tool: {name}')],
				is_error=True,
			)

		self.server.add_request_handler('tools/list', types.PaginatedRequestParams, handle_list_tools)
		self.server.add_request_handler('tools/call', types.CallToolRequestParams, handle_call_tool)

	def _ensure_namespace(self) -> dict[str, Any]:
		if self._namespace is None:
			ns: dict[str, Any] = {}
			exec(_NAMESPACE_IMPORTS, ns)
			harness_cloud.install(ns)
			ns['start_remote_daemon'] = self._start_remote
			self._namespace = ns
		return self._namespace

	def _ensure_daemon(self, code: str) -> None:
		"""Mirror run.py: daemon must be up before helpers run, except for code that starts or stops a cloud browser
		(anywhere in it: attaching first would attach the user's Chrome)."""
		self._ensure_namespace()
		if not harness_cloud.calls_cloud_admin(code):
			harness_cloud.ensure_daemon()

	def _start_remote(self, name: str = 'remote', profileName: str | None = None, **create_kwargs: Any) -> dict:
		if self._remote and self._remote != name and admin.daemon_alive(self._remote):
			raise CloudBrowserError(
				f'This server already drives cloud browser {self._remote!r}: stop_remote_daemon({self._remote!r}) first.'
			)
		create_kwargs.setdefault('timeout', CLOUD_TIMEOUT_MINUTES)
		browser = harness_cloud.start(name, profileName, create_kwargs, self._namespace)
		self._remote = name
		if browser.get('id'):
			detach: dict[str, Any] = ipc.spawn_kwargs()  # own session: a Ctrl-C to this server's group does not kill it first
			self._reapers.append(
				subprocess.Popen(
					[sys.executable, '-P', '-c', _REAPER, name, browser['id']],  # -P: never import from the cwd
					stdin=subprocess.PIPE,
					stdout=subprocess.DEVNULL,
					stderr=subprocess.DEVNULL,
					**detach,
				)
			)
		return browser

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
			except CloudAuthRequired:  # its own message names `browser-harness auth login`, not this server's tool
				print(LOGIN_HINT, file=buffer)
			except CloudBrowserError as e:
				print(f'Error: {e}', file=buffer)
			except BaseException:
				traceback.print_exc(file=buffer)
		return buffer.getvalue()

	def _sign_in(self, force: bool, wait: float = LOGIN_WAIT_SECONDS) -> str:
		"""Start (or keep waiting on) one browser login. The key never appears in the result."""
		from browser_harness import auth

		with self._login_lock:
			login = self._login
			if login is not None and not login.thread.is_alive():  # finished since the last call: report it once
				self._login = login = None if login.error is None else login
			if login is None:
				try:
					status = auth.auth_status()
				except Exception as e:  # an unreadable auth file
					status = {'status': 'error', 'reason': str(e)}
				if status.get('source') == 'env':
					if not force:
						return f'Signed in to Browser Use Cloud (key from BROWSER_USE_API_KEY). {LOGIN_NEXT}'
					return 'BROWSER_USE_API_KEY is set for this server and wins over a stored key: fix or unset it in the MCP config.'
				if status.get('status') == 'authenticated' and not force:
					return f'Signed in to Browser Use Cloud (key from {status.get("path")}). {LOGIN_NEXT}'
				try:
					login = self._login = _Login()
				except Exception as e:  # network error, auth server refused the request
					return f'Could not start Browser Use Cloud login: {e}'
		login.thread.join(wait)
		if login.thread.is_alive():
			how = 'in the browser tab that just opened' if login.opened else 'by opening this URL in a browser'
			return (
				f'Waiting for the user to approve Browser Use {how}: {login.start.auth_url}\n'
				'Call browser_login again after approving. No browser on this machine? Run `browser-use login --device-code` '
				'in a terminal instead.'
			)
		with self._login_lock:
			if self._login is login:
				self._login = None
		if login.error:
			return f'Browser Use Cloud login failed: {login.error}. Call browser_login to try again.'
		return f'Signed in to Browser Use Cloud. {LOGIN_NEXT}'

	def _screenshot(self, full: bool, max_dim: int | None) -> str:
		buffer = StringIO()
		with redirect_stdout(buffer), redirect_stderr(buffer):
			ns = self._ensure_namespace()
			harness_cloud.ensure_daemon()
			path = ns['capture_screenshot'](full=full, max_dim=max_dim)
		with open(path, 'rb') as f:
			return base64.b64encode(f.read()).decode()

	def _instructions(self) -> str:
		return MCP_GUIDE + _harness_skill_text()

	async def run(self):
		if sys.stdin is None:
			raise RuntimeError('MCP stdio transport requires stdin, but this process was launched without one.')

		async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
			try:
				await self.server.run(
					read_stream,
					write_stream,
					self.server.create_initialization_options(),
				)
			except BrokenPipeError:
				pass


async def main():
	os.environ.setdefault('BH_CLIENT', 'browser-use-mcp')
	server = CLIMCPServer()
	await server.run()


if __name__ == '__main__':
	asyncio.run(main())
