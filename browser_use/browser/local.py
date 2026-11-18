"""Local browsers Browser launches itself: Browser('chromium') (a fresh profile) and Browser('chrome', profile=...)
(a temporary copy of one of your Chrome profiles). Attaching to the Chrome you have open stays in browser-harness."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from browser_use.exceptions import BrowserConfigError

logger = logging.getLogger(__name__)

START_TIMEOUT_S = 30  # Chrome start until its DevTools port is open
TMP_PREFIX = 'browser-use-chrome-'
OWNER = '.owner'  # in each LocalBrowser temp dir, locked while its process lives; unlocked = left by a dead process
# Rebuilt by Chrome, large, or owned by the running Chrome: never copied from a real profile
SKIP_COPY = shutil.ignore_patterns(
	'Cache',
	'Code Cache',
	'GPUCache',
	'DawnCache',
	'DawnGraphiteCache',
	'DawnWebGPUCache',
	'GrShaderCache',
	'GraphiteDawnCache',
	'ShaderCache',
	'CacheStorage',
	'ScriptCache',
	'Singleton*',
	'LOCK',
	'lockfile',
	'DevToolsActivePort',
)


def default_user_data_dirs() -> list[Path]:
	"""Chromium-family browsers' default user-data-dirs, in browser-harness's discovery order (Google Chrome first)."""
	from browser_harness.daemon import profile_dirs

	return profile_dirs()


def chrome_user_data_dir() -> Path:
	"""Google Chrome's default user-data-dir (where its profiles live)."""
	return default_user_data_dirs()[0]


def is_default_user_data_dir(path: str | Path) -> bool:
	p = Path(path).expanduser().resolve()
	return any(p == d.expanduser().resolve() for d in default_user_data_dirs())


def live_debug_dirs() -> list[Path]:
	"""Default user-data-dirs whose browser has remote debugging on right now (harness discovery order)."""
	from browser_harness import daemon

	return [base for base in daemon.PROFILES if daemon._devtools_port_live(base) and not _left_over(base)]


def _left_over(base: Path) -> bool:
	"""DevToolsActivePort was written before the browser now holding this dir started, or no browser holds it: Chrome
	leaves the file when it quits, so its port is free for any process. POSIX only (Windows has no SingletonLock)."""
	from browser_harness import daemon

	if sys.platform == 'win32':
		return False
	try:
		written = (base / 'DevToolsActivePort').stat().st_mtime
		started = os.lstat(base / 'SingletonLock').st_mtime
	except OSError:
		return True
	return written < started or not (daemon.browser_running_for_profile(base) or _holder_wrote_it(base))


def _holder_wrote_it(base: Path) -> bool:
	"""What listens on DevToolsActivePort's port serves the browser websocket the file names: the browser that wrote the
	file holds the port, though the pid in its SingletonLock is not one this process can see (Chrome in another PID
	namespace: a sidecar container sharing the home dir and localhost). A process that took the port after that browser
	quit does not know the id, unless it read it from that browser's /json/version while it ran (and could drive it
	then). Chrome 147+ on its default dir answers 404 there: unproven, as before."""
	try:
		port, path = (base / 'DevToolsActivePort').read_text(encoding='utf-8', errors='replace').split()[:2]
		local = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 127.0.0.1 itself, never an HTTP proxy
		with local.open('http://127.0.0.1:%d/json/version' % int(port), timeout=1) as r:
			ws = json.loads(r.read(65536))['webSocketDebuggerUrl']  # ~500 bytes from Chrome
		return urllib.parse.urlsplit(ws).path == path
	except Exception:  # - 404, not a browser, no such field: not proven
		return False


def require_debug_port() -> None:
	"""Before a browser-harness daemon discovers your Chrome: one of your browsers must have remote debugging on. With
	none, browser-harness 0.1.13 attached to whatever answered on 127.0.0.1:9222 / 9223, which any local user or
	process can open (another user's Chrome, a fake one): the agent then typed your secrets into their browser.
	A Chrome that is closed is launched as browser-harness does; else chrome://inspect opens and this raises."""
	from browser_harness import admin, daemon

	if not admin._is_local_chrome_mode():
		return
	# browser-harness reads every dir's DevToolsActivePort in turn and attaches to whatever answers on its port, or
	# falls through to 9222 / 9223 when that is not a browser: a left-over file whose port someone now holds is both.
	for base in daemon.PROFILES:
		if daemon._devtools_port_live(base) and _left_over(base):
			port = (base / 'DevToolsActivePort').read_text(errors='replace').split()[0]
			raise RuntimeError(
				f'remote-debugging-setup: {base / "DevToolsActivePort"} is left from an earlier browser session and '
				f'another process now listens on its port {port}; browser-harness would attach to that process. Delete '
				'that file (Chrome writes a new one when remote debugging starts), then run again.'
			)
	if live_debug_dirs():
		return
	if not has_display():  # a server or container: no Chrome window to turn remote debugging on in
		raise RuntimeError(
			'remote-debugging-setup: no browser here has remote debugging on, and there is no display to turn it on in '
			'Chrome. Set BU_CDP_URL to http://127.0.0.1:PORT of a Chrome started with --remote-debugging-port=PORT, or '
			'use a cloud browser (start_remote_daemon() in the CLI, Browser() in the library).'
		)
	if not daemon.supported_browser_running() and admin._launch_browser():
		deadline = time.monotonic() + (daemon.TOGGLE_BOOT_GRACE if daemon.remote_debugging_toggle_profiles() else 3)
		while time.monotonic() < deadline:
			if live_debug_dirs():
				return
			time.sleep(0.3)
	admin._open_chrome_inspect_once()
	raise RuntimeError(
		'remote-debugging-setup: none of your browsers has remote debugging on (no live DevToolsActivePort in '
		f'{", ".join(map(str, daemon.PROFILES))}). In Chrome, open chrome://inspect/#remote-debugging, tick "Allow remote '
		'debugging for this browser instance", then run again and click Allow. Ports 9222/9223 are never guessed: for '
		'a Chrome you started with --remote-debugging-port=PORT, set BU_CDP_URL to http://127.0.0.1:PORT or pass '
		'Browser(cdp_url=...).'
	)


def require_debug_port_unless_attached(name: str | None = None) -> None:
	"""require_debug_port(), except for daemon name when it already reaches its browser (one BU_CDP_WS started, an
	orchestrator's): browser-harness reuses it and discovers nothing. The CLI, --cli-mcp and Browser('chrome')."""
	from browser_harness import admin

	try:
		admin.require_existing_daemon(name)
	except RuntimeError:
		require_debug_port()


def find_binary(executable_path: str | None = None, *, chrome_only: bool = False) -> str:
	"""executable_path, then BH_CHROME_PATH / CHROME_PATH (browser-harness's names), then the platform's Chrome,
	Chromium and Edge. chrome_only: Google Chrome only (a copied Chrome profile's cookies decrypt only in Chrome)."""
	if executable_path:
		if not Path(executable_path).expanduser().is_file():
			raise FileNotFoundError(f'executable_path={executable_path!r} is not a file')
		if is_snap(str(Path(executable_path).expanduser())):
			raise RuntimeError(_snap_error(executable_path))
		return str(Path(executable_path).expanduser())
	tried = [p for k in ('BH_CHROME_PATH', 'CHROME_PATH') if (p := (os.environ.get(k) or '').strip())]
	for path in tried:  # it silently fell back to another browser
		if not Path(path).expanduser().is_file():
			logger.warning('BH_CHROME_PATH / CHROME_PATH %r is not a file; looking for an installed browser instead', path)
	on_path: list[str] = []
	if sys.platform == 'darwin':
		apps = ['Google Chrome'] if chrome_only else ['Google Chrome', 'Chromium', 'Microsoft Edge', 'Google Chrome Canary']
		tried += [
			str(root / f'{a}.app/Contents/MacOS/{a}')
			for a in apps
			for root in (Path('/Applications'), Path.home() / 'Applications')
		]
	elif sys.platform == 'win32':
		rels = [r'Google\Chrome\Application\chrome.exe']
		rels += [] if chrome_only else [r'Chromium\Application\chrome.exe', r'Microsoft\Edge\Application\msedge.exe']
		roots = [r for k in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA') if (r := os.environ.get(k))]
		tried += [str(Path(root) / rel) for rel in rels for root in roots]
	else:
		on_path = ['google-chrome-stable', 'google-chrome']
		on_path += [] if chrome_only else ['chromium', 'chromium-browser', 'microsoft-edge-stable', 'microsoft-edge']
		tried += [p for n in on_path if (p := shutil.which(n))]  # a bare name would be a file in the working directory
	if not chrome_only:
		tried += playwright_chromium()  # `browser-use install` (Playwright's Chromium), last: an installed Chrome wins
	snaps = []
	for path in tried:
		if Path(path).expanduser().is_file():
			if is_snap(str(Path(path).expanduser())):
				snaps.append(path)
				continue
			return str(Path(path).expanduser())
	if snaps:
		raise RuntimeError(_snap_error(snaps[0]))
	tried += [f'{n} on PATH' for n in on_path]
	if chrome_only:  # a copied Chrome profile needs real Chrome: Playwright's Chromium cannot decrypt its cookies
		raise RuntimeError(
			f'No Google Chrome found (tried {", ".join(tried)}). Install it, or pass executable_path=... or set BH_CHROME_PATH.'
		)
	raise RuntimeError(
		f'No Chrome, Chromium or Edge found (tried {", ".join(tried)}). Install one or run `browser-use install` '
		"(Playwright's Chromium), or pass executable_path=... or set BH_CHROME_PATH."
	)


def playwright_chromium() -> list[str]:
	"""Chromium binaries `browser-use install` (uvx playwright install chromium) left in Playwright's cache, newest first.
	PLAYWRIGHT_BROWSERS_PATH, else the platform default. Newer builds ship Chrome for Testing, older ones Chromium."""
	root = os.environ.get('PLAYWRIGHT_BROWSERS_PATH', '').strip()
	if root in ('', '0'):
		if sys.platform == 'darwin':
			root = str(Path.home() / 'Library/Caches/ms-playwright')
		elif sys.platform == 'win32':
			root = str(Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData/Local') / 'ms-playwright')
		else:
			root = str(Path.home() / '.cache/ms-playwright')
	builds = sorted(
		Path(root).expanduser().glob('chromium-*'),
		key=lambda p: int(p.name.split('-')[-1]) if p.name.split('-')[-1].isdigit() else -1,
		reverse=True,
	)
	if sys.platform == 'darwin':
		rels = [
			'chrome-mac*/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing',
			'chrome-mac*/Chromium.app/Contents/MacOS/Chromium',
		]
	elif sys.platform == 'win32':
		rels = ['chrome-win*/chrome.exe']
	else:
		rels = ['chrome-linux*/chrome']
	return [str(hit) for build in builds for rel in rels for hit in sorted(build.glob(rel))]


def is_snap(path: str) -> bool:
	"""Linux Snap Chromium (Ubuntu's chromium, also behind the /usr/bin/chromium-browser wrapper script). Its
	confinement hides our /tmp profile from it, so it never reports a DevTools port."""
	if not sys.platform.startswith('linux'):
		return False
	try:
		real = os.path.realpath(path)
		with open(real, 'rb') as f:
			head = f.read(4096)
	except OSError:
		return False
	return '/snap/' in real or (head.startswith(b'#!') and b'/snap/' in head)


def _snap_error(path: str) -> str:
	return (
		f'{path} is Snap Chromium, which cannot open DevTools for a browser it did not start itself. Install Google '
		'Chrome from https://www.google.com/chrome/ (the .deb) and pass executable_path=... or set BH_CHROME_PATH; '
		'`browser-use doctor --fix-snap` shows the steps.'
	)


def resolve_profile(root: Path, name: str) -> str:
	"""The profile directory ('Default', 'Profile 1', ...) whose directory or display name is name."""
	try:
		cache = json.loads((root / 'Local State').read_text(encoding='utf-8', errors='replace'))['profile']['info_cache']
		profiles = {d: str((info or {}).get('name') or d) for d, info in cache.items() if (root / d).is_dir()}
	except (OSError, ValueError, KeyError, TypeError, AttributeError):
		profiles = {}
	if not profiles:
		raise BrowserConfigError(f'No Chrome profiles found in {root}. Open Chrome once, or use Browser("chromium").')
	hits = [d for d, n in profiles.items() if name in (d, n)]
	hits = hits or [d for d, n in profiles.items() if name.casefold() in (d.casefold(), n.casefold())]
	if len(hits) == 1:
		return hits[0]
	listing = ', '.join(f'{n!r} ({d})' for d, n in profiles.items())
	raise BrowserConfigError(f'{"Several" if hits else "No"} Chrome profiles match {name!r}. Your profiles: {listing}')


def copy_profile(root: Path, directory: str, dest: Path) -> None:
	"""Local State (it holds the cookie key on Windows and Linux) plus one profile directory, without caches. Chrome may
	keep running: files it holds locked are skipped with a warning; locked cookies (Windows, while Chrome runs) raise,
	since the copy would have none of the logins it is for."""
	dest.mkdir(parents=True, exist_ok=True)
	shutil.copy2(root / 'Local State', dest / 'Local State')
	try:
		shutil.copytree(root / directory, dest / directory, ignore=SKIP_COPY, symlinks=True, dirs_exist_ok=True)
	except shutil.Error as e:  # copytree copies everything it can, then reports the files it could not read
		skipped = sorted({Path(err[0]).name for err in e.args[0] if isinstance(err, tuple) and err})
		if 'Cookies' in skipped:
			raise RuntimeError(
				f'Could not copy the cookies of Chrome profile {directory!r}: Chrome holds them locked (Windows does while '
				'Chrome runs). Quit Chrome and run again.'
			) from None
		logger.warning('Copied Chrome profile %r without files Chrome holds open: %s', directory, ', '.join(skipped[:10]))


def _try_lock(f) -> bool:
	"""Non-blocking exclusive lock on an open file; the OS drops it when the process dies, however it dies."""
	try:
		if sys.platform == 'win32':
			import msvcrt

			msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
		else:
			import fcntl

			fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
		return True
	except OSError:
		return False


def sweep_stale_dirs(root: Path | None = None) -> None:
	"""Delete temp dirs that LocalBrowsers of dead processes left (SIGKILL, OOM, a crash, a Windows file lock at stop):
	a profile copy holds the user's cookies and saved passwords. A dir whose owner still runs stays locked."""
	for d in Path(root or tempfile.gettempdir()).glob(f'{TMP_PREFIX}*'):
		try:
			if time.time() - (d / OWNER).stat().st_mtime < 60:  # just created: its owner may not hold the lock yet
				continue
			with open(d / OWNER, 'r+b') as f:
				if not _try_lock(f):
					continue
		except OSError:  # no owner file (another process is creating the dir) or unreadable: not ours to judge
			continue
		shutil.rmtree(d, ignore_errors=True)


def has_display() -> bool:
	from browser_harness.admin import _has_local_gui

	return _has_local_gui()


def chrome_args(user_data_dir: Path, *, headless: bool, fresh: bool, profile_directory: str | None = None) -> list[str]:
	args = [f'--user-data-dir={user_data_dir}', '--remote-debugging-port=0', '--no-first-run', '--no-default-browser-check']
	args.append('--allow-pre-commit-input')  # 0.x and Playwright: keys and clicks reach a tab that has not painted yet
	# 0.x and Playwright: a page the agent is not looking at (a background tab; any tab of a headed window that is
	# covered or behind a locked screen) keeps running its timers and rendering, instead of ~1 timer tick a second
	args += [
		'--disable-background-timer-throttling',
		'--disable-renderer-backgrounding',
		'--disable-backgrounding-occluded-windows',
	]
	if fresh:  # a profile of our own never asks for (or reads) the OS keychain; a copied profile needs the real key
		args += (
			['--use-mock-keychain']
			if sys.platform == 'darwin'
			else ['--password-store=basic']
			if sys.platform.startswith('linux')
			else []
		)
	else:  # a copy is signed in to the user's Google account: sync would write the agent's history, tabs and saved
		args.append('--disable-sync')  # passwords to the account and from there into the real profile
	if headless:
		args += ['--headless=new', '--window-size=1440,900']
	if sys.platform.startswith('linux') and (
		os.geteuid() == 0 or Path('/.dockerenv').exists() or Path('/run/.containerenv').exists()
	):
		args.append('--no-sandbox')  # Chrome refuses to start as root with the sandbox; containers usually lack it
	if profile_directory:
		args.append(f'--profile-directory={profile_directory}')
	return [*args, 'about:blank']


def _ws_url(user_data_dir: Path, log: Path) -> str | None:
	"""Chrome writes its browser websocket to DevToolsActivePort and stderr once the DevTools port is open."""
	try:
		lines = (user_data_dir / 'DevToolsActivePort').read_text(encoding='utf-8', errors='replace').splitlines()
		if len(lines) >= 2 and lines[0].strip().isdigit() and lines[1].startswith('/devtools/browser/'):
			return f'ws://127.0.0.1:{lines[0].strip()}{lines[1].strip()}'
	except OSError:
		pass
	try:
		if m := re.search(rb'DevTools listening on (ws://\S+)', log.read_bytes()):
			return m.group(1).decode()
	except OSError:
		pass
	return None


class LocalBrowser:
	"""One Chrome this process launched. stop() kills it and deletes everything it created; safe while launch() runs
	in another thread (a cancelled Browser.start), so a Chrome is never left behind."""

	def __init__(self) -> None:
		sweep_stale_dirs()
		self.tmp = Path(tempfile.mkdtemp(prefix=TMP_PREFIX))  # holds the log and, unless kept, the profile
		self._owner = open(self.tmp / OWNER, 'wb')  # locked while this process lives: sweep_stale_dirs skips the dir
		_try_lock(self._owner)
		self.user_data_dir: Path | None = None
		self.proc: subprocess.Popen | None = None
		self.ws: str | None = None  # the browser websocket, once Chrome reported it
		self._lock = threading.Lock()
		self._stopped = False
		self.watchdog: subprocess.Popen | None = None  # set once the daemon is up (Browser._start)

	def start(
		self,
		*,
		executable_path: str | None = None,
		headless: bool | None = None,
		user_data_dir: str | Path | None = None,
		profile: str | None = None,
	) -> str:
		"""Launch Chrome; returns its browser websocket URL. profile: copy that Chrome profile into a temp dir first.
		user_data_dir: a dedicated dir that is kept (default: a temp dir deleted on stop)."""
		try:
			return self._start(executable_path, headless, user_data_dir, profile)
		except BaseException:
			if self._stopped:  # stop() ran mid-start: a profile copy still running in this thread recreated the dir
				self._remove_tmp()
			raise

	def _start(
		self, executable_path: str | None, headless: bool | None, user_data_dir: str | Path | None, profile: str | None
	) -> str:
		binary = find_binary(executable_path, chrome_only=profile is not None)
		headless = not has_display() if headless is None else headless
		directory = None
		if profile is not None:
			root = chrome_user_data_dir()
			directory = resolve_profile(root, profile)
			udd = self.tmp / 'profile'
			copy_profile(root, directory, udd)
		else:
			udd = Path(user_data_dir).expanduser() if user_data_dir else self.tmp / 'profile'
			udd.mkdir(parents=True, exist_ok=True)
			(udd / 'DevToolsActivePort').unlink(missing_ok=True)  # a stale one from an earlier run
		self.user_data_dir = udd
		args = chrome_args(udd, headless=headless, fresh=profile is None, profile_directory=directory)
		try:
			return self._launch(binary, args)
		except RuntimeError as e:  # Linux without user namespaces or a setuid sandbox helper (some CI runners, VMs)
			if 'No usable sandbox' not in str(e) or '--no-sandbox' in args:
				raise
			logger.warning('Chrome has no usable sandbox here; starting it with --no-sandbox')
			return self._launch(binary, [*args[:-1], '--no-sandbox', args[-1]])

	def _launch(self, binary: str, args: list[str]) -> str:
		assert self.user_data_dir is not None
		log = self.tmp / 'chrome.log'
		with self._lock:
			if self._stopped:
				raise RuntimeError('the browser was stopped while it started')
			with open(log, 'wb') as err:
				self.proc = subprocess.Popen(
					[binary, *args],
					stdin=subprocess.DEVNULL,
					stdout=subprocess.DEVNULL,
					stderr=err,
					start_new_session=sys.platform != 'win32',  # its own process group: _kill reaches every helper
					creationflags=getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0),
				)
		proc, deadline = self.proc, time.monotonic() + START_TIMEOUT_S
		while time.monotonic() < deadline and not self._stopped:
			if ws := _ws_url(self.user_data_dir, log):
				self.ws = ws
				return ws
			if (code := proc.poll()) is not None:
				tail = log.read_bytes()[-600:].decode(errors='replace').strip()
				# Only a kept user_data_dir can be held by another Chrome; a temp or copied profile is new to this run
				lock = '' if self.user_data_dir.is_relative_to(self.tmp) else f' is another Chrome using {self.user_data_dir}?'
				raise RuntimeError(f'{Path(binary).name} exited at start (code {code});{lock} {tail}')
			time.sleep(0.05)
		if self._stopped:
			raise RuntimeError('the browser was stopped while it started')
		raise RuntimeError(f'{Path(binary).name} did not open its DevTools port within {START_TIMEOUT_S}s')

	def watch(self, daemon: str, daemon_pid: int | None) -> None:
		"""Start the watchdog that cleans up after this process if it dies without stopping Chrome (SIGKILL, OOM).
		daemon: the browser-harness daemon's name (a reattach replaces the process, never the name)."""
		if self.proc is not None and self.watchdog is None:
			self.watchdog = start_watchdog(self.proc.pid, self.tmp, daemon, daemon_pid)

	def stop(self) -> None:
		watchdog, self.watchdog = self.watchdog, None
		if watchdog is not None:  # first: a normal stop must not race it
			with contextlib.suppress(OSError):
				watchdog.kill()
			with contextlib.suppress(Exception):
				watchdog.wait(5)
		with self._lock:
			self._stopped = True
			proc, self.proc = self.proc, None
		if proc is not None:
			_kill(proc, self.ws)
		self._remove_tmp()

	def _remove_tmp(self) -> None:
		self._owner.close()
		for _ in range(20):  # Windows keeps files locked for a moment after the processes exit
			shutil.rmtree(self.tmp, ignore_errors=True)
			if not self.tmp.exists():
				return
			time.sleep(0.1)


# Runs detached next to each Browser's daemon. Its stdin is a pipe only the Python process that started the Browser
# holds: the read returns at EOF, when that process dies however it dies (SIGKILL, OOM), and it then stops the cloud
# browser (else it bills until its timeout) and ends the daemon, and the Chrome process group and temp profile of a
# launched Chrome. A normal stop kills the watchdog first, so it does nothing.
# A child that process fork()ed without exec holds the pipe too: the cleanup then waits for that child to end.
# The daemon is the one answering on its name now (a reattach replaces it); else the pid it started with, only while
# that pid is still the same process (never a process that reused the number). The same for Chrome: one that exited
# first (crashed, quit by the user) left its pid free, and the group that reused it was killed.
WATCHDOG = r"""
import json, os, shutil, signal, subprocess, sys, time
sys.stdin.buffer.read()
chrome, tmp, name, first, started = int(sys.argv[1]), sys.argv[2], sys.argv[3], int(sys.argv[4]), json.loads(sys.argv[5])
chrome_started = json.loads(sys.argv[6])
cloud = os.environ.get('BU_CLEANUP_BROWSER_ID', '')
daemon = 0
try:
    from browser_harness import _ipc, admin
    if cloud:
        admin._stop_cloud_browser(cloud)
    daemon = _ipc.identify(name, 2.0) or 0
    if not daemon and first and started is not None and admin._process_start_time(first) == started:
        daemon = first
    if chrome and chrome_started is not None and admin._process_start_time(chrome) != chrome_started:
        chrome = 0  # exited before us: the number may be another process group's now
except Exception:
    pass
def kill(pid, group, sig):
    try:
        if sys.platform == 'win32':
            subprocess.run(['taskkill', '/F', '/T', '/PID', str(pid)], capture_output=True)
        else:
            (os.killpg if group else os.kill)(pid, sig)
    except OSError:
        pass
if daemon:
    kill(daemon, False, signal.SIGTERM)
if chrome:  # never 0: killpg(0) is this watchdog's own group
    kill(chrome, True, signal.SIGTERM)
time.sleep(3)
if sys.platform != 'win32':
    if chrome:
        kill(chrome, True, signal.SIGKILL)
    if daemon:
        kill(daemon, False, signal.SIGKILL)
for _ in range(20 if tmp else 0):
    shutil.rmtree(tmp, ignore_errors=True)
    if not os.path.exists(tmp):
        break
    time.sleep(0.25)
"""


def start_watchdog(
	chrome_pid: int, tmp: Path | str, daemon: str, daemon_pid: int | None, cloud_id: str = ''
) -> subprocess.Popen | None:
	"""The watchdog (WATCHDOG) for a launched Chrome, or for a daemon alone (chrome_pid 0, tmp '') and the cloud browser
	cloud_id; None when it cannot start. The id drives the browser without a key (its CDP hostname): it goes in the
	environment, which only this user can read, never argv (any local user's ps)."""
	started = chrome_started = None
	with contextlib.suppress(Exception):
		from browser_harness import admin

		started = admin._process_start_time(daemon_pid) if daemon_pid else None
		chrome_started = admin._process_start_time(chrome_pid) if chrome_pid else None
	try:
		args = (str(chrome_pid), str(tmp), daemon, str(daemon_pid or 0), json.dumps(started), json.dumps(chrome_started))
		return subprocess.Popen(
			[sys.executable, '-P', '-c', WATCHDOG, *args],
			env={**os.environ, 'BU_CLEANUP_BROWSER_ID': cloud_id},
			stdin=subprocess.PIPE,
			stdout=subprocess.DEVNULL,
			stderr=subprocess.DEVNULL,
			start_new_session=sys.platform != 'win32',  # a Ctrl-C to our process group does not end it first
			creationflags=getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0),
		)
	except OSError as e:
		logger.debug('no watchdog for %s: %s', daemon, e)
		return None


def _close_over_cdp(ws: str) -> bool:
	"""CDP Browser.close: Chrome shuts down as when its last window closes, writing cookies and storage to the profile
	first. False when it could not be sent."""
	try:
		from websockets.sync.client import connect

		with connect(ws, open_timeout=3, close_timeout=1, max_size=None) as c:
			c.send(json.dumps({'id': 1, 'method': 'Browser.close'}))
			with contextlib.suppress(Exception):  # Chrome may close the socket before it answers
				c.recv(timeout=3)
		return True
	except Exception as e:  # - fall back to a signal
		logger.debug('Browser.close over CDP failed: %s', e)
		return False


def _kill(proc: subprocess.Popen, ws: str | None = None) -> None:
	"""Browser.close over CDP (else SIGTERM to the browser process alone), SIGKILL after 5 s; on POSIX then the whole
	process group, so no helper survives. A SIGTERM to the whole group killed the network service with the browser, before
	it wrote the cookies of a user_data_dir profile."""
	win = sys.platform == 'win32'

	def send(sig: int) -> None:
		try:
			proc.send_signal(sig) if win else os.killpg(proc.pid, sig)
		except OSError:
			pass

	if proc.poll() is None:
		if not (ws and _close_over_cdp(ws)) and not win:  # Windows: SIGTERM is TerminateProcess, no cleanup at all
			with contextlib.suppress(OSError):
				proc.send_signal(signal.SIGTERM)
		try:
			proc.wait(5)
		except subprocess.TimeoutExpired:
			proc.kill() if win else send(signal.SIGKILL)
			try:
				proc.wait(5)
			except subprocess.TimeoutExpired:
				logger.warning('Chrome (pid %s) did not exit', proc.pid)
	if not win:
		send(signal.SIGKILL)  # helpers still in the group after the browser process exited
