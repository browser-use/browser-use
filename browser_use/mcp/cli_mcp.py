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
from browser_use.exceptions import removed
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
OLD_TOOLS = {  # the 0.x browser-use --mcp server's tools (it ran the removed engine); browser_screenshot is kept
	'browser_navigate', 'browser_click', 'browser_type', 'browser_get_state', 'browser_extract_content',
	'browser_get_html', 'browser_scroll', 'browser_go_back', 'browser_list_tabs', 'browser_switch_tab',
	'browser_close_tab', 'retry_with_browser_use_agent', 'browser_list_sessions', 'browser_close_session',
	'browser_close_all',
}  # fmt: skip
OLD_TOOL_HINT = 'browser_exec runs Python with the browser-harness helpers (goto_url, click_at_xy, js, list_tabs, ...).'
CLOUD_TIMEOUT_MINUTES = 30  # default lifetime of a cloud browser this server starts; start_remote_daemon(timeout=) overrides

MCP_GUIDE = f"""# This MCP server

These rules override the skill below where they differ:
- Code runs in browser_exec; there is no shell, so ignore `BU_NAME=... browser-use <<'PY'` examples.
- Local: without a cloud browser, browser_exec drives the user's own Chrome (the default daemon).
- Cloud: `start_remote_daemon("work")` (call browser_login first if not signed in). Every later browser_exec and
  browser_screenshot drives that cloud browser; never pass BU_NAME. One cloud browser at a time per server.
- It lives {CLOUD_TIMEOUT_MINUTES} minutes unless you pass `timeout=<minutes>` (up to 240), and this server stops it when it
  exits. Once it ends, calls fail with an error: start a new one, never fall back to the local Chrome.
- Code runs in this server's process: it can read the server's environment (BROWSER_USE_API_KEY when set) and files.
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
		self._jobs: set[asyncio.Task] = set()  # _locked() calls: kept referenced while they run
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
					'cloud browser; then every call drives that one until it ends (stopped when this server exits). '
					"A cloud browser's downloads stay on the remote host, never in ~/Downloads (a file there is not its "
					'download): GET https://api.browser-use.com/api/v4/browsers/{id}/downloads lists them.'
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
				output, failed = await self._locked(self._execute, code)
				return types.CallToolResult(
					content=[types.TextContent(type='text', text=output or '(no output)')], is_error=failed
				)
			if name == 'browser_screenshot':
				max_dim = arguments.get('max_dim')
				if max_dim is not None and (isinstance(max_dim, bool) or not isinstance(max_dim, int) or max_dim < 1):
					return types.CallToolResult(
						content=[types.TextContent(type='text', text="Error: 'max_dim' must be a positive integer")],
						is_error=True,
					)
				try:
					png = await self._locked(self._screenshot, bool(arguments.get('full', False)), max_dim)
				except CloudBrowserError as e:
					return types.CallToolResult(content=[types.TextContent(type='text', text=f'Error: {e}')], is_error=True)
				content: list[types.ContentBlock] = [types.ImageContent(type='image', data=png, mime_type='image/png')]
				return types.CallToolResult(content=content)
			if name == 'browser_login':
				text = await asyncio.to_thread(self._sign_in, bool(arguments.get('force', False)))
				return types.CallToolResult(content=[types.TextContent(type='text', text=text)])
			text = removed(f'The MCP tool {name} (the 0.x browser-use --mcp server)', OLD_TOOL_HINT) if name in OLD_TOOLS else ''
			return types.CallToolResult(
				content=[types.TextContent(type='text', text=text or f'Unknown tool: {name}')],
				is_error=True,
			)

		self.server.add_request_handler('tools/list', types.PaginatedRequestParams, handle_list_tools)
		self.server.add_request_handler('tools/call', types.CallToolRequestParams, handle_call_tool)

	async def _locked(self, fn: Any, *args: Any) -> Any:
		"""fn(*args) in a thread, one at a time. A call the client cancels (its timeout) keeps the lock until its thread
		ends: the thread cannot be stopped, and the next call's output capture would otherwise collect its prints.
		The lock is held by a task of its own: the MCP SDK cancels a request through an AnyIO cancel scope, which cancels
		every await of the request's task again, so a wait there would end early and release the lock. A call cancelled
		before it got the lock never runs."""
		abandoned = False

		async def job() -> Any:
			async with self._exec_lock:
				if abandoned:
					raise asyncio.CancelledError
				return await asyncio.to_thread(fn, *args)

		task = asyncio.ensure_future(job())
		self._jobs.add(task)
		task.add_done_callback(self._jobs.discard)
		task.add_done_callback(lambda t: t.cancelled() or t.exception())  # an abandoned call's error is never awaited
		try:
			return await asyncio.shield(task)
		except asyncio.CancelledError:
			abandoned = True
			raise

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

	def _execute(self, code: str, connect: bool = True) -> tuple[str, bool]:
		"""Run code in the persistent namespace, capturing stdout/stderr. Returns (output, whether it failed): a
		failure is the tool result's is_error, not only a traceback in its text.

		Runs in a worker thread: harness helpers are synchronous socket IPC. Output is
		captured because stdout carries the MCP protocol.
		"""
		buffer, failed = StringIO(), True
		with redirect_stdout(buffer), redirect_stderr(buffer):
			try:
				ns = self._ensure_namespace()
				if connect:
					self._ensure_daemon(code)
				exec(code, ns)
				failed = False
			except CloudAuthRequired:  # its own message names `browser-harness auth login`, not this server's tool
				print(LOGIN_HINT, file=buffer)
			except CloudBrowserError as e:
				print(f'Error: {e}', file=buffer)
			except BaseException:
				traceback.print_exc(file=buffer)
		return buffer.getvalue(), failed

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
			# print() from a thread model code started, outside any call, sat in sys.stdout's buffer and was flushed
			# onto the restored protocol stream at exit, corrupting it: such output goes to stderr instead.
			stdout, sys.stdout = sys.stdout, sys.stderr
			try:
				await self.server.run(
					read_stream,
					write_stream,
					self.server.create_initialization_options(),
				)
			except BrokenPipeError:
				pass
			finally:
				sys.stdout = stdout


async def main():
	os.environ.setdefault('BH_CLIENT', 'browser-use-mcp')
	server = CLIMCPServer()
	await server.run()


if __name__ == '__main__':
	asyncio.run(main())
