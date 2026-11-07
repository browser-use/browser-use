"""Browser('chromium') and Browser('chrome', profile=...): launching, profile copies, stopping, and which running
Chrome Browser('chrome') attaches to. Fake browsers stand in for Chrome where the test is about our side; the
end-to-end tests at the bottom launch the real Chrome (marked `chrome`)."""

import asyncio
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path

import pytest
from conftest import script

from browser_use import Agent, Browser
from browser_use.browser import browser as browser_mod
from browser_use.browser import local as _local

posix_only = pytest.mark.skipif(sys.platform == 'win32', reason='the fake browser is a shebang script')


@pytest.fixture
def fake_chrome(tmp_path):
	"""fake_chrome(mode) -> path of an executable that behaves like Chrome at start. It records its argv and pid in
	tmp_path. ok: writes DevToolsActivePort; slow: writes it after 0.5 s; hang: never; exit: dies with a stderr line;
	sandbox: dies like Chrome without a usable sandbox unless --no-sandbox is passed."""

	def make(mode: str) -> str:
		path = tmp_path / f'fake-chrome-{mode}'
		path.write_text(
			f"""#!{sys.executable}
import os, pathlib, sys, time
args = sys.argv[1:]
out = pathlib.Path({str(tmp_path)!r})
(out / 'argv').write_text('\\n'.join(args)); (out / 'pid').write_text(str(os.getpid()))
udd = pathlib.Path(next(a.split('=', 1)[1] for a in args if a.startswith('--user-data-dir=')))
mode = {mode!r}
if mode == 'exit':
	print('boom: bad flag', file=sys.stderr); sys.exit(3)
if mode == 'sandbox' and '--no-sandbox' not in args:
	print('[FATAL:zygote_host_impl_linux.cc] No usable sandbox!', file=sys.stderr); sys.exit(1)
if mode == 'slow':
	time.sleep(0.5)
if mode != 'hang':
	(udd / 'DevToolsActivePort').write_text('4321\\n/devtools/browser/fake\\n')
time.sleep(600)
"""
		)
		path.chmod(0o755)
		return str(path)

	return make


def alive(pid: int) -> bool:
	try:
		os.kill(pid, 0)
		return True
	except ProcessLookupError:
		return False


@posix_only
def test_fresh_browser_gets_its_own_temp_profile_and_stop_removes_everything(fake_chrome, tmp_path):
	lb = _local.LocalBrowser()
	ws = lb.start(executable_path=fake_chrome('ok'), headless=True)
	argv = (tmp_path / 'argv').read_text().splitlines()
	pid = int((tmp_path / 'pid').read_text())
	assert ws == 'ws://127.0.0.1:4321/devtools/browser/fake'
	assert f'--user-data-dir={lb.tmp / "profile"}' in argv and '--remote-debugging-port=0' in argv
	assert '--headless=new' in argv and argv[-1] == 'about:blank'
	if sys.platform == 'darwin':
		assert '--use-mock-keychain' in argv  # a fresh profile never reads the user's keychain
	lb.stop()
	assert not alive(pid) and not lb.tmp.exists()


@posix_only
def test_kept_user_data_dir_survives_stop_and_a_stale_port_file_is_ignored(fake_chrome, tmp_path):
	udd = tmp_path / 'kept'
	udd.mkdir()
	(udd / 'DevToolsActivePort').write_text('1111\n/devtools/browser/stale\n')  # left by an earlier run
	(udd / 'Cookies').write_text('logins')
	lb = _local.LocalBrowser()
	assert lb.start(executable_path=fake_chrome('slow'), headless=True, user_data_dir=udd).endswith('/fake')
	lb.stop()
	assert (udd / 'Cookies').read_text() == 'logins' and not lb.tmp.exists()


@posix_only
def test_browser_that_exits_at_start_raises_with_its_stderr(fake_chrome):
	lb = _local.LocalBrowser()
	with pytest.raises(RuntimeError, match=r'exited at start \(code 3\).*boom: bad flag'):
		lb.start(executable_path=fake_chrome('exit'), headless=True)
	lb.stop()
	assert not lb.tmp.exists()


@posix_only
def test_no_usable_sandbox_retries_once_without_it(fake_chrome, tmp_path):
	lb = _local.LocalBrowser()
	assert lb.start(executable_path=fake_chrome('sandbox'), headless=True).endswith('/fake')
	argv = (tmp_path / 'argv').read_text().splitlines()
	assert '--no-sandbox' in argv and argv[-1] == 'about:blank'
	lb.stop()


@posix_only
def test_stop_during_launch_kills_the_browser_being_started(fake_chrome, tmp_path):
	lb = _local.LocalBrowser()
	errors = []

	def start():
		try:
			lb.start(executable_path=fake_chrome('hang'), headless=True)
		except RuntimeError as e:
			errors.append(str(e))

	t = threading.Thread(target=start)
	t.start()
	for _ in range(100):
		if (tmp_path / 'pid').exists():
			break
		time.sleep(0.05)
	pid = int((tmp_path / 'pid').read_text())
	lb.stop()
	t.join(5)
	assert errors == ['the browser was stopped while it started'] and not alive(pid) and not lb.tmp.exists()


@pytest.fixture
def no_daemon(monkeypatch):
	"""Daemon start/stop recorded instead of run: these tests are about the browser Browser launched."""
	from browser_harness import admin

	calls = []
	monkeypatch.setattr(admin, 'ensure_daemon', lambda *a, **k: calls.append(('start', k.get('name'), k.get('env'))))
	monkeypatch.setattr(browser_mod, '_shutdown_daemon', lambda name: calls.append(('stop', name)))
	yield calls
	browser_mod._LIVE.clear()


@posix_only
async def test_browser_chromium_runs_its_own_daemon_and_stop_ends_the_browser(fake_chrome, tmp_path, no_daemon):
	browser = Browser('chromium', executable_path=fake_chrome('ok'), headless=True)
	env = await browser.start()
	pid, tmp = int((tmp_path / 'pid').read_text()), browser._local.tmp
	# never the shared default daemon; BU_OWN_BROWSER: the agent's tab is the visible one (C09)
	assert env == {'BU_NAME': browser.name, 'BU_OWN_BROWSER': '1'} and env['BU_NAME'].startswith('bu')
	assert no_daemon == [
		('start', browser.name, {'BU_CDP_WS': 'ws://127.0.0.1:4321/devtools/browser/fake', 'BH_TAB_MARKER': '0'})
	]
	await browser.stop()
	assert no_daemon[-1] == ('stop', env['BU_NAME']) and not alive(pid) and not tmp.exists() and browser._local is None


@posix_only
async def test_a_local_browser_that_died_is_named_and_never_blamed_on_a_cloud_websocket(fake_chrome, tmp_path, monkeypatch):
	"""Night swarm 11-07 (C07): when our own Chrome died, browser-harness's error said 'remote browser WebSocket
	connection failed ... If you use Browser Use cloud ... start_remote_daemon()' for Browser('chromium')."""
	from browser_harness import admin

	def ensure_daemon(wait=None, name=None, env=None):  # Chrome dies before the daemon connects to it
		os.kill(int((tmp_path / 'pid').read_text()), 9)
		browser._local.proc.wait(5)
		raise RuntimeError('CDP WS handshake failed -- remote browser WebSocket connection failed. start_remote_daemon()')

	monkeypatch.setattr(admin, 'ensure_daemon', ensure_daemon)
	browser = Browser('chromium', executable_path=fake_chrome('ok'), headless=True)
	with pytest.raises(RuntimeError) as e:
		await browser.start()
	assert str(e.value) == 'the local browser exited (code -9): it crashed, was killed or closed'
	assert browser._local is None and not browser_mod._LIVE


@posix_only
async def test_cancelled_start_never_leaves_a_local_browser_running(fake_chrome, tmp_path, no_daemon):
	browser = Browser('chromium', executable_path=fake_chrome('hang'), headless=True)
	task = asyncio.create_task(browser.start())
	for _ in range(100):
		if (tmp_path / 'pid').exists():
			break
		await asyncio.sleep(0.05)
	task.cancel()
	with pytest.raises(asyncio.CancelledError):
		await task
	assert not alive(int((tmp_path / 'pid').read_text())) and browser._local is None and not browser_mod._LIVE


@posix_only
async def test_process_exit_cleanup_stops_local_browsers(fake_chrome, tmp_path, no_daemon):
	browser = Browser('chromium', executable_path=fake_chrome('ok'), headless=True, keep_alive=True)
	await browser.start()
	browser_mod._stop_all()  # what atexit and the SIGTERM handler run
	assert not alive(int((tmp_path / 'pid').read_text())) and not browser_mod._LIVE


def chrome_root(tmp_path: Path, profiles: dict[str, str]) -> Path:
	"""A Chrome user-data-dir with these profiles ({directory: display name})."""
	root = tmp_path / 'Chrome'
	for d in profiles:
		(root / d / 'Cache').mkdir(parents=True)
		(root / d / 'Cache' / 'blob').write_text('x' * 1000)
		(root / d / 'Cookies').write_text(f'cookies of {d}')
		(root / d / 'Local Storage' / 'leveldb').mkdir(parents=True)
		(root / d / 'Local Storage' / 'leveldb' / 'LOCK').write_text('')
		(root / d / 'Local Storage' / 'leveldb' / '000003.log').write_text('storage')
	(root / 'SingletonLock').write_text('host-1')
	info = {d: {'name': n} for d, n in profiles.items()}
	(root / 'Local State').write_text(json.dumps({'profile': {'info_cache': info}, 'os_crypt': {'encrypted_key': 'k'}}))
	return root


def test_profile_is_found_by_display_name_or_directory(tmp_path):
	root = chrome_root(tmp_path, {'Default': 'Personal', 'Profile 1': 'Work', 'Profile 2': 'work stuff'})
	assert _local.resolve_profile(root, 'Work') == 'Profile 1'  # exact display name beats the case-folded one
	assert _local.resolve_profile(root, 'Profile 2') == _local.resolve_profile(root, 'WORK STUFF') == 'Profile 2'
	assert _local.resolve_profile(root, 'Default') == 'Default'
	with pytest.raises(ValueError, match=r"No Chrome profiles match 'Gaming'.*'Personal' \(Default\), 'Work' \(Profile 1\)"):
		_local.resolve_profile(root, 'Gaming')
	with pytest.raises(ValueError, match='No Chrome profiles found'):
		_local.resolve_profile(tmp_path / 'nothing', 'Work')


def test_ambiguous_profile_name_raises(tmp_path):
	root = chrome_root(tmp_path, {'Profile 1': 'Work', 'Profile 2': 'Work'})
	with pytest.raises(ValueError, match="Several Chrome profiles match 'Work'"):
		_local.resolve_profile(root, 'Work')


def test_profile_copy_keeps_logins_and_skips_caches_and_locks(tmp_path):
	root = chrome_root(tmp_path, {'Default': 'Personal', 'Profile 1': 'Work'})
	dest = tmp_path / 'copy'
	_local.copy_profile(root, 'Profile 1', dest)
	assert (dest / 'Profile 1' / 'Cookies').read_text() == 'cookies of Profile 1'
	assert (dest / 'Profile 1' / 'Local Storage' / 'leveldb' / '000003.log').exists()
	assert json.loads((dest / 'Local State').read_text())['os_crypt'] == {'encrypted_key': 'k'}  # the cookie key
	assert not (dest / 'Profile 1' / 'Cache').exists() and not (dest / 'Default').exists()
	assert not (dest / 'SingletonLock').exists() and not (dest / 'Profile 1' / 'Local Storage' / 'leveldb' / 'LOCK').exists()
	assert (root / 'Profile 1' / 'Cache' / 'blob').exists()  # the source is never changed


def test_profile_copy_launches_in_chrome_with_the_real_keychain(tmp_path):
	args = _local.chrome_args(tmp_path, headless=False, fresh=False, profile_directory='Profile 1')
	assert '--profile-directory=Profile 1' in args and '--use-mock-keychain' not in args
	assert '--password-store=basic' not in args and '--headless=new' not in args


def test_profile_copy_runs_with_sync_off():
	"""The copy is signed in to the user's Google account: with sync on, the agent's history, tabs and saved passwords
	would reach the account and the real profile."""
	assert '--disable-sync' in _local.chrome_args(Path('x'), headless=True, fresh=False, profile_directory='Default')
	assert '--disable-sync' not in _local.chrome_args(Path('x'), headless=True, fresh=True)
	assert '--allow-pre-commit-input' in _local.chrome_args(Path('x'), headless=False, fresh=True)  # C09, as in 0.x


def test_locked_cookies_fail_the_profile_copy_and_other_locked_files_warn(tmp_path, monkeypatch):
	"""Windows locks Cookies while Chrome runs: a copy without them has none of the logins it is for."""
	import shutil

	root = chrome_root(tmp_path, {'Default': 'Personal'})

	def locked(*names):
		def copytree(src, dst, **kwargs):
			errors = [(str(Path(src) / n), str(Path(dst) / n), 'locked') for n in names]
			raise shutil.Error(errors)

		return copytree

	monkeypatch.setattr(shutil, 'copytree', locked('Network/Cookies', 'Login Data'))
	with pytest.raises(RuntimeError, match="cookies of Chrome profile 'Default'.*Quit Chrome"):
		_local.copy_profile(root, 'Default', tmp_path / 'copy1')
	monkeypatch.setattr(shutil, 'copytree', locked('Login Data', 'History'))
	warned: list[str] = []
	monkeypatch.setattr(_local.logger, 'warning', lambda msg, *args: warned.append(msg % args))
	_local.copy_profile(root, 'Default', tmp_path / 'copy2')
	assert warned == ["Copied Chrome profile 'Default' without files Chrome holds open: History, Login Data"]


def test_stop_during_the_profile_copy_leaves_no_copy_on_disk(tmp_path, monkeypatch):
	"""Ctrl-C while a large profile copies: stop() deletes the temp dir, the copy still running would recreate it."""
	root = chrome_root(tmp_path, {'Default': 'Personal'})
	monkeypatch.setattr(_local, 'chrome_user_data_dir', lambda: root)
	monkeypatch.setattr(_local, 'find_binary', lambda *a, **k: 'chrome')
	real_copy, copying = _local.copy_profile, threading.Event()

	def slow_copy(*args):
		copying.set()
		time.sleep(0.5)
		real_copy(*args)

	monkeypatch.setattr(_local, 'copy_profile', slow_copy)
	lb = _local.LocalBrowser()
	errors = []

	def start():
		try:
			lb.start(headless=True, profile='Personal')
		except RuntimeError as e:
			errors.append(str(e))

	t = threading.Thread(target=start)
	t.start()
	assert copying.wait(5)
	lb.stop()
	t.join(5)
	assert errors == ['the browser was stopped while it started'] and not lb.tmp.exists()


def test_dirs_left_by_dead_processes_are_swept_and_live_ones_kept(tmp_path):
	"""A SIGKILL, OOM or crash skips stop(): the next LocalBrowser deletes that profile copy (cookies, passwords)."""
	import subprocess

	code = 'import sys, time\nfrom browser_use.browser.local import LocalBrowser\nlb = LocalBrowser()\nprint(lb.tmp, flush=True)\ntime.sleep(60)'
	env = {**os.environ, 'TMPDIR': str(tmp_path), 'TEMP': str(tmp_path), 'TMP': str(tmp_path)}
	proc = subprocess.Popen([sys.executable, '-c', code], stdout=subprocess.PIPE, text=True, env=env)
	try:
		dead = Path(proc.stdout.readline().strip())  # type: ignore[union-attr]
		assert dead.parent == tmp_path and (dead / _local.OWNER).exists()
		old = time.time() - 3600
		os.utime(dead / _local.OWNER, (old, old))
		_local.sweep_stale_dirs(tmp_path)
		assert dead.exists()  # its process still runs
	finally:
		proc.kill()
		proc.wait(10)
	unowned, young = tmp_path / f'{_local.TMP_PREFIX}unowned', tmp_path / f'{_local.TMP_PREFIX}young'
	unowned.mkdir()
	young.mkdir()
	(young / _local.OWNER).write_bytes(b'')
	_local.sweep_stale_dirs(tmp_path)
	assert not dead.exists() and unowned.exists() and young.exists()


def test_snap_chromium_is_refused_with_the_fix(tmp_path, monkeypatch):
	"""Snap confinement hides our /tmp profile: the browser never reports a DevTools port (a 30 s timeout)."""
	wrapper = tmp_path / 'chromium-browser'  # Ubuntu's /usr/bin/chromium-browser
	wrapper.write_text('#!/bin/sh\nexec /snap/bin/chromium "$@"\n')
	native = tmp_path / 'google-chrome'
	native.write_text('#!/bin/sh\nexec /opt/google/chrome/chrome "$@"\n')
	monkeypatch.setattr(sys, 'platform', 'linux')
	monkeypatch.setenv('PATH', str(tmp_path / 'empty'))
	monkeypatch.setenv('BH_CHROME_PATH', str(wrapper))
	monkeypatch.setenv('PLAYWRIGHT_BROWSERS_PATH', str(tmp_path / 'no-playwright'))
	with pytest.raises(RuntimeError, match='Snap Chromium.*doctor --fix-snap'):
		_local.find_binary()
	with pytest.raises(RuntimeError, match='Snap Chromium'):
		_local.find_binary(str(wrapper))
	assert _local.find_binary(str(native)) == str(native)


def test_executable_path_that_is_not_a_file_raises(tmp_path):
	with pytest.raises(FileNotFoundError, match='executable_path'):
		_local.find_binary(str(tmp_path / 'no-chrome'))


def test_a_bh_chrome_path_that_is_not_a_file_warns(tmp_path, monkeypatch, caplog):
	"""Low: BH_CHROME_PATH=/nonexistent silently fell back to the installed Chrome."""
	import logging

	monkeypatch.setenv('BH_CHROME_PATH', str(tmp_path / 'nope'))
	monkeypatch.setattr(logging.getLogger('browser_use'), 'propagate', True)
	try:
		_local.find_binary()
	except RuntimeError:
		pass  # no browser installed here: the warning still came first
	assert 'is not a file' in caplog.text and 'nope' in caplog.text


def test_bh_chrome_path_is_honored(tmp_path, monkeypatch):
	binary = tmp_path / 'my-chrome'
	binary.write_text('')
	monkeypatch.setenv('BH_CHROME_PATH', str(binary))
	assert _local.find_binary() == str(binary)


def test_playwright_chromium_from_browser_use_install_is_found_last(tmp_path, monkeypatch):
	"""`browser-use install` puts Chromium in Playwright's cache; find_binary uses it when no Chrome is installed."""
	monkeypatch.setattr(sys, 'platform', 'linux')
	monkeypatch.setenv('PATH', str(tmp_path / 'empty'))
	monkeypatch.delenv('BH_CHROME_PATH', raising=False)
	monkeypatch.delenv('CHROME_PATH', raising=False)
	monkeypatch.setenv('PLAYWRIGHT_BROWSERS_PATH', str(tmp_path / 'pw'))
	for build in ('chromium-1200', 'chromium-1248'):
		(tmp_path / 'pw' / build / 'chrome-linux64').mkdir(parents=True)
		(tmp_path / 'pw' / build / 'chrome-linux64' / 'chrome').write_text('')
	assert _local.find_binary() == str(tmp_path / 'pw/chromium-1248/chrome-linux64/chrome')
	with pytest.raises(RuntimeError, match='No Google Chrome found'):
		_local.find_binary(chrome_only=True)  # a copied Chrome profile needs real Chrome


@pytest.fixture
def debug_dirs(tmp_path, monkeypatch):
	"""Three browsers' default dirs (Chrome first, as in browser-harness); live(name) turns remote debugging on."""
	from browser_harness import admin, daemon

	dirs = {n: tmp_path / n for n in ('chrome', 'canary', 'edge')}
	for d in dirs.values():
		d.mkdir()
	monkeypatch.setattr(daemon, 'PROFILES', list(dirs.values()))
	monkeypatch.setattr(_local, 'chrome_user_data_dir', lambda: dirs['chrome'])
	monkeypatch.setattr(admin, 'daemon_alive', lambda name=None: False)
	monkeypatch.delenv('BU_CDP_WS', raising=False)
	monkeypatch.delenv('BU_CDP_URL', raising=False)
	servers = []

	def live(name):
		s = socket.socket()
		s.bind(('127.0.0.1', 0))
		s.listen()
		servers.append(s)
		(dirs[name] / 'DevToolsActivePort').write_text(f'{s.getsockname()[1]}\n/devtools/browser/{name}\n')

	yield live
	for s in servers:
		s.close()


@pytest.mark.parametrize('on', [['chrome', 'canary', 'edge'], ['chrome'], ['edge'], []])
def test_attach_picks_chrome_or_the_only_browser_with_remote_debugging(debug_dirs, on):
	for name in on:
		debug_dirs(name)
	browser_mod._check_one_chrome()  # browser-harness then attaches to the first live one


def test_attach_raises_when_several_browsers_but_not_chrome_have_remote_debugging(debug_dirs):
	debug_dirs('canary')
	debug_dirs('edge')
	with pytest.raises(RuntimeError, match='several browsers have remote debugging on.*none of them is Google Chrome'):
		browser_mod._check_one_chrome()


def test_attach_never_scans_when_the_shared_daemon_is_up_or_a_cdp_endpoint_is_set(debug_dirs, monkeypatch):
	from browser_harness import admin

	debug_dirs('canary')
	debug_dirs('edge')
	monkeypatch.setattr(admin, 'daemon_alive', lambda name=None: True)
	browser_mod._check_one_chrome()  # the running daemon is the answer
	monkeypatch.setattr(admin, 'daemon_alive', lambda name=None: False)
	monkeypatch.setenv('BU_CDP_WS', 'ws://127.0.0.1:1/devtools/browser/x')
	browser_mod._check_one_chrome()  # the daemon will not discover anything


async def test_attach_failure_names_the_fix(monkeypatch):
	from browser_harness import admin

	def ensure_daemon(wait=None, name=None, env=None):
		raise RuntimeError('remote-debugging-setup: opened chrome://inspect/#remote-debugging in Chrome')

	monkeypatch.setattr(admin, 'ensure_daemon', ensure_daemon)
	monkeypatch.setattr(admin, 'daemon_alive', lambda name=None: True)
	with pytest.raises(RuntimeError, match=r"(?s)Browser\('chrome'\) could not attach.*chrome://inspect.*Browser\('chromium'\)"):
		await Browser('chrome').start()


# End to end with the real Chrome


async def test_fresh_chromium_end_to_end_has_no_cookies_and_leaves_nothing(chrome_binary, tmp_path):
	model, _ = script(
		(
			'python',
			{
				'code': "new_tab('data:text/html,<title>Fresh</title>'); wait_for_load(); "
				"t = page_info()['title']; n = len(cdp('Storage.getCookies')['cookies'])"
			},
		),
		('finish_from_repl', {'success': True, 'expression': "f'{t}|{n}'"}),
	)
	browser = Browser('chromium', headless=True, executable_path=chrome_binary, keep_alive=True)
	result = await Agent('Read the title', model, browser=browser, workspace=tmp_path).run()
	assert (result.status, result.final_result()) == ('completed', 'Fresh|0'), result.error
	assert browser._local is not None
	proc, tmp = browser._local.proc, browser._local.tmp
	assert proc is not None and proc.poll() is None and tmp.exists()
	await browser.stop()
	assert proc.poll() is not None and not tmp.exists() and not browser_mod._LIVE


async def test_a_launched_browser_downloads_into_the_workspace(chrome_binary, tmp_path):
	"""M14: Browser('chromium') saved downloads to the user's real ~/Downloads."""
	link = 'data:text/html,<a id=a href="data:text/plain,hello" download="report.txt">x</a>'
	model, _ = script(
		(
			'python',
			{
				'code': f"new_tab('{link}'); wait_for_load(); js('document.getElementById(\"a\").click()'); import time; time.sleep(2)"
			},
		),
		('finish', {'success': True, 'result': 'ok'}),
	)
	browser = Browser('chromium', headless=True, executable_path=chrome_binary)
	result = await Agent('t', model, browser=browser, workspace=tmp_path).run()
	assert result.final_result() == 'ok', result.error
	assert (tmp_path / 'downloads' / 'report.txt').read_text() == 'hello'


async def test_two_fresh_browsers_run_side_by_side(chrome_binary):
	from browser_harness import _ipc as ipc

	browsers = [Browser('chromium', headless=True, executable_path=chrome_binary) for _ in range(2)]
	envs = await asyncio.gather(*(b.start() for b in browsers))
	try:
		assert envs[0]['BU_NAME'] != envs[1]['BU_NAME']
		ids = []
		for env in envs:
			c, token = ipc.connect(env['BU_NAME'], timeout=5)
			try:
				ids.append(ipc.request(c, token, {'method': 'Target.getTargets', 'params': {}})['result'])
			finally:
				c.close()
		assert all(r['targetInfos'] for r in ids)
		assert browsers[0]._local.proc.pid != browsers[1]._local.proc.pid  # type: ignore[union-attr]
	finally:
		await asyncio.gather(*(b.stop() for b in browsers))


async def test_chrome_profile_copy_carries_its_logins(chrome_binary, tmp_path, monkeypatch):
	"""Browser('chrome', profile=...) launches on a copy: Chrome 136+ refuses remote debugging on the real dir."""
	from browser_harness import _ipc as ipc
	from websockets.sync.client import connect

	src = tmp_path / 'Chrome'
	src.mkdir()
	owner = _local.LocalBrowser()  # stands in for the user's Chrome: logs in to example.test in 'Profile 1'
	owner.user_data_dir = src
	ws = owner._launch(chrome_binary, _local.chrome_args(src, headless=True, fresh=False, profile_directory='Profile 1'))
	cookie = {'name': 'session', 'value': 'logged-in', 'domain': 'example.test', 'path': '/', 'expires': time.time() + 3600}
	with connect(ws, max_size=None) as conn:
		conn.send(json.dumps({'id': 1, 'method': 'Storage.setCookies', 'params': {'cookies': [cookie]}}))
		assert json.loads(conn.recv())['id'] == 1
		conn.send(json.dumps({'id': 2, 'method': 'Browser.close'}))  # flushes cookies and Local State to disk
	assert owner.proc is not None
	owner.proc.wait(20)
	owner.stop()
	assert (src / 'Profile 1' / 'Cookies').exists()

	monkeypatch.setattr(_local, 'chrome_user_data_dir', lambda: src)
	browser = Browser('chrome', profile='Profile 1', headless=True, executable_path=chrome_binary)
	env = await browser.start()
	try:
		assert browser._local is not None and browser._local.user_data_dir == browser._local.tmp / 'profile'
		c, token = ipc.connect(env['BU_NAME'], timeout=5)
		try:
			cookies = ipc.request(c, token, {'method': 'Storage.getCookies', 'params': {}})['result']['cookies']
		finally:
			c.close()
		assert [(k['name'], k['value']) for k in cookies] == [('session', 'logged-in')]
		copy = browser._local.tmp
	finally:
		await browser.stop()
	assert not copy.exists() and (src / 'Profile 1' / 'Cookies').exists()


async def test_a_kept_user_data_dir_keeps_its_cookies_across_a_normal_stop(chrome_binary, tmp_path):
	"""H8: stop() sent SIGTERM to Chrome's whole process group, so the network service died before it wrote the
	cookies: a user_data_dir profile lost them on every normal stop (3/3). Chrome is now closed over CDP first."""
	cookie = {'name': 'c', 'value': 'kept', 'domain': 'example.test', 'path': '/', 'expires': time.time() + 86_400}
	udd = tmp_path / 'profile'
	browser = Browser('chromium', headless=True, executable_path=chrome_binary, user_data_dir=udd)
	await browser.start()
	assert browser.name
	browser_mod._daemon_cdp(browser.name, 'Storage.setCookies', cookies=[cookie])
	await browser.stop()
	await browser.start()
	try:
		assert browser.name
		cookies = browser_mod._daemon_cdp(browser.name, 'Storage.getCookies')['cookies']
		assert [(c['name'], c['value']) for c in cookies if c['domain'] == 'example.test'] == [('c', 'kept')]
	finally:
		await browser.stop()


@posix_only
def test_sigkill_of_python_leaves_no_chrome_daemon_or_profile(chrome_binary, tmp_path):
	"""M16: SIGKILL of the Python process orphaned the launched Chrome, its daemon and the temp profile."""
	import signal
	import subprocess

	code = f"""
import asyncio, json, sys
from browser_harness import _ipc as ipc
from browser_use import Browser
async def main():
    b = Browser('chromium', headless=True, executable_path={chrome_binary!r})
    await b.start()
    print(json.dumps({{'chrome': b._local.proc.pid, 'daemon': ipc.identify(b.name), 'tmp': str(b._local.tmp)}}), flush=True)
    await asyncio.sleep(600)
asyncio.run(main())
"""
	proc = subprocess.Popen([sys.executable, '-c', code], stdout=subprocess.PIPE, cwd=tmp_path)
	assert proc.stdout
	info = json.loads(proc.stdout.readline())
	assert alive(info['chrome']) and info['daemon'] and alive(info['daemon']) and Path(info['tmp']).exists()
	proc.send_signal(signal.SIGKILL)
	proc.wait(10)
	deadline = time.monotonic() + 15
	while time.monotonic() < deadline and (alive(info['chrome']) or alive(info['daemon']) or Path(info['tmp']).exists()):
		time.sleep(0.2)
	assert not alive(info['chrome']) and not alive(info['daemon']) and not Path(info['tmp']).exists()


@posix_only
def test_the_watchdog_ends_a_reattached_daemon_and_never_a_process_that_reused_the_old_pid(chrome_binary, tmp_path, monkeypatch):
	"""Review: the watchdog kept the daemon pid it started with. After a reattach replaced the daemon, a SIGKILL of
	Python left the new daemon running, and the old pid (possibly reused by another process) was signalled."""
	import signal
	import subprocess

	from browser_use.browser.local import start_watchdog

	code = f"""
import asyncio, json, os, signal, time
from browser_harness import _ipc as ipc
from browser_use import Browser
async def main():
    b = Browser('chromium', headless=True, executable_path={chrome_binary!r})
    await b.start()
    old = ipc.identify(b.name)
    os.kill(old, signal.SIGKILL)
    while ipc.identify(b.name, 0.2):
        time.sleep(0.1)
    await b.reattach()
    print(json.dumps({{'chrome': b._local.proc.pid, 'daemon': ipc.identify(b.name), 'old': old}}), flush=True)
    await asyncio.sleep(600)
asyncio.run(main())
"""
	proc = subprocess.Popen([sys.executable, '-c', code], stdout=subprocess.PIPE, cwd=tmp_path)
	assert proc.stdout
	info = json.loads(proc.stdout.readline())
	assert info['daemon'] and info['daemon'] != info['old'] and alive(info['daemon']), info
	proc.send_signal(signal.SIGKILL)
	proc.wait(10)
	deadline = time.monotonic() + 15
	while time.monotonic() < deadline and (alive(info['chrome']) or alive(info['daemon'])):
		time.sleep(0.2)
	assert not alive(info['chrome']) and not alive(info['daemon']), info

	# a pid the daemon once had, now another process (its start time differs from the daemon's): never signalled
	from browser_harness import admin

	chrome = subprocess.Popen(['sleep', '60'], start_new_session=True)
	other = subprocess.Popen(['sleep', '60'])
	monkeypatch.setattr(admin, '_process_start_time', lambda pid: 'when the daemon started')
	try:
		watchdog = start_watchdog(chrome.pid, tmp_path / 'gone', f'butestnodaemon{os.getpid()}', other.pid)
		assert watchdog and watchdog.stdin
		watchdog.stdin.close()  # what the death of the process that started it does
		watchdog.wait(20)
		assert chrome.wait(5) is not None
		time.sleep(0.2)
		assert other.poll() is None, 'the watchdog signalled a process that is not the daemon'
	finally:
		for p in (chrome, other):
			p.kill()
