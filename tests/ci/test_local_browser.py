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
	with pytest.raises(RuntimeError, match=r'exited at start \(code 3\).*boom: bad flag') as raised:
		lb.start(executable_path=fake_chrome('exit'), headless=True)
	assert 'another Chrome' not in str(raised.value)  # rc5 local-3: a fresh temp profile is never locked by another Chrome
	lb.stop()
	assert not lb.tmp.exists()


@posix_only
def test_a_kept_user_data_dir_that_exits_at_start_names_the_profile_lock(fake_chrome, tmp_path):
	lb = _local.LocalBrowser()
	with pytest.raises(RuntimeError, match=r'exited at start \(code 3\); is another Chrome using .*kept\?.*boom'):
		lb.start(executable_path=fake_chrome('exit'), headless=True, user_data_dir=tmp_path / 'kept')
	lb.stop()


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


def test_start_returns_after_the_launch_tab_is_gone(monkeypatch):
	"""Linux Chrome lists a tab for a moment after Target.closeTarget answered: start() returned with the launch tab
	still in Target.getTargets, so list_tabs() right after start() gave 2 (CI, about 1 launch in 8)."""
	tabs = {'own': True, 'launch': True}
	gone_after = {}  # targetId -> getTargets calls it is still listed for after closeTarget

	def cdp(name, method, **params):
		if method == 'Target.getTargets':
			for t, n in list(gone_after.items()):
				gone_after[t] = n - 1
				if n == 0:
					del tabs[t], gone_after[t]
			return {'targetInfos': [{'type': 'page', 'targetId': t, 'url': 'about:blank'} for t in tabs]}
		if method == 'Target.closeTarget':
			gone_after[params['targetId']] = 3
			return {'success': True}
		return {}

	monkeypatch.setattr(browser_mod, '_daemon_cdp', cdp)
	monkeypatch.setattr(browser_mod, '_daemon_request', lambda name, req: {'targetId': 'own'})
	Browser('chromium')._close_launch_tab()
	assert [t['targetId'] for t in cdp('launchtab', 'Target.getTargets')['targetInfos']] == ['own']


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
	with pytest.raises(RuntimeError, match='No Google Chrome found') as raised:
		_local.find_binary(chrome_only=True)  # a copied Chrome profile needs real Chrome
	assert 'browser-use install' not in str(raised.value)  # Playwright's Chromium cannot open a copied Chrome profile
	monkeypatch.setenv('PLAYWRIGHT_BROWSERS_PATH', str(tmp_path / 'none'))
	with pytest.raises(RuntimeError, match=r'No Chrome, Chromium or Edge found .*run `browser-use install`'):
		_local.find_binary()  # rc5 local-2: the library error names the documented fix, not only `browser-use doctor`


def test_a_file_named_like_a_browser_in_the_working_directory_is_never_launched(tmp_path, monkeypatch):
	"""cubic: the Linux names not on PATH stayed in the list as bare names, which is_file() read in the working directory:
	a file named ./chromium there was launched as the browser."""
	monkeypatch.setattr(sys, 'platform', 'linux')
	monkeypatch.setenv('PATH', str(tmp_path / 'empty'))
	monkeypatch.delenv('BH_CHROME_PATH', raising=False)
	monkeypatch.delenv('CHROME_PATH', raising=False)
	monkeypatch.setenv('PLAYWRIGHT_BROWSERS_PATH', str(tmp_path / 'pw'))
	(tmp_path / 'chromium').write_text('')
	monkeypatch.chdir(tmp_path)
	with pytest.raises(RuntimeError, match='No Chrome, Chromium or Edge found .*chromium on PATH'):
		_local.find_binary()


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
		lock = dirs[name] / 'SingletonLock'  # the running browser (this process) took the dir before writing the port
		if sys.platform != 'win32' and not lock.is_symlink():
			lock.symlink_to(f'{socket.gethostname()}-{os.getpid()}')
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


async def test_attach_failure_names_the_fix(debug_dirs, monkeypatch):
	from browser_harness import admin

	def ensure_daemon(wait=None, name=None, env=None):
		raise RuntimeError('remote-debugging-setup: opened chrome://inspect/#remote-debugging in Chrome')

	debug_dirs('chrome')
	monkeypatch.setattr(admin, 'ensure_daemon', ensure_daemon)
	monkeypatch.setattr(admin, 'daemon_alive', lambda name=None: True)
	with pytest.raises(RuntimeError, match=r"(?s)Browser\('chrome'\) could not attach.*chrome://inspect.*Browser\('chromium'\)"):
		await Browser('chrome').start()


@pytest.fixture
def attaches(debug_dirs, monkeypatch):
	"""Chrome is open with remote debugging off. Yields the daemons browser-harness was asked to start (it would
	discover the browser itself) and whether chrome://inspect was opened."""
	from browser_harness import admin, daemon

	calls: list[str | None] = []
	opened: list[bool] = []
	monkeypatch.setattr(admin, 'ensure_daemon', lambda wait=None, name=None, env=None: calls.append(name))
	monkeypatch.setattr(daemon, 'supported_browser_running', lambda: True)
	monkeypatch.setattr(admin, '_open_chrome_inspect_once', lambda: opened.append(True))
	monkeypatch.setattr(admin, '_launch_browser', lambda: pytest.fail('launched a browser'))
	monkeypatch.setattr(_local, 'has_display', lambda: True)  # a desktop: chrome://inspect can be ticked
	yield calls, opened


async def test_attach_never_lets_browser_harness_guess_port_9222(attaches):
	"""Fable EXEC-2: with no DevToolsActivePort live (Chrome open, chrome://inspect not ticked yet), Browser('chrome'),
	the CLI and --cli-mcp still started browser-harness's discovery, which then attached to whatever answered on
	127.0.0.1:9222 / 9223: another user's Chrome, or a fake one serving its own ws URL. The agent ran there."""
	from browser_use import harness_cloud

	calls, opened = attaches
	with pytest.raises(RuntimeError, match=r"(?s)Browser\('chrome'\) could not attach.*chrome://inspect.*never guessed"):
		await Browser('chrome').start()
	with pytest.raises(RuntimeError, match=r'(?s)remote-debugging-setup.*chrome://inspect.*BU_CDP_URL'):
		harness_cloud.ensure_daemon(name=f'butestattach{os.getpid()}')  # the CLI's and --cli-mcp's attach
	assert calls == [] and opened == [True, True]


async def test_attach_on_a_box_with_no_display_names_what_works_there(attaches, monkeypatch):
	"""e2e 1.0.1: `echo 'print(1)' | browser-use` on a fresh python:3.12-slim (no display, no Chrome) said to tick a
	box in chrome://inspect, which nobody can open there."""
	from browser_use import harness_cloud

	calls, opened = attaches
	monkeypatch.setattr(_local, 'has_display', lambda: False)
	with pytest.raises(RuntimeError, match=r'remote-debugging-setup: .*no display.*BU_CDP_URL.*start_remote_daemon\(\)') as e:
		harness_cloud.ensure_daemon(name=f'butestheadless{os.getpid()}')  # the CLI's attach
	assert 'chrome://inspect' not in str(e.value) and calls == [] and opened == []


@posix_only
@pytest.mark.parametrize('state', ['restarted', 'closed'])
async def test_attach_refuses_a_left_over_debug_port_another_process_now_holds(attaches, debug_dirs, state):
	"""Chrome leaves DevToolsActivePort behind when it quits. Whoever then listens on that port got the attach
	(browser-harness reads the file first), or, answering as no browser, sent browser-harness on to 9222 / 9223."""
	from browser_harness import daemon

	from browser_use import harness_cloud

	calls, opened = attaches
	debug_dirs('chrome')
	port_file, lock = daemon.PROFILES[0] / 'DevToolsActivePort', daemon.PROFILES[0] / 'SingletonLock'
	if state == 'restarted':
		os.utime(port_file, (time.time() - 3600, time.time() - 3600))  # written by the Chrome before this one
	else:
		lock.unlink()
	debug_dirs('edge')  # another browser that does have remote debugging on: browser-harness still reads Chrome's first
	with pytest.raises(RuntimeError, match=r'(?s)could not attach.*left from an earlier browser session'):
		await Browser('chrome').start()
	with pytest.raises(RuntimeError, match=r'remote-debugging-setup: .*DevToolsActivePort is left'):
		harness_cloud.ensure_daemon(name=f'butestleftover{os.getpid()}')
	assert calls == [] and opened == []


async def test_attach_starts_the_daemon_once_your_chrome_has_remote_debugging_on(attaches, debug_dirs, monkeypatch):
	from browser_harness import admin, daemon

	from browser_use import harness_cloud

	calls, opened = attaches
	debug_dirs('edge')
	await Browser('chrome').start()
	harness_cloud.ensure_daemon(name='butestattached')
	assert calls == [None, 'butestattached'] and opened == []
	# Chrome closed: launched as browser-harness does, and attached once it writes DevToolsActivePort
	(daemon.PROFILES[2] / 'DevToolsActivePort').unlink()
	monkeypatch.setattr(daemon, 'supported_browser_running', lambda: False)
	monkeypatch.setattr(admin, '_launch_browser', lambda: debug_dirs('chrome') or (None, None))
	await Browser('chrome').start()
	assert calls == [None, 'butestattached', None] and opened == []


async def test_attach_reuses_a_daemon_that_already_reaches_its_browser(attaches, monkeypatch):
	"""rc5 merge: `BU_NAME=<a daemon BU_CDP_WS started> browser-use` (CI's chrome fixture, an orchestrator's daemon)
	failed with remote-debugging-setup, though that daemon discovers nothing. Browser('chrome') reuses the running
	default daemon too (_check_one_chrome), so it skips the gate the same way."""
	from browser_harness import admin

	from browser_use import harness_cloud

	calls, opened = attaches
	monkeypatch.setattr(admin, 'require_existing_daemon', lambda name=None: None)  # healthy, attached by BU_CDP_WS
	harness_cloud.ensure_daemon(name='butestcdp')
	await Browser('chrome').start()
	assert calls == ['butestcdp', None] and opened == []


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


async def test_a_launched_browsers_pages_run_at_full_speed_out_of_sight(chrome_binary, tmp_path):
	"""1.0 dropped 0.x's (and Playwright's) --disable-background-timer-throttling, --disable-renderer-backgrounding and
	--disable-backgrounding-occluded-windows. A page the agent is not looking at ran its timers ~15x slower: a tab in the
	background, and on a headed Chrome (the macOS default) every tab once the window was covered or the screen locked
	(live: 3 of 60 setInterval ticks, 1 of ~130 animation frames, document hidden)."""
	model, _ = script(
		(
			'python',
			{
				'code': "a = new_tab('data:text/html,<p>a'); wait_for_load(); js('(window.t = 0, setInterval(() => window.t++, 50), 1)'); "
				"new_tab('data:text/html,<p>b'); wait_for_load(); wait(3); switch_tab(a); ticks = js('window.t')"
			},
		),
		('finish_from_repl', {'success': True, 'expression': 'ticks'}),
	)
	browser = Browser('chromium', headless=True, executable_path=chrome_binary)
	result = await Agent('Count', model, browser=browser, workspace=tmp_path).run()
	assert result.status == 'completed', result.error
	assert int(result.final_result() or 0) > 30, result.final_result()  # 60 at full speed; throttled: 1 per second


async def test_a_launched_browser_has_one_tab(chrome_binary):
	"""C63: Chrome's launch tab stayed next to the tab our named daemon opens: list_tabs() gave 2, headed showed a blank
	extra tab."""
	browser = Browser('chromium', headless=True, executable_path=chrome_binary)
	try:
		await browser.start()
		pages = [t for t in browser._cdp()('Target.getTargets')['targetInfos'] if t['type'] == 'page']
		assert len(pages) == 1, pages
	finally:
		await browser.stop()


async def test_a_launched_browser_downloads_into_the_workspace(chrome_binary, tmp_path):
	"""M14: Browser('chromium') saved downloads to the user's real ~/Downloads. C13: the model was never told a download
	started (it missed it in drain_events() output and clicked again), and the result listed no downloaded files."""
	link = 'data:text/html,<a id=a href="data:text/plain,hello" download="report.txt">x</a>'
	model, seen = script(
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
	assert result.downloads == [tmp_path / 'downloads' / 'report.txt']
	assert '[download started: report.txt]' in str(seen[1][-1])


async def test_downloads_lists_the_files_a_launched_browser_finished(chrome_binary, tmp_path):
	"""Docs runs: the model clicked a download, drained events before the download's arrived and clicked again
	('sample (1).txt'). downloads() lists what the browser finished."""
	import http.server

	class Files(http.server.BaseHTTPRequestHandler):
		def do_GET(self):
			if self.path == '/f':
				body, headers = b'hello', {'Content-Disposition': 'attachment; filename="report.txt"'}
			else:
				body, headers = b'<a id=a href="/f">report</a>', {'Content-Type': 'text/html'}
			self.send_response(200)
			for k, v in {**headers, 'Content-Length': str(len(body))}.items():
				self.send_header(k, v)
			self.end_headers()
			self.wfile.write(body)

		def log_message(self, *args):
			pass

	server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Files)
	threading.Thread(target=server.serve_forever, daemon=True).start()
	page = f'http://127.0.0.1:{server.server_address[1]}/'
	code = (
		f"new_tab('{page}'); wait_for_load(); print('before', downloads())\n"
		"js('document.getElementById(\"a\").click()'); import time; time.sleep(2); print('after', downloads())"
	)
	model, seen = script(('python', {'code': code}), ('finish', {'success': True, 'result': 'ok'}))
	browser = Browser('chromium', headless=True, executable_path=chrome_binary)
	try:
		result = await Agent('t', model, browser=browser, workspace=tmp_path).run()
	finally:
		server.shutdown()
	assert result.final_result() == 'ok', result.error
	output = str(seen[1][-1])
	assert 'before []' in output and "after [{'name': 'report.txt', 'size': 5}]" in output, output


@pytest.mark.parametrize('mode', ['default', 'ultrafast'])
async def test_two_downloads_with_one_name_both_survive(chrome_binary, tmp_path, mode):
	"""Customer task (retest 3, bu-fast, Browser('chromium')): 'download the January and the February invoice'. Both
	were served as invoice.txt and Chrome wrote the second over the first: January was lost, downloads() listed one
	file. Now the later one is 'invoice (1).txt', as cloud copies are named, and is there by that name within the cell
	that downloaded it."""
	import http.server

	class Invoices(http.server.BaseHTTPRequestHandler):
		def do_GET(self):
			if self.path.startswith('/invoice'):
				body = f'invoice for month {self.path[-1]}'.encode()
				headers = {'Content-Disposition': 'attachment; filename="invoice.txt"'}
			else:
				body, headers = b'<a href="/invoice?m=1">Jan</a><a href="/invoice?m=2">Feb</a>', {'Content-Type': 'text/html'}
			self.send_response(200)
			for k, v in {**headers, 'Content-Length': str(len(body))}.items():
				self.send_header(k, v)
			self.end_headers()
			self.wfile.write(body)

		def log_message(self, *args):
			pass

	server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Invoices)
	threading.Thread(target=server.serve_forever, daemon=True).start()
	page = f'http://127.0.0.1:{server.server_address[1]}/'
	code = (
		f"new_tab('{page}'); wait_for_load(); import os, time\n"
		'for i in range(2):\n'
		'    js(f"document.links[{i}].click()")\n'
		'    t = time.time()\n'
		'    while len(downloads()) <= i and time.time() - t < 10: time.sleep(0.1)\n'
		'time.sleep(0.5)\n'
		"print('files', {n: open(f'downloads/{n}').read() for n in sorted(os.listdir('downloads'))})"
	)
	model, seen = script(('python', {'code': code}), ('finish', {'success': True, 'result': 'ok'}))
	browser = Browser('chromium', headless=True, executable_path=chrome_binary)
	try:
		result = await Agent('t', model, browser=browser, workspace=tmp_path, mode=mode).run()
	finally:
		server.shutdown()
	assert result.final_result() == 'ok', result.error
	expected = {'invoice (1).txt': 'invoice for month 2', 'invoice.txt': 'invoice for month 1'}  # sorted(os.listdir())
	output = str(seen[1][-1].parts[0].content)
	assert f'files {expected}' in output, output
	assert {p.name: p.read_text() for p in result.downloads} == expected


async def test_a_download_that_finishes_after_the_run_is_named_at_the_stop(chrome_binary, tmp_path):
	"""The worker is closed when a download still running at the end of a run finishes: Browser.stop() waits for it
	and names it, so result.downloads lists slow.bin, not a guid."""
	import http.server

	class Slow(http.server.BaseHTTPRequestHandler):
		def do_GET(self):
			if self.path == '/f':
				self.send_response(200)
				self.send_header('Content-Disposition', 'attachment; filename="slow.bin"')
				self.send_header('Content-Length', '30000')
				self.end_headers()
				for _ in range(15):
					self.wfile.write(b'x' * 2000)
					self.wfile.flush()
					time.sleep(0.2)
			else:
				self.send_response(200)
				self.send_header('Content-Type', 'text/html')
				self.end_headers()
				self.wfile.write(b'<a id=a href="/f">slow</a>')

		def log_message(self, *args):
			pass

	server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Slow)
	threading.Thread(target=server.serve_forever, daemon=True).start()
	code = (
		f"new_tab('http://127.0.0.1:{server.server_address[1]}/'); wait_for_load(); js('document.getElementById(\"a\").click()')"
	)
	model, _ = script(('python', {'code': code}), ('finish', {'success': True, 'result': 'ok'}))
	browser = Browser('chromium', headless=True, executable_path=chrome_binary)
	try:
		result = await Agent('t', model, browser=browser, workspace=tmp_path).run()
	finally:
		server.shutdown()
	assert result.final_result() == 'ok', result.error
	assert [(p.name, p.stat().st_size) for p in result.downloads] == [('slow.bin', 30000)]


async def test_a_keep_alive_download_that_finishes_after_the_run_never_holds_the_stop(chrome_binary, tmp_path, monkeypatch):
	"""rc5 local-download-keepalive-1: with Browser(keep_alive=True) the run's REPL worker keeps running and drains the
	daemon's events, so it took the 'completed' event of a download still running as run() returned. browser.stop()
	waited DOWNLOADS_TIMEOUT_S (300 s) and warned the finished slow.bin was lost."""
	import http.server

	class Slow(http.server.BaseHTTPRequestHandler):
		def do_GET(self):
			if self.path == '/f':
				self.send_response(200)
				self.send_header('Content-Disposition', 'attachment; filename="slow.bin"')
				self.send_header('Content-Length', '30000')
				self.end_headers()
				for _ in range(15):
					self.wfile.write(b'x' * 2000)
					self.wfile.flush()
					time.sleep(0.2)
			else:
				self.send_response(200)
				self.send_header('Content-Type', 'text/html')
				self.end_headers()
				self.wfile.write(b'<a id=a href="/f">slow</a>')

		def log_message(self, *args):
			pass

	monkeypatch.setattr(browser_mod, 'DOWNLOADS_TIMEOUT_S', 30)  # a failure waits 30 s, not 300 s
	server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Slow)
	threading.Thread(target=server.serve_forever, daemon=True).start()
	code = (
		f"new_tab('http://127.0.0.1:{server.server_address[1]}/'); wait_for_load(); js('document.getElementById(\"a\").click()'); "
		"import glob, time; [time.sleep(0.1) for _ in range(50) if not glob.glob('downloads/*')]"  # begun, as by a next step
	)
	model, _ = script(('python', {'code': code}), ('finish', {'success': True, 'result': 'ok'}))
	browser = Browser('chromium', headless=True, executable_path=chrome_binary, keep_alive=True)
	agent = Agent('t', model, browser=browser, workspace=tmp_path)
	try:
		result = await agent.run()
		assert result.final_result() == 'ok', result.error
		assert not (tmp_path / 'downloads' / 'slow.bin').exists()  # still running: it finishes during the stop
		started = time.monotonic()
		await browser.stop()
		stop_s = time.monotonic() - started
	finally:
		server.shutdown()
		await agent.close()
		await browser.stop()
	assert stop_s < 10, stop_s
	assert [(p.name, p.stat().st_size) for p in (tmp_path / 'downloads').iterdir()] == [('slow.bin', 30000)]


def test_name_download_never_overwrites_and_keeps_the_file_in_its_dir(tmp_path):
	from browser_use.utils import name_download

	(tmp_path / 'a.txt').write_text('first')
	for guid, name, expected in [
		('g1', 'a.txt', 'a (1).txt'),
		('g2', '../../a.txt', 'a (2).txt'),
		('g3', '..', 'g3'),
		('g4', None, 'g4'),
	]:
		(tmp_path / guid).write_text(guid)
		assert name_download(tmp_path / guid, name) == tmp_path / expected
		assert (tmp_path / expected).read_text() == guid
	assert (tmp_path / 'a.txt').read_text() == 'first'
	assert name_download(tmp_path / 'gone', 'b.txt') is None and not (tmp_path / 'b.txt').exists()


def test_name_download_without_hard_links_never_lets_two_downloads_take_one_name(tmp_path, monkeypatch):
	"""Review: on a filesystem without hard links the fallback checked dest.exists() and then moved; a second download
	of the same name landing in between was replaced (Unix rename overwrites)."""
	import os

	from browser_use.utils import name_download

	def no_links(src, dst):
		raise OSError(1, 'Operation not permitted')

	moves, raced = {n: getattr(os, n) for n in ('rename', 'replace')}, []

	def move_after_a_racer(name):
		def move(src, dst):
			if not raced:  # the other download finishes between our free-name check and our move
				raced.append(None)
				raced[0] = name_download(tmp_path / 'g2', 'invoice.txt')
			return moves[name](src, dst)

		return move

	monkeypatch.setattr(os, 'link', no_links)
	for name in moves:
		monkeypatch.setattr(os, name, move_after_a_racer(name))
	(tmp_path / 'g1').write_text('first')
	(tmp_path / 'g2').write_text('second')
	mine = name_download(tmp_path / 'g1', 'invoice.txt')
	assert mine and raced[0] and mine != raced[0]
	assert sorted(p.read_text() for p in tmp_path.iterdir()) == ['first', 'second']


def test_the_prompt_says_where_downloads_land_and_never_to_move_them(tmp_path):
	"""C12: the prompt told the model to call Browser.setDownloadBehavior; it picked /tmp or cwd, and files missed
	workspace/downloads. Only a Chrome the Browser launched gets the downloads/ line: Browser('chrome') saves to yours."""
	from browser_use.agent.prompt import LOCAL_PROMPT

	def prompt(browser):
		agent = Agent('t', 'test', browser=browser, workspace=tmp_path)
		agent._build()
		return '\n'.join(i.instruction for i in agent._agent._instructions if isinstance(i.instruction, str))

	for browser, local in ((Browser('chromium'), True), (Browser('chrome', profile='Default'), True), (Browser('chrome'), False)):
		text = prompt(browser)
		assert 'never call Browser.setDownloadBehavior' in text and (LOCAL_PROMPT in text) == local


async def test_downloads_land_in_the_workspace_after_a_reattach(chrome_binary, tmp_path):
	"""C12: Chrome drops Browser.setDownloadBehavior when the connection that set it closes. It was sent once per run,
	so after a mid-run daemon reattach downloads went to the user's real ~/Downloads."""
	link = 'data:text/html,<a id=a href="data:text/plain,hello" download="after.txt">x</a>'
	browser = Browser('chromium', headless=True, executable_path=chrome_binary)
	browser._downloads_dir = tmp_path / 'downloads'  # what Agent.run sets
	await browser.start()
	try:
		assert browser.name
		browser_mod._kill_daemon(browser.name)
		await browser.reattach()
		target = browser_mod._daemon_cdp(browser.name, 'Target.createTarget', url=link)['targetId']
		session = browser_mod._daemon_cdp(browser.name, 'Target.attachToTarget', targetId=target, flatten=True)['sessionId']
		browser_mod._daemon_cdp(browser.name, 'Page.enable', session_id=session)  # as on the tab the daemon attaches
		await asyncio.sleep(1)
		browser_mod._daemon_cdp(
			browser.name, 'Runtime.evaluate', expression='document.getElementById("a").click()', session_id=session
		)
		await asyncio.sleep(2)
		# in the workspace; saved as its guid until an events reader names it (no Agent here: the stop below)
		assert [p.read_text() for p in (tmp_path / 'downloads').iterdir()] == ['hello']
	finally:
		await browser.stop()
	assert [p.name for p in (tmp_path / 'downloads').iterdir()] == ['after.txt']


async def test_a_download_in_the_agents_second_tab_reports_its_progress(chrome_binary, tmp_path):
	"""RC local-1: Browser.setDownloadBehavior went to the daemon's tab session, and Chrome then sends Browser.download*
	only for that tab's downloads. A download in the agent's second new_tab() never reported done, so stop() waited
	DOWNLOADS_TIMEOUT_S (300 s) and warned that the finished file was lost."""
	link = 'data:text/html,<a id=a href="data:text/plain,hello" download="second.txt">x</a>'
	browser = Browser('chromium', headless=True, executable_path=chrome_binary)
	browser._downloads_dir = tmp_path / 'downloads'  # what Agent.run sets
	await browser.start()
	try:
		assert browser.name
		target = browser_mod._daemon_cdp(browser.name, 'Target.createTarget', url=link)['targetId']
		session = browser_mod._daemon_cdp(browser.name, 'Target.attachToTarget', targetId=target, flatten=True)['sessionId']
		browser_mod._daemon_request(browser.name, {'meta': 'set_session', 'session_id': session, 'target_id': target})
		await asyncio.sleep(1)  # as new_tab() then wait_for_load()
		browser_mod._daemon_cdp(browser.name, 'Runtime.evaluate', expression='document.getElementById("a").click()')
		events, deadline = [], time.monotonic() + 10
		while time.monotonic() < deadline and not any(
			e['method'] == 'Browser.downloadProgress' and e['params'].get('state') == 'completed' for e in events
		):
			await asyncio.sleep(0.2)
			events += browser_mod._daemon_request(browser.name, {'meta': 'drain_events'})['events']
		assert 'Browser.downloadWillBegin' in {e['method'] for e in events}
		assert any(e['method'] == 'Browser.downloadProgress' and e['params'].get('state') == 'completed' for e in events)
	finally:
		await browser.stop()


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
	try:  # a failed step must not leave the stand-in Chrome running
		with connect(ws, max_size=None) as conn:
			conn.send(json.dumps({'id': 1, 'method': 'Storage.setCookies', 'params': {'cookies': [cookie]}}))
			assert json.loads(conn.recv())['id'] == 1
			conn.send(json.dumps({'id': 2, 'method': 'Browser.close'}))  # flushes cookies and Local State to disk
		assert owner.proc is not None
		owner.proc.wait(20)
	finally:
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
def test_sigkill_of_python_stops_the_cloud_browser_and_its_daemon(chrome, tmp_path):
	"""C58: SIGKILL (or OOM) of a cloud run left the cloud browser billing until its 60 min timeout and its daemon
	orphaned: the watchdog ran only next to a launched Chrome. A local Chrome stands in for the cloud browser, a local
	server for the cloud API."""
	import http.server
	import signal
	import subprocess

	stops = []

	class Api(http.server.BaseHTTPRequestHandler):
		def do_PATCH(self):
			stops.append((self.path, json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
			self.send_response(200)
			self.end_headers()
			self.wfile.write(b'{}')

		def log_message(self, *args):
			pass

	server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Api)
	threading.Thread(target=server.serve_forever, daemon=True).start()
	site = tmp_path / 'site'
	site.mkdir()  # every Python started below (the watchdog too) sends browser-harness's cloud calls to the server
	(site / 'sitecustomize.py').write_text(
		f"from browser_harness import admin\nadmin.BU_API = 'http://127.0.0.1:{server.server_port}'\n"
	)
	code = f"""
import asyncio, json
from browser_harness import _ipc as ipc
from browser_use import Browser
from browser_use.browser import browser as browser_mod
browser_mod._cloud = lambda path, method='GET', body=None: {{'id': 'c58-browser', 'cdpUrl': {chrome['http']!r}}}
async def main():
    b = Browser(use_cloud=True)
    await b.start()
    print(json.dumps({{'daemon': ipc.identify(b.name)}}), flush=True)
    await asyncio.sleep(600)
asyncio.run(main())
"""
	env = {**os.environ, 'PYTHONPATH': str(site), 'BROWSER_USE_API_KEY': 'bu_test'}
	proc = subprocess.Popen([sys.executable, '-c', code], stdout=subprocess.PIPE, cwd=tmp_path, env=env)
	daemon = 0
	try:
		assert proc.stdout
		daemon = json.loads(proc.stdout.readline())['daemon']
		assert daemon and alive(daemon)
		proc.send_signal(signal.SIGKILL)
		proc.wait(10)
		deadline = time.monotonic() + 15
		while time.monotonic() < deadline and (not stops or alive(daemon)):
			time.sleep(0.2)
		assert stops == [('/browsers/c58-browser', {'action': 'stop'})]
		assert not alive(daemon)
	finally:
		proc.kill()
		if daemon and alive(daemon):
			os.kill(daemon, signal.SIGKILL)
		server.shutdown()


@posix_only
def test_the_watchdog_never_signals_a_process_group_that_reused_the_chrome_pid(tmp_path, monkeypatch):
	"""The watchdog SIGTERMed, then SIGKILLed, the process group of the Chrome pid it started with, unchecked. A Chrome
	that already exited (crashed, quit by the user) before its Python died left that number free: the group that reused
	it (another Chrome, a shell's job) was killed. Only the process with the Chrome's start time is signalled."""
	import subprocess

	from browser_harness import admin

	from browser_use.browser.local import start_watchdog

	reused = subprocess.Popen(['sleep', '60'], start_new_session=True)  # a group leader now holding the Chrome's pid
	real = admin._process_start_time
	monkeypatch.setattr(admin, '_process_start_time', lambda pid: 'when Chrome started' if pid == reused.pid else real(pid))
	try:
		watchdog = start_watchdog(reused.pid, tmp_path / 'gone', f'butestnodaemon{os.getpid()}', None)
		assert watchdog and watchdog.stdin
		watchdog.stdin.close()  # what the death of the process that started it does
		watchdog.wait(20)
		time.sleep(0.2)
		assert reused.poll() is None, 'the watchdog signalled a process group that is not its Chrome'
	finally:
		reused.kill()


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
	real = admin._process_start_time
	monkeypatch.setattr(admin, '_process_start_time', lambda pid: 'when the daemon started' if pid == other.pid else real(pid))
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
