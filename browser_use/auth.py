"""The Browser Use API key: BROWSER_USE_API_KEY, else the key `browser-use login` stored (browser-harness's store)."""

import os
import re
import urllib.parse
from pathlib import Path

from browser_use.exceptions import MissingAPIKeyError

KEYS_URL = 'https://cloud.browser-use.com/settings?tab=api-keys'


def clean_api_key(key: str, source: str, what: str = 'Browser Use Cloud') -> str:
	"""The key without surrounding whitespace (a trailing newline from a file or `echo`). Whitespace or a control
	character inside it raises without the key in the message: an HTTP client would reject the header and print it."""
	key = key.strip()
	if not key.isascii() or any(c.isspace() or not c.isprintable() for c in key):
		raise MissingAPIKeyError(
			what,
			f'The key in {source} has a space, line break, control or non-ASCII character inside it (not shown); copy the key '
			f'again from {KEYS_URL} and paste it without them.',
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


def browser_use_api_key(what: str = 'Browser Use Cloud') -> str:
	key = os.environ.get('BROWSER_USE_API_KEY')
	if key and key.strip():
		return clean_api_key(key, 'BROWSER_USE_API_KEY', what)
	from browser_harness.auth import AuthError, stored_auth_record

	try:
		record = stored_auth_record() or {}
	except (AuthError, AttributeError):  # not valid JSON, or JSON that is not an object (a list): say the store is bad
		raise MissingAPIKeyError(what, corrupt_store_message()) from None
	except OSError as e:  # an unwritable HOME: browser-harness creates its config dir to look for the stored key
		raise MissingAPIKeyError(
			what,
			f'Set BROWSER_USE_API_KEY, or set {harness_dir_setting(e.filename)} to a writable dir only this user can write '
			f'to: the dir of the key `browser-use login` stores, {e.filename or ""}, cannot be created ({e.strerror or e}).',
		) from None
	if not record.get('api_key'):
		raise MissingAPIKeyError(what)
	# Scopes are the server's to judge: a key it rejects (an older login's v3 browser-only key) gets a 403 that the
	# cloud and gateway errors turn into "run `browser-use login` again".
	return clean_api_key(str(record['api_key']), 'the key `browser-use login` stored', what)


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
			f'create one at {KEYS_URL} and set BROWSER_USE_API_KEY.'
		)
	elif status == 401:
		hint = f' The API key was rejected: run `browser-use login`, or create a key at {KEYS_URL} and set BROWSER_USE_API_KEY.'
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
