"""`browser-use login`, the browser_login MCP tool and the shared key store, against a fake Browser Use auth server.

The fake server speaks the cloud's /cloud/cli-auth contract (browser OAuth with PKCE). "The user approves" is a GET of
the CLI's loopback callback, as the approve page's redirect does. No test opens a real browser or reads a real key.
"""

import base64
import hashlib
import json
import os
import subprocess
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FAKE_KEY = 'bu_' + 'f' * 40  # shaped like a real key, so the redaction rule would catch a leak


class FakeAuthServer:
	def __init__(self, auto_approve: bool):
		self.auto_approve = auto_approve
		self.starts: list[dict] = []
		self.tokens: list[dict] = []
		owner = self

		class Handler(BaseHTTPRequestHandler):
			def do_POST(self):
				body = json.loads(self.rfile.read(int(self.headers['Content-Length'])) or b'{}')
				if self.path == '/cloud/cli-auth/browser':
					owner.starts.append(body)
					if owner.auto_approve:
						threading.Thread(target=owner.approve, daemon=True).start()
					self._json(
						200, {'authorization_uri': f'{owner.url}/device/authorize?state={body["state"]}', 'expires_in': 600}
					)
				elif self.path == '/cloud/cli-auth/device':
					self._json(200, {'device_code': 'd1', 'user_code': 'ABCD-1234', 'verification_uri': owner.url, 'interval': 1})
				elif self.path == '/cloud/cli-auth/token' and body.get('device_code'):
					self._json(400, {'error': 'authorization_pending'})  # the user never approves
				elif self.path == '/cloud/cli-auth/token':
					owner.tokens.append(body)
					start = owner.starts[-1]
					challenge = base64.urlsafe_b64encode(hashlib.sha256(body['code_verifier'].encode()).digest()).rstrip(b'=')
					if body['code'] != 'approved-code' or challenge.decode() != start['code_challenge']:
						self._json(400, {'error': 'invalid_grant'})
					else:
						self._json(200, {'api_key': FAKE_KEY, 'api_key_id': 'k1', 'project_id': 'p1', 'scopes': ['*:*:*']})
				else:
					self._json(404, {})

			def do_GET(self):  # the key check of `login --api-key-stdin`
				ok = self.path.startswith('/api/v4/browsers') and self.headers['X-Browser-Use-API-Key'] == FAKE_KEY
				self._json(200 if ok else 401, {'items': []} if ok else {'detail': 'Invalid API key.'})

			def _json(self, status, data):
				raw = json.dumps(data).encode()
				self.send_response(status)
				self.send_header('Content-Type', 'application/json')
				self.send_header('Content-Length', str(len(raw)))
				self.end_headers()
				self.wfile.write(raw)

			def log_message(self, *args):
				pass

		self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
		self.url = f'http://127.0.0.1:{self.server.server_address[1]}'
		threading.Thread(target=self.server.serve_forever, daemon=True).start()

	def approve(self):
		"""What the approve page does: redirect the user's browser to the CLI's loopback callback."""
		start = self.starts[-1]
		urllib.request.urlopen(f'{start["redirect_uri"]}?code=approved-code&state={start["state"]}', timeout=10).read()


@pytest.fixture
def store(tmp_path, monkeypatch):
	"""A private key store and no key in the environment."""
	path = tmp_path / 'browser-harness' / 'auth.json'
	monkeypatch.setenv('BH_AUTH_PATH', str(path))
	monkeypatch.delenv('BROWSER_USE_API_KEY', raising=False)
	return path


@pytest.fixture
def auth_server(monkeypatch):
	"""auth_server(auto_approve) starts a FakeAuthServer the CLI talks to; it is shut down after the test."""
	servers: list[FakeAuthServer] = []

	def start(auto_approve: bool) -> FakeAuthServer:
		servers.append(FakeAuthServer(auto_approve))
		monkeypatch.setenv('BROWSER_USE_CLOUD_API_URL', servers[-1].url)
		return servers[-1]

	yield start
	for server in servers:
		server.server.shutdown()
		server.server.server_close()


def _cli(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
	env = os.environ.copy()
	env['PYTHONPATH'] = os.pathsep.join(part for part in (str(ROOT), env.get('PYTHONPATH', '')) if part)
	env.pop('BH_DEVICE_NAME', None)
	# a desktop session: without one (SSH, a Linux server) `login` signs in with a device code (test_missing_key.py)
	env.update(DISPLAY=':0')
	for var in ('SSH_CONNECTION', 'SSH_TTY'):
		env.pop(var, None)
	return subprocess.run(
		[sys.executable, '-m', 'browser_use', *args], cwd=ROOT, env=env, input=stdin, capture_output=True, text=True, timeout=60
	)


def test_login_stores_the_key_in_the_shared_store_without_printing_it(store, monkeypatch, auth_server):
	server = auth_server(auto_approve=True)
	result = _cli('login', '--no-open')
	assert result.returncode == 0, result.stderr
	assert FAKE_KEY not in result.stdout + result.stderr
	assert server.starts[0]['client_id'] == 'browser-use-terminal' and server.starts[0]['device_name'] == 'browser-use'
	assert 'Signed in' in result.stdout and 'browser-use --cli-mcp' in result.stdout
	# rr-install 2: `python -c` named a command uv projects lack (`uv run browser-use login`); the code is the example
	assert 'python -c' not in result.stdout and '  from browser_use import Agent\n' in result.stdout
	assert json.loads(store.read_text())['browser_use']['api_key'] == FAKE_KEY
	if sys.platform != 'win32':
		assert store.stat().st_mode & 0o077 == 0  # owner-only

	# One login works everywhere: the library, browser-harness, and the default model all read that store
	from browser_harness.auth import get_browser_use_api_key

	from browser_use.auth import browser_use_api_key
	from browser_use.llm import ChatBrowserUse

	assert browser_use_api_key() == get_browser_use_api_key() == FAKE_KEY
	assert ChatBrowserUse().pydantic_model().client.api_key == FAKE_KEY
	monkeypatch.setenv('BROWSER_USE_API_KEY', 'fake-env-key-wins-over-the-store')
	assert browser_use_api_key() == 'fake-env-key-wins-over-the-store'

	result = _cli('logout')
	assert result.returncode == 0 and '"logged-out"' in result.stdout
	assert not store.exists()


def test_login_failure_exits_nonzero_and_stores_nothing(store, monkeypatch):
	monkeypatch.setenv('BROWSER_USE_CLOUD_API_URL', 'http://127.0.0.1:9')  # nothing listens: the start request fails
	result = _cli('login', '--no-open')
	assert result.returncode == 1 and 'network error' in result.stderr
	assert 'Signed in' not in result.stdout
	assert not store.exists()


@pytest.mark.skipif(sys.platform == 'win32', reason='SIGINT to a child process is POSIX')
def test_ctrl_c_during_device_login_cancels_without_a_traceback(store, auth_server):
	"""rc5 cli-5: Ctrl-C while `login --device-code` waited printed a ~60-line KeyboardInterrupt traceback."""
	import signal

	auth_server(auto_approve=False)
	env = {**os.environ, 'PYTHONPATH': os.pathsep.join(p for p in (str(ROOT), os.environ.get('PYTHONPATH', '')) if p)}
	proc = subprocess.Popen(
		[sys.executable, '-m', 'browser_use', 'login', '--device-code', '--no-open'],
		cwd=ROOT,
		env=env,
		stdout=subprocess.PIPE,
		stderr=subprocess.PIPE,
		text=True,
	)
	watchdog = threading.Timer(30, proc.kill)  # a CLI that never prints the wait line ends the read below with EOF
	watchdog.start()
	try:
		assert proc.stdout is not None
		for line in proc.stdout:
			if line.startswith('Waiting for login'):
				break
		watchdog.cancel()
		proc.send_signal(signal.SIGINT)
		out, err = proc.communicate(timeout=30)
	finally:
		proc.kill()  # never leave it polling the fake server
	assert proc.returncode == 130, err
	assert err.strip() == 'Login cancelled.' and 'Signed in' not in out
	assert not store.exists()


def test_ctrl_c_at_the_api_key_prompt_cancels_without_a_traceback(store, monkeypatch, capsys):
	"""Ctrl-C at `login --api-key-stdin`'s hidden key prompt, or during its key check, printed a KeyboardInterrupt
	traceback: only the approval wait was covered."""
	from browser_use import auth, cli

	events = []
	monkeypatch.setattr(auth, 'record_auth_event', lambda stage, **fields: events.append(stage))

	for var in ('BH_CLIENT', 'BH_CLIENT_VERSION', 'BH_DEVICE_NAME'):
		monkeypatch.delenv(var, raising=False)  # restored after the test; the command sets them

	def interrupted():
		raise KeyboardInterrupt

	monkeypatch.setattr(cli, '_read_api_key_stdin', interrupted)
	try:
		code = cli._run_login_command(['--api-key-stdin'])
	except KeyboardInterrupt:
		pytest.fail('KeyboardInterrupt escaped `login --api-key-stdin` (a traceback for the user)')
	assert code == 130
	assert capsys.readouterr().err.strip() == 'Login cancelled.'
	assert not store.exists()
	assert events == ['login_started', 'login_cancelled']


def test_login_help_names_browser_use(store):
	result = _cli('login', '--help')
	assert result.returncode == 0
	assert 'browser-use auth login' in result.stdout and 'browser-harness' not in result.stdout


def test_missing_key_names_the_one_command(store):
	from browser_use.auth import browser_use_api_key
	from browser_use.exceptions import MissingAPIKeyError

	with pytest.raises(MissingAPIKeyError, match='BROWSER_USE_API_KEY'):
		browser_use_api_key()
	# piped CLI code: browser-harness's own message names `browser-harness auth login`, not on PATH for uv tool installs
	result = _cli(stdin='start_remote_daemon("browser-use-tests-login")\n')
	assert result.returncode == 1
	assert 'Run `browser-use login`' in result.stderr and 'Traceback' not in result.stderr


@pytest.mark.parametrize('automatic', [False, True])
def test_login_records_success_after_the_key_is_stored(store, monkeypatch, auth_server, automatic):
	from browser_use import auth, cli

	server = auth_server(auto_approve=True)
	events = []
	monkeypatch.setattr(auth, 'record_auth_event', lambda stage, **fields: events.append((stage, store.exists(), fields)))
	assert cli._run_login_command(['--no-open'], automatic=automatic) == 0
	assert [(stage, exists) for stage, exists, fields in events] == [('login_started', False), ('login_succeeded', True)]
	assert all(fields == {'method': 'browser', 'automatic': automatic} for stage, exists, fields in events)
	assert len(server.tokens) == 1


def test_interactive_missing_key_opens_login_and_reuses_the_saved_key(store, monkeypatch, auth_server, capsys):
	from browser_harness import auth as harness_auth

	from browser_use import auth
	from browser_use.llm import ChatBrowserUse

	server = auth_server(auto_approve=True)
	opened, events = [], []
	monkeypatch.setattr(auth, '_can_open_login', lambda: True)
	monkeypatch.setattr(auth, '_login_attempted', False)
	monkeypatch.setattr(auth, '_reported_key_sources', set())
	monkeypatch.setattr(auth, 'record_auth_event', lambda stage, **fields: events.append(stage))
	monkeypatch.setattr(harness_auth.webbrowser, 'open', lambda url: opened.append(url) or True)
	assert ChatBrowserUse().pydantic_model().client.api_key == FAKE_KEY
	assert ChatBrowserUse().pydantic_model().client.api_key == FAKE_KEY
	assert len(opened) == len(server.starts) == 1
	assert events == ['missing_key', 'login_started', 'login_succeeded', 'key_available']
	output = capsys.readouterr()
	assert output.out == '' and opened[0] in output.err and FAKE_KEY not in output.err


@pytest.mark.parametrize(
	'terminal, ci, setting, display, allowed',
	[
		(True, '', '', True, True),
		(False, '', '', True, False),
		(True, '1', '', True, False),
		(True, '', 'false', True, False),
		(True, '', '', False, False),
	],
)
def test_automatic_login_requires_an_interactive_desktop(monkeypatch, terminal, ci, setting, display, allowed):
	from browser_use import auth

	monkeypatch.setattr(auth.sys, 'platform', 'linux')
	monkeypatch.setattr(auth.sys.stdin, 'isatty', lambda: terminal)
	for name in ('CI', 'GITHUB_ACTIONS', 'BROWSER_USE_AUTO_LOGIN', 'DISPLAY', 'WAYLAND_DISPLAY'):
		monkeypatch.delenv(name, raising=False)
	if ci:
		monkeypatch.setenv('CI', ci)
	if setting:
		monkeypatch.setenv('BROWSER_USE_AUTO_LOGIN', setting)
	if display:
		monkeypatch.setenv('DISPLAY', ':1')
		monkeypatch.setenv('XDG_CURRENT_DESKTOP', 'GNOME')
		monkeypatch.setenv('XDG_SESSION_TYPE', 'x11')
	assert auth._can_open_login() is allowed


def test_virtual_display_alone_does_not_start_login(monkeypatch):
	from browser_use import auth

	monkeypatch.setattr(auth.sys, 'platform', 'linux')
	monkeypatch.setattr(auth.sys.stdin, 'isatty', lambda: True)
	for name in ('CI', 'GITHUB_ACTIONS', 'XDG_CURRENT_DESKTOP', 'XDG_SESSION_TYPE', 'BROWSER_USE_AUTO_LOGIN'):
		monkeypatch.delenv(name, raising=False)
	monkeypatch.setenv('DISPLAY', ':99')
	assert not auth._can_open_login()


def test_web_search_uses_the_same_login_flow_for_a_custom_model(store, monkeypatch, auth_server):
	from conftest import script

	from browser_use import Agent, Browser, auth

	auth_server(auto_approve=True)
	monkeypatch.setattr(auth, '_can_open_login', lambda: True)
	monkeypatch.setattr(auth, '_login_attempted', False)
	monkeypatch.setattr('browser_harness.auth.webbrowser.open', lambda url: True)
	agent = Agent('Search the web', script()[0], browser=Browser('chromium'), web_search=True)
	agent._build()
	assert agent._search is not None
	assert json.loads(store.read_text())['browser_use']['api_key'] == FAKE_KEY


def test_failed_automatic_login_does_not_reopen_on_each_key_request(store, monkeypatch):
	from browser_use import auth, cli
	from browser_use.exceptions import MissingAPIKeyError

	starts = []
	monkeypatch.setattr(auth, '_can_open_login', lambda: True)
	monkeypatch.setattr(auth, '_login_attempted', False)
	monkeypatch.setattr(cli, '_run_login_command', lambda *args, **kwargs: starts.append(True) or 1)
	for _ in range(2):
		with pytest.raises(MissingAPIKeyError):
			auth.browser_use_api_key(auto_login=True)
	assert starts == [True] and not store.exists()


def test_failed_login_records_failure_without_claiming_a_stored_key(store, monkeypatch):
	from browser_use import auth, cli

	events = []
	monkeypatch.setenv('BROWSER_USE_CLOUD_API_URL', 'http://127.0.0.1:9')
	monkeypatch.setattr(auth, 'record_auth_event', lambda stage, **fields: events.append(stage))
	assert cli._run_login_command(['--no-open']) == 1
	assert events == ['login_started', 'login_failed'] and not store.exists()


def test_a_stored_key_goes_to_the_server_whatever_its_scopes_and_a_scope_403_asks_for_a_new_login(store, monkeypatch):
	"""Scopes are the server's to judge: a local scope check would loop `browser-use login` on any scope name it did
	not expect. An older login's v3 key reaches API v4, and its 403 names the fix."""
	import io
	import urllib.error
	import urllib.request

	from browser_harness.auth import AuthRecord, save_auth_record

	from browser_use.auth import browser_use_api_key
	from browser_use.browser import browser as browser_mod

	for scopes in (['v3:browsers:create', 'v3:profiles:read'], ['browsers:create'], ['*:*:*'], []):
		save_auth_record(AuthRecord(api_key=FAKE_KEY, scopes=scopes))
		assert browser_use_api_key() == FAKE_KEY

	def forbidden(req, timeout=None):
		assert req.get_header('X-browser-use-api-key') == FAKE_KEY
		body = io.BytesIO(b'{"detail": "API key missing required scope: v4:browsers:create"}')
		raise urllib.error.HTTPError(req.full_url, 403, 'Forbidden', {}, body)  # type: ignore[arg-type]

	save_auth_record(AuthRecord(api_key=FAKE_KEY, scopes=['v3:browsers:create']))
	monkeypatch.setattr(browser_mod, 'urlopen_keyed', forbidden)
	with pytest.raises(RuntimeError, match='HTTP 403') as raised:
		browser_mod._cloud('/browsers', 'POST', {})
	assert 'Run `browser-use login` again' in str(raised.value) and FAKE_KEY not in str(raised.value)


def test_mcp_browser_login_finishes_across_calls_and_never_returns_the_key(store, monkeypatch, auth_server):
	from browser_use.mcp import cli_mcp

	server = auth_server(auto_approve=False)
	opened: list[str] = []
	monkeypatch.setattr(cli_mcp, '_open_url', lambda url: opened.append(url) or True)  # never a real browser
	monkeypatch.setenv('BH_DEVICE_NAME', 'placeholder')
	monkeypatch.delenv('BH_DEVICE_NAME')
	mcp = cli_mcp.CLIMCPServer()

	# Not signed in: browser_exec says which tool fixes it
	output = mcp._execute('start_remote_daemon("browser-use-tests-login")')[0]
	assert cli_mcp.LOGIN_HINT in output

	first = mcp._sign_in(force=False, wait=0.2)[0]
	assert 'Waiting for the user to approve' in first and 'call browser_login again' in first.lower()
	assert opened == [f'{server.url}/device/authorize?state={server.starts[0]["state"]}'] and opened[0] in first
	assert server.starts[0]['device_name'] == 'browser-use-mcp'

	assert mcp._sign_in(force=False, wait=0.2)[0] == first  # still pending: no second login is started
	assert len(server.starts) == 1

	server.approve()
	done = mcp._sign_in(force=False, wait=10)[0]
	assert done.startswith('Signed in to Browser Use Cloud')
	assert json.loads(store.read_text())['browser_use']['api_key'] == FAKE_KEY
	assert FAKE_KEY not in first + done

	again = mcp._sign_in(force=False, wait=0.2)[0]  # already signed in: no new login
	assert again.startswith('Signed in') and str(store) in again and len(server.starts) == 1


def test_mcp_browser_login_reports_a_denied_approval(store, monkeypatch, auth_server):
	from browser_use.mcp import cli_mcp

	server = auth_server(auto_approve=False)
	monkeypatch.setattr(cli_mcp, '_open_url', lambda url: False)
	mcp = cli_mcp.CLIMCPServer()
	pending = mcp._sign_in(force=False, wait=0.2)[0]
	assert 'by opening this URL in a browser' in pending
	start = server.starts[0]
	urllib.request.urlopen(f'{start["redirect_uri"]}?error=access_denied&state={start["state"]}', timeout=10).read()
	result = mcp._sign_in(force=False, wait=10)[0]
	assert result.startswith('Browser Use Cloud login failed: auth failed: access_denied')
	assert not store.exists()


def test_mcp_browser_login_with_an_env_key(store, monkeypatch):
	from browser_use.mcp import cli_mcp

	monkeypatch.setenv('BROWSER_USE_API_KEY', 'fake-env-key')
	mcp = cli_mcp.CLIMCPServer()
	assert 'key from BROWSER_USE_API_KEY' in mcp._sign_in(force=False, wait=0)[0]
	assert 'BROWSER_USE_API_KEY is set' in mcp._sign_in(force=True, wait=0)[0]  # a new stored key would not be used


async def test_mcp_lists_browser_login():
	from browser_use.mcp import cli_mcp

	names = [tool.name for tool in cli_mcp.CLIMCPServer()._tool_definitions()]
	assert names == ['browser_exec', 'browser_screenshot', 'browser_login', 'browser_feedback']


def test_logout_prints_the_real_store_path_and_version_names_both_packages(store):
	from importlib.metadata import version

	store.parent.mkdir(parents=True)
	store.write_text(json.dumps({'browser_use': {'api_key': FAKE_KEY}}))
	result = _cli('logout')
	assert result.returncode == 0 and json.loads(result.stdout)['path'] == str(store)  # .../browser-harness/auth.json

	result = _cli('--version')
	assert result.stdout.strip() == f'browser-use {version("browser-use")} (browser-harness {version("browser-harness")})'


def test_a_key_with_whitespace_inside_never_appears_in_an_error_or_the_store(store, monkeypatch):
	"""H4: a key with a newline inside was stored by login and sent as is; urllib/http.client then raised "Invalid
	header value b'bu_...'" with the whole key, from the cloud browser, the gateway preflight and start_remote_daemon."""
	from browser_use import Browser, ChatBrowserUse, harness_cloud
	from browser_use.auth import browser_use_api_key
	from browser_use.exceptions import MissingAPIKeyError

	bad = FAKE_KEY[:20] + '\nsecond-line' + FAKE_KEY[20:]
	result = _cli('login', '--api-key-stdin', stdin=bad + '\n')
	assert result.returncode == 1 and 'line break' in result.stderr and not store.exists()
	assert FAKE_KEY[:20] not in result.stderr + result.stdout

	monkeypatch.setenv('BROWSER_USE_API_KEY', FAKE_KEY + '\n')  # a trailing newline (echo, a file) is just stripped
	assert browser_use_api_key() == FAKE_KEY
	monkeypatch.setenv('BROWSER_USE_API_KEY', FAKE_KEY + '\u00e9')  # http.client would send it as latin-1
	with pytest.raises(MissingAPIKeyError, match='non-ASCII'):
		browser_use_api_key()
	monkeypatch.setenv('BROWSER_USE_API_KEY', bad)
	for fail in (
		browser_use_api_key,
		lambda: ChatBrowserUse(api_key=bad),
		lambda: ChatBrowserUse().preflight(),
		lambda: __import__('asyncio').run(Browser().start()),
	):
		with pytest.raises(MissingAPIKeyError) as raised:
			fail()
		assert 'line break' in str(raised.value) and FAKE_KEY[:20] not in str(raised.value)
	ns: dict = {}
	harness_cloud.install(ns)
	with pytest.raises(harness_cloud.CloudBrowserError) as raised:
		ns['start_remote_daemon']('bukeynewline')
	assert 'line break' in str(raised.value) and FAKE_KEY[:20] not in str(raised.value)


def test_api_key_stdin_stores_only_a_browser_use_key(store, auth_server):
	auth_server(auto_approve=False)
	result = _cli('login', '--api-key-stdin', stdin='sk-' + 'x' * 40)
	assert result.returncode == 1 and 'start with bu_' in result.stderr and 'Signed in' not in result.stdout
	assert not store.exists()

	result = _cli('login', '--api-key-stdin', stdin='bu_' + 'g' * 40)  # shaped right, but the cloud rejects it
	assert result.returncode == 1 and 'rejected that key' in result.stderr and 'Signed in' not in result.stdout
	assert not store.exists()

	result = _cli('login', '--api-key-stdin', stdin=FAKE_KEY + '\n')
	assert result.returncode == 0, result.stderr
	assert json.loads(store.read_text())['browser_use']['api_key'] == FAKE_KEY and FAKE_KEY not in result.stdout


def test_auth_login_checks_the_key_like_login(store, auth_server):
	"""rr-climcp 2: `browser-use auth login --api-key-stdin` (the form the bundled SKILL.md teaches) went straight to
	browser-harness: a key the cloud rejects was stored, 'authenticated', exit 0."""
	auth_server(auto_approve=False)
	result = _cli('auth', 'login', '--api-key-stdin', stdin='bu_' + 'g' * 40)
	assert result.returncode == 1 and 'rejected that key' in result.stderr, result.stdout + result.stderr
	assert not store.exists()
	result = _cli('auth', 'login', '--api-key-stdin', stdin=FAKE_KEY)
	assert result.returncode == 0 and 'Signed in' in result.stdout, result.stderr
	assert json.loads(store.read_text())['browser_use']['api_key'] == FAKE_KEY
	result = _cli('auth', 'logout')
	assert result.returncode == 0 and not store.exists()


def test_a_corrupt_key_store_is_named_and_login_or_logout_repairs_it(store, auth_server):
	auth_server(auto_approve=False)
	from browser_use.auth import browser_use_api_key
	from browser_use.exceptions import MissingAPIKeyError

	store.parent.mkdir(parents=True)
	store.write_text('{"browser_use": {"api_key": "bu_trunc')
	with pytest.raises(MissingAPIKeyError, match='is corrupt') as raised:
		browser_use_api_key()
	assert str(store) in str(raised.value) and 'browser-use login' in str(raised.value)

	result = _cli('login', '--api-key-stdin', stdin=FAKE_KEY)
	assert result.returncode == 0, result.stderr
	assert json.loads(store.read_text())['browser_use']['api_key'] == FAKE_KEY
	assert store.with_name('auth.json.corrupt').read_text().startswith('{"browser_use"')  # kept, not lost

	store.write_text('["a list, not an object"]')  # low: AttributeError 'list' object has no attribute 'get'
	with pytest.raises(MissingAPIKeyError, match='is corrupt'):
		browser_use_api_key()
	result = _cli('login', '--api-key-stdin', stdin=FAKE_KEY)
	assert result.returncode == 0, result.stderr
	# review: the second corrupt store replaced the first backup, which may hold the only copy of a key
	assert store.with_name('auth.json.corrupt').read_text().startswith('{"browser_use"')
	assert store.with_name('auth.json.corrupt.2').read_text() == '["a list, not an object"]'

	store.write_text('not json')
	result = _cli('logout')
	assert result.returncode == 0, result.stderr
	assert json.loads(result.stdout)['status'] == 'logged-out' and not store.exists()


def test_a_rejected_key_names_the_login_command(store, monkeypatch):
	import io
	import urllib.error
	import urllib.request

	from browser_use.browser import browser as browser_mod

	monkeypatch.setenv('BROWSER_USE_API_KEY', FAKE_KEY)

	def unauthorized(req, timeout=None):
		raise urllib.error.HTTPError(
			req.full_url, 401, 'Unauthorized', {}, io.BytesIO(b'{"detail": "Invalid API key, see ?tab=api-keys\\u0026new=1"}')
		)  # type: ignore[arg-type]

	monkeypatch.setattr(browser_mod, 'urlopen_keyed', unauthorized)
	with pytest.raises(RuntimeError, match='HTTP 401') as raised:
		browser_mod._cloud('/browsers', 'POST', {})
	message = str(raised.value)
	assert 'Invalid API key, see ?tab=api-keys&new=1.' in message and '{' not in message  # the detail, not raw JSON
	assert 'run `browser-use login`' in message and 'BROWSER_USE_API_KEY is set' in message and FAKE_KEY not in message

	def sentence(req, timeout=None):  # rr-failure 7: a detail that ends its sentence printed '..'
		raise urllib.error.HTTPError(req.full_url, 401, 'x', {}, io.BytesIO(b'{"detail": "Sign in first."}'))  # type: ignore[arg-type]

	monkeypatch.setattr(browser_mod, 'urlopen_keyed', sentence)
	with pytest.raises(RuntimeError, match=r'HTTP 401 Sign in first\. The API key was rejected'):
		browser_mod._cloud('/browsers', 'POST', {})


def test_a_callback_with_the_wrong_state_neither_completes_nor_aborts_the_login(store, monkeypatch, auth_server):
	import urllib.error

	from browser_use.mcp import cli_mcp

	server = auth_server(auto_approve=False)
	monkeypatch.setattr(cli_mcp, '_open_url', lambda url: True)
	mcp = cli_mcp.CLIMCPServer()
	assert 'Waiting for the user to approve' in mcp._sign_in(force=False, wait=0.2)[0]
	start = server.starts[0]
	with pytest.raises(urllib.error.HTTPError) as raised:
		urllib.request.urlopen(f'{start["redirect_uri"]}?code=stolen&state=wrong', timeout=10)
	assert raised.value.code == 400 and b'login complete' not in raised.value.read()

	server.approve()  # the real approval still finishes the same login
	assert mcp._sign_in(force=False, wait=10)[0].startswith('Signed in to Browser Use Cloud')
	assert json.loads(store.read_text())['browser_use']['api_key'] == FAKE_KEY


def test_the_missing_key_error_puts_login_first_then_a_tagged_link_then_the_no_key_way(monkeypatch):
	monkeypatch.setenv('ANONYMIZED_TELEMETRY', 'true')  # tagged only with telemetry on
	from browser_use.exceptions import MissingAPIKeyError, missing_key_text
	from browser_use.utils import get_browser_use_version

	text = str(MissingAPIKeyError('The default model (bu-fast)', gate='default_model'))
	lines = text.splitlines()
	assert len(lines) <= 4 and lines[0].startswith('The default model (bu-fast) needs a Browser Use API key.')
	assert text.index('browser-use login') < text.index('BROWSER_USE_API_KEY') < text.index('No key')
	assert '--device-code' in lines[0]
	url = f'https://cloud.browser-use.com/new-api-key?ref=bu-lib&gate=default_model&v={get_browser_use_version()}'
	assert url in text and "Browser('chromium')" in lines[-1]
	web = str(MissingAPIKeyError('Agent(web_search=True)', gate='web_search'))
	assert 'ChatOpenAI' not in web and 'web_search off' in web  # they already run their own model and browser

	notebook = missing_key_text('Browser()', 'cloud_browser', notebook=True).splitlines()
	assert notebook[0].startswith('Run `import browser_use; browser_use.login()` in a cell') and len(notebook) <= 4


async def test_the_cloud_browser_uses_the_key_the_gateway_model_was_given(store, monkeypatch, tmp_path):
	"""ChatBrowserUse(api_key=...) with the default Browser() and no env or stored key: the browser asked for a key the
	user had already passed."""
	import io
	import urllib.error

	from browser_use import Agent, ChatBrowserUse
	from browser_use.browser import browser as browser_mod

	sent: list[str | None] = []

	def refuse(req, timeout=None):
		sent.append(req.get_header('X-browser-use-api-key'))
		raise urllib.error.HTTPError(req.full_url, 402, 'Payment Required', {}, io.BytesIO(b'{"detail": "no credits"}'))  # type: ignore[arg-type]

	monkeypatch.setattr(browser_mod, 'urlopen_keyed', refuse)
	agent = Agent('t', ChatBrowserUse(api_key=FAKE_KEY), workspace=tmp_path)
	agent._build()
	with pytest.raises(RuntimeError, match='HTTP 402'):  # past the key check: the create call carried the model's key
		await agent.browser.start()
	assert sent == [FAKE_KEY]


def test_a_cloud_browser_is_stopped_with_the_key_it_was_created_with(store, monkeypatch, tmp_path):
	"""keep_alive Browser: Agent 1 on ChatBrowserUse(api_key=k) creates the cloud browser with k, Agent 2 on its own model
	sets the browser's model key to None. The stop looked the key up again, raised, and the browser billed on."""
	import contextlib
	import io

	from conftest import script

	from browser_use import Agent, Browser, ChatBrowserUse
	from browser_use.browser import browser as browser_mod

	sent: list[tuple[str, str | None]] = []

	def answer(req, timeout=None):
		sent.append((req.get_method(), req.get_header('X-browser-use-api-key')))
		return contextlib.nullcontext(io.BytesIO(json.dumps({'id': 'b1', 'cdpUrl': 'http://cdp'}).encode()))

	monkeypatch.setattr(browser_mod, 'urlopen_keyed', answer)
	browser = Browser(keep_alive=True)
	Agent('t', ChatBrowserUse(api_key=FAKE_KEY), browser=browser, workspace=tmp_path)._build()
	browser._create({})
	Agent('t', script()[0], browser=browser, workspace=tmp_path)._build()
	assert browser._llm_key is None
	assert browser._stop_now() and browser.stopped
	assert sent == [('POST', FAKE_KEY), ('PATCH', FAKE_KEY)]


@pytest.mark.parametrize('operation', ['list', 'copy', 'stop'])
async def test_cloud_downloads_use_the_creation_key_after_the_model_changes(store, monkeypatch, tmp_path, operation):
	"""A model-supplied key owns the cloud session's downloads, including files listed only after stop()."""
	import io
	import urllib.parse

	from conftest import script

	from browser_use import Agent, Browser, ChatBrowserUse
	from browser_use.browser import browser as browser_mod

	sent = []
	stopped = False
	content = {'before.csv': b'before', 'second.csv': b'second', 'after.csv': b'after'}

	def answer(req, timeout=None):
		nonlocal stopped
		sent.append((req.get_method(), req.get_header('X-browser-use-api-key')))
		assert sent[-1][1] == FAKE_KEY
		if req.get_method() == 'POST':
			result = {'id': 'b1', 'cdpUrl': 'http://cdp'}
		elif req.get_method() == 'PATCH':
			stopped = True
			result = {}
		else:
			query = urllib.parse.parse_qs(urllib.parse.urlsplit(req.full_url).query)
			second = query.get('cursor') == ['second']
			names = ['second.csv'] if second else ['before.csv', *(['after.csv'] if stopped else [])]
			result = {
				'files': [
					{'path': '/dl/' + name, 'size': len(content[name]), 'url': 'https://files.test/' + name} for name in names
				],
				'hasMore': not second,
				'nextCursor': None if second else 'second',
			}
		return io.BytesIO(json.dumps(result).encode())

	monkeypatch.setattr(browser_mod, 'urlopen_keyed', answer)
	monkeypatch.setattr(browser_mod.urllib.request, 'urlopen', lambda url, **kwargs: io.BytesIO(content[url.rsplit('/', 1)[1]]))
	browser = Browser(keep_alive=True)
	Agent('t', ChatBrowserUse(api_key=FAKE_KEY), browser=browser, workspace=tmp_path)._build()
	browser._create({})
	Agent('t', script()[0], browser=browser, workspace=tmp_path)._build()
	assert browser._llm_key is None
	try:
		if operation == 'list':
			assert await browser.list_downloads() == [
				{'name': name, 'size': len(content[name])} for name in ('before.csv', 'second.csv')
			]
		else:
			files = await (
				browser.stop(tmp_path / 'downloads') if operation == 'stop' else browser.download_files(tmp_path / 'downloads')
			)
			expected = content if operation == 'stop' else {name: content[name] for name in ('before.csv', 'second.csv')}
			assert {p.name: p.read_bytes() for p in files} == expected
		if operation == 'stop':
			assert stopped and browser.id is None
			assert browser._cloud_key == ()
		assert sum(method == 'GET' for method, _ in sent) == (4 if operation == 'stop' else 2)
	finally:
		browser._stop_now()


@pytest.mark.parametrize('stop_succeeds', [True, False])
def test_late_cloud_create_releases_its_key_only_after_a_successful_stop(store, monkeypatch, tmp_path, stop_succeeds):
	"""A timed-out create's callback has no post-stop download pass, but a failed stop still needs its key to retry."""
	import concurrent.futures
	import io

	from conftest import script

	from browser_use import Agent, Browser, ChatBrowserUse
	from browser_use.browser import browser as browser_mod

	sent = []
	expected_patches = 1 if stop_succeeds else 4

	def answer(req, timeout=None):
		sent.append((req.get_method(), req.get_header('X-browser-use-api-key')))
		assert sent[-1][1] == FAKE_KEY
		if req.get_method() == 'PATCH' and not stop_succeeds:
			raise OSError('temporary stop failure')
		return io.BytesIO(json.dumps({'id': 'b1', 'cdpUrl': 'http://cdp'}).encode())

	monkeypatch.setattr(browser_mod, 'urlopen_keyed', answer)
	monkeypatch.setattr(browser_mod.time, 'sleep', lambda _: None)
	browser = Browser()
	Agent('t', ChatBrowserUse(api_key=FAKE_KEY), browser=browser, workspace=tmp_path)._build()
	creating: concurrent.futures.Future[None] = concurrent.futures.Future()
	browser._creating, browser._create_deadline = creating, 0
	browser_mod._LIVE.add(browser)
	assert not browser._stop_now()  # the create exceeded its deadline: register the real completion callback
	browser._create({})
	Agent('t', script()[0], browser=browser, workspace=tmp_path)._build()
	try:
		creating.set_result(None)
		assert browser.stopped is stop_succeeds
		if not stop_succeeds:
			assert browser._cloud_key == (FAKE_KEY,) and browser in browser_mod._LIVE
			assert browser._creating is creating
			stop_succeeds = True
			browser._stop_late(creating)  # retry with the original credential, after the failure clears
		assert browser._cloud_key == () and browser._creating is None
		assert browser.stopped and browser not in browser_mod._LIVE
		assert sent == [('POST', FAKE_KEY)] + [('PATCH', FAKE_KEY)] * expected_patches
	finally:
		stop_succeeds = True
		browser._stop_now()
