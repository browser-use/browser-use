"""Which browser the agent drives.

Browser()                 a Browser Use Cloud browser (default; needs a Browser Use API key)
Browser(local=True)       your local Chrome through the browser-harness daemon
Browser(cdp_url=...)      any running browser with remote debugging

Agent.run() stops the browser at the end unless Browser(keep_alive=True). Cloud browsers are also stopped when the
process exits or gets SIGTERM, and the server stops them after cloud_timeout minutes either way.
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
from urllib.parse import urlparse

from browser_use.auth import browser_use_api_key
from browser_use.config import load_env

logger = logging.getLogger(__name__)
load_env()  # 0.x read .env on import; credentials below resolve from it

CLOUD_API = 'https://api.browser-use.com/api/v4'
UNSUPPORTED = {  # 0.x BrowserSession/BrowserProfile options -> what to do instead
	'headless': 'cloud browsers (Browser()) are always headless. On a server or in Docker, start '
	"chromium --headless=new --remote-debugging-port=9222 yourself and pass Browser(cdp_url='http://127.0.0.1:9222'). "
	'Browser(local=True) needs a desktop Chrome.',
	'user_data_dir': 'use Browser(local=True) to drive your own Chrome profile, or cloud_profile_id for cloud logins.',
	'executable_path': 'Browser(local=True) uses the Chrome browser-harness finds or launches.',
	'allowed_domains': 'domain restrictions are not in 1.0 yet.',
	'prohibited_domains': 'domain restrictions are not in 1.0 yet.',
	'browser_profile': 'BrowserProfile was removed; pass options to Browser(...).',
	'storage_state': 'use cloud_profile_id (cloud) or your Chrome profile (local=True).',
	'proxy': 'use cloud_proxy_country_code on cloud browsers.',
}
LOCAL_START_WAIT_S = 120  # Browser(local=True): Chrome start plus the user clicking Allow on its remote-debugging prompt
DOWNLOADS_TIMEOUT_S = 300  # per download pass; a slow or huge download never holds the stop (and billing) longer
_LIVE: set[Browser] = set()  # browsers this process owns that still need stopping
_POOL = concurrent.futures.ThreadPoolExecutor(thread_name_prefix='browser-use-cloud')  # joined at exit
_handlers_installed = False


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
			' Create a key with v4 browser access at https://cloud.browser-use.com/settings?tab=api-keys and set '
			'BROWSER_USE_API_KEY.'
			if 'missing required scope' in detail
			else ''
		)
		raise RuntimeError(f'Browser Use Cloud {method} {path} failed: HTTP {e.code} {detail}.{hint}') from None


def _profile_id(profile: str) -> str:
	"""A cloud profile id, or the id of the one profile with exactly this name."""
	if re.fullmatch(r'[0-9a-f-]{36}', profile):
		return profile
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


def _shutdown_daemon(name: str) -> None:
	"""Ask our daemon to shut down without waiting for its process to exit.

	browser-harness 0.1.13 daemons exit ~20 s after acknowledging shutdown, and admin.restart_daemon waits 15 s for
	that, which would add 15 s to every Agent.run(). The acknowledged daemon closes its tab and endpoint itself."""
	from browser_harness import _ipc as ipc
	from browser_harness import admin

	try:
		c, token = ipc.connect(name, timeout=5.0)
		try:
			if ipc.request(c, token, {'meta': 'shutdown'}).get('ok'):
				return
		finally:
			c.close()
	except Exception:  # - fall back to the slow, forceful path
		pass
	try:
		admin.restart_daemon(name)
	except Exception:  # - cleanup must not mask the result
		pass


def _stop_all() -> None:
	for browser in list(_LIVE):
		browser._stop_now()


def _on_sigterm(signum, frame) -> None:
	_stop_all()
	signal.signal(signal.SIGTERM, signal.SIG_DFL)
	os.kill(os.getpid(), signal.SIGTERM)


def _install_cleanup() -> None:
	"""atexit + SIGTERM: never leave a billed browser behind. Leaves a SIGTERM handler the app set alone."""
	global _handlers_installed
	if _handlers_installed:
		return
	_handlers_installed = True
	atexit.register(_stop_all)
	if threading.current_thread() is threading.main_thread() and signal.getsignal(signal.SIGTERM) is signal.SIG_DFL:
		signal.signal(signal.SIGTERM, _on_sigterm)


class Browser:
	def __init__(
		self,
		*,
		local: bool = False,
		use_cloud: bool | None = None,
		cdp_url: str | None = None,
		keep_alive: bool = False,
		cloud_profile_id: str | None = None,
		cloud_proxy_country_code: str | None = 'us',
		cloud_timeout: int = 60,
		live_view: bool = False,
		**kwargs,
	):
		"""keep_alive: Agent.run() leaves the browser running (stop it with `await browser.stop()`).
		cloud_profile_id: a cloud profile id or name (logins persist in it). cloud_proxy_country_code=None turns the
		proxy off. cloud_timeout: minutes (1-240). live_view: print and open the interactive live view URL (anyone
		with that link can drive the browser)."""
		if kwargs:
			name = next(iter(kwargs))
			hint = UNSUPPORTED.get(name, 'see MIGRATING.md for the 1.0 Browser options.')
			raise TypeError(f'Browser({name}=...) is not supported in browser-use 1.0: {hint}')
		if sum(map(bool, (local, cdp_url, use_cloud))) > 1:
			raise ValueError('Pass only one of local=True, cdp_url=... or use_cloud=True')
		self.local = local or (use_cloud is False and not cdp_url)  # 0.x Browser(use_cloud=False) meant local
		self.cdp_url = cdp_url
		self.use_cloud = not self.local and not cdp_url
		self.keep_alive, self.live_view = keep_alive, live_view
		self.profile, self.proxy, self.timeout = cloud_profile_id, cloud_proxy_country_code, cloud_timeout
		self.name: str | None = None  # browser-harness daemon this Browser owns; None = the shared default daemon
		self.id: str | None = None  # cloud browser id
		self.live_url: str | None = None  # interactive; anyone with the link can drive the browser
		self.cloud_cdp_url: str | None = None
		self.stopped = False  # the cloud browser is stopped (reset on every start)
		self._env: dict[str, str] | None = None  # set while started; what the REPL worker needs
		self._lock = asyncio.Lock()  # one start or stop at a time: they never interleave
		self._creating: concurrent.futures.Future | None = None  # the cloud POST, which outlives a cancelled start
		self._stopping: asyncio.Future | None = None  # the stop thread, which outlives a cancelled stop
		# stop() and atexit/SIGTERM never run _stop_now at the same time; reentrant: SIGTERM during atexit cleanup runs
		# the handler on the thread that holds it
		self._stop_mutex = threading.RLock()

	@property
	def cdp_host(self) -> str | None:
		"""Hostname of the CDP endpoint (telemetry counts browser vendors by it). None for local Chrome."""
		url = self.cdp_url or self.cloud_cdp_url
		return urlparse(url).hostname if url else None

	async def start(self) -> dict[str, str]:
		"""Attach a browser-harness daemon (idempotent while started); returns the env the REPL worker needs."""
		async with self._lock:
			await self._stopped()
			if self._env is None:
				self._env = await self._start()
			return self._env

	async def _stopped(self) -> None:
		"""Wait for a stop thread a cancelled stop() left running, so a new start never overlaps it."""
		if self._stopping is not None:
			with contextlib.suppress(Exception):
				await asyncio.shield(self._stopping)
			self._stopping = None

	async def _start(self) -> dict[str, str]:
		from browser_harness import admin

		if self.local:
			# Bounded: without a wait, browser-harness waits forever on Chrome's "Allow remote debugging?" prompt, and
			# run(timeout=) only starts counting after the browser started.
			try:
				await asyncio.to_thread(admin.ensure_daemon, wait=LOCAL_START_WAIT_S)
			except RuntimeError as e:
				if not str(e).startswith('permission-blocked'):
					raise
				raise RuntimeError(
					f'Browser(local=True): Chrome did not allow remote debugging within {LOCAL_START_WAIT_S:g}s. Click '
					'Allow on its "Allow remote debugging?" prompt (macOS: or run `browser-harness mac-approve` in another '
					f'shell), then run again. ({e})'
				) from None
			return {}
		if self.use_cloud:
			browser_use_api_key('Browser() (a Browser Use Cloud browser)')  # fail before anything starts
			if self.id and not self.stopped and not await asyncio.to_thread(self._stop_now):
				raise RuntimeError(f'Cloud browser {self.id} is still running and could not be stopped; retry browser.stop()')
		_install_cleanup()
		self.name = f'bu{uuid.uuid4().hex[:8]}'
		_LIVE.add(self)
		try:
			if self.cdp_url:
				ws = await asyncio.to_thread(_ws_url, self.cdp_url)
			else:
				ws = await self._start_cloud()
			await asyncio.to_thread(admin.ensure_daemon, name=self.name, env={'BU_CDP_WS': ws, 'BH_TAB_MARKER': '0'})
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
		await asyncio.wrap_future(self._creating)
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
			if name:
				_shutdown_daemon(name)
			if self._creating is not None:  # a cancelled start's POST may still be in flight
				concurrent.futures.wait([self._creating], timeout=120)
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
			_LIVE.discard(self)
			return True

	async def stop(self, downloads_dir: str | Path | None = None) -> list[Path]:
		"""Stop the daemon this Browser started and its cloud browser. Never touches your local Chrome.
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
				await self.download_files(dest, skip, out=out, browser_id=browser_id)
		except Exception as e:  # - the result is already delivered
			logger.warning('Could not fetch cloud browser downloads: %s', e or type(e).__name__)

	async def download_files(
		self, dest: str | Path, skip: set[str] | None = None, *, out: list[Path] | None = None, browser_id: str | None = None
	) -> list[Path]:
		"""Copy the files the cloud browser downloaded into dest. Returns the local paths.
		skip: remote paths to leave out; each copied path is added to it. A file that fails to copy is logged and
		left out of skip, so a later call retries it."""
		browser_id = browser_id or self.id
		if not browser_id:
			return []
		dest, cursor, skip = Path(dest), None, set() if skip is None else skip
		out = [] if out is None else out
		while True:
			q = f'/browsers/{browser_id}/downloads?includeUrls=true&limit=100' + (f'&cursor={cursor}' if cursor else '')
			page = await asyncio.to_thread(_cloud, q)
			for f in page.get('files', []):
				if f['path'] in skip:
					continue
				path = dest / Path(f['path']).name
				try:
					data = await asyncio.to_thread(lambda u=f['url']: urllib.request.urlopen(u, timeout=120).read())  # noqa: ASYNC210 - in a thread
					path.parent.mkdir(parents=True, exist_ok=True)
					path.write_bytes(data)
				except Exception as e:
					logger.warning('Could not copy cloud download %s: %s', f['path'], e)
					continue
				skip.add(f['path'])
				out.append(path)
			cursor = page.get('nextCursor')
			if not page.get('hasMore') or not cursor:
				return out
