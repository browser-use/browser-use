"""Cloud browsers in the browser-use CLI and MCP server, which run piped code against browser-harness daemons.

Rules browser-harness alone does not keep for them:
- After start_remote_daemon(name), every helper in this process drives that daemon, wherever it appears in the code.
- A daemon name that ran a cloud browser never falls back to the user's local Chrome. browser-harness replaces a stale
  cloud daemon with a local-Chrome one under the same name; here the call fails with one line instead.
- Cloud errors (bad key, rejected arguments, corrupt key store) are one line with the server's detail and the fix.
- The live-view URL (it grants control of the browser) is neither opened nor returned unless BH_OPEN_LIVE_URL is on.

Which names ran a cloud browser is kept in a `.cloud` file next to the daemon's pid file, holding the browser id until
it is stopped, so a later process (the next CLI call) knows it too.
"""

import ast
import os
import time
import urllib.error
from pathlib import Path
from typing import Any

from browser_harness import _ipc as ipc
from browser_harness import admin, helpers
from browser_harness.auth import AuthError

from browser_use.auth import cloud_error_hint, corrupt_store_message

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


def _healthy(name: str) -> bool:
	for attempt in range(2):  # browser-harness's own stale check: two CDP probes 0.5 s apart
		try:
			admin.require_existing_daemon(name)
			return True
		except RuntimeError:
			if attempt == 0:
				time.sleep(0.5)
	return False


def stop_cloud(name: str, browser_id: str | None = None) -> None:
	"""Best effort: end the cloud browser behind name (or browser_id), even when its daemon was killed."""
	recorded = _recorded_id(name)
	browser_id = browser_id or recorded
	if browser_id and browser_id == recorded and admin.daemon_alive(name):
		try:
			admin.stop_remote_daemon(name)  # stops the browser, then the daemon, and removes its socket
		except Exception:
			pass
	if browser_id:
		admin._stop_cloud_browser(browser_id)  # a no-op on a stopped browser; the only way once the daemon is gone
		if browser_id == recorded:
			_marker(name).write_text('')


def ensure_daemon(wait: float | None = None, name: str | None = None, env: dict[str, str] | None = None) -> None:
	"""browser-harness's ensure_daemon, except that a name that ran a cloud browser fails closed once it is gone."""
	name = name or admin.NAME
	if env or not was_cloud(name):
		return admin.ensure_daemon(wait=wait, name=name, env=env)
	os.environ.setdefault('BH_TAB_MARKER', '0')  # helpers mark tab titles client side; cloud pages stay untouched
	if _healthy(name):
		return
	stop_cloud(name)
	raise CloudBrowserError(
		f'Cloud browser {name!r} has ended (cloud timeout, stopped, or its daemon died). It was not replaced with your '
		f'local Chrome. Start a new one: start_remote_daemon({name!r})'
	)


def start(name: str, profile_name: str | None, create_kwargs: dict[str, Any], namespace: dict[str, Any] | None) -> dict:
	"""browser-harness's start_remote_daemon with one-line errors, then route this process to the new daemon."""
	os.environ.setdefault('BH_TAB_MARKER', '0')  # the daemon spawned below inherits it
	try:
		browser = admin.start_remote_daemon(name, profile_name, **create_kwargs)
	except urllib.error.HTTPError as e:
		detail = e.read().decode(errors='replace').strip()[:500]
		raise CloudBrowserError(
			f'Browser Use Cloud refused to start a browser: HTTP {e.code} {detail}.{cloud_error_hint(e.code, detail)}'
		) from None
	except urllib.error.URLError as e:
		raise CloudBrowserError(f'Could not reach Browser Use Cloud: {e.reason}') from None
	except AuthError:
		raise CloudBrowserError(corrupt_store_message()) from None
	_marker(name).write_text(str(browser.get('id') or ''))
	route(name, namespace)
	if not admin._should_show_remote_live_view():
		browser = {k: v for k, v in browser.items() if k != 'liveUrl'}
	return browser


def stop(name: str = 'remote') -> None:
	admin.stop_remote_daemon(name)
	if _recorded_id(name):
		_marker(name).write_text('')


def forget(name: str) -> None:
	"""Let name drive a local Chrome again (`BU_NAME=<name> browser-use --reload`)."""
	_marker(name).unlink(missing_ok=True)


def install(namespace: dict[str, Any]) -> None:
	"""Put the guarded ensure_daemon / start_remote_daemon / stop_remote_daemon into an exec namespace."""
	os.environ.setdefault('BH_OPEN_LIVE_URL', '0')  # the live URL grants control: not printed, opened or returned

	def start_remote_daemon(name: str = 'remote', profileName: str | None = None, **create_kwargs: Any) -> dict:
		return start(name, profileName, create_kwargs, namespace)

	start_remote_daemon.__doc__ = admin.start_remote_daemon.__doc__
	namespace['ensure_daemon'] = ensure_daemon
	namespace['start_remote_daemon'] = start_remote_daemon
	namespace['stop_remote_daemon'] = stop
