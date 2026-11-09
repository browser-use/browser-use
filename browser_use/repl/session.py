"""Parent side of the REPL worker (worker.py). Kill-and-restart on timeout; files and the browser survive.

Transport: the worker connects back to a 127.0.0.1 ephemeral port and proves itself with a random token, so it
works the same on Windows, macOS and Linux (no inherited file descriptors).

Secrets: the worker gets an allowlisted environment (no API keys or tokens), which only keeps keys out of its own
environment: as your user it can still read the parent's environment (ps -E, /proc/<pid>/environ) and .env file
(MIGRATING.md "Trust model"). sensitive_data values travel over the
control channel, are typed with type_secret(name) (domain-scoped ones only into a matching focused frame), and are replaced with
<secret:name> in the text the worker returns and in its cell files and checkpoints. Not a sandbox: model-written
Python can read the values and local files, write unredacted files, and screenshots or js() reads of a field can
reveal a typed value (MIGRATING.md "Trust model").
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import contextvars
import fnmatch
import hmac
import html
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import time
import urllib.parse
import weakref
from collections.abc import Awaitable, Callable, Iterable
from pathlib import Path
from typing import Any, cast

from browser_use import search as web

MODES = ('default', 'ultrafast')
STREAM_LIMIT = 256 * 1024 * 1024
MAX_OUTPUT_CHARS = 12_000  # per cell, cut in the worker so a huge print never crosses the channel
ENV_ALLOW = {
	'PATH', 'PATHEXT', 'HOME', 'USERPROFILE', 'HOMEDRIVE', 'HOMEPATH', 'USER', 'USERNAME', 'LOGNAME', 'SHELL', 'TERM',
	'SYSTEMROOT', 'SYSTEMDRIVE', 'WINDIR', 'COMSPEC', 'APPDATA', 'LOCALAPPDATA', 'PROGRAMDATA', 'PROGRAMFILES',
	'TEMP', 'TMP', 'TMPDIR', 'LANG', 'LANGUAGE', 'TZ', 'XDG_CONFIG_HOME', 'XDG_RUNTIME_DIR', 'XDG_CACHE_HOME',
	'DISPLAY', 'WAYLAND_DISPLAY', 'PYTHONPATH', 'VIRTUAL_ENV',
	# corporate proxies and CAs: http_get() and requests/httpx in cells need them like the parent does
	'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY', 'SSL_CERT_FILE', 'SSL_CERT_DIR', 'REQUESTS_CA_BUNDLE',
	'CURL_CA_BUNDLE',
}  # fmt: skip
ENV_ALLOW_PREFIXES = ('LC_', 'BU_', 'BH_')  # browser-harness reads BU_NAME, BH_RUNTIME_DIR, BH_TMP_DIR, ...
ENV_DENY = {'BU_CDP_WS', 'BU_CDP_URL', 'BU_MODE', 'BU_HIGHLIGHT_ACTIONS'}  # CDP URLs can carry credentials; Repl sets the rest
RESTARTED = '{why}. The REPL restarted: Python variables are lost; files, checkpoints and browser state survive.'
SHORT_SECRET = 4  # shorter values are redacted only where they stand alone (not inside a longer word or number)
SECRET_ENV = re.compile(r'KEY|TOKEN|SECRET|PASSW|CREDENTIAL|AUTH', re.I)
SECRET_PLACEHOLDER = re.compile(r'<secret>([^<]+)</secret>|<secret:([^>]+)>')  # 0.x's form, and 1.0 redaction's


def check_mode(mode: str | None) -> str:
	if mode is None:  # Pi: mode undefined means 'default'
		return 'default'
	if mode not in MODES:
		raise ValueError("mode must be 'default' or 'ultrafast'.")
	return mode


def check_loop() -> None:
	"""The REPL worker is a subprocess, which a SelectorEventLoop on Windows cannot start (NotImplementedError):
	raise a clear error before anything (a billed cloud browser) starts."""
	if sys.platform == 'win32' and isinstance(asyncio.get_running_loop(), asyncio.SelectorEventLoop):
		raise RuntimeError(
			'browser-use needs the default ProactorEventLoop on Windows (it starts a subprocess); this loop is a '
			'SelectorEventLoop. Remove asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy()).'
		)


def worker_env(extra: dict[str, str] | None = None) -> dict[str, str]:
	"""The REPL worker's environment: an allowlist of the parent's, never anything that looks like a credential."""
	env = {
		k: v
		for k, v in os.environ.items()
		if (k.upper() in ENV_ALLOW or k.upper().startswith(ENV_ALLOW_PREFIXES))
		and k.upper() not in ENV_DENY
		and not SECRET_ENV.search(k)
	}
	return {**env, **(extra or {})}


Secrets = dict[str, Any] | Iterable[tuple]  # 0.x sensitive_data, or (name, value[, domain]) tuples


def scoped_secrets(sensitive_data: Secrets | None) -> list[tuple[str, str, str | None]]:
	"""0.x sensitive_data -> (name, value, domain pattern or None).

	{'name': 'value'} types anywhere; {'https://site.com' or '*.site.com': {'name': 'value'}} types only on pages
	whose URL matches the pattern (domain_matches)."""
	if sensitive_data is None:
		return []
	if not isinstance(sensitive_data, dict):
		return [(t[0], t[1], t[2] if len(t) > 2 else None) for t in sensitive_data]
	out: list[tuple[str, str, str | None]] = []
	for key, value in cast(dict[str, Any], sensitive_data).items():
		if isinstance(value, dict):
			for name, v in value.items():
				if not isinstance(v, str):
					raise TypeError(f'sensitive_data[{key!r}][{name!r}] must be a string')
				out.append((name, v, key))
		elif isinstance(value, str):
			out.append((key, value, None))
		else:
			raise TypeError(f"sensitive_data[{key!r}] must be a string, or {{'name': 'value'}} for the domain pattern {key!r}")
	return out


def domain_matches(url: str, pattern: str) -> bool:
	"""0.x match_url_with_domain_pattern: 'site.com' = https only, 'http*://site.com' = both schemes, '*.site.com'
	= site.com and its subdomains. A port in the pattern must match; without one any port does."""
	try:
		u = urllib.parse.urlparse(url)
		scheme, host = (u.scheme or '').lower(), (u.hostname or '').lower()
		if not scheme or not host:  # about:blank, chrome://newtab, data:...
			return False
		pattern = pattern.lower()
		p_scheme, p_host = pattern.split('://', 1) if '://' in pattern else ('https', pattern)
		p_host, _, p_port = p_host.partition('/')[0].partition(':')
		if not fnmatch.fnmatchcase(scheme, p_scheme) or (p_port and str(u.port or '') != p_port):
			return False
		if p_host in ('*', host):
			return True
		if '*' not in p_host or p_host.count('*.') > 1 or p_host.endswith('.*') or '*' in p_host.replace('*.', ''):
			return False  # only '*.domain' and '*domain' globs, as in 0.x
		if p_host.startswith('*.') and host == p_host[2:]:
			return True
		return fnmatch.fnmatchcase(host, p_host)
	except ValueError:  # a malformed URL or port
		return False


def _html_escaped(value: str) -> tuple[str, ...]:
	"""value as page HTML shows it: Chrome's outerHTML escapes & < > in text and & " < > in attributes (older Chrome
	only & "), Python's html.escape also '."""
	text = value.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
	return text, text.replace('"', '&quot;'), value.replace('&', '&amp;').replace('"', '&quot;'), html.escape(value)


def _base64_cores(b: bytes) -> list[str]:
	"""The base64 text of b inside a longer encoded string ('Basic ' + b64('user:' + password), a base64 JSON blob),
	at each of the 3 byte offsets it can start at: only the characters that b's own bits decide."""
	cores = []
	for k in range(3):
		start, end = -(-8 * k // 6), 8 * (k + len(b)) // 6  # characters whose 6 bits all fall inside b
		for encode in (base64.b64encode, base64.urlsafe_b64encode):
			cores.append(encode(bytes(k) + b).decode()[start:end])
	return cores


def secret_forms(values: Secrets) -> list[tuple[str, str]]:
	"""(form, name) for each secret value; its JSON-, repr()- and HTML-escaped forms (a value with quotes, backslashes,
	newlines, & or < no longer matches once serialized); its lower- and upper-case forms (a site shows an email
	lowercased); and its reversed, base64 (also inside a longer base64 string), hex and URL-encoded forms. Longest
	first."""
	forms: dict[str, str] = {}
	for name, value, _ in scoped_secrets(values):
		if not value:
			continue
		forms[value] = name
		escaped = (json.dumps(value)[1:-1], json.dumps(value, ensure_ascii=False)[1:-1], repr(value)[1:-1], *_html_escaped(value))
		for form in escaped:
			forms.setdefault(form, name)  # escapes only make a value longer: never a shorter, over-matching form
		for form in (value.lower(), value.upper()):  # same length; a 1-3 character one only as a whole word (redact_forms)
			forms.setdefault(form, name)
		if len(value) >= 4:  # encodings of a 1-3 character value would redact ordinary text
			b = value.encode()
			b64 = base64.b64encode(b).decode()
			for form in (value[::-1], b64, b64.rstrip('='), base64.urlsafe_b64encode(b).decode(), b.hex(), b.hex().upper(),
						 urllib.parse.quote(value, safe=''), urllib.parse.quote_plus(value)):  # fmt: skip
				forms.setdefault(form, name)
		if len(value) >= 6:  # shorter values give cores of 4-6 characters, which occur by chance in any base64 blob
			for text in dict.fromkeys((value, escaped[0])):  # as is, and as it sits in base64 of JSON
				for form in _base64_cores(text.encode()):
					forms.setdefault(form, name)
	return sorted(forms.items(), key=lambda kv: -len(kv[0]))


def redact(text: Any, values: Secrets) -> Any:
	"""Replace secret values (and common encodings of them) with <secret:name>, in strings, lists and dicts.
	Only the text passed here is redacted; it is not a sandbox."""
	return redact_forms(text, secret_forms(values))


def redact_forms(text: Any, forms: list[tuple[str, str]]) -> Any:
	"""redact() with precomputed secret_forms()."""
	if isinstance(text, list):
		return [redact_forms(t, forms) for t in text]
	if isinstance(text, dict):
		return {redact_forms(k, forms): redact_forms(v, forms) for k, v in text.items()}
	if not isinstance(text, str):
		return text
	for form, name in forms:
		if len(form) < SHORT_SECRET:  # a 1-3 character value only as a whole word: '9' must not turn 2019 into 201<secret>
			text = re.sub(rf'(?<![^\W_]){re.escape(form)}(?![^\W_])', f'<secret:{name}>', text)
		else:
			text = text.replace(form, f'<secret:{name}>')
	return text


def clip(text: str, path: Path | str) -> str:
	"""Cell output for the model: at most MAX_OUTPUT_CHARS, then where the full text is."""
	return text if len(text) <= MAX_OUTPUT_CHARS else f'{text[:MAX_OUTPUT_CHARS]}\n[Truncated. Full captured output: {path}]'


def _head(path: Path) -> str:
	"""The start of a cell's output file, enough for clip(): a cell may have printed gigabytes before it hung."""
	try:
		with open(path, encoding='utf-8', errors='replace') as f:
			return f.read(MAX_OUTPUT_CHARS + 1)
	except FileNotFoundError:
		return ''


def _kill_tree(pid: int, job: int | None = None) -> None:
	"""Kill the worker and every process its cells started (a surviving subprocess could keep driving the browser),
	also after the worker itself died: POSIX kills its process group, Windows terminates its job object."""
	if sys.platform == 'win32':
		if job is not None:
			import ctypes

			kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
			kernel32.TerminateJobObject(job, 1)
			kernel32.CloseHandle(job)
		subprocess.run(['taskkill', '/F', '/T', '/PID', str(pid)], capture_output=True)
	else:
		try:
			os.killpg(pid, signal.SIGKILL)  # the worker leads its own process group (start_new_session)
		except (ProcessLookupError, PermissionError):
			pass


async def _exited(proc: subprocess.Popen) -> None:
	"""Wait for the process to exit, and reap it."""
	while proc.poll() is None:  # noqa: ASYNC110 - polled: an asyncio child watcher would tie it to one event loop
		await asyncio.sleep(0.02)


_WORKERS: dict[int, int | None] = {}  # pid -> Windows job of every live worker this process started


def _end_worker(pid: int, job: int | None) -> None:
	_WORKERS.pop(pid, None)
	_kill_tree(pid, job)


def kill_workers() -> None:
	"""Kill every live REPL worker and the processes its cells started (atexit, SIGTERM): a cell left running after
	this process exits could keep driving the browser, its timeout gone with us."""
	while _WORKERS:
		_kill_tree(*_WORKERS.popitem())


def _job_for(pid: int) -> int | None:
	"""Windows: a job object holding the worker; processes its cells start join it, so they can be killed after the
	worker died (taskkill /T no longer finds them then). Kill-on-close: when this process dies, however it dies,
	Windows closes its job handle and kills the worker's whole tree. None when it cannot be created."""
	if sys.platform != 'win32':
		return None
	import ctypes

	class Basic(ctypes.Structure):  # JOBOBJECT_BASIC_LIMIT_INFORMATION
		_fields_ = [
			('PerProcessUserTimeLimit', ctypes.c_int64), ('PerJobUserTimeLimit', ctypes.c_int64),
			('LimitFlags', ctypes.c_uint32), ('MinimumWorkingSetSize', ctypes.c_size_t),
			('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', ctypes.c_uint32),
			('Affinity', ctypes.c_size_t), ('PriorityClass', ctypes.c_uint32), ('SchedulingClass', ctypes.c_uint32),
		]  # fmt: skip

	class Extended(ctypes.Structure):  # JOBOBJECT_EXTENDED_LIMIT_INFORMATION
		_fields_ = [
			('BasicLimitInformation', Basic), ('IoInfo', ctypes.c_uint64 * 6), ('ProcessMemoryLimit', ctypes.c_size_t),
			('JobMemoryLimit', ctypes.c_size_t), ('PeakProcessMemoryUsed', ctypes.c_size_t),
			('PeakJobMemoryUsed', ctypes.c_size_t),
		]  # fmt: skip

	kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
	handle = ctypes.c_void_p  # HANDLEs are pointer-sized: the default int restype truncates them on 64-bit Windows
	kernel32.CreateJobObjectW.restype = kernel32.OpenProcess.restype = handle
	kernel32.SetInformationJobObject.argtypes = [handle, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
	kernel32.AssignProcessToJobObject.argtypes = [handle, handle]
	kernel32.CloseHandle.argtypes = [handle]
	job = kernel32.CreateJobObjectW(None, None)
	info = Extended()
	info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
	if job:  # best effort: without it the worker's watchdog still exits when we die (worker._watch_parent)
		kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))  # JobObjectExtendedLimit...
	process = kernel32.OpenProcess(0x0101, False, pid)  # PROCESS_SET_QUOTA | PROCESS_TERMINATE
	ok = bool(job and process and kernel32.AssignProcessToJobObject(job, process))
	if process:
		kernel32.CloseHandle(process)
	if not ok and job:
		kernel32.CloseHandle(job)
	return job if ok else None


class Repl:
	"""mode='ultrafast' adds the `bu` helpers to the worker (BU_MODE=ultrafast). reattach: starts the browser-harness
	daemon again after a cell lost it (Browser.start). after_cell: runs after each cell, outside the worker; returns
	(lines appended to the cell's output, blocks counted as domain_blocked) (Browser.after_cell). search: defines
	search() in the worker, answered here (the API key stays in this process). downloads: defines downloads() in the
	worker, answered here (Browser.list_downloads). highlight_actions: orange corner brackets around what the agent
	clicks or types into (repl/highlight.py)."""

	def __init__(
		self,
		workspace: Path,
		env: dict[str, str] | None = None,
		mode: str | None = 'default',
		secrets: Secrets | None = None,
		reattach: Callable[[], Awaitable[Any]] | None = None,
		after_cell: Callable[[], Awaitable[tuple[list[str], int]]] | None = None,
		search: web.WebSearch | None = None,
		downloads: Callable[[], Awaitable[list[dict]]] | None = None,
		highlight_actions: bool = False,
	):
		self.workspace, self.env, self.mode = workspace, env or {}, check_mode(mode)
		self.highlight_actions = highlight_actions
		self.reattach, self.after_cell, self.search, self.downloads = reattach, after_cell, search, downloads
		self.secrets = scoped_secrets(secrets)  # (name, value, domain pattern or None)
		# a plain Popen, not an asyncio subprocess: asyncio's child watcher belongs to the loop that started the worker,
		# which a keep_alive Agent outlives (asyncio.run per run); killed after that loop closed, the worker was never
		# reaped on Linux (pidfd watcher) and logged "Loop ... that handles pid ... is closed" on macOS
		self.proc: subprocess.Popen[bytes] | None = None
		self.job: int | None = None  # Windows job object of the worker's process tree
		self._reaper: weakref.finalize | None = None  # ends the worker of a Repl dropped without close()
		self.loop: asyncio.AbstractEventLoop | None = None
		self.state = workspace / '.browser-use'
		(self.state / 'captcha.json').unlink(missing_ok=True)  # solver state of an earlier browser session; restarts keep it
		# Continue the workspace's cell numbering: a follow-up run's new REPL must not overwrite earlier cells' files,
		# which the retained conversation still points to.
		cells = (p.stem for p in (self.state / 'cells').glob('*.txt'))
		self.n = max((int(c) for c in cells if c.isdigit()), default=0)
		self.lock = asyncio.Lock()  # the model may emit parallel python calls; the worker runs one cell at a time
		self.start_ns = 0  # time spent starting workers (telemetry ms_repl_start)
		self._lock_loop: asyncio.AbstractEventLoop | None = None  # the loop self.lock serves (a lock binds to one)

	async def start(self) -> None:
		# In a context of its own: the worker's socket reader holds the context it was opened in while it is open, and the
		# run's (Pydantic AI's RunContext -> Session -> this Repl) kept an Agent dropped without close() from being freed
		started = time.perf_counter_ns()
		try:
			await asyncio.create_task(self._start(), context=contextvars.Context())
		finally:
			self.start_ns += time.perf_counter_ns() - started

	async def _start(self) -> None:
		check_loop()
		await self.close()  # a dead previous worker's cell processes may still run: kill its group/job before replacing it
		self.state.mkdir(parents=True, exist_ok=True)
		self.loop = asyncio.get_running_loop()
		token = secrets.token_hex(32)
		connected: asyncio.Future = asyncio.get_running_loop().create_future()

		async def on_connect(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
			try:
				line = await asyncio.wait_for(reader.readline(), 10)
			except Exception:  # - a stray client
				line = b''
			if not connected.done() and hmac.compare_digest(line.strip(), token.encode()):
				connected.set_result((reader, writer))
			else:
				writer.close()

		server = await asyncio.start_server(on_connect, '127.0.0.1', 0, limit=STREAM_LIMIT)
		port = server.sockets[0].getsockname()[1]
		env = worker_env(self.env)
		env.update(BH_TAB_MARKER='0', BU_STATE_DIR=str(self.state), BU_REPL_PORT=str(port), BU_REPL_TOKEN=token)
		# A naive call never reaches another browser (the user's own Chrome): a `browser-harness` CLI call reuses this run's
		# daemon or fails, and any daemon a cell starts dials a dead port instead of discovering a local Chrome.
		env.update(BH_REQUIRE_EXISTING_DAEMON='1', BU_CDP_WS='ws://127.0.0.1:9/browser-use-owns-the-browser')
		env['BU_REPL_PARENT_PID'] = str(os.getpid())  # the worker exits when we die (worker._watch_parent)
		# A browser-harness CLI call from a cell would send its piped code and output (page text) as cli_event, and the
		# allowlisted env drops ANONYMIZED_TELEMETRY. The run is already counted (agent_event).
		env['BH_TELEMETRY'] = '0'
		env.update(PYTHONUTF8='1', PYTHONIOENCODING='utf-8')  # page text is Unicode; Windows defaults to cp1252
		if self.mode == 'ultrafast':
			env['BU_MODE'] = 'ultrafast'
		if self.highlight_actions:
			env['BU_HIGHLIGHT_ACTIONS'] = '1'
		log = open(self.state / 'worker.log', 'ab')  # noqa: ASYNC230 - handed to the child process
		try:
			self.proc = subprocess.Popen(  # noqa: ASYNC220 - asyncio forks synchronously too; see self.proc
				# -P: the workspace is not sys.path[0]: a json.py there must not shadow the stdlib (worker.py appends it)
				[sys.executable, '-P', '-m', 'browser_use.repl.worker'],
				cwd=self.workspace,
				stdin=subprocess.DEVNULL,
				stdout=log,
				stderr=log,
				env=env,
				# Own process group, so a reset kills the cell's subprocesses too.
				**(
					{'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP}  # type: ignore[attr-defined]
					if sys.platform == 'win32'
					else {'start_new_session': True}
				),
			)
			self.job = _job_for(self.proc.pid)  # before the first cell: every process a cell starts joins it
			_WORKERS[self.proc.pid] = self.job
			# An Agent on a keep_alive Browser keeps its REPL until close(): one dropped without it (a service running
			# many Agents on one Browser) left a ~35 MB worker each until exit
			self._reaper = weakref.finalize(self, _end_worker, self.proc.pid, self.job)
			self._reaper.atexit = False  # exit: kill_workers, before browsers stop
			from browser_use.browser.browser import _install_cleanup

			_install_cleanup()  # atexit and SIGTERM kill the worker (kill_workers) before they stop browsers
			exited = asyncio.ensure_future(_exited(self.proc))
			try:
				done, _ = await asyncio.wait({connected, exited}, timeout=60, return_when=asyncio.FIRST_COMPLETED)
			finally:
				exited.cancel()
			if connected not in done:
				raise RuntimeError(f'REPL worker failed to start; see {self.state / "worker.log"}')
			self.reader, self.writer = connected.result()
			init = {'secrets': self.secrets, 'search': self.search is not None, 'downloads': self.downloads is not None}
			self.writer.write(json.dumps(init).encode() + b'\n')
			await self.writer.drain()
			if not await asyncio.wait_for(self.reader.readline(), 60):
				raise ConnectionError('worker exited')
		except BaseException as e:  # cancelled or failed half way: never leave a half-started worker behind
			await self.close()
			if isinstance(e, (TimeoutError, ConnectionError)):
				raise RuntimeError(f'REPL worker failed to start; see {self.state / "worker.log"}') from e
			raise
		finally:
			log.close()
			server.close()

	async def close(self) -> None:
		if (writer := getattr(self, 'writer', None)) is not None:  # our end of the worker connection; idempotent
			with contextlib.suppress(RuntimeError):  # its event loop is closed (a finished run_sync's)
				writer.close()  # left open, it lingered (CLOSE_WAIT) until a garbage collection freed it
		proc, self.proc = self.proc, None
		job, self.job = self.job, None
		if proc is None:
			return
		if self._reaper is not None:
			self._reaper.detach()
		_end_worker(proc.pid, job)  # also when the worker already exited: processes its cells started may still run
		if proc.poll() is None:
			with contextlib.suppress(OSError):  # already gone
				proc.kill()
			with contextlib.suppress(TimeoutError):  # reaped from any loop: SIGKILL ends it in milliseconds
				await asyncio.wait_for(_exited(proc), 5)

	async def call(self, op: str, code: str, timeout: float) -> dict[str, Any]:
		# Ultrafast prints the page state after the cell's code, so its cells may run up to 10 s past the timeout.
		if self._lock_loop is not (loop := asyncio.get_running_loop()):  # reused from a new loop (asyncio.run per run)
			self.lock, self._lock_loop = asyncio.Lock(), loop
		async with self.lock:
			r = await self._call(op, code, timeout + (10 if self.mode == 'ultrafast' else 0))
			if r.get('error_type') == 'BrowserConnectionLost' and self.reattach is not None:
				try:
					env = await self.reattach()
					if isinstance(env, dict) and env != self.env:  # another daemon (a new browser): the worker must use it
						self.env = env
						await self.close()
						r['error'] += (
							'\n[The browser was stopped and a new one started: its tabs, logins and page state are gone, and '
							'the REPL restarted (Python variables are lost; files survive).]'
						)
					else:
						r['error'] += (
							'\n[browser-use started the daemon again on the same browser: retry; check the page state first.]'
						)
				except Exception as e:
					r['error'] += f'\n[{e}. Finish with what you have.]'
					r['browser_gone'] = True  # the agent's next turn is delivery-only: no cells without a browser
			if self.after_cell is not None and op == 'exec':
				notices, blocks = await self.after_cell()
				if notices:
					# first: the cell's own output after a blocked click (an error page titled with the blocked host) can read
					# as a successful landing
					r['output'] = '\n'.join(filter(None, [*notices, r.get('output') or '']))
				if blocks:
					events = r.setdefault('stats', {}).setdefault('events', {})
					events['domain_blocked'] = events.get('domain_blocked', 0) + blocks
		return {**r, **{k: redact(r.get(k), self.secrets) for k in ('output', 'error', 'value')}}

	async def _search(self, args: Any) -> dict[str, Any]:
		"""{'value': the search result} or {'error': the message search() raises in the cell}."""
		if self.search is None or not isinstance(args, dict):
			return {'error': 'Web search is not enabled.'}
		try:  # the total deadline; the socket timeout alone lets a slow trickle run on
			return {'value': await asyncio.wait_for(asyncio.to_thread(self.search, **args), web.SEARCH_TIMEOUT_S)}
		except TimeoutError:
			return {'error': f'Search failed: timed out after {web.SEARCH_TIMEOUT_S:g} s.'}
		except web.SearchError as e:
			return {'error': str(e)}
		except Exception as e:  # - bad arguments: the cell's error says what
			return {'error': f'Search failed: {type(e).__name__}: {e}'}

	async def _downloads(self) -> dict[str, Any]:
		"""{'value': the downloaded files} or {'error': the message downloads() raises in the cell}."""
		if self.downloads is None:
			return {'error': 'downloads() is not available for this browser.'}
		try:
			return {'value': await asyncio.wait_for(self.downloads(), 60)}
		except Exception as e:  # - the API failed or timed out: the cell's error says what
			return {'error': f'downloads() failed: {type(e).__name__}: {e}'}

	async def _call(self, op: str, code: str, timeout: float) -> dict[str, Any]:
		try:  # one cleanup boundary: a cancel during startup, the send or the wait never leaves a half-used worker
			# A worker started on another (finished) event loop cannot be driven from this one: replace it.
			moved = self.proc is not None and self.loop is not asyncio.get_running_loop()
			if moved or self.proc is None or self.proc.poll() is not None:
				await self.start()
			self.n += 1
			n = self.n
			try:
				self.writer.write(json.dumps({'op': op, 'code': code, 'n': n}).encode() + b'\n')
				await self.writer.drain()
				async with asyncio.timeout(timeout):
					while True:
						line = await self.reader.readline()
						if not line:
							raise ConnectionError('worker exited')
						msg = json.loads(line)
						if msg.get('type') in ('search', 'downloads'):  # the cell called one: answered while it waits
							answer = await (self._search(msg.get('args')) if msg['type'] == 'search' else self._downloads())
							self.writer.write(json.dumps(answer).encode() + b'\n')
							await self.writer.drain()
							continue
						if msg.get('n') == n:  # never hand one call another call's answer
							if moved:
								msg['output'] = f'[{RESTARTED.format(why="This run uses a new event loop")}]\n{msg["output"]}'
							return msg
			except (TimeoutError, ConnectionError) as e:
				await self.close()
				out = self.state / 'cells' / f'{n:04d}.txt'
				why = f'Cell timed out after {timeout:g}s' if isinstance(e, TimeoutError) else 'REPL worker exited'
				return {
					'output': clip(_head(out), out),
					'images': [],
					'output_file': str(out),
					'value': None,
					'error': f'{RESTARTED.format(why=why)} Actions may already have happened; inspect before retrying.',
					'error_type': 'CellTimeout' if isinstance(e, TimeoutError) else 'WorkerExited',
				}
		except asyncio.CancelledError:  # the whole run was cancelled or timed out: the cell may still be running
			await self.close()
			raise
