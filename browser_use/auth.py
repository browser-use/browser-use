"""The Browser Use API key: BROWSER_USE_API_KEY, else the key `browser-use login` stored (browser-harness's store)."""

import os
import urllib.parse

from browser_use.exceptions import MissingAPIKeyError

KEYS_URL = 'https://cloud.browser-use.com/settings?tab=api-keys'


def browser_use_api_key(what: str = 'Browser Use Cloud') -> str:
	key = os.environ.get('BROWSER_USE_API_KEY')
	if key:
		return key
	from browser_harness.auth import AuthError, stored_auth_record

	try:
		record = stored_auth_record() or {}
	except AuthError:  # the store is not valid JSON: say so, a "no key" message would send the user in circles
		raise MissingAPIKeyError(what, corrupt_store_message()) from None
	if not record.get('api_key'):
		raise MissingAPIKeyError(what)
	# Scopes are the server's to judge: a key it rejects (an older login's v3 browser-only key) gets a 403 that the
	# cloud and gateway errors turn into "run `browser-use login` again".
	return str(record['api_key'])


def cloud_error_hint(status: int, detail: str) -> str:
	"""The fix for a Browser Use Cloud error, as a sentence to append ('' when the key is not the problem)."""
	if 'missing required scope' in detail:
		hint = (
			' Run `browser-use login` again for a key with v4 access (older logins stored browser-only v3 keys), or '
			f'create one at {KEYS_URL} and set BROWSER_USE_API_KEY.'
		)
	elif status == 401:
		hint = f' The API key was rejected: run `browser-use login`, or create a key at {KEYS_URL}.'
	else:
		return ''
	if os.environ.get('BROWSER_USE_API_KEY'):
		hint += ' BROWSER_USE_API_KEY is set and wins over the key `browser-use login` stored: fix or unset it.'
	return hint


def corrupt_store_message() -> str:
	from browser_harness.auth import auth_path

	return (
		f'The Browser Use key store {auth_path()} is corrupt (not valid JSON). Run `browser-use login` to replace it '
		'(the old file is kept next to it as auth.json.corrupt), or `browser-use logout` to remove it.'
	)


def corrupt_store_path():
	"""The key store's path when it exists but is not valid JSON, else None."""
	from browser_harness.auth import AuthError, auth_path, load_auth_file

	try:
		load_auth_file()
	except AuthError:
		return auth_path()
	return None


def set_aside_corrupt_store() -> str | None:
	"""Before a login: move a corrupt key store to auth.json.corrupt so the new key can be saved. Returns a notice."""
	path = corrupt_store_path()
	if path is None:
		return None
	backup = path.with_name(path.name + '.corrupt')
	os.replace(path, backup)
	return f'The key store {path} was corrupt (not valid JSON); moved it to {backup}.'


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

		def do_GET(self):  # noqa: N802 - stdlib handler API
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
