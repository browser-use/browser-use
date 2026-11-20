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
		return {
			'id': '',
			'liveUrl': 'https://live.example.invalid/x',
			'cdpUrl': 'https://cdp.example.invalid/x',
			'timeout': create_kwargs.get('timeout'),
		}

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
	mcp = cli_mcp.CLIMCPServer()
	name = mcp._remote

	# not the first statement: a prefix check would attach the local Chrome before the cloud browser starts
	out = mcp._execute('b = start_remote_daemon("work")\nprint(sorted(b))\nprint(b["timeout"])')[0]
	assert fake_cloud == [name], out
	assert 'liveUrl' not in out and 'live.example' not in out  # it grants control of the browser
	assert 'cdpUrl' not in out and 'cdp.example' not in out  # so does the CDP URL, with no key
	assert out.splitlines()[-1] == str(cli_mcp.CLOUD_TIMEOUT_MINUTES)

	out = mcp._execute('new_tab("data:text/html,<title>cloud page</title>"); wait_for_load(); print(page_info()["title"])')[0]
	assert out.strip().splitlines()[-1] == 'cloud page', out
	assert mcp._execute('print(NAME)')[0].strip() == name

	out = mcp._execute('start_remote_daemon("work")')[0]
	assert f'Daemon {name!r} is already running' in out and 'Traceback' not in out and fake_cloud == [name]


def test_old_mcp_configs_get_their_own_chromium_never_the_users_chrome(fake_cloud, chrome_binary, monkeypatch):
	"""C44: the 0.x `--mcp` server ran its own Chromium; 1.0 sent those configs to the --cli-mcp server, which drives the
	user's logged-in Chrome. `--mcp` keeps a Chromium of its own (until a cloud browser starts); --cli-mcp is unchanged."""
	import asyncio

	from browser_harness import admin

	from browser_use import Browser, cli
	from browser_use.mcp import cli_mcp

	runs = []
	monkeypatch.setattr(cli, '_run_mcp_stdio_server', lambda module, **kwargs: runs.append((module, kwargs)))
	cli._run_mcp_server()
	cli._run_cli_mcp_server()
	assert runs == [('browser_use.mcp.cli_mcp', {'own_browser': True}), ('browser_use.mcp.cli_mcp', {})]
	assert "the user's own Chrome" in cli_mcp.CLIMCPServer()._instructions()

	mcp = cli_mcp.CLIMCPServer(own_browser=True)
	assert mcp._browser is not None and mcp._browser.kind == 'chromium'
	assert "its own Chromium (a temp profile, not the user's Chrome)" in mcp._instructions()
	mcp._browser = Browser('chromium', executable_path=chrome_binary, headless=True)  # CI has no display
	try:
		out, failed = mcp._execute('new_tab("about:blank#own"); print(page_info()["url"])')
		assert not failed and out.strip().endswith('#own'), out  # no_local_chrome: never the user's Chrome
		assert admin.NAME == mcp._browser.name and mcp._screenshot(False, None)
		out = mcp._execute('start_remote_daemon(); print(NAME)')[0]
		assert fake_cloud == [mcp._remote] and out.strip().endswith(mcp._remote), out
		assert mcp._execute('print(NAME)')[0].strip() == mcp._remote  # the cloud browser now, not the Chromium
	finally:
		asyncio.run(mcp._browser.stop())


def test_python_m_browser_use_mcp_is_the_mcp_server_with_its_own_chromium(monkeypatch, capsys):
	"""0.x `python -m browser_use.mcp` ran the --mcp server (own Chromium); 1.0's module form attached to the user's
	logged-in Chrome (own_browser=False)."""
	import runpy

	from browser_use import cli

	runs = []
	monkeypatch.setattr(cli, '_run_mcp_stdio_server', lambda module, **kwargs: runs.append((module, kwargs)))
	with pytest.raises(SystemExit) as exited:
		runpy.run_module('browser_use.mcp', run_name='__main__')
	assert exited.value.code == 0 and runs == [('browser_use.mcp.cli_mcp', {'own_browser': True})]
	assert capsys.readouterr().err.startswith('python -m browser_use.mcp is deprecated')  # rr-install 3: it named --mcp


def test_old_mcp_config_domain_limits_carry_over_and_a_proxy_refuses_to_start(tmp_path, monkeypatch, capsys):
	"""0.x --mcp read allowed_domains from config.json (and BROWSER_USE_ALLOWED_DOMAINS); 1.0 ignored the file, so an MCP
	client kept to one site got a browser that goes anywhere, and the variable killed the server ('Connection closed')."""
	import json

	from browser_use import cli
	from browser_use.mcp import cli_mcp

	runs = []
	monkeypatch.setattr(cli, '_run_mcp_stdio_server', lambda module, **kwargs: runs.append(kwargs))
	monkeypatch.setenv('BROWSER_USE_CONFIG_DIR', str(tmp_path))
	profile = {'id': 'p1', 'default': True, 'allowed_domains': ['example.com'], 'headless': True}
	(tmp_path / 'config.json').write_text(json.dumps({'browser_profile': {'p0': {'id': 'p0'}, 'p1': profile}}))
	assert cli._run_mcp_server() == 0
	monkeypatch.setenv('BROWSER_USE_ALLOWED_DOMAINS', 'example.org, ')
	assert cli._run_mcp_server() == 0
	assert runs == [
		{'own_browser': True, 'allowed_domains': ['example.com']},
		{'own_browser': True, 'allowed_domains': ['example.org']},
	]
	for kwargs in runs:
		domains = cli_mcp.CLIMCPServer(**kwargs)._browser.domains  # pyright: ignore[reportOptionalMemberAccess]
		assert domains.blocked('https://www.iana.org/help/example-domains')
		assert not domains.blocked(f'https://{kwargs["allowed_domains"][0]}/')
	(tmp_path / 'config.json').write_text(json.dumps({'browser_profile': {'p1': {**profile, 'proxy': {'server': 'http://p:8'}}}}))
	assert cli._run_mcp_server() == 2 and len(runs) == 2
	assert 'browser-use --mcp with a proxy' in capsys.readouterr().err


def test_mcp_never_stops_or_drives_a_cloud_browser_another_server_started(fake_cloud, monkeypatch):
	"""C22: two MCP servers both following the guide's start_remote_daemon("work"): B's start failed with "stop it
	first", B's stop_remote_daemon("work") ended A's browser, and A then drove B's new one (its cookies)."""
	from browser_harness import admin

	from browser_use.mcp import cli_mcp

	monkeypatch.delenv('BH_OPEN_LIVE_URL', raising=False)
	other = _name('work')
	admin.start_remote_daemon(other)  # another server's (or the CLI's) cloud browser under the name this server is given
	mcp = cli_mcp.CLIMCPServer()

	out = mcp._execute(f'start_remote_daemon({other!r})')[0]
	out += mcp._execute(f'stop_remote_daemon({other!r})')[0]
	assert admin.daemon_alive(other), out
	assert fake_cloud == [other, mcp._remote] and not admin.daemon_alive(mcp._remote), out


def test_cloud_upload_sends_the_files_bytes_not_a_local_path(fake_cloud, tmp_path):
	"""Astra r1-2: the CLI and MCP namespaces kept browser-harness's upload_file, which hands the browser a path on this
	machine; a cloud browser's host has no such file. The local path returns None; the bytes path returns the count."""
	from browser_use.mcp import cli_mcp

	mcp = cli_mcp.CLIMCPServer()
	mcp._execute(f'start_remote_daemon({_name("upload")!r})')[0]
	(tmp_path / 'cv.txt').write_text('hello cloud')
	out = mcp._execute(
		"new_tab('data:text/html,<input type=file id=f>'); wait_for_load()\n"
		f"print(upload_file('#f', {str(tmp_path / 'cv.txt')!r}), "
		"js(\"document.getElementById('f').files[0].name + ':' + document.getElementById('f').files[0].size\"))"
	)[0]
	assert out.strip().splitlines()[-1] == '1 cv.txt:11', out


def _recorded(name: str, browser_id: str):
	"""A cloud browser recorded under name whose daemon is gone (SIGKILL, OOM: no exit cleanup stopped it)."""
	from browser_use import harness_cloud

	harness_cloud._marker(name).write_text(browser_id)
	return harness_cloud


def test_a_socket_path_too_long_for_the_os_is_one_line_before_a_cloud_browser_is_created(monkeypatch, tmp_path):
	"""Live: with a long HOME (socket path over macOS's 104 bytes) `start_remote_daemon()` in the CLI created and billed a
	cloud browser, then failed with a traceback ending "RuntimeError: stopped remote browser <id>"; local calls printed
	"fatal: AF_UNIX path too long". Neither named the path or the fix, which Browser() already does."""
	from browser_harness import _ipc as ipc
	from browser_harness import admin

	from browser_use import harness_cloud

	if sys.platform == 'win32':
		pytest.skip('Windows uses TCP loopback')
	long_dir = tmp_path / ('a' * 120)
	monkeypatch.setattr(ipc, '_sock_path', lambda name: long_dir / f'bu-{name}.sock')
	created = []
	monkeypatch.setattr(admin, 'start_remote_daemon', lambda *a, **k: created.append(a))
	monkeypatch.setattr(admin, 'ensure_daemon', lambda *a, **k: created.append(a))
	ns: dict = {}
	harness_cloud.install(ns)
	for call in (lambda: ns['start_remote_daemon'](_name('long')), lambda: ns['ensure_daemon']()):
		with pytest.raises(harness_cloud.CloudBrowserError, match=r'socket path is \d+ bytes.*BH_RUNTIME_DIR') as raised:
			call()
		assert str(long_dir) in str(raised.value)
	assert created == []


def test_a_runtime_dir_other_users_can_write_is_refused_and_the_cloud_marker_is_private(monkeypatch, shared_runtime_dir):
	"""EXEC-3 / NET-3: our socket-path error suggested BH_RUNTIME_DIR=/tmp/bh, and browser-harness uses a dir that
	already exists as is. Another user's /tmp/bh held the daemon socket (they could swap it for a fake daemon) and the
	.cloud marker (0644: the browser id, which alone drives the cloud browser)."""
	from browser_harness import admin, helpers

	from browser_use import harness_cloud

	shared = shared_runtime_dir
	created = []
	monkeypatch.setattr(admin, 'start_remote_daemon', lambda *a, **k: created.append(a) or {'id': 'b-secret'})
	monkeypatch.setattr(admin, 'ensure_daemon', lambda *a, **k: created.append(a))
	monkeypatch.setattr(admin, 'daemon_alive', lambda name=None: False)
	monkeypatch.setattr(admin, 'NAME', admin.NAME)  # route() rebinds these
	monkeypatch.setattr(helpers, 'NAME', helpers.NAME)
	ns: dict = {}
	harness_cloud.install(ns)
	for call in (lambda: ns['start_remote_daemon'](_name('shared')), lambda: ns['ensure_daemon']()):
		with pytest.raises(harness_cloud.CloudBrowserError, match=r'is writable by other users.*chmod 700'):
			call()
	shared.chmod(0o700)
	getuid = os.getuid
	monkeypatch.setattr(os, 'getuid', lambda: getuid() + 1)  # the same dir, owned by someone else
	with pytest.raises(harness_cloud.CloudBrowserError, match='owned by another user') as raised:
		ns['ensure_daemon']()
	assert 'chmod' not in str(raised.value) and 'BH_RUNTIME_DIR to a new path' in str(raised.value)  # not theirs to chmod
	assert created == []
	monkeypatch.setattr(os, 'getuid', getuid)  # now a private dir of our own
	name = _name('private')
	old = os.umask(0o022)
	try:
		harness_cloud._marker(name).write_text('')  # 0644, as an older version wrote it
		ns['start_remote_daemon'](name)
	finally:
		os.umask(old)
	marker = harness_cloud._marker(name)
	assert marker.read_text() == 'b-secret' and marker.stat().st_mode & 0o777 == 0o600


def test_stopping_a_cloud_browser_twice_is_a_no_op_and_an_unknown_name_is_one_line():
	"""Live: a second stop_remote_daemon(name) after a successful stop (the skill says to stop when done; the agent cannot
	tell a timeout from a stop) raised a 20-line traceback ending in "daemon 'x' is unavailable for required clean
	shutdown", exit 1. So did a name nothing started."""
	from browser_harness import admin

	name = _name('twice')
	harness_cloud = _recorded(name, '')  # what a successful stop leaves
	ns: dict = {}
	harness_cloud.install(ns)
	try:
		assert not admin.daemon_alive(name)
		ns['stop_remote_daemon'](name)
		assert harness_cloud._recorded_id(name) == ''
		harness_cloud.forget(name)
		with pytest.raises(harness_cloud.CloudBrowserError, match=f'No cloud browser {name!r} is running here'):
			ns['stop_remote_daemon'](name)
	finally:
		harness_cloud.forget(name)


def test_a_new_start_under_a_name_stops_the_browser_still_recorded_there_first(fake_cloud, monkeypatch):
	"""Astra r1-3: the new browser's id overwrote the only record of the old one, which billed until its timeout."""
	from browser_harness import admin

	stops: list[str] = []
	stopped = [False]
	monkeypatch.setattr(admin, '_stop_cloud_browser', lambda browser_id, strict=False: stops.append(browser_id) or stopped[0])
	name = _name('again')
	harness_cloud = _recorded(name, 'browser-a')
	ns: dict = {}
	harness_cloud.install(ns)
	with pytest.raises(harness_cloud.CloudBrowserError, match='browser-a .*could not be stopped, so no new one was started'):
		ns['start_remote_daemon'](name)
	assert fake_cloud == [] and harness_cloud._recorded_id(name) == 'browser-a'
	stopped[0] = True
	ns['start_remote_daemon'](name)
	assert stops == ['browser-a', 'browser-a'] and fake_cloud == [name]


def test_a_failed_cloud_stop_keeps_the_browser_id_for_a_retry(monkeypatch):
	"""Astra r1-4: the id was erased even when the stop failed (cloud API down); later calls had nothing to stop."""
	from browser_harness import admin

	stopped = [False]
	monkeypatch.setattr(admin, '_stop_cloud_browser', lambda browser_id, strict=False: stopped[0])
	name = _name('retry')
	harness_cloud = _recorded(name, 'browser-a')
	try:
		assert harness_cloud.stop_cloud(name) is False and harness_cloud._recorded_id(name) == 'browser-a'
		stopped[0] = True
		assert harness_cloud.stop_cloud(name) is True and harness_cloud._recorded_id(name) == ''
	finally:
		harness_cloud.forget(name)


def test_reload_stops_the_recorded_cloud_browser_before_forgetting_it(monkeypatch):
	"""cubic: `BU_NAME=<name> browser-use --reload` deleted the only record of a cloud browser whose daemon was killed; it
	billed until its timeout with nothing left to stop it."""
	from browser_harness import admin

	stops: list[str] = []
	stopped = [False]
	monkeypatch.setattr(admin, '_stop_cloud_browser', lambda browser_id, strict=False: stops.append(browser_id) or stopped[0])
	name = _name('reload')
	harness_cloud = _recorded(name, 'browser-a')
	try:
		with pytest.raises(harness_cloud.CloudBrowserError, match='Could not stop cloud browser browser-a'):
			harness_cloud.forget(name)
		assert harness_cloud._recorded_id(name) == 'browser-a'  # kept for the retry
		stopped[0] = True
		harness_cloud.forget(name)
		assert stops == ['browser-a', 'browser-a'] and harness_cloud._recorded_id(name) is None
	finally:
		harness_cloud._marker(name).unlink(missing_ok=True)


def test_stop_remote_daemon_stops_the_cloud_browser_after_its_daemon_was_killed(monkeypatch):
	"""Fable r1: browser-harness's stop needs a live daemon ('unavailable for required clean shutdown'); the browser
	billed until its timeout."""
	from browser_harness import admin

	stops: list[str] = []
	monkeypatch.setattr(
		admin, '_stop_cloud_browser', lambda browser_id, strict=False: stops.append(browser_id) or bool(stops[1:])
	)
	name = _name('killed')
	harness_cloud = _recorded(name, 'browser-a')
	ns: dict = {}
	harness_cloud.install(ns)
	try:
		with pytest.raises(harness_cloud.CloudBrowserError, match='Could not stop cloud browser browser-a'):
			ns['stop_remote_daemon'](name)  # the first stop fails: the id stays for the retry
		ns['stop_remote_daemon'](name)
		assert stops == ['browser-a', 'browser-a'] and harness_cloud._recorded_id(name) == ''
	finally:
		harness_cloud.forget(name)


def test_a_cloud_daemon_that_ended_never_falls_back_to_the_local_chrome(fake_cloud):
	from browser_harness import admin

	from browser_use.harness_cloud import CloudBrowserError
	from browser_use.mcp import cli_mcp

	mcp = cli_mcp.CLIMCPServer()
	name = mcp._remote
	mcp._execute('start_remote_daemon()')[0]
	admin.restart_daemon(name)  # the cloud browser timed out / its daemon died

	for out in (mcp._execute('print(page_info())')[0], mcp._execute('print(page_info())')[0]):
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

	server = f"""
import sys, time
from browser_harness import admin
from browser_use.mcp import cli_mcp

def start_remote_daemon(name='remote', profileName=None, **kw):
	admin.ensure_daemon(name=name, env={{'BU_CDP_WS': {chrome['ws']!r}}})
	return {{'id': 'no-such-browser'}}

admin.start_remote_daemon = start_remote_daemon
print(cli_mcp.CLIMCPServer()._execute('start_remote_daemon()'), flush=True)
print('ready', flush=True)
time.sleep(600)
"""
	env = {**os.environ, 'PYTHONPATH': str(ROOT)}
	env.pop('BROWSER_USE_API_KEY', None)  # the reaper's cloud stop then fails on "no key" before any request
	proc = subprocess.Popen([sys.executable, '-c', server], env=env, stdout=subprocess.PIPE, text=True)
	name = f'mcp-{proc.pid}'  # the server's own cloud daemon name
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

		harness_cloud._marker(name).unlink(missing_ok=True)  # its fake id cannot be stopped: forget() would keep it


# An MCP server whose cloud start is faked (no Browser Use Cloud): start_remote_daemon() returns browser id argv[1]
_FAKE_CLOUD_SERVER = """
import asyncio, sys
from browser_use import harness_cloud
from browser_use.mcp import cli_mcp
harness_cloud.start = lambda name, profile, kwargs, namespace: {'id': sys.argv[1]}
if len(sys.argv) > 2:  # record the stops this process makes
	harness_cloud.stop_cloud = lambda name, browser_id=None: open(sys.argv[2], 'a').write(name + chr(10)) > 0
asyncio.run(cli_mcp.main())
"""


def _server_env(**extra: str) -> dict[str, str]:
	env = {**os.environ, 'PYTHONPATH': os.pathsep.join(p for p in (str(ROOT), os.environ.get('PYTHONPATH', '')) if p)}
	env.pop('BROWSER_USE_API_KEY', None)
	return {**env, **extra}


@pytest.mark.skipif(sys.platform != 'win32', reason='POSIX leaves it to the reaper: that stop waits on the daemon')
async def test_mcp_server_stops_its_cloud_browser_itself_when_the_client_closes_it(tmp_path):
	"""win-cli-1: on Windows the official mcp client kills the server's whole Job Object right after the server exits,
	reaper included, and the cloud browser billed on. The server now stops it itself before it exits."""
	from mcp import ClientSession, StdioServerParameters
	from mcp.client.stdio import stdio_client

	stops = tmp_path / 'stops.txt'
	params = StdioServerParameters(command=sys.executable, args=['-c', _FAKE_CLOUD_SERVER, '', str(stops)], env=_server_env())
	with (tmp_path / 'server.err').open('w') as errlog:  # sys.stderr: an earlier test may have left one with no fileno()
		async with stdio_client(params, errlog) as (read, write), ClientSession(read, write) as session:
			await session.initialize()
			result = await session.call_tool('browser_exec', {'code': 'start_remote_daemon()'})
			assert not result.is_error, result.content
	assert stops.read_text().startswith('mcp-')  # read once the client is done with the server: it exited


@pytest.mark.skipif(sys.platform != 'win32', reason='the mcp client kills a Job Object on Windows only')
def test_mcp_cloud_browser_is_stopped_when_the_mcp_client_is_killed_on_windows():
	"""win-cli-1: a killed client closes its Job Object, which kills the server and every process in it at once. The
	reaper runs outside it and still stops the browser: its PATCH goes through a local proxy that records the CONNECT."""
	import socket
	import threading

	seen: list[bytes] = []
	proxy = socket.create_server(('127.0.0.1', 0))

	def serve() -> None:
		while True:
			try:
				conn, _ = proxy.accept()
			except OSError:
				return
			with conn:
				seen.append(conn.recv(4096).split(b'\r\n', 1)[0])

	threading.Thread(target=serve, daemon=True).start()
	client = f"""
import anyio, os, sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
async def main():
	params = StdioServerParameters(command=sys.executable, args=['-c', {_FAKE_CLOUD_SERVER!r}, 'test-browser'], env=dict(os.environ))
	async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
		await session.initialize()
		print((await session.call_tool('browser_exec', {{'code': 'start_remote_daemon()'}})).is_error, flush=True)
		await anyio.sleep(600)
anyio.run(main)
"""
	env = _server_env(BROWSER_USE_API_KEY='bu_' + 'x' * 40, HTTPS_PROXY=f'http://127.0.0.1:{proxy.getsockname()[1]}')
	env.pop('NO_PROXY', None)
	proc = subprocess.Popen([sys.executable, '-c', client], env=env, stdout=subprocess.PIPE, text=True)
	try:
		assert proc.stdout is not None and proc.stdout.readline().strip() == 'False'
		assert not seen  # nothing stopped it while the server runs
		proc.kill()
		proc.wait(10)
		deadline = time.monotonic() + 20
		while not seen and time.monotonic() < deadline:
			time.sleep(0.2)
		assert seen and seen[0].startswith(b'CONNECT api.browser-use.com:443'), seen
	finally:
		proc.kill()
		proxy.close()


async def test_mcp_exec_reports_failures_and_a_cancelled_call_never_bleeds_into_the_next(monkeypatch):
	"""M28: browser_exec never set is_error, a traceback came back as a success. M27: a call the client timed out kept
	running and its prints showed up in the next call's result."""
	import asyncio

	from browser_use.mcp.cli_mcp import CLIMCPServer

	server = CLIMCPServer()
	monkeypatch.setattr(server, '_ensure_daemon', lambda code: None)
	assert server._execute('print("ok")') == ('ok\n', False)
	text, failed = server._execute('1/0')
	assert failed and 'ZeroDivisionError' in text
	runaway = asyncio.ensure_future(
		server._locked(server._execute, 'import time\nfor i in range(6):\n    print("RUNAWAY", i)\n    time.sleep(0.1)')
	)
	await asyncio.sleep(0.15)
	runaway.cancel()
	# runs while the cancelled cell still prints (C23: it no longer holds the lock): none of those prints land here
	text, failed = await server._locked(server._execute, 'import time\nprint("MINE")\ntime.sleep(0.3)')
	assert (text, failed) == ('MINE\n', False)


def test_a_failing_cell_shows_its_own_frames_and_names_the_helpers_for_an_unknown_name(monkeypatch):
	"""Daytona 1.0.1: every failing cell's traceback began with this server's exec() frame, and click_element(3) (a 0.x
	action) said only NameError, where the piped CLI names the 1.0 helpers."""
	from browser_use.mcp.cli_mcp import CLIMCPServer

	server = CLIMCPServer()
	monkeypatch.setattr(server, '_ensure_daemon', lambda code: None)
	text, failed = server._execute('click_element(3)')
	assert failed and 'cli_mcp.py' not in text and 'File "<string>", line 1' in text, text
	assert "'click_element' is not defined here" in text and 'new_tab(url)' in text and 'page_info()' in text, text
	text, failed = server._execute('import json\njson.loads("{")')
	assert failed and 'cli_mcp.py' not in text and 'JSONDecodeError' in text and 'not defined here' not in text, text


async def test_mcp_a_cancelled_call_lets_go_of_the_lock_and_a_queued_one_never_runs():
	"""C23: a hung cell (find /, a wait that never returns) kept the lock after the client cancelled it, so every later
	call timed out and a cloud browser could not even be stopped. The MCP SDK cancels through an AnyIO cancel scope.
	A call cancelled while it still waited for the lock must never run later."""
	import threading

	import anyio

	from browser_use.mcp.cli_mcp import CLIMCPServer

	server = CLIMCPServer()
	release, ran = threading.Event(), []

	def work(tag: str, block: bool = False) -> tuple[str, bool]:
		ran.append(tag)
		if block:
			release.wait()
		return tag, False

	async def cancelled(tag: str, block: bool, after: float) -> None:
		with anyio.move_on_after(after):  # what the MCP server does with a request the client cancelled
			await server._locked(work, tag, block)

	try:
		async with anyio.create_task_group() as tg:
			tg.start_soon(cancelled, 'hung', True, 0.1)
			await anyio.sleep(0.02)
			tg.start_soon(cancelled, 'queued', False, 0.05)  # gives up while 'hung' still holds the lock
		with anyio.fail_after(2):
			assert await server._locked(work, 'next') == ('next', False)  # while the hung thread still runs
		assert ran == ['hung', 'next']
	finally:
		release.set()


async def test_mcp_a_local_browser_that_cannot_attach_is_one_tool_error_naming_the_reason(monkeypatch):
	"""Live: with no local Chrome to attach, browser_screenshot raised out of the handler (the client got a JSON-RPC
	error, not a tool result the model reads) and browser_exec, even of `print(1+1)`, returned a 14-line traceback of
	browser-harness internals ending in "didn't come up -- check <log file>": the reason was only in that log."""
	from browser_harness import admin
	from mcp import types

	from browser_use import harness_cloud
	from browser_use.mcp import cli_mcp

	def no_chrome(*args, **kwargs):
		raise RuntimeError(f"daemon {admin.NAME} didn't come up -- check /tmp/bu-{admin.NAME}.log")

	monkeypatch.setattr(harness_cloud, 'ensure_daemon', no_chrome)
	reason = 'fatal: chrome-not-running: no supported Chromium-family browser is running -- start Chrome, then retry'
	monkeypatch.setattr(admin, '_log_tail', lambda name=None: reason)
	_desktop_with_chrome(monkeypatch)  # where the chrome://inspect setup works: the user's Chrome, never a fallback
	monkeypatch.delenv('BROWSER_USE_API_KEY', raising=False)
	mcp = cli_mcp.CLIMCPServer()
	handler = mcp.server._request_handlers['tools/call'].handler
	for key in ('', 'bu_test'):
		if key:
			monkeypatch.setenv('BROWSER_USE_API_KEY', key)
		for name, arguments in (('browser_exec', {'code': 'print(1 + 1)'}), ('browser_screenshot', {})):
			r = await handler(None, types.CallToolRequestParams(name=name, arguments=arguments))
			text = r.content[0].text  # type: ignore[union-attr]
			assert r.is_error and 'Traceback' not in text and len(text.strip().splitlines()) == 1, (name, text)
			assert 'chrome-not-running: no supported Chromium-family browser is running' in text, (name, text)
			# the way out when there is no local browser: start_remote_daemon() only with a key for it to use
			assert ('start_remote_daemon()' in text) == bool(key) and ('BROWSER_USE_API_KEY' in text) != bool(key), text


def _desktop_with_chrome(monkeypatch):
	from browser_use.browser import local

	monkeypatch.setattr(local, 'has_display', lambda: True)
	monkeypatch.setenv('BH_CHROME_PATH', sys.executable)  # an installed browser, as far as find_binary can tell


@pytest.fixture
def headless_box(monkeypatch):
	"""A server with no display and no attachable Chrome, where nothing may attach the user's Chrome. Every Browser
	start is recorded and answered by start (default: a daemon named own-chromium)."""
	from browser_harness import admin, helpers

	from browser_use import Browser, harness_cloud
	from browser_use.browser import local

	monkeypatch.setattr(admin, 'NAME', admin.NAME)  # routing rebinds these: restore them for the next test
	monkeypatch.setattr(helpers, 'NAME', helpers.NAME)
	monkeypatch.setattr(local, 'has_display', lambda: False)
	monkeypatch.setattr(local, 'live_debug_dirs', lambda: [])
	monkeypatch.setattr(harness_cloud, 'ensure_daemon', lambda *a, **k: pytest.fail("attached the user's Chrome"))
	monkeypatch.delenv('BU_CDP_URL', raising=False)
	monkeypatch.delenv('BU_CDP_WS', raising=False)
	monkeypatch.delenv('BROWSER_USE_API_KEY', raising=False)
	box = {'kinds': [], 'start': None}

	async def start(self):
		box['kinds'].append(self.kind)
		if box['start']:
			return await box['start']()
		return {'BU_NAME': 'own-chromium'}

	monkeypatch.setattr(Browser, 'start', start)
	return box


async def _exec(mcp, code: str) -> tuple[list[str], bool]:
	"""A browser_exec call as the client sees it: the text of each content block, and is_error."""
	from mcp import types

	handler = mcp.server._request_handlers['tools/call'].handler
	r = await handler(None, types.CallToolRequestParams(name='browser_exec', arguments={'code': code}))
	return [c.text for c in r.content], r.is_error


async def test_cli_mcp_on_a_headless_box_drives_its_own_chromium_and_says_so(headless_box):
	"""1.0.1: 144 headless Linux devices got only "remote-debugging-setup: none of your browsers has remote debugging on
	... start_remote_daemon()" from every browser_exec, with no Chrome to set up and no key for a cloud browser."""
	from browser_use.mcp import cli_mcp

	mcp = cli_mcp.CLIMCPServer()
	(out, note), failed = await _exec(mcp, 'print(NAME)')
	assert not failed and out == 'own-chromium\n' and headless_box['kinds'] == ['chromium'], (out, note)
	assert 'own Chromium on a temp profile, not your Chrome (no display here' in note, note
	assert await _exec(mcp, 'print(NAME)') == (['own-chromium\n'], False)  # said once


@pytest.mark.skipif(sys.platform == 'win32', reason='the fake uvx is a POSIX script')
async def test_cli_mcp_with_no_browser_installed_installs_chromium_without_touching_stdout(
	headless_box, tmp_path, monkeypatch, capfd
):
	"""A fresh server or container (python:3.12-slim) has no browser at all: the first call installs Playwright's
	Chromium as `browser-use install` does, and its output never reaches stdout, the MCP channel."""
	from browser_use.mcp import cli_mcp

	uvx = tmp_path / 'uvx'
	uvx.write_text(
		f'#!{sys.executable}\nimport sys\nprint("Downloading Chromium")\nopen(sys.argv[0] + ".args", "w").write(" ".join(sys.argv[1:]))\n'
	)
	uvx.chmod(0o755)
	monkeypatch.setenv('PATH', str(tmp_path))  # this uvx only: never the machine's apt-get, even as root
	starts = []

	async def start():
		starts.append(1)
		if len(starts) == 1:
			raise RuntimeError('No Chrome, Chromium or Edge found (tried chromium on PATH). Install one ...')
		return {'BU_NAME': 'own-chromium'}

	headless_box['start'] = start
	(out, note), failed = await _exec(cli_mcp.CLIMCPServer(), 'print(NAME)')
	assert not failed and out == 'own-chromium\n' and "Installed Playwright's Chromium" in note, (out, note)
	args = (tmp_path / 'uvx.args').read_text()
	assert args.startswith('playwright install chromium --no-shell'), args
	assert ('--with-deps' in args) == (sys.platform.startswith('linux') and os.geteuid() == 0), args  # system libraries
	assert 'Downloading' not in capfd.readouterr().out  # the fd itself: a child process writes there, not sys.stdout


async def test_with_no_browser_at_all_the_error_says_what_to_install_and_names_the_cloud_only_with_a_key(
	headless_box, monkeypatch
):
	"""No Chrome, Chromium that cannot start, no key: one line saying what to do. start_remote_daemon() fails without a
	key, so it is named only when there is one."""
	from mcp import types

	from browser_use.mcp import cli_mcp

	monkeypatch.setenv('PATH', '')  # no uvx to install Chromium with

	async def start():
		raise RuntimeError('No Chrome, Chromium or Edge found (tried chromium on PATH). Install one ...')

	headless_box['start'] = start
	for key in ('', 'bu_test'):
		if key:
			monkeypatch.setenv('BROWSER_USE_API_KEY', key)
		handler = cli_mcp.CLIMCPServer().server._request_handlers['tools/call'].handler
		r = await handler(None, types.CallToolRequestParams(name='browser_exec', arguments={'code': 'print(1)'}))
		text = r.content[0].text  # type: ignore[union-attr]
		assert r.is_error and len(text.strip().splitlines()) == 1 and text.startswith('Error: No browser to drive'), text
		assert 'uvx (to install Chromium) is not on PATH' in text and 'Install Google Chrome or Chromium' in text, text
		assert ('start_remote_daemon()' in text) == bool(key) and ('BROWSER_USE_API_KEY' in text) != bool(key), text


async def test_cli_mcp_keeps_the_users_chrome_where_it_can_be_set_up(monkeypatch):
	"""A desktop with Chrome installed keeps the chrome://inspect setup: driving the user's logged-in Chrome is the point
	of --cli-mcp. Its first result says so, in a block of its own: a client that parses the code's output (JSON) broke
	once per server start when the note came first in it."""
	from browser_harness import admin, helpers

	from browser_use import Browser, harness_cloud
	from browser_use.mcp import cli_mcp

	monkeypatch.setattr(admin, 'NAME', admin.NAME)
	monkeypatch.setattr(helpers, 'NAME', helpers.NAME)
	_desktop_with_chrome(monkeypatch)
	monkeypatch.delenv('BU_CDP_URL', raising=False)
	monkeypatch.delenv('BU_CDP_WS', raising=False)
	attached = []
	monkeypatch.setattr(harness_cloud, 'ensure_daemon', lambda *a, **k: attached.append(1))
	monkeypatch.setattr(Browser, 'start', lambda self: pytest.fail('started its own Chromium'))
	mcp = cli_mcp.CLIMCPServer()
	assert await _exec(mcp, 'print(1)') == (['1\n', 'Browser: your own Chrome (its tabs and logins).'], False)
	assert await _exec(mcp, 'print(2)') == (['2\n'], False) and attached == [1, 1]


def _setup_fails(monkeypatch, error: str = 'remote-debugging-setup: none of your browsers has remote debugging on (...)'):
	"""A desktop with Chrome whose remote debugging is off: attaching it raises require_debug_port's setup error."""
	from browser_harness import admin, daemon, helpers

	from browser_use import harness_cloud

	monkeypatch.setattr(admin, 'NAME', admin.NAME)
	monkeypatch.setattr(helpers, 'NAME', helpers.NAME)
	monkeypatch.setattr(daemon, 'remote_debugging_toggle_profiles', lambda: [])  # never this machine's Local State
	_desktop_with_chrome(monkeypatch)
	monkeypatch.delenv('BU_CDP_URL', raising=False)
	monkeypatch.delenv('BU_CDP_WS', raising=False)
	attempts = []

	def ensure_daemon(*a, **k):
		attempts.append(1)
		raise RuntimeError(error)

	monkeypatch.setattr(harness_cloud, 'ensure_daemon', ensure_daemon)
	return attempts


async def test_cli_mcp_with_remote_debugging_off_drives_its_own_chromium_and_says_how_to_get_chrome(monkeypatch):
	"""1.0.0/1.0.1: ~390 Mac and Windows devices, and 72 of 101 Cursor-on-Linux ones, got only the chrome://inspect setup
	error from every browser_exec and never ran a cell. The setup error now falls back to the server's own Chromium; the
	note says how to switch to the user's Chrome. Once on it, it stays (the model's tabs live there)."""
	from browser_use import Browser
	from browser_use.mcp import cli_mcp

	attempts = _setup_fails(monkeypatch)
	kinds = []

	async def start(self):
		kinds.append(self.kind)
		return {'BU_NAME': 'own-chromium'}

	monkeypatch.setattr(Browser, 'start', start)
	mcp = cli_mcp.CLIMCPServer()
	(out, note), failed = await _exec(mcp, 'print(NAME)')
	assert not failed and out == 'own-chromium\n' and kinds == ['chromium'], (out, note)
	assert "this server's own Chromium on a temp profile, not your Chrome (your Chrome has remote debugging off" in note
	assert 'chrome://inspect/#remote-debugging' in note and 'restart this MCP server' in note, note
	assert await _exec(mcp, 'print(NAME)') == (['own-chromium\n'], False) and attempts == [1]


async def test_a_setup_error_with_no_chromium_to_fall_back_on_keeps_the_setup_steps(monkeypatch):
	"""Brave or Arc with remote debugging off: find_binary has no Chromium to launch, so the setup steps are the only way
	and the error stays as 1.0.1 gave it (not "No browser to drive"). The next call tries the user's browser again.
	Other attach errors never fall back."""
	from browser_use import Browser
	from browser_use.mcp import cli_mcp

	attempts = _setup_fails(monkeypatch)

	async def start(self):
		raise RuntimeError('No Chrome, Chromium or Edge found (tried ...)')

	monkeypatch.setattr(Browser, 'start', start)
	mcp = cli_mcp.CLIMCPServer()
	for n in (1, 2):
		(out,), failed = await _exec(mcp, 'print(1)')
		assert failed and out.startswith('Error: remote-debugging-setup: none of your browsers') and len(attempts) == n, out
	_setup_fails(monkeypatch, "daemon default didn't come up")
	monkeypatch.setattr(Browser, 'start', lambda self: pytest.fail('fell back on an error that is not the setup'))
	(out,), failed = await _exec(cli_mcp.CLIMCPServer(), 'print(1)')
	assert failed and "didn't come up" in out, out


async def test_a_setup_error_with_the_toggle_on_never_falls_back(monkeypatch, tmp_path):
	"""Review: remote debugging turned on but Chrome not up yet (a slow cold start, or closed while Edge runs) gives the
	same setup error. Falling back there held the server on its own Chromium until a restart, with a note saying the
	toggle was off. 1.0.1's error stays, and the next call attaches the user's Chrome."""
	from browser_harness import daemon

	from browser_use import Browser
	from browser_use.mcp import cli_mcp

	attempts = _setup_fails(monkeypatch)
	monkeypatch.setattr(daemon, 'remote_debugging_toggle_profiles', lambda: [tmp_path])
	monkeypatch.setattr(Browser, 'start', lambda self: pytest.fail('fell back with the toggle on'))
	(out,), failed = await _exec(cli_mcp.CLIMCPServer(), 'print(1)')
	assert failed and out.startswith('Error: remote-debugging-setup: none of your browsers') and attempts == [1], out


def test_every_setup_fallback_note_says_to_restart_the_server():
	"""Review: a left-over DevToolsActivePort also falls back, and its own "then run again" did nothing once the server
	ran its own Chromium."""
	from browser_use.mcp import cli_mcp

	left = RuntimeError(
		'remote-debugging-setup: /x/DevToolsActivePort is left from an earlier browser session and another process now '
		'listens on its port 9222; browser-harness would attach to that process. Delete that file (Chrome writes a new one '
		'when remote debugging starts), then run again.'
	)
	why = cli_mcp._setup_reason(left)
	assert why.startswith('/x/DevToolsActivePort is left') and why.endswith('starts), then restart this MCP server'), why
	assert cli_mcp._setup_reason(RuntimeError('remote-debugging-setup: none of your browsers ...')) == cli_mcp.CHROME_SETUP


def test_browser_exec_code_writes_text_files_as_utf8_on_a_cp1252_locale(monkeypatch, tmp_path):
	"""1.0.0: 15 devices' cells failed with UnicodeEncodeError, the model's own open(path, 'w').write(page_text) on
	Windows (cp1252). The agent's worker runs with PYTHONUTF8=1; browser_exec code now gets the same default."""
	import locale

	from browser_use.mcp import cli_mcp

	monkeypatch.setattr(locale, 'getpreferredencoding', lambda do_setlocale=True: 'cp1252')
	monkeypatch.setattr(cli_mcp.CLIMCPServer, '_ensure_daemon', lambda self, code: None)
	path = tmp_path / 'out.txt'
	code = f"open({str(path)!r}, 'w').write('\u00e9t\u00e9 \U0001f600')\nprint(open({str(path)!r}).read())\nprint(open({str(path)!r}, 'rb').read()[:4])"
	out, failed = cli_mcp.CLIMCPServer()._execute(code)
	assert not failed and out == "\u00e9t\u00e9 \U0001f600\nb'\\xc3\\xa9t\\xc3'\n", out
	assert open(path, encoding='cp1252', errors='replace').read() != '\u00e9t\u00e9 \U0001f600'  # it really is UTF-8 on disk


def test_cli_and_mcp_cdp_calls_wait_20_s_unless_the_caller_says_otherwise(monkeypatch):
	"""browser-harness waits 5 s for any CDP answer; on --cli-mcp 5-8% of devices hit _IPCResponseTimeout on a click or a
	navigation. capture.install (the CLI and --cli-mcp) gives every call the agent's 20 s; an explicit timeout stays."""
	from browser_harness import helpers

	from browser_use.repl import capture

	sent = []
	raw = lambda method, session_id=None, **params: sent.append((method, params.get('_response_timeout'))) or {}  # noqa: E731
	monkeypatch.setattr(helpers, 'cdp', raw)
	capture.install()
	helpers.cdp('Input.dispatchMouseEvent', type='mousePressed', x=1, y=1)
	helpers.cdp('Runtime.evaluate', expression='1', _response_timeout=2)
	assert sent == [('Input.dispatchMouseEvent', 20.0), ('Runtime.evaluate', 2)]


@pytest.mark.parametrize('opened_by', ['before', 'this call'])
def test_cli_and_mcp_cdp_calls_on_a_page_a_dialog_froze_say_so(monkeypatch, opened_by):
	"""Review: with 20 s and no dialog check, every js() or click on a page an alert() froze waited 20 s and ended in a
	bare timeout. As in the agent's cdp(): 2 s once a dialog is known, and the timeout names the dialog. A timeout with
	no dialog stays a timeout."""
	from browser_harness import helpers

	from browser_use.repl import capture

	sent, dialog = [], {'type': 'confirm', 'message': 'Leave?'}
	pending = [dialog] if opened_by == 'before' else [None, dialog]

	def raw(method, session_id=None, **params):
		sent.append(params['_response_timeout'])
		raise TimeoutError

	monkeypatch.setattr(helpers, 'cdp', raw)
	monkeypatch.setattr(helpers, '_send', lambda req: {'dialog': pending.pop(0) if pending else None})
	capture.install()
	with pytest.raises(RuntimeError, match=r"A JavaScript confirm is open \('Leave\?'\).*Page.handleJavaScriptDialog"):
		helpers.cdp('Runtime.evaluate', expression='1')
	assert sent == ([2.0] if opened_by == 'before' else [20.0])
	with pytest.raises(TimeoutError):
		helpers.cdp('Runtime.evaluate', expression='1')


@pytest.mark.parametrize('browser', ['brave', 'none', 'snap'])
async def test_a_desktop_keeps_any_browser_it_can_set_up_and_never_installs_chromium(browser, tmp_path, monkeypatch):
	"""1.0.1 review: on a desktop whose browser find_binary does not know (Brave, Arc, Dia, a Flatpak Chrome) --cli-mcp
	fell back to its own Chromium and installed Playwright's (150 MB) inside one tool call. 1.0.0 set up the user's
	browser there. A desktop with no browser at all gets the error naming `browser-use install`, never an install; one
	with only Snap Chromium says so, not 'no Chrome is installed'."""
	from browser_harness import admin, daemon, helpers

	from browser_use import Browser, harness_cloud
	from browser_use.browser import local
	from browser_use.mcp import cli_mcp

	monkeypatch.setattr(admin, 'NAME', admin.NAME)
	monkeypatch.setattr(helpers, 'NAME', helpers.NAME)
	monkeypatch.setattr(local, 'has_display', lambda: True)
	monkeypatch.setattr(local, 'live_debug_dirs', lambda: [])
	monkeypatch.delenv('BU_CDP_URL', raising=False)
	monkeypatch.delenv('BU_CDP_WS', raising=False)
	brave = tmp_path / 'BraveSoftware/Brave-Browser'
	monkeypatch.setattr(daemon, 'PROFILES', [tmp_path / 'google-chrome', brave])
	if browser == 'brave':
		brave.mkdir(parents=True)
		(brave / 'Local State').write_text('{}')
	snap = '/usr/bin/chromium-browser is Snap Chromium, which cannot open DevTools for a browser it did not start itself.'
	missing = 'No Chrome, Chromium or Edge found (tried chromium on PATH). Install one ...'

	def find_binary(*a, **k):
		raise RuntimeError(snap if browser == 'snap' else missing)

	async def start(self):
		local.find_binary()  # what Browser('chromium').start() does first

	monkeypatch.setattr(local, 'find_binary', find_binary)
	monkeypatch.setattr(Browser, 'start', start)
	monkeypatch.setattr(cli_mcp, '_install_chromium', lambda: pytest.fail('installed Chromium on a desktop'))
	attached = []
	monkeypatch.setattr(harness_cloud, 'ensure_daemon', lambda *a, **k: attached.append(1))
	(text, *note), failed = await _exec(cli_mcp.CLIMCPServer(), 'print(1)')
	if browser == 'brave':
		assert (text, note, failed, attached) == ('1\n', ['Browser: your own Chrome (its tabs and logins).'], False, [1])
		return
	assert failed and not attached and text.startswith('Error: No browser to drive') and 'browser-use install' in text, text
	why = 'only Snap Chromium is installed' if browser == 'snap' else 'no Chrome, Chromium or Edge is installed'
	assert f'no Chrome to attach ({why}' in text, text


@pytest.mark.chrome
def test_cli_mcp_on_a_headless_box_opens_a_page_in_its_own_chromium(chrome_binary, monkeypatch):
	"""End to end on a real Chromium: what a headless server's first browser_exec does."""
	from browser_harness import admin, helpers

	from browser_use import harness_cloud
	from browser_use.browser import local
	from browser_use.mcp import cli_mcp

	monkeypatch.setattr(admin, 'NAME', admin.NAME)
	monkeypatch.setattr(helpers, 'NAME', helpers.NAME)
	monkeypatch.setattr(local, 'has_display', lambda: False)
	monkeypatch.setattr(local, 'live_debug_dirs', lambda: [])
	monkeypatch.setattr(harness_cloud, 'ensure_daemon', lambda *a, **k: pytest.fail("attached the user's Chrome"))
	monkeypatch.setenv('BH_CHROME_PATH', chrome_binary)
	monkeypatch.delenv('BU_CDP_URL', raising=False)
	mcp = cli_mcp.CLIMCPServer()
	try:
		out, failed = mcp._execute(
			'new_tab("data:text/html,<title>own page</title>"); wait_for_load(); print(page_info()["title"])'
		)
		assert not failed and out == 'own page\n' and 'own Chromium' in (mcp._note or ''), (out, mcp._note)
	finally:
		if mcp._browser is not None:
			import asyncio

			asyncio.run(mcp._browser.stop())


def test_mcp_stray_prints_never_reach_the_protocol_stream(tmp_path):
	"""M29: print() from a thread the model's code started landed on stdout and broke the client's JSON-RPC parsing."""
	import json
	import os
	import subprocess
	import sys
	import time

	env = {**os.environ, 'BU_CDP_URL': 'http://127.0.0.1:1', 'BU_NAME': f'butestmcp{os.getpid()}', 'HOME': str(tmp_path)}
	proc = subprocess.Popen(
		[sys.executable, '-m', 'browser_use', '--cli-mcp'],
		stdin=subprocess.PIPE,
		stdout=subprocess.PIPE,
		stderr=subprocess.PIPE,
		env=env,
		cwd=tmp_path,
	)
	code = 'if False: start_remote_daemon()\nimport threading, time\nthreading.Thread(target=lambda: (time.sleep(0.5), print("LATE"))).start()'
	messages = [
		{
			'jsonrpc': '2.0',
			'id': 1,
			'method': 'initialize',
			'params': {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 't', 'version': '1'}},
		},
		{'jsonrpc': '2.0', 'method': 'notifications/initialized'},
		{'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {'name': 'browser_exec', 'arguments': {'code': code}}},
	]
	assert proc.stdin and proc.stdout
	for m in messages:
		proc.stdin.write((json.dumps(m) + '\n').encode())
		proc.stdin.flush()
	lines: list[str] = []
	while not any(json.loads(line).get('id') == 2 for line in lines):  # a slow runner's first call can take seconds
		line = proc.stdout.readline().decode()
		assert line, 'the server ended before it answered the call'
		lines += [line] if line.strip() else []
	time.sleep(2)  # the thread prints 0.5 s after the call
	out, err = proc.communicate(timeout=30)
	lines += [line for line in out.decode().splitlines() if line.strip()]
	assert len(lines) == 2 and all(json.loads(line)['id'] in (1, 2) for line in lines), out
	assert b'LATE' in err


def test_concurrent_cold_starts_against_a_cdp_url_spawn_one_daemon_at_a_time(monkeypatch):
	"""M31: with BU_CDP_URL, concurrent CLI cold starts raced (browser-harness takes no spawn lock in CDP mode) and
	orphaned daemons."""
	import socket
	import threading
	import time

	from browser_harness import admin

	from browser_use import harness_cloud

	listener = socket.create_server(('127.0.0.1', 0))  # a refused BU_CDP_URL now fails before the spawn lock
	monkeypatch.setenv('BU_CDP_URL', f'http://127.0.0.1:{listener.getsockname()[1]}')
	active, peak, lock = [0], [0], threading.Lock()

	def ensure(wait=None, name=None, env=None):
		with lock:
			active[0] += 1
			peak[0] = max(peak[0], active[0])
		time.sleep(0.2)
		with lock:
			active[0] -= 1

	monkeypatch.setattr(admin, 'ensure_daemon', ensure)
	name = f'butestcdpspawn{os.getpid()}'
	threads = [threading.Thread(target=harness_cloud.ensure_daemon, kwargs={'name': name}) for _ in range(3)]
	for t in threads:
		t.start()
	for t in threads:
		t.join(10)
	listener.close()
	assert peak[0] == 1


def test_mcp_own_chromium_ignores_a_stale_cloud_marker_and_starts_one_at_a_time(monkeypatch):
	"""Review: --mcp checked was_cloud(f'mcp-{pid}'): a .cloud marker an earlier server with the same pid left sent this
	one to ensure_daemon() on admin.NAME='default', the user's Chrome (C44). And a cell the client gave up on could run
	Browser.start() beside the next call's, each on its own event loop."""
	import asyncio
	import threading

	from browser_harness import _ipc as ipc
	from browser_harness import admin, helpers

	from browser_use import harness_cloud
	from browser_use.mcp import cli_mcp

	monkeypatch.setattr(admin, 'NAME', admin.NAME)
	monkeypatch.setattr(helpers, 'NAME', helpers.NAME)
	mcp = cli_mcp.CLIMCPServer(own_browser=True)
	marker = ipc.pid_path(mcp._remote).with_suffix('.cloud')
	marker.parent.mkdir(parents=True, exist_ok=True)
	marker.write_text('')  # stopped cloud browser of an earlier server with this pid
	inside, most = [0], [0]

	async def start():
		inside[0] += 1
		most[0] = max(most[0], inside[0])
		await asyncio.sleep(0.2)
		inside[0] -= 1
		return {'BU_NAME': 'own-chromium'}

	monkeypatch.setattr(mcp._browser, 'start', start)
	monkeypatch.setattr(harness_cloud, 'ensure_daemon', lambda *a, **k: pytest.fail("drove the user's Chrome"))
	mcp._ensure_namespace()
	try:
		threads = [threading.Thread(target=mcp._attach) for _ in range(2)]
		for t in threads:
			t.start()
		for t in threads:
			t.join(10)
	finally:
		marker.unlink(missing_ok=True)
	assert admin.NAME == 'own-chromium' and most[0] == 1


def test_mcp_servers_keep_their_daemons_apart_with_bh_runtime_dir_set(tmp_path):
	"""rr-climcp 1: with BH_RUNTIME_DIR set (what our socket-path error tells users to do), browser-harness named every
	daemon's files plain bu.sock / bu.pid / bu.cloud inside the MCP server: server B drove server A's cloud browser, a
	stopped cloud browser left a bu.cloud that failed every later server's local calls, and start_remote_daemon() after
	a local call found 'Daemon mcp-<pid> is already running' (the local one)."""
	code = (
		'from browser_harness import _ipc as ipc, admin\n'
		'from browser_use.mcp import cli_mcp\n'
		's = cli_mcp.CLIMCPServer()\n'
		'print(ipc._sock_path(s._remote) != ipc._sock_path(admin.NAME), ipc.pid_path(s._remote) != ipc.pid_path(admin.NAME))\n'
	)
	env = {k: v for k, v in os.environ.items() if not k.startswith('BH_')}
	env.update(BH_RUNTIME_DIR=str(tmp_path), BH_UPDATE_CHECK='0', PYTHONPATH=str(ROOT))
	r = subprocess.run([sys.executable, '-c', code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
	assert r.stdout.strip() == 'True True', r.stdout + r.stderr


def test_mcp_with_allowed_domains_refuses_a_blocked_url_in_so_many_words():
	"""rr-climcp 3: --mcp with allowed_domains kept the page on about:blank, but new_tab() returned success and the next
	page_info() failed with 'Inspected target navigated or closed': the model was never told the domain is blocked."""
	from browser_use.mcp import cli_mcp

	mcp = cli_mcp.CLIMCPServer(own_browser=True, allowed_domains=['example.com'])
	for code in (
		"new_tab('https://blocked.example.org/')",
		"goto_url('https://blocked.example.org/')",
		"http_get('https://blocked.example.org/')",
	):
		out, failed = mcp._execute(code, connect=False)
		assert failed and 'blocked: blocked.example.org is not in allowed_domains' in out, out


def test_mcp_with_allowed_domains_has_no_cloud_browser_to_escape_them(monkeypatch):
	"""Fable 1.0.0: a cloud browser has no domain Guard, so start_remote_daemon() under --mcp's allowed_domains let raw
	cdp/js navigations, clicks and redirects open any site."""
	from browser_harness import admin

	from browser_use.mcp import cli_mcp

	monkeypatch.setattr(admin, 'start_remote_daemon', lambda *a, **k: pytest.fail('started a cloud browser'))
	mcp = cli_mcp.CLIMCPServer(own_browser=True, allowed_domains=['example.com'])
	monkeypatch.setattr(mcp, '_attach', lambda: pytest.fail('attached a browser'))
	for code in ('start_remote_daemon()', 'stop_remote_daemon()'):
		out, failed = mcp._execute(code)
		name = code.removesuffix('()')
		assert failed and f"PermissionError: {name}() is off: this server's allowed_domains" in out, out
	assert 'start_remote_daemon() is off' in mcp._instructions()


def test_mcp_http_get_is_plain_http_from_this_machine_even_with_a_key(monkeypatch):
	"""Fable 1.0.0: without domain rules, --cli-mcp kept browser-harness's http_get, which with BROWSER_USE_API_KEY set
	sent the URL and its headers (Authorization, cookies) to the fetch-use proxy instead of fetching it here."""
	import threading
	from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

	import fetch_use

	from browser_use.mcp import cli_mcp

	seen = []

	class Handler(BaseHTTPRequestHandler):
		def do_GET(self):
			seen.append(self.headers.get('Authorization'))
			self.send_response(200)
			self.end_headers()
			self.wfile.write(b'local ok')

		def log_message(self, *a):
			pass

	server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
	threading.Thread(target=server.serve_forever, daemon=True).start()
	monkeypatch.setenv('BROWSER_USE_API_KEY', 'bu_test')
	monkeypatch.setattr(fetch_use, 'fetch_sync', lambda *a, **k: pytest.fail('http_get went through fetch-use'))
	url = f'http://127.0.0.1:{server.server_address[1]}/internal'
	try:
		for mcp in (cli_mcp.CLIMCPServer(), cli_mcp.CLIMCPServer(own_browser=True)):
			out, failed = mcp._execute(f'print(http_get({url!r}, headers={{"Authorization": "Bearer t"}}))', connect=False)
			assert (out, failed) == ('local ok\n', False)
	finally:
		server.shutdown()
	assert seen == ['Bearer t', 'Bearer t']
