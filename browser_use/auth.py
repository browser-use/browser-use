"""The Browser Use API key: BROWSER_USE_API_KEY, else the key `browser-use login` stored (browser-harness's store)."""

import os
import re
import signal
import sys
import threading
import urllib.parse
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from browser_use.exceptions import MissingAPIKeyError, keys_url

STORED = 'the key browser-use login stored'
OFF, ON = ('0', 'false', 'no', 'off'), ('1', 'true', 'yes', 'on')
_login_lock = threading.Lock()
_login_attempted = False
_reported_key_sources: set[str] = set()
_key_sources_lock = threading.Lock()


def record_auth_event(stage: str, *, method: str = '', automatic: bool = False, **fields: str | None) -> None:
	"""Record login progress without credentials or account identifiers (library_auth; fields: key_gate, key_reason,
	outcome, entry). Never raises."""
	try:
		from browser_use.telemetry.auth_events import capture

		capture(stage, method, automatic, fields)
	except Exception:
		pass


def _can_open_login() -> bool:
	from browser_use.cli import _stdin_is_terminal

	return (
		sys.stdin is not None
		and _stdin_is_terminal()
		and 'ipykernel' not in sys.modules
		and os.getenv('BROWSER_USE_AUTO_LOGIN', 'true').strip().lower() not in OFF
		and not (os.getenv('CI') or os.getenv('GITHUB_ACTIONS'))
		and bool(
			sys.platform in ('darwin', 'win32')
			or (
				os.getenv('XDG_CURRENT_DESKTOP')
				and os.getenv('XDG_SESSION_TYPE') in ('x11', 'wayland')
				and (os.getenv('DISPLAY') or os.getenv('WAYLAND_DISPLAY'))
			)
		)
	)


def _can_show_device_code() -> bool:
	"""A person at a terminal where no browser opens for them: over SSH, or Linux without a desktop. _can_open_login's
	terminal, CI, notebook and BROWSER_USE_AUTO_LOGIN rules, and stderr a terminal too (the link and code go there). Not
	in a container (Docker, podman, Kubernetes) unless BROWSER_USE_AUTO_LOGIN=1: `docker run -t` gives a terminal nobody
	may read, and the code waits until it expires."""
	from browser_use import config
	from browser_use.cli import _stdin_is_terminal
	from browser_use.utils import is_ssh

	auto = os.getenv('BROWSER_USE_AUTO_LOGIN', '').strip().lower()
	if auto in OFF or os.getenv('CI') or os.getenv('GITHUB_ACTIONS') or 'ipykernel' in sys.modules:
		return False
	try:
		if sys.stdin is None or not _stdin_is_terminal() or not sys.stderr.isatty():
			return False
	except (AttributeError, ValueError):  # replaced or closed streams (a daemon, pytest's capture)
		return False
	if not (is_ssh() or sys.platform not in ('darwin', 'win32')):
		return False
	return auto in ON or not config.is_in_container()


def auto_login_method() -> str | None:
	"""The login a run on a missing key starts by itself: 'browser' on an interactive desktop (one click), 'device' (a
	link and a code to approve on any device) at a terminal over SSH or on Linux without a desktop, where a browser
	cannot reach this machine's loopback callback. None: no login (a script, server, CI, notebook, container, or where
	the wait would block others: _login_can_block)."""
	from browser_use.utils import is_ssh

	if not _login_can_block():
		return None
	if not is_ssh() and _can_open_login():
		return 'browser'
	return 'device' if _can_show_device_code() else None


def _login_can_block() -> bool:
	"""The login a run starts blocks its thread until approved (600 s, or until a device code expires). Only on the main
	thread, the one Ctrl-C reaches (a worker's login, as in a ThreadPoolExecutor, Streamlit or Gradio, ran to its end),
	and with no other task on this thread's event loop (a server, asyncio.gather): each one stalled for the whole wait."""
	import asyncio

	if threading.current_thread() is not threading.main_thread():
		return False
	try:
		loop = asyncio.get_running_loop()
	except RuntimeError:
		return True
	return asyncio.all_tasks(loop) <= {asyncio.current_task(loop)}


AUTO_LOGIN_TEXT = {
	'browser': 'Browser Use needs a key. Opening sign-in; approve access to continue this run.',
	'device': 'Browser Use needs a key. No browser opens here (SSH or no desktop): approve the code below on any device to continue this run.',
}


def _available_key(key: str, source: str, what: str, gate: str | None = None) -> str:
	key = clean_api_key(key, source, what, gate)
	with _key_sources_lock:
		report = source not in _reported_key_sources
		if report:
			_reported_key_sources.add(source)
	if report:
		record_auth_event('key_available', method='env' if source == 'BROWSER_USE_API_KEY' else 'stored')
	return key


def _login_for_key(what: str, gate: str | None = None, method: str = 'browser') -> str:
	"""One automatic login per process (concurrent runs wait for it, and use the key it stores). Bounded: the browser
	login waits 600 s, a device code until it expires. Ctrl-C ends it, and the run, with the missing-key error."""
	global _login_attempted
	with _login_lock:
		from browser_harness.auth import stored_auth_record

		if key := (stored_auth_record() or {}).get('api_key'):
			return _available_key(str(key), STORED, what, gate)
		if _login_attempted:
			raise MissingAPIKeyError(what, gate=gate)
		_login_attempted = True
		from browser_use.cli import _run_login_command

		try:
			with _ctrl_c_interrupts():
				print(AUTO_LOGIN_TEXT[method], file=sys.stderr, flush=True)
				code = _run_login_command(['--device-code'] if method == 'device' else [], automatic=True)
		except KeyboardInterrupt:
			code = 130
		except Exception as e:  # a token poll that timed out reading (TimeoutError), a reply not JSON: still the key error
			raise MissingAPIKeyError(what, gate=gate) from e
		if code == 0 and (key := (stored_auth_record() or {}).get('api_key')):
			return _available_key(str(key), STORED, what, gate)
		raise MissingAPIKeyError(what, gate=gate)


@contextmanager
def _ctrl_c_interrupts() -> Iterator[None]:
	"""Ctrl-C raises KeyboardInterrupt while the login waits. Under asyncio.run and run_sync the first Ctrl-C only
	cancels the run's task, which a blocking wait never sees: the login went on until its 600 s timeout."""
	if threading.current_thread() is not threading.main_thread():
		yield
		return
	previous = signal.getsignal(signal.SIGINT)
	if previous in (signal.SIG_IGN, None):  # nohup, a background job: Ctrl-C stays off
		yield
		return
	signal.signal(signal.SIGINT, signal.default_int_handler)
	try:
		yield
	finally:
		signal.signal(signal.SIGINT, previous)


def clean_api_key(key: str, source: str, what: str = 'Browser Use Cloud', gate: str | None = None) -> str:
	"""The key without surrounding whitespace (a trailing newline from a file or `echo`). Whitespace or a control
	character inside it raises without the key in the message: an HTTP client would reject the header and print it."""
	key = key.strip()
	if not key.isascii() or any(c.isspace() or not c.isprintable() for c in key):
		raise MissingAPIKeyError(
			what,
			f'The key in {source} has a space, line break, control or non-ASCII character inside it (not shown); copy the key '
			f'again from {keys_url(gate)} and paste it without them.',
			gate=gate,
			key_reason='bad_chars',
		)
	return key


def harness_dir_setting(path: object) -> str:
	"""The setting that chose browser-harness dir path: BH_CONFIG_DIR, BH_RUNTIME_DIR, BH_TMP_DIR or BH_AGENT_WORKSPACE
	when set to it or a dir around it (each overrides BH_HOME for its dir), else BH_HOME."""
	try:
		failed = Path(str(path)).expanduser().resolve() if path else None
	except (OSError, RuntimeError, ValueError):  # it only picks the hint: an unresolvable path keeps the BH_HOME one
		failed = None
	for name in ('BH_CONFIG_DIR', 'BH_RUNTIME_DIR', 'BH_TMP_DIR', 'BH_AGENT_WORKSPACE'):
		if failed is None or not (raw := os.environ.get(name)):
			continue
		try:
			base = Path(raw).expanduser().resolve()
		except (OSError, RuntimeError, ValueError):  # a malformed override ('~nouser/x', a NUL): skip it
			continue
		if failed.is_relative_to(base) or base.is_relative_to(failed):
			return name
	return 'BH_HOME'


def browser_use_api_key(
	what: str = 'Browser Use Cloud', gate: str | None = None, fallback: str | None = None, *, auto_login: bool = False
) -> str:
	"""BROWSER_USE_API_KEY, else the key `browser-use login` stored, else fallback (the key of a gateway model the same
	Agent runs). gate (what needs it: default_model, gateway_model, web_search, cloud_browser) goes on the error and the
	library_auth missing_key event. auto_login: a missing key at an interactive terminal starts a login
	(auto_login_method) and the call returns the key it stored."""
	key = os.environ.get('BROWSER_USE_API_KEY')
	try:
		if key and key.strip():
			return _available_key(key, 'BROWSER_USE_API_KEY', what, gate)
		try:
			return _stored_api_key(what, gate)
		except MissingAPIKeyError:
			if fallback:
				return fallback
			raise
	except MissingAPIKeyError as e:
		record_auth_event('missing_key', automatic=auto_login, key_gate=gate, key_reason=e.key_reason)
		if auto_login and e.key_reason == 'missing' and (method := auto_login_method()):
			return _login_for_key(what, gate, method)
		raise


def _stored_api_key(what: str, gate: str | None) -> str:
	from browser_harness.auth import AuthError, stored_auth_record

	try:
		record = stored_auth_record() or {}
	except (AuthError, AttributeError):  # not valid JSON, or JSON that is not an object (a list): say the store is bad
		raise MissingAPIKeyError(what, corrupt_store_message(), gate=gate, key_reason='corrupt_store') from None
	except OSError as e:  # an unwritable HOME: browser-harness creates its config dir to look for the stored key
		raise MissingAPIKeyError(
			what,
			f'Set BROWSER_USE_API_KEY, or set {harness_dir_setting(e.filename)} to a writable dir only this user can write '
			f'to: the dir of the key `browser-use login` stores, {e.filename or ""}, cannot be created ({e.strerror or e}).',
			gate=gate,
			key_reason='unwritable_store',
		) from None
	if not record.get('api_key'):
		raise MissingAPIKeyError(what, gate=gate)
	# Scopes are the server's to judge: a key it rejects (an older login's v3 browser-only key) gets a 403 that the
	# cloud and gateway errors turn into "run `browser-use login` again".
	return _available_key(str(record['api_key']), STORED, what, gate)


def cloud_error_text(status: int, detail: str) -> str:
	"""'HTTP 401 <detail>. <hint>' for a Browser Use Cloud error. The detail's own final period is dropped, and none is
	added after a detail that ends with a link: a terminal would make the period part of it."""
	detail = detail.strip()[:500].rstrip('.')
	end = '' if re.search(r'https?://\S+$', detail) else '.'
	return f'HTTP {status} {detail}{end}{cloud_error_hint(status, detail)}'


def cloud_error_hint(status: int, detail: str) -> str:
	"""The fix for a Browser Use Cloud error, as a sentence to append ('' when the key is not the problem)."""
	if 'missing required scope' in detail:
		hint = (
			' Run `browser-use login` again for a key with v4 access (older logins stored browser-only v3 keys), or '
			f'create one at {keys_url()} and set BROWSER_USE_API_KEY.'
		)
	elif status == 401:
		hint = f' The API key was rejected: run `browser-use login`, or create a key at {keys_url()} and set BROWSER_USE_API_KEY.'
	else:
		return ''
	if os.environ.get('BROWSER_USE_API_KEY'):
		hint += ' BROWSER_USE_API_KEY is set and wins over the key `browser-use login` stored: fix or unset it.'
	return hint


def corrupt_store_message() -> str:
	from browser_harness.auth import auth_path

	return (
		f'The Browser Use key store {auth_path()} is corrupt (not a valid JSON object). Run `browser-use login` to replace it '
		'(the old file is kept next to it as auth.json.corrupt), or `browser-use logout` to remove it.'
	)


def corrupt_store_path():
	"""The key store's path when it exists but is not valid JSON, else None."""
	from browser_harness.auth import AuthError, auth_path, load_auth_file

	try:
		data = load_auth_file()
	except AuthError:
		return auth_path()
	return None if isinstance(data, dict) else auth_path()


def set_aside_corrupt_store() -> str | None:
	"""Before a login: move a corrupt key store to auth.json.corrupt so the new key can be saved. Returns a notice."""
	path = corrupt_store_path()
	if path is None:
		return None
	backup, n = path.with_name(path.name + '.corrupt'), 1
	while backup.exists():  # an earlier corrupt store may hold the only copy of a key: keep it
		n += 1
		backup = path.with_name(f'{path.name}.corrupt.{n}')
	os.replace(path, backup)
	return f'The key store {path} was corrupt (not a valid JSON object); moved it to {backup}.'


def harden_login_callback() -> None:
	"""browser-harness's OAuth loopback callback treats any request with a wrong `state` as the login's answer: it
	aborts the pending login and still shows "login complete". Ignore such requests instead (400, nothing changes)."""
	from browser_harness import auth

	if getattr(auth._callback_server, '__bu_strict_state__', False):
		return
	original = auth._callback_server

	def callback_server(callback):
		server = original(callback)
		handler = server.RequestHandlerClass  # a class made per login, so patching it touches only this server
		answer = handler.do_GET  # type: ignore[attr-defined]

		def do_GET(self):  # - stdlib handler API
			parsed = urllib.parse.urlparse(self.path)
			state = urllib.parse.parse_qs(parsed.query).get('state', [None])[0]
			if parsed.path == auth.CALLBACK_PATH and state != callback.state:
				body = b'<html><body><h1>Not your Browser Use login</h1><p>This link does not match the sign-in in progress. Nothing changed.</p></body></html>'
				self.send_response(400)
				self.send_header('Content-Type', 'text/html; charset=utf-8')
				self.send_header('Content-Length', str(len(body)))
				self.end_headers()
				self.wfile.write(body)
				return
			answer(self)

		handler.do_GET = do_GET  # type: ignore[attr-defined]
		return server

	callback_server.__bu_strict_state__ = True  # type: ignore[attr-defined]
	auth._callback_server = callback_server


# --- signing in: `browser-use login`, browser_use.login() and the login a run starts on a missing key ---

DEVICE_CODE_HINT = 'No browser on this machine, or approving on another one? Run `browser-use login --device-code`.'


def login_method(open_url: bool = True) -> str:
	"""'device' where a browser this opens cannot reach this machine's 127.0.0.1 loopback callback (SSH, Linux without a
	display, no browser Python can open), else 'browser' (one click, no code to compare). open_url=False (--no-open):
	'browser', the link is printed for a browser the user opens."""
	import webbrowser

	if not open_url:
		return 'browser'
	if not can_open_browser():
		return 'device'
	try:
		webbrowser.get()
	except webbrowser.Error:
		return 'device'
	return 'browser'


def can_open_browser() -> bool:
	"""A browser can open here for the person at this machine. Not over SSH or on Linux without a display, where
	Python's webbrowser would start a text browser (lynx, w3m) in the terminal, or open one nobody sees."""
	from browser_use.utils import has_display, is_ssh

	return has_display() and not is_ssh()


def login_outcome(e: BaseException) -> str:
	"""A failed login as an enum (library_auth outcome): never its message, which can quote a server's text."""
	import asyncio

	if isinstance(e, KeyboardInterrupt | asyncio.CancelledError | EOFError):
		return 'cancelled'
	text = str(e).lower()
	if 'timed out waiting for browser auth' in text:
		return 'callback_timeout'
	if 'timed out waiting for device auth' in text or 'expired_token' in text:
		return 'device_timeout'
	if 'network error' in text or isinstance(e, OSError):
		return 'network'
	if 'denied' in text:
		return 'denied'
	if any(w in text for w in ('api key', 'rejected that key', 'start with bu_', 'line break', 'too short')):
		return 'invalid_key'
	return 'error'


def mark_device_login() -> None:
	"""browser-harness stores a device-code login as source 'oauth': mark it, so key_source tells the two apart. Only
	telemetry reads it: off, the key file is left as the login wrote it (off means no file written for telemetry)."""
	from browser_harness import auth

	from browser_use.telemetry.service import telemetry

	try:
		if not telemetry().enabled:
			return
		record = auth.stored_auth_record()
		if record and record.get('source') == 'oauth':
			auth.save_auth_record(auth.AuthRecord(**{**record, 'source': 'device_code'}))
	except Exception:  # - only telemetry reads it: the key is stored either way
		pass


def sign_in(method: str, *, open_url: bool, out) -> None:
	"""One login, start to stored key, printing the link (and the code) to out: 'browser' (the loopback callback; 600 s
	at most) or 'device' (a code to approve on any device, until it expires). The caller hardens the callback first."""
	from browser_harness import auth

	if method == 'device':
		start = auth.start_device_auth(open_url=False)  # opened here: not after a Ctrl-C during its request
		if open_url:
			_open(start.open_uri)
		print(f'Approve Browser Use access on any device: {start.open_uri} (code {start.user_code})', file=out, flush=True)
		auth.complete_device_auth(start)
		mark_device_login()
		return
	start = auth.start_browser_auth(open_url=open_url)
	print(f'Approve Browser Use access: {start.auth_url}', file=out, flush=True)
	auth.complete_browser_auth(start)


def _open(url: str) -> bool:
	import webbrowser

	try:
		return bool(webbrowser.open(url))
	except Exception:  # - no browser: the link is printed either way
		return False


def login(method: str | None = None) -> None:
	"""Sign in to Browser Use Cloud from Python (a notebook cell, Colab, a script): prints a link (and a code), waits for
	the approval and stores the key where `browser-use login` does; later runs in any process use it, no restart.
	method: 'browser' | 'device'; default: a device code in a notebook, over SSH or without a display."""
	if method not in (None, 'browser', 'device'):
		raise ValueError(f"method must be 'browser', 'device' or None, not {method!r}")
	notebook = 'ipykernel' in sys.modules
	method = method or ('device' if notebook else login_method())
	harden_login_callback()
	if notice := set_aside_corrupt_store():
		print(notice)
	record_auth_event('login_started', method=method)
	try:
		sign_in(method, open_url=not notebook and can_open_browser(), out=sys.stdout)
	except BaseException as e:
		outcome = login_outcome(e)
		record_auth_event('login_cancelled' if outcome == 'cancelled' else 'login_failed', method=method, outcome=outcome)
		raise
	record_auth_event('login_succeeded', method=method)
	print('Signed in. The key is saved for every later run.')
