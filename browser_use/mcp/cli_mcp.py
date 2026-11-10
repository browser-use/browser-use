"""MCP server exposing the CLI 3.0
Run with: browser-use --cli-mcp
"""

import asyncio
import base64
import contextvars
import functools
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import webbrowser
from contextlib import contextmanager
from io import StringIO
from typing import Any

import browser_harness
import mcp.server.stdio
import mcp.types as types
from browser_harness import _ipc as ipc
from browser_harness.auth import CloudAuthRequired
from mcp.server import Server

import browser_use
from browser_use import Browser, harness_cloud
from browser_use.auth import browser_use_api_key, harden_login_callback, set_aside_corrupt_store
from browser_use.browser.browser import _name_daemon_files
from browser_use.domains import DomainRules
from browser_use.exceptions import removed
from browser_use.harness_cloud import CloudBrowserError
from browser_use.repl.capture import install as install_capture
from browser_use.repl.page_info import install as install_page_info
from browser_use.repl.session import MAX_OUTPUT_CHARS, clip
from browser_use.utils import get_browser_use_version

_NAMESPACE_IMPORTS = (
	'from browser_harness.admin import ('
	'daemon_alive, ensure_daemon, restart_daemon, start_remote_daemon, stop_remote_daemon)\n'
	'from browser_harness.helpers import *\n'
)


_INTERNAL = tuple(os.path.dirname(m.__file__ or '') + os.sep for m in (browser_harness, browser_use))

LOGIN_HINT = 'Not signed in to Browser Use Cloud. Call the browser_login tool (it opens the browser to approve), then retry.'
LOGIN_WAIT_SECONDS = 45.0
LOGIN_NEXT = 'Start a cloud browser with start_remote_daemon() in browser_exec.'
OLD_TOOLS = {  # the 0.x browser-use --mcp server's tools (it ran the removed engine); browser_screenshot is kept
	'browser_navigate', 'browser_click', 'browser_type', 'browser_get_state', 'browser_extract_content',
	'browser_get_html', 'browser_scroll', 'browser_go_back', 'browser_list_tabs', 'browser_switch_tab',
	'browser_close_tab', 'retry_with_browser_use_agent', 'browser_list_sessions', 'browser_close_session',
	'browser_close_all',
}  # fmt: skip
OLD_TOOL_HINT = 'browser_exec runs Python with the browser-harness helpers (goto_url, click_at_xy, js, list_tabs, ...).'
CLOUD_TIMEOUT_MINUTES = 30  # default lifetime of a cloud browser this server starts; start_remote_daemon(timeout=) overrides
INSTALL_TIMEOUT_S = 600  # Playwright's Chromium (~150 MB) and, as root on Linux, its system libraries
NO_CLOUD_WITH_DOMAINS = (
	"{name}() is off: this server's allowed_domains / prohibited_domains hold only on its own Chromium, and a cloud "
	'browser would open any site'
)

MCP_GUIDE = f"""# This MCP server

These rules override the skill below where they differ:
- Code runs in browser_exec; there is no shell, so ignore `BU_NAME=... browser-use <<'PY'` examples.
- Local: without a cloud browser, browser_exec drives {{local}}.
- Cloud: `start_remote_daemon()` (call browser_login first if not signed in). Every later browser_exec and
  browser_screenshot drives that cloud browser; never pass BU_NAME. One cloud browser per server, under a name only it
  uses: a name passed to start_remote_daemon / stop_remote_daemon is ignored.
- It lives {CLOUD_TIMEOUT_MINUTES} minutes unless you pass `timeout=<minutes>` (up to 240), and this server stops it when it
  exits. Once it ends, calls fail with an error: start a new one, never fall back to the local Chrome.
- Code runs in this server's process: it can read the server's environment (BROWSER_USE_API_KEY when set) and files.
- The live view and CDP URLs grant control of the browser, so they are not shown. Only if the user asks to watch, run
  `os.environ["BH_OPEN_LIVE_URL"] = "1"` before start_remote_daemon: the live view then opens in their browser, and
  both are returned.

"""

# Runs detached for each cloud browser this server starts, and stops that browser once the server exits however it ends
# (stdin closed, SIGTERM, SIGKILL). POSIX: its stdin is a pipe only this server holds, and the read returns at EOF.
# Windows: the mcp client puts the server in a Job Object it kills whole once the server exits or the client dies, so the
# reaper starts outside it (_spawn_outside_job) and waits on the server's process (BU_CLEANUP_PID). A process created
# after BU_CLEANUP_SINCE reused that pid: the server is gone. Whenever it cannot tell, it exits and stops nothing.
# The browser id comes in the environment, never argv: it drives the browser without a key, and argv is in any local
# user's ps.
_REAPER = (
	'import os, sys\n'
	"if os.environ.get('BU_CLEANUP_PID'):\n"
	'\timport ctypes\n'
	"\tk = ctypes.WinDLL('kernel32', use_last_error=True)\n"
	'\tk.OpenProcess.restype = ctypes.c_void_p\n'
	'\tk.GetProcessTimes.argtypes = [ctypes.c_void_p] * 5\n'
	'\tk.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]\n'
	"\th, t = k.OpenProcess(0x101000, False, int(os.environ['BU_CLEANUP_PID'])), (ctypes.c_uint64 * 4)()\n"
	'\tif not h:\n'
	'\t\tif ctypes.get_last_error() != 87: sys.exit()\n'  # 87: no such process
	'\telif not k.GetProcessTimes(h, *(ctypes.addressof(t) + 8 * i for i in range(4))): sys.exit()\n'
	"\telif t[0] / 1e7 - 11644473600 < float(os.environ['BU_CLEANUP_SINCE']):\n"
	'\t\tif k.WaitForSingleObject(h, 0xFFFFFFFF) != 0: sys.exit()\n'
	'else:\n'
	'\tsys.stdin.buffer.read()\n'
	'from browser_use.harness_cloud import stop_cloud\n'
	'from browser_use.utils import install_tls_opener; install_tls_opener()\n'
	"stop_cloud(sys.argv[1], os.environ['BU_CLEANUP_BROWSER_ID'])\n"
)


def _spawn_outside_job(args: list[str], env: dict[str, str]) -> bool:
	"""Windows: start args through WMI, which creates the process outside this one's Job Object (CreateProcess with
	CREATE_BREAKAWAY_FROM_JOB is refused: the mcp client's job does not allow breakaway). env is its whole environment.
	Whether it started; False also where WMI is unavailable or blocked."""
	try:
		import pythoncom
		import win32com.client

		pythoncom.CoInitialize()  # a worker thread runs the cell
		wmi = win32com.client.GetObject(r'winmgmts:\\.\root\cimv2')
		startup = wmi.Get('Win32_ProcessStartup').SpawnInstance_()
		startup.Properties_.Item('ShowWindow').Value = 0  # SW_HIDE: no console window
		startup.Properties_.Item('EnvironmentVariables').Value = [f'{k}={v}' for k, v in env.items()]
		process = wmi.Get('Win32_Process')
		params = process.Methods_('Create').InParameters.SpawnInstance_()
		params.Properties_.Item('CommandLine').Value = subprocess.list2cmdline(args)
		params.Properties_.Item('ProcessStartupInformation').Value = startup
		return process.ExecMethod_('Create', params).Properties_.Item('ReturnValue').Value == 0
	except Exception:
		return False


_cell = threading.local()  # .buffer: where the cell running on this thread prints
# The (exception class, message) of each failure in the tool call in progress (telemetry): asyncio.to_thread runs
# _execute in a copy of the call's context, which holds this same list
_call_errors: contextvars.ContextVar[list[tuple[str, str]] | None] = contextvars.ContextVar(
	'browser_use_mcp_errors', default=None
)
TOOLS = ('browser_exec', 'browser_screenshot', 'browser_login')


def _error_class(e: BaseException) -> str:
	"""The exception's class for telemetry, and its message unless the cell's own code raised it: Claude's code raises
	with what it typed or read from the page (`assert name in text, f'{name} missing'`), which no scrub can know."""
	from browser_use.telemetry.stats import error_class, raised_by_cell

	errors = _call_errors.get()
	name = error_class(e)
	if errors is not None:
		try:
			message = '' if raised_by_cell(e) else str(e)[:4096]
		except Exception:  # - a __str__ that raises
			message = ''
		errors.append((name, message))
	return name


def _print_cell_traceback(e: BaseException, file: StringIO) -> None:
	"""The traceback from the cell's first frame (this server's exec() frame is noise to the model) to the last frame
	outside browser-harness and browser-use: their internals (js() -> _js_evaluate -> _runtime_value) say nothing the
	exception line does not."""
	tb = e.__traceback__.tb_next if e.__traceback__ else None
	files, t = [], tb
	while t is not None:
		files.append(t.tb_frame.f_code.co_filename)
		t = t.tb_next
	limit = len(files)
	while limit > 1 and files[limit - 1].startswith(_INTERNAL):
		limit -= 1
	traceback.print_exception(type(e), e, tb, limit=limit or None, file=file)


class NoBrowserError(RuntimeError):
	"""Nothing to drive: no Chrome to attach and the server's own Chromium could not start. One line, with the fix."""


def _no_chrome_here() -> str | None:
	"""Why --cli-mcp cannot use the user's Chrome on this machine, or None when it can (maybe after the chrome://inspect
	setup): no Chrome is attachable, and that setup needs a display and an installed Chrome, Chromium or Edge (Playwright's
	Chromium is not one a user sets up). A BU_CDP_URL / BU_CDP_WS is always used as given."""
	from browser_harness import admin, daemon

	from browser_use.browser import local

	if not admin._is_local_chrome_mode() or local.live_debug_dirs():
		return None
	if not local.has_display():
		why = 'no display here to turn on remote debugging in a Chrome'
	elif any((base / 'Local State').is_file() for base in daemon.PROFILES):
		return None  # a browser browser-harness attaches once set up, find_binary or not: Brave, Arc, a Flatpak Chrome
	else:
		try:
			if local.find_binary() not in local.playwright_chromium():
				return None
			why = 'no Chrome, Chromium or Edge is installed'
		except RuntimeError as e:  # none installed, or only Snap Chromium
			why = 'no Chrome, Chromium or Edge is installed'
			if 'Snap Chromium' in str(e):
				why = 'only Snap Chromium is installed, which cannot be attached'
	try:
		admin.require_existing_daemon()  # a daemon already attached (an orchestrator's BU_CDP_WS): browser-harness reuses it
		return None
	except Exception:
		return why


def _install_chromium() -> float:
	"""`browser-use install` for a machine with no browser at all (a fresh server or container): Playwright's Chromium, and
	as root on Linux its system libraries. Its output never reaches stdout (the MCP channel). Returns the seconds it took;
	raises why it could not."""
	uvx = shutil.which('uvx')
	if not uvx:
		raise RuntimeError('no Chrome or Chromium is installed, and uvx (to install Chromium) is not on PATH')
	steps = [[uvx, 'playwright', 'install', 'chromium', '--no-shell']]
	if sys.platform.startswith('linux') and os.geteuid() == 0:
		steps[0].append('--with-deps')
		if apt := shutil.which('apt-get'):  # Playwright's own node needs libatomic1, which slim images (python:*-slim) lack
			steps[:0] = [[apt, 'update', '-qq'], [apt, 'install', '-y', '-qq', '--no-install-recommends', 'libatomic1']]
	started, env = time.monotonic(), {**os.environ, 'DEBIAN_FRONTEND': 'noninteractive'}
	for cmd in steps:
		try:
			r = subprocess.run(
				cmd,
				stdin=subprocess.DEVNULL,
				capture_output=True,
				text=True,
				errors='replace',
				env=env,
				timeout=INSTALL_TIMEOUT_S,
			)
		except (OSError, subprocess.TimeoutExpired) as e:
			raise RuntimeError(f'installing Chromium failed: {e}') from None
		if r.returncode:
			last = next((line.strip() for line in reversed((r.stdout + r.stderr).splitlines()) if line.strip()), '')
			raise RuntimeError(f'`{" ".join([os.path.basename(cmd[0]), *cmd[1:]])}` failed (exit {r.returncode}): {last[-300:]}')
	return time.monotonic() - started


def _cloud_hint() -> str:
	"""The way to a cloud browser: start_remote_daemon() only when a key is there for it to use."""
	try:
		browser_use_api_key()
		return 'start a cloud browser: start_remote_daemon()'
	except RuntimeError:  # MissingAPIKeyError, or a corrupt key store
		return "set BROWSER_USE_API_KEY in this MCP server's env (or call browser_login) for a Browser Use Cloud browser"


class _CellStream:
	"""Stands in for sys.stdout/sys.stderr: a cell's thread prints into its own buffer, any other thread into stream
	(while serving: stderr). So prints from threads a cell starts are not in its result (the browser_exec description
	says so): per-thread capture is what lets a hung cell's prints never land in the next call's result."""

	def __init__(self, stream: Any):
		self.stream = stream

	def __getattr__(self, name: str) -> Any:
		return getattr(getattr(_cell, 'buffer', None) or self.stream, name)


@contextmanager
def _capture(buffer: StringIO):
	"""redirect_stdout/redirect_stderr for this thread only: a cell the client gave up on keeps printing into its own
	buffer, never into the next call's."""
	for name in ('stdout', 'stderr'):
		if not isinstance(getattr(sys, name), _CellStream):
			setattr(sys, name, _CellStream(getattr(sys, name)))
	_cell.buffer = buffer
	try:
		yield
	finally:
		_cell.buffer = None


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


def _refusing(fn: Any, rules: DomainRules) -> Any:
	"""fn(url, ...) raising the one-line refusal the agent's helpers give (repl/worker.py) for a URL rules block. The
	browser blocks it anyway, but new_tab() then returned success and the next call failed naming nothing."""

	@functools.wraps(fn)
	def checked(*args: Any, **kwargs: Any) -> Any:
		if why := rules.blocked(str(args[0] if args else kwargs.get('url', 'about:blank'))):
			raise PermissionError(why)
		return fn(*args, **kwargs)

	return checked


def _local_http_get(rules: DomainRules | None) -> Any:
	"""The agent's http_get (repl/worker.py): plain HTTP from this machine, every redirect hop checked against rules.
	browser-harness's sent the URL and headers (Authorization, cookies) to the fetch-use proxy whenever
	BROWSER_USE_API_KEY was set, and followed a redirect from an allowed host to any host. Its own opener, not
	install_opener: this process's cloud, login and telemetry calls use urllib too."""
	from browser_use.repl import worker

	def check(url: str) -> None:
		if rules and (why := rules.blocked(str(url))):
			raise PermissionError(why)

	opener = worker.redirect_checking_opener(check)

	def http_get(url: str, headers: dict | None = None, timeout: float = 20.0) -> str | bytes:
		return worker._http_get(url, headers, timeout, opener.open)

	http_get.__doc__ = worker.http_get.__doc__
	return _refusing(http_get, rules) if rules else http_get


def _refuse_cloud(name: str, *args: Any, **kwargs: Any) -> Any:
	raise PermissionError(NO_CLOUD_WITH_DOMAINS.format(name=name))


def _harness_skill_text() -> str:
	from browser_use.skills.browser_use import skill_text

	return skill_text()


class CLIMCPServer:
	"""Stateful stdio MCP server wrapping the browser-harness exec model."""

	def __init__(self, own_browser: bool = False, **browser_options: Any):
		_name_daemon_files()  # with BH_RUNTIME_DIR set, its cloud daemon and the local one would share one bu.sock
		# --mcp (0.x configs): a Chromium of its own on a temp profile, as the 0.x server ran, with its config's
		# allowed_domains / prohibited_domains (cli._mcp_browser_options); --cli-mcp: the user's Chrome, or a Chromium
		# of its own where none can be used (_no_chrome_here)
		self._own_browser = own_browser
		self._browser = Browser('chromium', **browser_options) if own_browser else None
		self._fallback: str | None = None  # why --cli-mcp runs its own Chromium instead of the user's Chrome
		self._own_started = False  # the own Chromium started once: later failures are its own, not "no browser"
		self._install_tried = False
		self._installed: float | None = None  # seconds _install_chromium took, until announced
		self._announced: str | None = None  # the browser the last browser_exec result named
		self._note: str | None = None  # the browser now in use, for the next browser_exec result's second block
		self.server: Server = Server(
			'browser-use',
			version=get_browser_use_version(),
			instructions=self._instructions(),
		)
		self._namespace: dict[str, Any] | None = None
		self._exec_lock = asyncio.Lock()
		self._login: _Login | None = None
		self._login_lock = threading.Lock()
		# _attach from a cell the client gave up on and from the next call: one Browser.start() at a time (its asyncio
		# lock binds to one event loop, and each thread runs its own)
		self._attach_lock = threading.Lock()
		self._remote = f'mcp-{os.getpid()}'  # this server's cloud daemon name: no other server or CLI shares it
		# set once start_remote_daemon ran here; not the .cloud marker, which an earlier server with this pid may have left
		self._cloud_started = False
		self._reapers: list[subprocess.Popen] = []  # held open so the pipes close only when this process exits
		self._calls = 0  # tool calls served (telemetry call_n)
		self._register_handlers()

	def _tool_definitions(self) -> list[types.Tool]:
		return [
			types.Tool(
				name='browser_exec',
				description=(
					'Execute Python in the browser-harness session. Helpers like new_tab(url), '
					'goto_url(url), page_info(), click_at_xy(x, y), type_text(text), js(code), '
					'cdp(method, ...), wait_for_load(), list_tabs() are pre-imported. The namespace '
					'persists across calls. Returns whatever the code prints (prints from threads it starts are not '
					'returned: collect their results and print them in the code itself). First navigation '
					'should be new_tab(url). Drives the local Chrome (the first result names it) until '
					'start_remote_daemon() starts a cloud browser; then every call drives that one until it ends '
					'(stopped when this server exits). '
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
			errors: list[tuple[str, str]] = []
			token = _call_errors.set(errors)
			started, result = time.monotonic(), None
			try:
				result = await call_tool(params.name, params.arguments or {})
				return result
			except BaseException as e:  # a cancelled call (the client's timeout): CancelledError
				_error_class(e)
				raise
			finally:
				_call_errors.reset(token)
				self._record_call(params.name, result, errors, time.monotonic() - started)

		async def call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
			if name == 'browser_exec':
				code = arguments.get('code')
				if not isinstance(code, str) or not code.strip():
					return types.CallToolResult(
						content=[types.TextContent(type='text', text="Error: 'code' must be a non-empty string")],
						is_error=True,
					)
				output, failed = await self._locked(self._execute, code)
				note, self._note = self._note, None
				if len(output) > MAX_OUTPUT_CHARS:  # same cap as the agent's cells; the full text stays readable on disk
					# utf-8: Windows' locale encoding (cp1252) failed the whole call on an emoji, after the cell ran; newline='':
					# the file holds the output as captured (Windows wrote each \n as \r\n)
					with tempfile.NamedTemporaryFile(
						'w', encoding='utf-8', errors='replace', newline='', prefix='browser_exec_', suffix='.txt', delete=False
					) as f:
						f.write(output)
					output = clip(output, f.name)
				content = [types.TextContent(type='text', text=output or '(no output)')]
				if note:  # its own block: a client that parses the code's output (JSON) gets only that in the first
					content.append(types.TextContent(type='text', text=note))
				return types.CallToolResult(content=content, is_error=failed)
			if name == 'browser_screenshot':
				max_dim = arguments.get('max_dim')
				if max_dim is not None and (isinstance(max_dim, bool) or not isinstance(max_dim, int) or max_dim < 1):
					return types.CallToolResult(
						content=[types.TextContent(type='text', text="Error: 'max_dim' must be a positive integer")],
						is_error=True,
					)
				try:
					png = await self._locked(self._screenshot, bool(arguments.get('full', False)), max_dim)
				except Exception as e:  # a tool result the model reads, never a JSON-RPC error
					_error_class(e)
					return types.CallToolResult(content=[types.TextContent(type='text', text=self._error(e))], is_error=True)
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

	def _record_call(self, name: str, result: types.CallToolResult | None, errors: list[tuple[str, str]], seconds: float) -> None:
		"""One mcp_server_event per tool call: queued, sent by the telemetry thread; never fails a call."""
		self._calls += 1
		try:
			from browser_harness import telemetry as harness_telemetry

			from browser_use.telemetry.service import telemetry
			from browser_use.telemetry.stats import MAX_ERROR, is_internal, scrub
			from browser_use.telemetry.views import MCPToolCallEvent

			if not telemetry().enabled:
				return
			if not errors and result is not None and result.is_error:  # no exception: rejected arguments, an unknown tool
				text = next((c.text for c in result.content if isinstance(c, types.TextContent)), '') if name in TOOLS else ''
				errors = [('invalid_arguments' if name in TOOLS else 'unknown_tool', text.removeprefix('Error: '))]
			detect = getattr(harness_telemetry, '_detect_agent_client', None)
			event = MCPToolCallEvent(
				version=get_browser_use_version(),
				tool_name=name if name in TOOLS or name in OLD_TOOLS else 'invalid',
				duration_seconds=round(seconds, 3),
				ok=result is not None and not result.is_error,
				error_type=errors[0][0] if errors else None,
				server='mcp' if self._own_browser else 'cli-mcp',
				browser='cloud' if self._cloud_started else 'chromium' if self._browser is not None else 'chrome',
				agent_client=detect() if detect else None,
				call_n=self._calls,
				is_internal=is_internal(),
				error_message=scrub(errors[0][1], [], MAX_ERROR) or None if errors else None,
			)
			telemetry().capture(event)
		except Exception:  # - telemetry never breaks a tool call
			pass

	async def _locked(self, fn: Any, *args: Any) -> Any:
		"""fn(*args) in a thread, one at a time. A call the client cancels (its timeout) lets go of the lock at once: its
		thread cannot be stopped and runs on, printing into its own buffer, but a hung cell never blocks the calls after
		it (stop_remote_daemon among them). A call cancelled before it got the lock never runs."""
		async with self._exec_lock:
			return await asyncio.to_thread(fn, *args)

	def _ensure_namespace(self) -> dict[str, Any]:
		if self._namespace is None:
			ns: dict[str, Any] = {}
			install_page_info()  # cli-1: before the * import binds page_info
			install_capture()  # win-cli-5: capture_screenshot() of a hidden tab activates it after a short try
			exec(_NAMESPACE_IMPORTS, ns)
			harness_cloud.install(ns)
			ns['start_remote_daemon'] = self._start_remote
			ns['stop_remote_daemon'] = lambda name=None: harness_cloud.stop(self._remote)
			rules = self._browser.domains if self._browser is not None else None  # --mcp with a 0.x config's domains
			if rules:
				for name in ('new_tab', 'goto_url'):
					ns[name] = _refusing(ns[name], rules)
				for name in harness_cloud.CLOUD_ADMIN:  # a cloud browser has no Guard: it would go anywhere
					ns[name] = functools.partial(_refuse_cloud, name)
			ns['http_get'] = _local_http_get(rules)
			self._namespace = ns
		return self._namespace

	def _ensure_daemon(self, code: str) -> None:
		"""Mirror run.py: daemon must be up before helpers run, except for code that starts or stops a cloud browser
		(anywhere in it: attaching first would attach the user's Chrome)."""
		self._ensure_namespace()
		if not harness_cloud.calls_cloud_admin(code):
			self._attach()
			self._note = self._browser_note() or self._note

	def _attach(self) -> None:
		"""Attach what helpers drive: the cloud browser this server started, else its own Chromium (--mcp, or --cli-mcp
		where the user's Chrome cannot be used), else the user's Chrome. Browser.start() launches the Chromium on first
		use and starts its daemon again if that died."""
		if self._cloud_started:
			return harness_cloud.ensure_daemon()
		if self._browser is None:
			with self._attach_lock:
				if self._browser is None and (why := _no_chrome_here()):
					self._browser, self._fallback = Browser('chromium'), why
		if self._browser is None:
			return harness_cloud.ensure_daemon()
		with self._attach_lock:
			try:
				harness_cloud.route(asyncio.run(self._start_own(self._browser))['BU_NAME'], self._namespace)
			except Exception as e:
				if self._own_started:  # it ran before: its own error (crashed, reattach failed)
					raise
				raise self._no_browser(e) from None
			self._own_started = True

	async def _start_own(self, browser: Browser) -> dict[str, str]:
		"""browser.start(); on a machine with no browser and no display (a server, a container), installs Playwright's
		Chromium first (once). Never on a desktop: 150 MB inside one tool call the user did not ask for."""
		from browser_use.browser import local

		try:
			return await browser.start()
		except RuntimeError as e:  # local.find_binary
			if self._install_tried or not str(e).startswith('No Chrome, Chromium or Edge found') or local.has_display():
				raise
		self._install_tried = True
		self._installed = await asyncio.to_thread(_install_chromium)
		return await browser.start()

	def _no_browser(self, e: Exception) -> NoBrowserError:
		reason = ' '.join((str(e) or type(e).__name__).split()).rstrip('.')  # one line: a Chrome log tail has several
		chrome = f'no Chrome to attach ({self._fallback}), and ' if self._fallback else ''
		rules = self._browser is not None and self._browser.domains
		cloud = '' if rules else f', or {_cloud_hint()}'
		how = (
			'sudo apt-get install -y libatomic1 && browser-use install'
			if sys.platform.startswith('linux')
			else 'browser-use install'
		)
		return NoBrowserError(
			f"No browser to drive: {chrome}this server's own Chromium could not start: {reason}. Install Google Chrome or "
			f'Chromium on this machine (or run `{how}`){cloud}.'
		)

	def _browser_note(self) -> str | None:
		"""The browser now in use, once per change, for the browser_exec result: None for a cloud browser (its start said)."""
		if self._cloud_started:
			return None
		if self._browser is None:
			from browser_harness import admin

			note = 'Browser: your own Chrome (its tabs and logins).'
			note = note if admin._is_local_chrome_mode() else 'Browser: the Chrome at BU_CDP_URL / BU_CDP_WS.'
		else:
			note = "Browser: this server's own Chromium on a temp profile, not your Chrome"
			note += f' ({self._fallback}).' if self._fallback else '.'
		if note == self._announced:
			return None
		self._announced = note
		if self._installed is not None:
			note += f" Installed Playwright's Chromium first ({self._installed:.0f} s)."
			self._installed = None
		return note

	def _start_remote(self, name: str = 'remote', profileName: str | None = None, **create_kwargs: Any) -> dict:
		name = self._remote  # a caller's name could be another server's browser: stopping or driving it hijacks it
		create_kwargs.setdefault('timeout', CLOUD_TIMEOUT_MINUTES)
		browser = harness_cloud.start(name, profileName, create_kwargs, self._namespace)
		self._cloud_started = True
		if browser.get('id'):
			args = [sys.executable, '-P', '-c', _REAPER, name]  # -P: never import from the cwd
			env = {**os.environ, 'BU_CLEANUP_BROWSER_ID': browser['id']}
			watch = {'BU_CLEANUP_PID': str(os.getpid()), 'BU_CLEANUP_SINCE': repr(time.time())}
			if os.name == 'nt' and _spawn_outside_job(args, {**env, **watch}):
				return browser
			detach: dict[str, Any] = ipc.spawn_kwargs()  # own session: a Ctrl-C to this server's group does not kill it first
			self._reapers.append(
				subprocess.Popen(
					args,
					env=env,
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
		with _capture(buffer):
			try:
				ns = self._ensure_namespace()
				if connect:
					self._ensure_daemon(code)
			except Exception as e:  # attaching the browser, before any of the code ran: one line, not harness internals
				_error_class(e)
				print(self._error(e), file=buffer)
				return buffer.getvalue(), failed
			try:
				exec(code, ns)
				failed = False
			except BaseException as e:
				_error_class(e)
				if isinstance(e, CloudAuthRequired | CloudBrowserError):
					print(self._error(e), file=buffer)
				else:
					from browser_use.telemetry.stats import raised_by_cell

					_print_cell_traceback(e, buffer)
					if isinstance(e, NameError) and e.name and raised_by_cell(e):
						from browser_use.cli import CORE_HELPERS

						print(
							f"'{e.name}' is not defined here (0.x actions like click_element were removed).\n{CORE_HELPERS}",
							file=buffer,
						)
		return buffer.getvalue(), failed

	def _error(self, e: Exception) -> str:
		"""One line for a failure to reach the browser. browser-harness's "daemon <name> didn't come up -- check <log>"
		named only a log file the model cannot read: its last line is the reason (browser-harness reads it the same way)."""
		if isinstance(e, CloudAuthRequired):  # its own message names `browser-harness auth login`, not this server's tool
			return LOGIN_HINT
		if isinstance(e, CloudBrowserError | NoBrowserError):
			return f'Error: {e}'
		from browser_harness import admin

		text = str(e) or type(e).__name__
		if " didn't come up -- check " in text and (reason := admin._log_tail(admin.NAME)):
			text = f'{text.partition(" -- check ")[0]}: {reason.removeprefix("fatal: ")}'
		if self._browser is None and not self._cloud_started:
			hint = _cloud_hint()
			text += f'. No local Chrome to use? {hint[0].upper()}{hint[1:]}'
		return f'Error: {text}'

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
		with _capture(buffer):
			ns = self._ensure_namespace()
			self._attach()
			path = ns['capture_screenshot'](full=full, max_dim=max_dim)
		with open(path, 'rb') as f:
			return base64.b64encode(f.read()).decode()

	def _instructions(self) -> str:
		if self._own_browser:
			local = "its own Chromium (a temp profile, not the user's Chrome)"
		else:
			local = (
				"the user's own Chrome; where none can be attached or set up (no Chrome installed, or Linux with no "
				'display) its own Chromium on a temp profile instead. The first browser_exec result says which'
			)
		guide = MCP_GUIDE.format(local=local)
		if self._browser is not None and self._browser.domains:
			guide += f'- {NO_CLOUD_WITH_DOMAINS.format(name="start_remote_daemon")}: ignore the Cloud rules above.\n\n'
		return guide + _harness_skill_text()

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
				# Windows: the client closed the session; stop the cloud browser before exiting, not only from the reaper (the
				# client kills the server's Job Object right after it exits, and with it a reaper WMI could not start).
				# Not on POSIX: the reaper already does it there, and this stop waits up to 15 s on the daemon it spawned.
				if self._cloud_started and os.name == 'nt':
					try:
						harness_cloud.stop_cloud(self._remote)
					except Exception:
						pass


async def main(own_browser: bool = False, **browser_options: Any):
	os.environ.setdefault('BH_CLIENT', 'browser-use-mcp')
	server = CLIMCPServer(own_browser, **browser_options)
	await server.run()


if __name__ == '__main__':
	asyncio.run(main())
