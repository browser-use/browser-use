"""Which browser the agent drives.

Browser()                         a Browser Use Cloud browser (default; needs a Browser Use API key)
Browser('chromium')               a fresh local Chrome/Chromium/Edge with its own temp profile (= Browser(local=True))
Browser('chrome')                 the Chrome you have open, attached through the shared browser-harness daemon
Browser('chrome', profile='Work') a new Chrome on a temporary copy of your Chrome profile 'Work'

Agent.run() stops the browser at the end unless Browser(keep_alive=True). Cloud browsers are also stopped when the
process exits or gets SIGTERM or SIGHUP, and the server stops them after cloud_timeout minutes either way.
"""

from __future__ import annotations

import asyncio
import atexit
import concurrent.futures
import contextlib
import json
import logging
import os
import re
import signal
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser
from pathlib import Path
from typing import Literal

from browser_use.auth import browser_use_api_key
from browser_use.browser import local as _local
from browser_use.config import load_env

logger = logging.getLogger(__name__)
load_env()  # 0.x read .env on import; credentials below resolve from it

CLOUD_API = 'https://api.browser-use.com/api/v4'
KINDS = ('cloud', 'chromium', 'chrome')
UNSUPPORTED = {  # 0.x BrowserSession/BrowserProfile options -> what to do instead
	'profile_directory': "use Browser('chrome', profile='Profile 1') (a copy of that Chrome profile).",
	'allowed_domains': 'domain restrictions are not in 1.0 yet.',
	'prohibited_domains': 'domain restrictions are not in 1.0 yet.',
	'browser_profile': 'BrowserProfile was removed; pass options to Browser(...).',
	'storage_state': "use cloud_profile_id (cloud), Browser('chrome', profile=...) or Browser('chromium', user_data_dir=...).",
	'proxy': 'use cloud_proxy_country_code on cloud browsers.',
}
CREATE_TIMEOUT_S = 120  # total for the cloud create; start() fails past it, and a browser that lands later is stopped
LOCAL_START_WAIT_S = 120  # Browser('chrome'): Chrome start plus the user clicking Allow on its remote-debugging prompt
DOWNLOADS_TIMEOUT_S = 300  # per download pass; a slow or huge download never holds the stop (and billing) longer
_LIVE: set[Browser] = set()  # browsers this process owns that still need stopping
_POOL = concurrent.futures.ThreadPoolExecutor(thread_name_prefix='browser-use-cloud')  # joined at exit
_atexit_installed = _signals_installed = False
MAX_NAME_BYTES = 255  # a file name, on every common filesystem


class _Default(str):
	"""A default value that Browser() tells apart from the same value passed explicitly."""


US = _Default('us')


def _cloud(path: str, method: str = 'GET', body: dict | None = None) -> dict:
	req = urllib.request.Request(
		f'{CLOUD_API}{path}',
		method=method,
		data=json.dumps(body).encode() if body is not None else None,
		headers={'X-Browser-Use-API-Key': browser_use_api_key(), 'Content-Type': 'application/json'},
	)
	try:
		with urllib.request.urlopen(req, timeout=60) as r:
			return json.loads(r.read() or b'{}')
	except urllib.error.HTTPError as e:
		detail = e.read().decode(errors='replace')[:500]
		hint = (
			' Run `browser-use login` again for a key with v4 access (older logins stored browser-only v3 keys), or '
			'create one at https://cloud.browser-use.com/settings?tab=api-keys and set BROWSER_USE_API_KEY.'
			if 'missing required scope' in detail
			else ''
		)
		raise RuntimeError(f'Browser Use Cloud {method} {path} failed: HTTP {e.code} {detail}.{hint}') from None


def _download(url: str, dest: Path, name: str, deadline: float) -> Path:
	"""Stream url into a new file in dest, never over an existing one ('report (1).csv' next to 'report.csv'). Stops at
	the monotonic deadline, so the thread ends then: run_sync's loop and interpreter exit never wait on a slow transfer.
	A transfer that fails or runs out of time leaves no file."""
	if (left := deadline - time.monotonic()) <= 0:
		raise TimeoutError('download deadline passed')
	with urllib.request.urlopen(url, timeout=min(30.0, left)) as r:  # the timeout bounds each read
		dest.mkdir(parents=True, exist_ok=True)
		stem, suffix = Path(name).stem, Path(name).suffix
		if len(suffix.encode()) > 32:  # not an extension: part of a long name
			stem, suffix = name, ''
		for i in range(10_000):
			tail = suffix if i == 0 else f' ({i}){suffix}'
			room = MAX_NAME_BYTES - len(tail.encode())  # a long name is shortened, never dropped
			path = dest / (stem.encode()[:room].decode(errors='ignore') + tail)
			try:
				f = open(path, 'xb')  # - exclusive create: two sessions never write the same file
				break
			except FileExistsError:
				continue
		else:
			raise FileExistsError(f'no free file name for {name} in {dest}')
		try:
			with f:
				size = 0
				while chunk := r.read1(65536):  # read1: returns what arrived, so the deadline is checked as bytes drip in
					f.write(chunk)
					size += len(chunk)
					if time.monotonic() > deadline:
						raise TimeoutError(f'download did not finish within its deadline ({name})')
				expected = (getattr(r, 'headers', None) or {}).get('Content-Length')
				if expected is not None and expected.isdigit() and size != int(expected):  # EOF before the end: truncated
					raise ConnectionError(f'download of {name} ended after {size} of {expected} bytes')
		except BaseException:
			path.unlink(missing_ok=True)
			raise
	return path


def json_page_copies(log: Path) -> set[str]:
	"""Names of the downloads in a REPL worker's downloads.jsonl that only copy a JSON page the tab displayed: a cloud
	browser saves https://host/data?q=1, shown as a page, as the download https://host/data.json (with any cookies the
	page echoed). Real downloads keep their own URL."""
	try:
		records = [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines() if line.strip()]
	except (OSError, ValueError):
		return set()
	pages = {
		urllib.parse.urlsplit(str(r['json_page']))._replace(query='', fragment='').geturl() + '.json'
		for r in records
		if isinstance(r, dict) and r.get('json_page')
	}
	return {str(r['name']) for r in records if isinstance(r, dict) and r.get('name') and r.get('url') in pages}


def _profile_id(profile: str) -> str:
	"""A cloud profile id, or the id of the one profile with exactly this name."""
	if re.fullmatch(r'[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}', profile, re.IGNORECASE):
		return profile.lower()
	items = _cloud(f'/profiles?pageSize=100&query={urllib.parse.quote(profile)}').get('items', [])
	ids = [p['id'] for p in items if p.get('name') == profile]
	if len(ids) != 1:
		raise ValueError(f'{len(ids)} cloud profiles are named {profile!r}; pass the profile id')
	return ids[0]


def _ws_url(cdp_url: str) -> str:
	if not cdp_url.startswith('http'):
		return cdp_url
	with urllib.request.urlopen(f'{cdp_url.rstrip("/")}/json/version', timeout=30) as r:
		return json.load(r)['webSocketDebuggerUrl']


def _shutdown_daemon(name: str) -> bool:
	"""Ask our daemon to shut down without waiting for its process to exit. True when it acknowledged: a daemon
	started with BU_BROWSER_ID acknowledges only once it stopped that cloud browser.

	browser-harness 0.1.13 daemons exit ~20 s after acknowledging shutdown, and admin.restart_daemon waits 15 s for
	that, which would add 15 s to every Agent.run(). The acknowledged daemon closes its tab and endpoint itself."""
	from browser_harness import _ipc as ipc
	from browser_harness import admin

	try:
		c, token = ipc.connect(name, timeout=5.0)
		try:
			c.settimeout(20.0)  # a cloud daemon stops its browser first (one API call, 15 s timeout)
			if ipc.request(c, token, {'meta': 'shutdown'}).get('ok'):
				return True
		finally:
			c.close()
	except Exception:  # - fall back to the slow, forceful path
		pass
	try:
		admin.restart_daemon(name)
	except Exception:  # - cleanup must not mask the result
		pass
	return False


def _name_daemon_files() -> None:
	"""browser-harness names a daemon's socket, pid and log file plain 'bu' when BH_RUNTIME_DIR or BH_TMP_DIR is set
	without BH_*_SHARED=1, so the daemons of parallel Browser()s shared one socket and drove each other's browser.
	Every daemon here has its own name: put it in the file names (this process, its daemons and its REPL workers)."""
	from browser_harness import _ipc as ipc

	if os.environ.get('BH_RUNTIME_DIR') or os.environ.get('BH_TMP_DIR'):
		os.environ['BH_RUNTIME_DIR_SHARED'] = os.environ['BH_TMP_DIR_SHARED'] = '1'
		ipc.BH_RUNTIME_DIR_SHARED = ipc.BH_TMP_DIR_SHARED = True


def _check_one_chrome() -> None:
	"""Browser('chrome') attaches where browser-harness would: the running default daemon, else the first browser
	with remote debugging on, Google Chrome first. Raises when that choice is a guess: several are on, none Chrome."""
	from browser_harness import admin

	if not admin._is_local_chrome_mode() or admin.daemon_alive():
		return
	live = _local.live_debug_dirs()
	if len(live) > 1 and live[0] != _local.chrome_user_data_dir():
		raise RuntimeError(
			f"Browser('chrome'): several browsers have remote debugging on ({', '.join(map(str, live))}) and none of "
			'them is Google Chrome. Turn it off in all but one (chrome://inspect/#remote-debugging), then run again.'
		)


def _stop_all() -> None:
	from browser_use.repl.session import kill_workers

	kill_workers()  # first: no agent code keeps acting on a browser while it stops
	for browser in list(_LIVE):
		browser._stop_now()


def _on_signal(signum, frame) -> None:
	_stop_all()
	signal.signal(signum, signal.SIG_DFL)
	os.kill(os.getpid(), signum)


def _install_cleanup() -> None:
	"""atexit + SIGTERM + SIGHUP (terminal closed): never leave a billed browser or a running REPL worker behind.
	Signal handlers can only be set on the main thread: called on another one, they are set by the next call on the main
	thread (Browser() calls it too). Leaves a handler the app set alone."""
	global _atexit_installed, _signals_installed
	if not _atexit_installed:
		_atexit_installed = True
		atexit.register(_stop_all)
	if _signals_installed or threading.current_thread() is not threading.main_thread():
		return
	_signals_installed = True
	for sig in (signal.SIGTERM, getattr(signal, 'SIGHUP', None)):  # no SIGHUP on Windows
		if sig is not None and signal.getsignal(sig) is signal.SIG_DFL:
			signal.signal(sig, _on_signal)


def _kind(kind: str | None, local: bool, use_cloud: bool | None, cdp_url: str | None) -> str:
	"""'cloud', 'chromium', 'chrome' or 'cdp' (cdp_url). local=True and 0.x use_cloud=False mean 'chromium'."""
	if kind is not None and kind not in KINDS:
		raise ValueError(f"Browser({kind!r}): pick 'cloud' (default), 'chromium' (a fresh local browser) or 'chrome' (yours)")
	if sum(map(bool, (kind, local, cdp_url, use_cloud))) > 1 or (use_cloud is False and kind == 'cloud'):
		raise ValueError("Pass one of Browser('chromium' | 'chrome' | 'cloud'), local=True, cdp_url=... or use_cloud=True")
	if cdp_url:
		return 'cdp'
	return kind or ('chromium' if local or use_cloud is False else 'cloud')


class Browser:
	def __init__(
		self,
		kind: Literal['cloud', 'chromium', 'chrome'] | None = None,
		*,
		profile: str | None = None,
		headless: bool | None = None,
		user_data_dir: str | Path | None = None,
		executable_path: str | None = None,
		local: bool = False,
		use_cloud: bool | None = None,
		cdp_url: str | None = None,
		keep_alive: bool = False,
		cloud_profile_id: str | None = None,
		cloud_proxy_country_code: str | None = US,
		cloud_timeout: int | None = None,
		live_view: bool = False,
		**kwargs,
	):
		"""kind: 'cloud' (default), 'chromium' (a fresh local browser; local=True is the same) or 'chrome' (the Chrome
		you have open; with profile='Work', a new Chrome on a temporary copy of that profile).
		headless (launched browsers; default: only without a display), executable_path (default: Chrome, Chromium or
		Edge, whichever is installed), user_data_dir ('chromium': a dedicated profile dir kept between runs instead of a
		temp one). keep_alive: Agent.run() leaves the browser running (stop it with `await browser.stop()`).
		cloud_profile_id: a cloud profile id or name (logins persist in it). cloud_proxy_country_code=None turns the
		proxy off. cloud_timeout: minutes (1-240, default 60). live_view: print and open the interactive live view URL
		(anyone with that link can drive the browser). The cloud_* options and live_view raise on a local browser."""
		if kwargs:
			name = next(iter(kwargs))
			hint = UNSUPPORTED.get(name, 'see MIGRATING.md for the 1.0 Browser options.')
			raise TypeError(f'Browser({name}=...) is not supported in browser-use 1.0: {hint}')
		self.kind = _kind(kind, local, use_cloud, cdp_url)
		launches = self.kind == 'chromium' or (self.kind == 'chrome' and profile is not None)
		where = {'cloud': 'Browser() (a cloud browser)', 'chrome': "Browser('chrome') (your open Chrome)"}.get(
			self.kind, f'Browser({self.kind!r})'
		)
		for option, value, ok in (
			('headless', headless is not None, launches),
			('executable_path', executable_path, launches),
			('user_data_dir', user_data_dir, self.kind == 'chromium'),
			('profile', profile is not None, self.kind == 'chrome'),
			('cloud_profile_id', cloud_profile_id, self.kind == 'cloud'),
			('cloud_proxy_country_code', not isinstance(cloud_proxy_country_code, _Default), self.kind == 'cloud'),
			('cloud_timeout', cloud_timeout is not None, self.kind == 'cloud'),
			('live_view', live_view, self.kind == 'cloud'),
		):
			if value and not ok:
				fix = {
					'profile': "Browser('chrome', profile=...) copies one of your Chrome profiles",
					'user_data_dir': "Browser('chromium', user_data_dir=...) keeps a dedicated profile dir",
					'cloud_profile_id': 'cloud profiles are for Browser() (a cloud browser)',
					'cloud_proxy_country_code': 'the proxy is for Browser() (a cloud browser); local browsers use your network',
					'cloud_timeout': 'the timeout is for Browser() (a cloud browser)',
					'live_view': 'live view is for Browser() (a cloud browser)',
				}.get(option, "Browser('chromium', ...) launches a local browser with it")
				raise ValueError(f'{where} does not take {option}=: {fix}')
		if user_data_dir and _local.is_default_user_data_dir(user_data_dir):
			raise ValueError(
				f"user_data_dir={str(user_data_dir)!r} is a browser's default profile dir, and Chrome 136+ refuses "
				"remote debugging on it. Use Browser('chrome', profile='<name>') for a copy of one of its profiles, "
				"Browser('chrome') to attach to the open Chrome, or another dir."
			)
		self.local = self.kind in ('chromium', 'chrome')
		self.cdp_url = cdp_url
		self.use_cloud = self.kind == 'cloud'
		self.chrome_profile, self.headless, self.user_data_dir = profile, headless, user_data_dir
		self.executable_path = executable_path
		self.keep_alive, self.live_view = keep_alive, live_view
		self.profile, self.proxy, self.timeout = cloud_profile_id, cloud_proxy_country_code, cloud_timeout or 60
		self._local: _local.LocalBrowser | None = None  # the Chrome this Browser launched, while it runs
		self.name: str | None = None  # browser-harness daemon this Browser owns; None = the shared default daemon
		self.id: str | None = None  # cloud browser id
		self.live_url: str | None = None  # interactive; anyone with the link can drive the browser
		self.cloud_cdp_url: str | None = None
		self.stopped = False  # the cloud browser is stopped (reset on every start)
		self._env: dict[str, str] | None = None  # set while started; what the REPL worker needs
		self._daemon_env: dict[str, str] = {}  # what our daemon was started with, to start it again if it dies
		# names of the downloads that are a cloud browser's copy of a JSON page it displayed (Agent fills it): not copied
		self.json_page_copies: set[str] = set()
		self._lock = asyncio.Lock()  # one start or stop at a time: they never interleave
		self._creating: concurrent.futures.Future | None = None  # the cloud POST, which outlives a cancelled start
		self._create_deadline = 0.0  # monotonic time after which start() and stop() stop waiting for that POST
		self._stopping: asyncio.Future | None = None  # the stop thread, which outlives a cancelled stop
		# stop() and atexit/SIGTERM never run _stop_now at the same time; reentrant: SIGTERM during atexit cleanup runs
		# the handler on the thread that holds it
		self._stop_mutex = threading.RLock()
		_install_cleanup()  # here too: the main thread, when start() runs on another

	async def start(self) -> dict[str, str]:
		"""Attach a browser-harness daemon (idempotent while started; a daemon that died is started again on the same
		browser); returns the env the REPL worker needs."""
		async with self._lock:
			await self._stopped()
			if self._env is None or not self.name:  # Browser('chrome'): ensuring the shared daemon is idempotent
				self._env = await self._start()
			else:
				await asyncio.to_thread(self._reattach)
			return self._env

	def _reattach(self) -> None:
		"""Our daemon is gone (crash, OOM, kill) or lost its browser connection: start it again on the same browser."""
		from browser_harness import admin

		assert self.name
		try:
			admin.ensure_daemon(name=self.name, env=self._daemon_env)  # a no-op while it answers
		except Exception as e:
			raise RuntimeError(f'The browser is gone: its browser-harness daemon stopped and could not reattach ({e})') from None

	async def _stopped(self) -> None:
		"""Wait for a stop thread a cancelled stop() left running, so a new start never overlaps it."""
		if self._stopping is not None:
			with contextlib.suppress(Exception):
				await asyncio.shield(self._stopping)
			self._stopping = None

	async def _start(self) -> dict[str, str]:
		from browser_harness import admin

		if self.kind == 'chrome' and self.chrome_profile is None:
			await asyncio.to_thread(_check_one_chrome)
			# Bounded: without a wait, browser-harness waits forever on Chrome's "Allow remote debugging?" prompt, and
			# run(timeout=) only starts counting after the browser started.
			try:
				await asyncio.to_thread(admin.ensure_daemon, wait=LOCAL_START_WAIT_S)
			except RuntimeError as e:
				if not str(e).startswith('permission-blocked'):
					raise RuntimeError(
						f"Browser('chrome') could not attach to your Chrome: {e}\nBrowser('chromium') starts a fresh browser "
						'that needs no setup.'
					) from None
				raise RuntimeError(
					f"Browser('chrome'): Chrome did not allow remote debugging within {LOCAL_START_WAIT_S:g}s. Click "
					'Allow on its "Allow remote debugging?" prompt (macOS: or run `browser-harness mac-approve` in another '
					f'shell), then run again. ({e})'
				) from None
			return {}
		if self.use_cloud:
			browser_use_api_key('Browser() (a Browser Use Cloud browser)')  # fail before anything starts
			if ((self.id and not self.stopped) or self._creating is not None) and not await asyncio.to_thread(self._stop_now):
				raise RuntimeError(
					f'Cloud browser {self.id or "(still being created)"} is still running and could not be stopped; retry '
					'browser.stop()'
				)
		_install_cleanup()
		_name_daemon_files()
		self.name = f'bu{uuid.uuid4().hex[:8]}'
		_LIVE.add(self)
		try:
			if self.cdp_url:
				ws = await asyncio.to_thread(_ws_url, self.cdp_url)
			elif self.use_cloud:
				ws = await self._start_cloud()
			else:  # 'chromium', or 'chrome' with a profile: a browser of our own
				self._local = _local.LocalBrowser()
				ws = await asyncio.to_thread(
					self._local.start,
					executable_path=self.executable_path,
					headless=self.headless,
					user_data_dir=self.user_data_dir,
					profile=self.chrome_profile,
				)
			# BU_BROWSER_ID: the daemon knows the cloud browser is its own, so it attaches to its visible tab (a background
			# tab is hidden, and a cloud browser never answers a hidden tab's screenshot) and stops it when it shuts down.
			self._daemon_env = {'BU_CDP_WS': ws, 'BH_TAB_MARKER': '0', **({'BU_BROWSER_ID': self.id} if self.id else {})}
			await asyncio.to_thread(admin.ensure_daemon, name=self.name, env=self._daemon_env)
		except BaseException:
			await self._stop()
			raise
		if self.live_view and self.live_url:
			print(f'Live view: {self.live_url}')
			webbrowser.open(self.live_url, new=2)
		return {'BU_NAME': self.name, **({'BU_REMOTE_BROWSER': '1'} if self.use_cloud else {})}

	async def _start_cloud(self) -> str:
		body = {'proxyCountryCode': self.proxy, 'timeout': self.timeout, 'browserScreenWidth': 1440, 'browserScreenHeight': 900}
		if self.profile:
			body['profileId'] = await asyncio.to_thread(_profile_id, self.profile)
		# The POST records the id from its own thread: a start cancelled mid-request still knows which browser to stop.
		self._creating = _POOL.submit(self._create, body)
		self._create_deadline = time.monotonic() + CREATE_TIMEOUT_S
		try:  # socket timeouts bound each read, not the whole response
			await asyncio.wait_for(asyncio.wrap_future(self._creating), CREATE_TIMEOUT_S)
		except TimeoutError:
			raise RuntimeError(f'Browser Use Cloud did not create a browser within {CREATE_TIMEOUT_S:g}s') from None
		assert self.cloud_cdp_url, 'the cloud API returned no cdpUrl'
		return await asyncio.to_thread(_ws_url, self.cloud_cdp_url)

	def _create(self, body: dict) -> None:
		info = _cloud('/browsers', 'POST', body)
		self.id, self.live_url, self.cloud_cdp_url, self.stopped = info['id'], info.get('liveUrl'), info['cdpUrl'], False
		logger.debug('Started cloud browser %s', self.id)  # never log live_url: it grants control of the browser

	def _stop_now(self) -> bool:
		"""Stop our daemon, then the cloud browser (PATCH stop ends billing and saves the profile).
		False when the cloud browser could not be stopped: it stays owned, so stop() again or process exit retries."""
		with self._stop_mutex:
			self._env = None
			name, self.name = self.name, None
			if name and _shutdown_daemon(name) and self.id and self._daemon_env.get('BU_BROWSER_ID') == self.id:
				self.stopped = True  # the daemon stopped it before it acknowledged
			launched, self._local = self._local, None
			if launched is not None:  # after the daemon: it never reconnects to a Chrome that is going away
				launched.stop()
			creating = self._creating
			if creating is not None:  # a cancelled or timed-out start's POST may still be in flight
				concurrent.futures.wait([creating], timeout=max(0.0, self._create_deadline - time.monotonic()))
				if not creating.done():  # past its deadline: it stays owned, and is stopped the moment it lands
					creating.add_done_callback(self._stop_late)
					logger.warning('A cloud browser is still being created; it will be stopped when it is.')
					return False
			if self.use_cloud and self.id and not self.stopped:
				error: Exception | None = None
				for attempt in range(3):
					try:
						_cloud(f'/browsers/{self.id}', 'PATCH', {'action': 'stop'})
						self.stopped = True
						break
					except Exception as e:
						error = e
						time.sleep(0.5 * (attempt + 1))
				else:
					logger.warning('Could not stop cloud browser %s (it stays registered for retry): %s', self.id, error)
					return False
			self._creating = None
			self.live_url = self.cloud_cdp_url = None  # dead now, and either one drove the browser
			_LIVE.discard(self)
			return True

	def _stop_late(self, creating: concurrent.futures.Future) -> None:
		"""A create that outlived stop() landed (or failed): stop that browser, unless a later stop already did."""
		with self._stop_mutex:
			if self._creating is creating:
				self._stop_now()

	async def stop(self, downloads_dir: str | Path | None = None) -> list[Path]:
		"""Stop the daemon this Browser started, and the cloud browser or local Chrome it started. Never touches the
		Chrome you have open.
		downloads_dir: copy what the cloud browser downloaded there. Returns the local paths."""
		async with self._lock:
			await self._stopped()
			return await self._stop(downloads_dir)

	async def _stop(self, downloads_dir: str | Path | None = None) -> list[Path]:
		files: list[Path] = []
		fetched: set[str] = set()
		browser_id = self.id
		try:
			if downloads_dir and self.use_cloud:  # before the stop too: the API may not list a stopped session's files
				await self._fetch_downloads(downloads_dir, fetched, files, browser_id)
		finally:  # even when cancelled mid-download: the stop always starts, and its thread always finishes
			self._stopping = asyncio.ensure_future(asyncio.to_thread(self._stop_now))
			stopped = await asyncio.shield(self._stopping)
			self._stopping = None
		if downloads_dir and self.use_cloud:  # and after: files that finished while the browser stopped
			await self._fetch_downloads(downloads_dir, fetched, files, browser_id)
		if stopped and self.id == browser_id:
			self.id = None
		return files

	async def _fetch_downloads(self, dest: str | Path, skip: set[str], out: list[Path], browser_id: str | None) -> None:
		try:
			async with asyncio.timeout(DOWNLOADS_TIMEOUT_S):
				deadline = time.monotonic() + DOWNLOADS_TIMEOUT_S  # the transfer threads stop on it too
				await self.download_files(dest, skip, out=out, browser_id=browser_id, deadline=deadline)
		except Exception as e:  # - the result is already delivered
			logger.warning('Could not fetch cloud browser downloads: %s', e or type(e).__name__)

	async def download_files(
		self,
		dest: str | Path,
		skip: set[str] | None = None,
		*,
		out: list[Path] | None = None,
		browser_id: str | None = None,
		deadline: float | None = None,
	) -> list[Path]:
		"""Copy the files the cloud browser downloaded into dest. Returns the local paths.
		skip: remote paths to leave out; each copied path is added to it. A file that fails to copy is logged and
		left out of skip, so a later call retries it. A name already in dest gets a ' (1)' suffix, never overwritten.
		Names in json_page_copies (a JSON page the browser displayed, which the cloud also saves) are left out.
		deadline: time.monotonic() value at which transfers stop (default: DOWNLOADS_TIMEOUT_S from now)."""
		browser_id = browser_id or self.id
		if not browser_id:
			return []
		deadline = time.monotonic() + DOWNLOADS_TIMEOUT_S if deadline is None else deadline
		dest, cursor, skip = Path(dest), None, set() if skip is None else skip
		out = [] if out is None else out
		while True:
			q = f'/browsers/{browser_id}/downloads?includeUrls=true&limit=100' + (f'&cursor={cursor}' if cursor else '')
			page = await asyncio.to_thread(_cloud, q)
			for f in page.get('files', []):
				if f['path'] in skip or re.sub(r' \(\d+\)(?=\.[^.]*$|$)', '', Path(f['path']).name) in self.json_page_copies:
					continue
				name = Path(f['path']).name
				name = name if name not in ('', '.', '..') else 'download'
				try:
					path = await asyncio.to_thread(_download, f['url'], dest, name, deadline)
				except Exception as e:
					logger.warning('Could not copy cloud download %s: %s', f['path'], e)
					continue
				skip.add(f['path'])
				out.append(path)
			cursor = page.get('nextCursor')
			if not page.get('hasMore') or not cursor:
				return out
