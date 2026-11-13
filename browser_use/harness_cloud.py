"""Cloud browsers in the browser-use CLI and MCP server, which run piped code against browser-harness daemons.

Rules browser-harness alone does not keep for them:
- After start_remote_daemon(name), every helper in this process drives that daemon, wherever it appears in the code.
- A daemon name that ran a cloud browser never falls back to the user's local Chrome. browser-harness replaces a stale
  cloud daemon with a local-Chrome one under the same name; here the call fails with one line instead.
- Cloud errors (bad key, rejected arguments, corrupt key store) are one line with the server's detail and the fix.
- The live-view and CDP URLs (each grants control of the browser) are neither opened nor returned unless
  BH_OPEN_LIVE_URL is on.
- A recorded cloud browser is never forgotten while it may still bill: its id stays recorded until a stop succeeds, a
  new start under the same name stops it first, and stop_remote_daemon stops it even when its daemon was killed.
- upload_file sends the file's bytes through the page while a cloud browser is attached (its host has no local paths).

Which names ran a cloud browser is kept in a `.cloud` file next to the daemon's pid file, holding the browser id until
it is stopped, so a later process (the next CLI call) knows it too.
"""

import ast
import ipaddress
import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from browser_harness import _ipc as ipc
from browser_harness import admin, helpers
from browser_harness.auth import AuthError

from browser_use.auth import clean_api_key, cloud_error_text, corrupt_store_message
from browser_use.exceptions import MissingAPIKeyError
from browser_use.remote_upload import uploader

CLOUD_ADMIN = frozenset({'start_remote_daemon', 'stop_remote_daemon'})


class CloudBrowserError(RuntimeError):
	"""A one-line, user-facing cloud browser error: shown without a traceback."""


def calls_cloud_admin(code: str) -> bool:
	"""Whether code calls start_remote_daemon / stop_remote_daemon anywhere (not only as its first statement)."""
	try:
		tree = ast.parse(code)
	except SyntaxError:
		return False
	for node in ast.walk(tree):
		if isinstance(node, ast.Call):
			func = node.func
			name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
			if name in CLOUD_ADMIN:
				return True
	return False


def _marker(name: str) -> Path:
	return ipc.pid_path(name).with_suffix('.cloud')


def _record(name: str, browser_id: str) -> None:
	"""The id alone drives the cloud browser: 0600, never readable by other local users (Path.write_text made it 0644)."""
	fd = os.open(_marker(name), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
	with os.fdopen(fd, 'w') as f:
		if os.name != 'nt':
			os.fchmod(fd, 0o600)  # a marker an older version wrote keeps its mode through O_CREAT
		f.write(browser_id)


def _recorded_id(name: str) -> str | None:
	"""The cloud browser id recorded for name: None when name never ran one here, '' once it was stopped."""
	try:
		return _marker(name).read_text().strip()
	except FileNotFoundError:
		return None


def was_cloud(name: str) -> bool:
	return _recorded_id(name) is not None or admin.daemon_browser_kind(name) == 'cloud'


def route(name: str, namespace: dict[str, Any] | None = None) -> None:
	"""Send this process's helpers (and later ensure_daemon calls) to daemon name."""
	admin.NAME = helpers.NAME = name
	os.environ['BU_NAME'] = name
	if namespace is not None and 'NAME' in namespace:
		namespace['NAME'] = name


def daemon_healthy(name: str) -> bool:
	"""Whether daemon name still reaches its browser: browser-harness's own stale check, two CDP probes 0.5 s apart."""
	for attempt in range(2):
		try:
			admin.require_existing_daemon(name)
			return True
		except RuntimeError:
			if attempt == 0:
				time.sleep(0.5)
	return False


def stop_cloud(name: str, browser_id: str | None = None) -> bool:
	"""End the cloud browser behind name (or browser_id), even when its daemon was killed. Whether it is stopped: the id
	stays recorded until then, so a later call can retry."""
	recorded = _recorded_id(name)
	browser_id = browser_id or recorded
	if browser_id and browser_id == recorded and admin.daemon_alive(name):
		try:
			admin.stop_remote_daemon(name)  # stops the browser, then the daemon, and removes its socket
		except Exception:
			pass
	if not browser_id:
		return True
	stopped = admin._stop_cloud_browser(browser_id)  # a no-op on a stopped browser; the only way once the daemon is gone
	if stopped and browser_id == recorded:
		_record(name, '')
	return stopped


def _check_socket_path(name: str) -> None:
	"""The OS caps the daemon's AF_UNIX socket path (macOS 104 bytes): a longer one created and billed a cloud browser
	before failing ("stopped remote browser <id>"), or failed locally with "AF_UNIX path too long". Say so first."""
	from browser_use.browser.browser import _check_socket_path

	try:
		_check_socket_path(name)
	except RuntimeError as e:
		raise CloudBrowserError(str(e)) from None


def ensure_daemon(wait: float | None = None, name: str | None = None, env: dict[str, str] | None = None) -> None:
	"""browser-harness's ensure_daemon, except that a name that ran a cloud browser fails closed once it is gone."""
	name = name or admin.NAME
	_check_socket_path(name)
	if env or not was_cloud(name):
		if admin._is_local_chrome_mode(env):  # browser-harness serializes these spawns itself
			from browser_use.browser.local import require_debug_port_unless_attached

			require_debug_port_unless_attached(name)  # never the 127.0.0.1:9222 guess (local.py)
			return admin.ensure_daemon(wait=wait, name=name, env=env)
		require_cdp_url_listening(name, env)
		# BU_CDP_URL / BU_CDP_WS: browser-harness takes no spawn lock there, so concurrent cold CLI calls each started
		# a daemon under one name and orphaned all but one. One spawn at a time (its own lock file: a stale daemon's
		# restart inside ensure_daemon takes browser-harness's).
		lock = admin._spawn_lock(name, timeout=60.0)
		lock.path = ipc.pid_path(name).with_suffix('.cdpspawnlock')
		with lock:
			return admin.ensure_daemon(wait=wait, name=name, env=env)
	os.environ.setdefault('BH_TAB_MARKER', '0')  # helpers mark tab titles client side; cloud pages stay untouched
	if daemon_healthy(name):
		return
	stop_cloud(name)
	raise CloudBrowserError(
		f'Cloud browser {name!r} has ended (cloud timeout, stopped, or its daemon died). It was not replaced with your '
		f'local Chrome. Start a new one: start_remote_daemon({name!r})'
	)


CDP_REFUSED_GRACE_S = 3.0  # a Chrome started just before this call opens its port within that


def require_cdp_url_listening(name: str, env: dict[str, str] | None = None) -> None:
	"""BU_CDP_URL (and no BU_CDP_WS, which wins) whose host refuses connections: nothing listens on that port, yet
	browser-harness retried it for 30 s on every call and then failed. Raise at once with both ways out, unless daemon
	name is still healthy (browser-harness then reuses it and never reads BU_CDP_URL). A port that is no number never
	works: raise at once too. A timeout, DNS, an HTTP error, or a proxy urllib uses for a host off this machine stays
	browser-harness's to retry and report."""
	merged = {**os.environ, **(env or {})}
	url = merged.get('BU_CDP_URL')
	if not url or merged.get('BU_CDP_WS'):
		return
	dedicated = '--user-data-dir=<a dir of its own>'
	try:
		u = urllib.parse.urlsplit(url)
		shown = f'{u.scheme}://{u.netloc.rpartition("@")[2]}'  # never the user:password@, path or query (a token)
		port = u.port
	except ValueError:
		scheme, sep, rest = url.partition('://')
		shown = scheme + sep + rest.split('/')[0].split('?')[0].rpartition('@')[2]
		raise RuntimeError(
			f'BU_CDP_URL={shown} is not a valid http://HOST:PORT URL. Set it to http://127.0.0.1:PORT where PORT is the number a Chrome '
			f'started with --remote-debugging-port=PORT {dedicated} listens on{_WAYS_OUT}'
		) from None
	host = u.hostname
	if not host:
		return
	if port is None:  # urllib dials the scheme's port; a remote https endpoint can serve DevTools there
		port = 443 if u.scheme in ('https', 'wss') else 80
		fix = (
			f'It names no port, so {port} was tried. Set it to http://127.0.0.1:PORT of a Chrome started with '
			f'--remote-debugging-port=PORT {dedicated}'
		)
	else:
		fix = f'Start Chrome with --remote-debugging-port={port} {dedicated}'
	if urllib.request.getproxies().get(u.scheme) and not _loopback(host) and not urllib.request.proxy_bypass(host):
		return  # browser-harness's urllib reaches it through that proxy, not directly
	deadline, checked = time.monotonic() + CDP_REFUSED_GRACE_S, False
	while True:
		try:
			socket.create_connection((host, port), timeout=5).close()  # Windows takes ~2 s to report a refusal
			return
		except ConnectionRefusedError:
			if not checked and admin.daemon_alive(name) and daemon_healthy(name):
				return
			checked = True
			if time.monotonic() >= deadline:
				break
			time.sleep(0.25)
		except OSError:
			return
	raise RuntimeError(f'BU_CDP_URL={shown} refused the connection: no browser listens on {host}:{port}. {fix}{_WAYS_OUT}')


_WAYS_OUT = (
	', or unset BU_CDP_URL and browser-use finds a browser itself (your Chrome with remote debugging on; --cli-mcp falls '
	"back to its own Chromium). For an MCP server, change it in the server's env in the MCP config, then restart the "
	'server.'
)


def _loopback(host: str) -> bool:
	try:
		return host == 'localhost' or ipaddress.ip_address(host).is_loopback
	except ValueError:
		return False


def start(name: str, profile_name: str | None, create_kwargs: dict[str, Any], namespace: dict[str, Any] | None) -> dict:
	"""browser-harness's start_remote_daemon with one-line errors, then route this process to the new daemon."""
	os.environ.setdefault('BH_TAB_MARKER', '0')  # the daemon spawned below inherits it
	_check_socket_path(name)
	if admin.daemon_alive(name):
		raise CloudBrowserError(f'Daemon {name!r} is already running: stop_remote_daemon({name!r}) first, or use another name')
	previous = _recorded_id(name)
	if previous and not stop_cloud(name):  # its daemon was killed: the new id would overwrite the only record of it
		raise CloudBrowserError(
			f'Cloud browser {previous} ({name!r}) from an earlier start could not be stopped, so no new one was started. '
			f'Retry start_remote_daemon({name!r}) or stop_remote_daemon({name!r}).'
		)
	if key := os.environ.get('BROWSER_USE_API_KEY'):  # browser-harness sends it as is: a newline in it would be printed
		try:
			os.environ['BROWSER_USE_API_KEY'] = clean_api_key(key, 'BROWSER_USE_API_KEY')
		except MissingAPIKeyError as e:
			raise CloudBrowserError(str(e)) from None
	try:
		browser = admin.start_remote_daemon(name, profile_name, **create_kwargs)
	except ValueError as e:  # http.client: "Invalid header value b'<the key>'" (a key from the store)
		if 'header' not in str(e).lower():
			raise
		raise CloudBrowserError(
			'The Browser Use API key has characters an HTTP header cannot carry (not shown); run `browser-use login` again.'
		) from None
	except urllib.error.HTTPError as e:
		detail = e.read().decode(errors='replace')
		raise CloudBrowserError(f'Browser Use Cloud refused to start a browser: {cloud_error_text(e.code, detail)}') from None
	except urllib.error.URLError as e:
		raise CloudBrowserError(f'Could not reach Browser Use Cloud: {e.reason}') from None
	except AuthError:
		raise CloudBrowserError(corrupt_store_message()) from None
	_record(name, str(browser.get('id') or ''))
	route(name, namespace)
	if not admin._should_show_remote_live_view():
		browser = {k: v for k, v in browser.items() if k not in ('liveUrl', 'cdpUrl')}
	return browser


def stop(name: str = 'remote') -> None:
	"""stop_remote_daemon: stops the recorded cloud browser even when its daemon is gone (killed, OOM)."""
	recorded = _recorded_id(name)
	if not recorded:  # no cloud browser recorded here: browser-harness's own stop, which needs a live daemon
		if admin.daemon_alive(name):
			admin.stop_remote_daemon(name)
		elif recorded is None:
			raise CloudBrowserError(f'No cloud browser {name!r} is running here: nothing to stop')
		return  # '': stopped already (a second stop after the first one, or after a timeout was noticed)
	if not stop_cloud(name):
		raise CloudBrowserError(f'Could not stop cloud browser {recorded} ({name!r}); retry stop_remote_daemon({name!r})')


def forget(name: str) -> None:
	"""Let name drive a local Chrome again (`BU_NAME=<name> browser-use --reload`). A cloud browser still recorded there is
	stopped first: the record is the only way to stop it once its daemon is gone, so it stays when the stop fails."""
	if (recorded := _recorded_id(name)) and not stop_cloud(name):
		raise CloudBrowserError(
			f'Could not stop cloud browser {recorded} ({name!r}); retry `BU_NAME={name} browser-use --reload`'
		)
	_marker(name).unlink(missing_ok=True)


def install(namespace: dict[str, Any]) -> None:
	"""Put the guarded ensure_daemon / start_remote_daemon / stop_remote_daemon / upload_file into an exec namespace."""
	os.environ.setdefault('BH_OPEN_LIVE_URL', '0')  # the live URL grants control: not printed, opened or returned

	def start_remote_daemon(name: str = 'remote', profileName: str | None = None, **create_kwargs: Any) -> dict:
		return start(name, profileName, create_kwargs, namespace)

	start_remote_daemon.__doc__ = admin.start_remote_daemon.__doc__
	namespace['ensure_daemon'] = ensure_daemon
	namespace['upload_file'] = uploader(helpers.cdp, lambda: was_cloud(admin.NAME))
	namespace['start_remote_daemon'] = start_remote_daemon
	namespace['stop_remote_daemon'] = stop
