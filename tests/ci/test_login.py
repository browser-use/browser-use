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


def _auth_server(monkeypatch, auto_approve: bool) -> FakeAuthServer:
	server = FakeAuthServer(auto_approve)
	monkeypatch.setenv('BROWSER_USE_CLOUD_API_URL', server.url)
	return server


def _cli(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
	env = os.environ.copy()
	env['PYTHONPATH'] = os.pathsep.join(part for part in (str(ROOT), env.get('PYTHONPATH', '')) if part)
	env.pop('BH_DEVICE_NAME', None)
	return subprocess.run(
		[sys.executable, '-m', 'browser_use', *args], cwd=ROOT, env=env, input=stdin, capture_output=True, text=True, timeout=60
	)


def test_login_stores_the_key_in_the_shared_store_without_printing_it(store, monkeypatch):
	server = _auth_server(monkeypatch, auto_approve=True)
	result = _cli('login', '--no-open')
	assert result.returncode == 0, result.stderr
	assert FAKE_KEY not in result.stdout + result.stderr
	assert server.starts[0]['client_id'] == 'browser-use-terminal' and server.starts[0]['device_name'] == 'browser-use'
	assert 'Signed in' in result.stdout and 'browser-use --cli-mcp' in result.stdout
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


def test_login_help_names_browser_use(store):
	result = _cli('login', '--help')
	assert result.returncode == 0
	assert 'browser-use auth login' in result.stdout and 'browser-harness' not in result.stdout


def test_missing_key_names_the_one_command(store):
	from browser_use.auth import browser_use_api_key
	from browser_use.exceptions import MissingAPIKeyError

	with pytest.raises(MissingAPIKeyError, match='Run `browser-use login`'):
		browser_use_api_key()
	# piped CLI code: browser-harness's own message names `browser-harness auth login`, not on PATH for uv tool installs
	result = _cli(stdin='start_remote_daemon("browser-use-tests-login")\n')
	assert result.returncode == 1
	assert 'Run `browser-use login`' in result.stderr and 'Traceback' not in result.stderr


def test_a_v3_only_key_from_an_older_login_asks_for_a_new_login(store):
	"""Older browser-harness logins stored v3 browser-only keys: API v4 browsers and the gateway answer 403."""
	from browser_harness.auth import AuthRecord, save_auth_record

	from browser_use.auth import browser_use_api_key
	from browser_use.exceptions import MissingAPIKeyError

	save_auth_record(AuthRecord(api_key=FAKE_KEY, scopes=['v3:browsers:create', 'v3:profiles:read']))
	with pytest.raises(MissingAPIKeyError, match='older login') as raised:
		browser_use_api_key()
	assert 'Run `browser-use login` again' in str(raised.value) and FAKE_KEY not in str(raised.value)
	save_auth_record(AuthRecord(api_key=FAKE_KEY, scopes=['*:*:*']))
	assert browser_use_api_key() == FAKE_KEY
	save_auth_record(AuthRecord(api_key=FAKE_KEY, source='manual'))  # pasted key: scopes unknown, the server decides
	assert browser_use_api_key() == FAKE_KEY


def test_mcp_browser_login_finishes_across_calls_and_never_returns_the_key(store, monkeypatch):
	from browser_use.mcp import cli_mcp

	server = _auth_server(monkeypatch, auto_approve=False)
	opened: list[str] = []
	monkeypatch.setattr(cli_mcp, '_open_url', lambda url: opened.append(url) or True)  # never a real browser
	monkeypatch.setenv('BH_DEVICE_NAME', 'placeholder')
	monkeypatch.delenv('BH_DEVICE_NAME')
	mcp = cli_mcp.CLIMCPServer()

	# Not signed in: browser_exec says which tool fixes it
	output = mcp._execute('start_remote_daemon("browser-use-tests-login")')
	assert cli_mcp.LOGIN_HINT in output

	first = mcp._sign_in(force=False, wait=0.2)
	assert 'Waiting for the user to approve' in first and 'call browser_login again' in first.lower()
	assert opened == [f'{server.url}/device/authorize?state={server.starts[0]["state"]}'] and opened[0] in first
	assert server.starts[0]['device_name'] == 'browser-use-mcp'

	assert mcp._sign_in(force=False, wait=0.2) == first  # still pending: no second login is started
	assert len(server.starts) == 1

	server.approve()
	done = mcp._sign_in(force=False, wait=10)
	assert done.startswith('Signed in to Browser Use Cloud')
	assert json.loads(store.read_text())['browser_use']['api_key'] == FAKE_KEY
	assert FAKE_KEY not in first + done

	again = mcp._sign_in(force=False, wait=0.2)  # already signed in: no new login
	assert again.startswith('Signed in') and str(store) in again and len(server.starts) == 1


def test_mcp_browser_login_reports_a_denied_approval(store, monkeypatch):
	from browser_use.mcp import cli_mcp

	server = _auth_server(monkeypatch, auto_approve=False)
	monkeypatch.setattr(cli_mcp, '_open_url', lambda url: False)
	mcp = cli_mcp.CLIMCPServer()
	pending = mcp._sign_in(force=False, wait=0.2)
	assert 'by opening this URL in a browser' in pending
	start = server.starts[0]
	urllib.request.urlopen(f'{start["redirect_uri"]}?error=access_denied&state={start["state"]}', timeout=10).read()
	result = mcp._sign_in(force=False, wait=10)
	assert result.startswith('Browser Use Cloud login failed: auth failed: access_denied')
	assert not store.exists()


def test_mcp_browser_login_with_an_env_key(store, monkeypatch):
	from browser_use.mcp import cli_mcp

	monkeypatch.setenv('BROWSER_USE_API_KEY', 'fake-env-key')
	mcp = cli_mcp.CLIMCPServer()
	assert 'key from BROWSER_USE_API_KEY' in mcp._sign_in(force=False, wait=0)
	assert 'BROWSER_USE_API_KEY is set' in mcp._sign_in(force=True, wait=0)  # a new stored key would not be used


async def test_mcp_lists_browser_login():
	from browser_use.mcp import cli_mcp

	names = [tool.name for tool in cli_mcp.CLIMCPServer()._tool_definitions()]
	assert names == ['browser_exec', 'browser_screenshot', 'browser_login']
