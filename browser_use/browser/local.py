"""Local browsers Browser launches itself: Browser('chromium') (a fresh profile) and Browser('chrome', profile=...)
(a temporary copy of one of your Chrome profiles). Attaching to the Chrome you have open stays in browser-harness."""

from __future__ import annotations

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
from pathlib import Path

logger = logging.getLogger(__name__)

START_TIMEOUT_S = 30  # Chrome start until its DevTools port is open
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

	return [base for base in daemon.PROFILES if daemon._devtools_port_live(base)]


def find_binary(executable_path: str | None = None, *, chrome_only: bool = False) -> str:
	"""executable_path, then BH_CHROME_PATH / CHROME_PATH (browser-harness's names), then the platform's Chrome,
	Chromium and Edge. chrome_only: Google Chrome only (a copied Chrome profile's cookies decrypt only in Chrome)."""
	if executable_path:
		if not Path(executable_path).expanduser().is_file():
			raise FileNotFoundError(f'executable_path={executable_path!r} is not a file')
		return str(Path(executable_path).expanduser())
	tried = [p for k in ('BH_CHROME_PATH', 'CHROME_PATH') if (p := (os.environ.get(k) or '').strip())]
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
		names = ['google-chrome-stable', 'google-chrome']
		names += [] if chrome_only else ['chromium', 'chromium-browser', 'microsoft-edge-stable', 'microsoft-edge']
		tried += [shutil.which(n) or n for n in names]
	for path in tried:
		if Path(path).expanduser().is_file():
			return str(Path(path).expanduser())
	kind = 'Google Chrome' if chrome_only else 'Chrome, Chromium or Edge'
	raise RuntimeError(
		f'No {kind} found (tried {", ".join(tried)}). Install one, or pass executable_path=... or set BH_CHROME_PATH.'
	)


def resolve_profile(root: Path, name: str) -> str:
	"""The profile directory ('Default', 'Profile 1', ...) whose directory or display name is name."""
	try:
		cache = json.loads((root / 'Local State').read_text(encoding='utf-8', errors='replace'))['profile']['info_cache']
		profiles = {d: str((info or {}).get('name') or d) for d, info in cache.items() if (root / d).is_dir()}
	except (OSError, ValueError, KeyError, TypeError, AttributeError):
		profiles = {}
	if not profiles:
		raise ValueError(f'No Chrome profiles found in {root}. Open Chrome once, or use Browser("chromium").')
	hits = [d for d, n in profiles.items() if name in (d, n)]
	hits = hits or [d for d, n in profiles.items() if name.casefold() in (d.casefold(), n.casefold())]
	if len(hits) == 1:
		return hits[0]
	listing = ', '.join(f'{n!r} ({d})' for d, n in profiles.items())
	raise ValueError(f'{"Several" if hits else "No"} Chrome profiles match {name!r}. Your profiles: {listing}')


def copy_profile(root: Path, directory: str, dest: Path) -> None:
	"""Local State (it holds the cookie key on Windows and Linux) plus one profile directory, without caches. Chrome may
	keep running: files it holds locked are skipped."""
	dest.mkdir(parents=True, exist_ok=True)
	shutil.copy2(root / 'Local State', dest / 'Local State')
	try:
		shutil.copytree(root / directory, dest / directory, ignore=SKIP_COPY, symlinks=True, dirs_exist_ok=True)
	except shutil.Error as e:  # copytree copies everything it can, then reports the files it could not read
		logger.debug('Skipped %d profile files Chrome holds open', len(e.args[0]))


def has_display() -> bool:
	from browser_harness.admin import _has_local_gui

	return _has_local_gui()


def chrome_args(user_data_dir: Path, *, headless: bool, fresh: bool, profile_directory: str | None = None) -> list[str]:
	args = [f'--user-data-dir={user_data_dir}', '--remote-debugging-port=0', '--no-first-run', '--no-default-browser-check']
	if fresh:  # a profile of our own never asks for (or reads) the OS keychain; a copied profile needs the real key
		args += (
			['--use-mock-keychain']
			if sys.platform == 'darwin'
			else ['--password-store=basic']
			if sys.platform.startswith('linux')
			else []
		)
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
		self.tmp = Path(tempfile.mkdtemp(prefix='browser-use-chrome-'))  # holds the log and, unless kept, the profile
		self.user_data_dir: Path | None = None
		self.proc: subprocess.Popen | None = None
		self._lock = threading.Lock()
		self._stopped = False

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
				return ws
			if (code := proc.poll()) is not None:
				tail = log.read_bytes()[-600:].decode(errors='replace').strip()
				raise RuntimeError(
					f'{Path(binary).name} exited at start (code {code}); is another Chrome using {self.user_data_dir}? {tail}'
				)
			time.sleep(0.05)
		if self._stopped:
			raise RuntimeError('the browser was stopped while it started')
		raise RuntimeError(f'{Path(binary).name} did not open its DevTools port within {START_TIMEOUT_S}s')

	def stop(self) -> None:
		with self._lock:
			self._stopped = True
			proc, self.proc = self.proc, None
		if proc is not None:
			_kill(proc)
		for _ in range(20):  # Windows keeps files locked for a moment after the processes exit
			shutil.rmtree(self.tmp, ignore_errors=True)
			if not self.tmp.exists():
				return
			time.sleep(0.1)


def _kill(proc: subprocess.Popen) -> None:
	"""SIGTERM (Chrome quits cleanly), SIGKILL after 5 s; on POSIX the whole process group, so no helper survives."""
	win = sys.platform == 'win32'

	def send(sig: int) -> None:
		try:
			proc.send_signal(sig) if win else os.killpg(proc.pid, sig)
		except OSError:
			pass

	if proc.poll() is None:
		send(signal.SIGTERM)
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
