"""Cloud browsers in the browser-use CLI and MCP server (browser_use/harness_cloud.py), with no Browser Use Cloud.

start_remote_daemon's cloud half is faked: it starts a real browser-harness daemon on the isolated test Chrome, the
way a cloud daemon attaches to its browser's CDP URL. Any attach to a *local* Chrome fails the test: on a developer's
machine that would be their own Chrome.
"""

import io
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROCESS_ENV = ('BU_NAME', 'BH_OPEN_LIVE_URL', 'BH_TAB_MARKER', 'BH_CLIENT', 'BH_CLIENT_VERSION', 'BH_DEVICE_NAME')


@pytest.fixture(autouse=True)
def restore_process_env(monkeypatch):
	"""The CLI and MCP code under test set process env defaults; give each test the env it started with."""
	for key in PROCESS_ENV:
		if key in os.environ:
			monkeypatch.setenv(key, os.environ[key])
		else:
			monkeypatch.delenv(key, raising=False)
	monkeypatch.setenv('BH_UPDATE_CHECK', '0')  # no PyPI version check from piped CLI code


@pytest.fixture
def no_local_chrome(monkeypatch):
	"""browser-harness may start daemons on an explicit CDP endpoint only, never discover the user's Chrome."""
	from browser_harness import admin

	original = admin.ensure_daemon

	def ensure_daemon(wait=None, name=None, env=None):
		if admin._is_local_chrome_mode(env):
			raise AssertionError(f'attached a local Chrome for daemon {name or admin.NAME!r}')
		return original(wait=wait, name=name, env=env)

	monkeypatch.setattr(admin, 'ensure_daemon', ensure_daemon)


@pytest.fixture
def fake_cloud(chrome, monkeypatch, no_local_chrome):
	"""admin.start_remote_daemon backed by the test Chrome. Yields the names it started; stops and forgets them."""
	from browser_harness import admin

	from browser_use import harness_cloud

	started: list[str] = []

	def start_remote_daemon(name='remote', profileName=None, **create_kwargs):
		# from a short-lived process, as the CLI does: the daemon is then nobody's zombie once it exits
		attach = f'from browser_harness import admin; admin.ensure_daemon(name={name!r}, env={{"BU_CDP_WS": {chrome["ws"]!r}}})'
		subprocess.run([sys.executable, '-c', attach], check=True, timeout=60)
		started.append(name)
		return {'id': '', 'liveUrl': 'https://live.example.invalid/grants-control', 'timeout': create_kwargs.get('timeout')}

	monkeypatch.setattr(admin, 'start_remote_daemon', start_remote_daemon)
	from browser_harness import helpers

	monkeypatch.setattr(admin, 'NAME', admin.NAME)  # routing rebinds these: restore them for the next test
	monkeypatch.setattr(helpers, 'NAME', helpers.NAME)
	yield started
	for name in started:
		try:
			admin.restart_daemon(name)
		except Exception:
			pass
		harness_cloud.forget(name)


def _name(tag: str) -> str:
	return f'bucloud{tag}{os.getpid()}'


def test_mcp_drives_the_cloud_browser_it_started_wherever_the_start_is_in_the_code(fake_cloud, monkeypatch):
	from browser_use.mcp import cli_mcp

	monkeypatch.delenv('BH_TAB_MARKER')  # cloud pages keep their title without the user setting it
	monkeypatch.delenv('BH_OPEN_LIVE_URL', raising=False)
	name = _name('route')
	mcp = cli_mcp.CLIMCPServer()

	# not the first statement: a prefix check would attach the local Chrome before the cloud browser starts
	out = mcp._execute(f'b = start_remote_daemon({name!r})\nprint(sorted(b))\nprint(b["timeout"])')
	assert fake_cloud == [name], out
	assert 'liveUrl' not in out and 'live.example' not in out  # it grants control of the browser
	assert out.splitlines()[-1] == str(cli_mcp.CLOUD_TIMEOUT_MINUTES)

	out = mcp._execute('new_tab("data:text/html,<title>cloud page</title>"); wait_for_load(); print(page_info()["title"])')
	assert out.strip().splitlines()[-1] == 'cloud page', out
	assert mcp._execute('print(NAME)').strip() == name

	other = _name('other')
	out = mcp._execute(f'start_remote_daemon({other!r})')
	assert f'already drives cloud browser {name!r}' in out and fake_cloud == [name]


def test_a_cloud_daemon_that_ended_never_falls_back_to_the_local_chrome(fake_cloud):
	from browser_harness import admin

	from browser_use.harness_cloud import CloudBrowserError
	from browser_use.mcp import cli_mcp

	name = _name('gone')
	mcp = cli_mcp.CLIMCPServer()
	mcp._execute(f'start_remote_daemon({name!r})')
	admin.restart_daemon(name)  # the cloud browser timed out / its daemon died

	for out in (mcp._execute('print(page_info())'), mcp._execute('print(page_info())')):
		assert f'Cloud browser {name!r} has ended' in out and f'start_remote_daemon({name!r})' in out, out
		assert 'Traceback' not in out and 'attached a local Chrome' not in out
	assert not admin.daemon_alive(name)
	with pytest.raises(CloudBrowserError, match='has ended'):
		mcp._screenshot(False, None)


def _cli(*args: str, stdin: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
	full = {**os.environ, **env}
	full['PYTHONPATH'] = os.pathsep.join(part for part in (str(ROOT), full.get('PYTHONPATH', '')) if part)
	full.pop('BROWSER_USE_API_KEY', None)
	full['BH_UPDATE_CHECK'] = '0'
	return subprocess.run(
		[sys.executable, '-m', 'browser_use', *args], cwd=ROOT, env=full, input=stdin, capture_output=True, text=True, timeout=90
	)


@pytest.fixture
def cli_env():
	"""A private runtime dir, and a dead CDP endpoint instead of local Chrome discovery: whatever the CLI does wrong,
	it can never reach the developer's Chrome."""
	runtime = tempfile.mkdtemp(prefix='bu', dir=None if os.name == 'nt' else '/tmp')  # AF_UNIX paths are short
	return {'BH_RUNTIME_DIR': runtime, 'BH_RUNTIME_DIR_SHARED': '1', 'BU_CDP_URL': 'http://127.0.0.1:9'}


def test_cli_fails_closed_for_a_name_that_ran_a_cloud_browser(cli_env):
	from browser_harness import _ipc as ipc

	name = _name('cli')
	marker = Path(cli_env['BH_RUNTIME_DIR']) / ipc.pid_path(name).with_suffix('.cloud').name
	marker.write_text('')  # what start_remote_daemon leaves behind once that browser was stopped
	result = _cli(stdin='print(page_info())\n', env={**cli_env, 'BU_NAME': name})
	assert result.returncode == 1
	assert f'Cloud browser {name!r} has ended' in result.stderr, result.stderr

	reload = _cli('--reload', stdin='', env={**cli_env, 'BU_NAME': name})  # on purpose: the name may go local again
	assert reload.returncode == 0 and not marker.exists(), reload.stderr


def test_cli_starts_a_cloud_browser_from_any_statement_without_attaching_first(cli_env, tmp_path):
	result = _cli(stdin='b = start_remote_daemon("bucloudstmt")\n', env={**cli_env, 'BH_AUTH_PATH': str(tmp_path / 'no.json')})
	assert result.returncode == 1
	assert 'Run `browser-use login`' in result.stderr and "didn't come up" not in result.stderr, result.stderr


def _http_error(status: int, body: bytes):
	def urlopen(req, timeout=None):
		raise urllib.error.HTTPError(req.full_url, status, 'error', {}, io.BytesIO(body))  # type: ignore[arg-type]

	return urlopen


def test_cloud_start_errors_are_one_line_with_the_server_detail_and_the_fix(monkeypatch, capsys):
	from browser_use import cli, harness_cloud

	monkeypatch.setenv('BROWSER_USE_API_KEY', 'bu_' + 'x' * 40)
	monkeypatch.setattr(urllib.request, 'urlopen', _http_error(401, b'{"detail": "Invalid API key"}'))
	ns: dict = {}
	harness_cloud.install(ns)
	with pytest.raises(harness_cloud.CloudBrowserError) as raised:
		ns['start_remote_daemon']('bucloud401')
	message = str(raised.value)
	assert 'HTTP 401' in message and 'Invalid API key' in message and 'browser-use login' in message
	assert 'BROWSER_USE_API_KEY is set' in message and 'bu_xxx' not in message

	monkeypatch.setattr(urllib.request, 'urlopen', _http_error(422, b'{"detail": "timeout must be <= 240"}'))
	with pytest.raises(harness_cloud.CloudBrowserError, match='HTTP 422 .*timeout must be <= 240') as raised:
		ns['start_remote_daemon']('bucloud422', timeout=999)
	assert 'login' not in str(raised.value)

	# the CLI prints it as one line, no traceback
	from browser_harness import run

	for key in ('ensure_daemon', 'start_remote_daemon', 'stop_remote_daemon'):
		monkeypatch.setitem(vars(run), key, vars(run)[key])
	monkeypatch.setattr(sys, 'argv', ['browser-use'])
	monkeypatch.setattr(sys, 'stdin', io.StringIO('start_remote_daemon("bucloudcli", timeout=999)\n'))
	assert cli._dispatch([])[0] == 1
	err = capsys.readouterr().err
	assert 'HTTP 422' in err and 'Traceback' not in err and len(err.strip().splitlines()) == 1


def test_mcp_server_exit_stops_the_cloud_browser_it_started_even_when_killed(chrome, tmp_path):
	"""The server is SIGKILLed: no handler runs in it. Its reaper still stops the daemon (and so the cloud browser)."""
	from browser_harness import admin

	name = _name('reap')
	server = f"""
import sys, time
from browser_harness import admin
from browser_use.mcp import cli_mcp

def start_remote_daemon(name='remote', profileName=None, **kw):
	admin.ensure_daemon(name=name, env={{'BU_CDP_WS': {chrome['ws']!r}}})
	return {{'id': 'no-such-browser'}}

admin.start_remote_daemon = start_remote_daemon
print(cli_mcp.CLIMCPServer()._execute({f'start_remote_daemon({name!r})'!r}), flush=True)
print('ready', flush=True)
time.sleep(600)
"""
	env = {**os.environ, 'PYTHONPATH': str(ROOT)}
	env.pop('BROWSER_USE_API_KEY', None)  # the reaper's cloud stop then fails on "no key" before any request
	proc = subprocess.Popen([sys.executable, '-c', server], env=env, stdout=subprocess.PIPE, text=True)
	try:
		assert proc.stdout is not None
		lines = [proc.stdout.readline() for _ in range(2)]
		assert lines[-1].strip() == 'ready', lines
		assert admin.daemon_alive(name)
		proc.kill()
		proc.wait(10)
		deadline = time.monotonic() + 20
		while admin.daemon_alive(name) and time.monotonic() < deadline:
			time.sleep(0.2)
		assert not admin.daemon_alive(name)
	finally:
		proc.kill()
		try:
			admin.restart_daemon(name)
		except Exception:
			pass
		from browser_use import harness_cloud

		harness_cloud.forget(name)
