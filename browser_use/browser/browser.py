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

logger = logging.getLogger(__name__)

CLOUD_API = 'https://api.browser-use.com/api/v4'
UNSUPPORTED = {  # 0.x BrowserSession/BrowserProfile options -> what to do instead
	'headless': 'Browser(local=True) attaches to your running Chrome; cloud browsers are always headless.',
	'user_data_dir': 'use Browser(local=True) to drive your own Chrome profile, or cloud_profile_id for cloud logins.',
	'executable_path': 'Browser(local=True) uses the Chrome browser-harness finds or launches.',
	'allowed_domains': 'domain restrictions are not in 1.0 yet.',
	'prohibited_domains': 'domain restrictions are not in 1.0 yet.',
	'browser_profile': 'BrowserProfile was removed; pass options to Browser(...).',
	'storage_state': 'use cloud_profile_id (cloud) or your Chrome profile (local=True).',
	'proxy': 'use cloud_proxy_country_code on cloud browsers.',
}
_LIVE: set[Browser] = set()  # browsers this process owns that still need stopping
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

	@property
	def cdp_host(self) -> str | None:
		"""Hostname of the CDP endpoint (telemetry counts browser vendors by it). None for local Chrome."""
		url = self.cdp_url or self.cloud_cdp_url
		return urlparse(url).hostname if url else None

	async def start(self) -> dict[str, str]:
		"""Attach a browser-harness daemon (idempotent while started); returns the env the REPL worker needs."""
		if self._env is not None:
			return self._env
		from browser_harness import admin

		if self.local:
			await asyncio.to_thread(admin.ensure_daemon)
			self._env = {}
			return self._env
		if self.use_cloud:
			browser_use_api_key('Browser() (a Browser Use Cloud browser)')  # fail before anything starts
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
			await self.stop()
			raise
		if self.live_view and self.live_url:
			print(f'Live view: {self.live_url}')
			webbrowser.open(self.live_url, new=2)
		self._env = {'BU_NAME': self.name, **({'BU_REMOTE_BROWSER': '1'} if self.use_cloud else {})}
		return self._env

	async def _start_cloud(self) -> str:
		body = {'proxyCountryCode': self.proxy, 'timeout': self.timeout, 'browserScreenWidth': 1440, 'browserScreenHeight': 900}
		if self.profile:
			body['profileId'] = await asyncio.to_thread(_profile_id, self.profile)
		info = await asyncio.to_thread(_cloud, '/browsers', 'POST', body)
		self.id, self.live_url, self.cloud_cdp_url, self.stopped = info['id'], info.get('liveUrl'), info['cdpUrl'], False
		logger.debug('Started cloud browser %s', self.id)  # never log live_url: it grants control of the browser
		return await asyncio.to_thread(_ws_url, info['cdpUrl'])

	def _stop_now(self) -> None:
		"""Stop our daemon, then the cloud browser (PATCH stop ends billing and saves the profile)."""
		self._env = None
		name, self.name = self.name, None
		if name:
			_shutdown_daemon(name)
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
				logger.warning('Could not stop cloud browser %s: %s', self.id, error)
		_LIVE.discard(self)

	async def stop(self, downloads_dir: str | Path | None = None) -> list[Path]:
		"""Stop the daemon this Browser started and its cloud browser. Never touches your local Chrome.
		downloads_dir: copy what the cloud browser downloaded there. Returns the local paths."""
		await asyncio.to_thread(self._stop_now)
		files: list[Path] = []
		if downloads_dir and self.id:
			try:
				files = await self.download_files(downloads_dir)
			except Exception as e:  # - the result is already delivered
				logger.warning('Could not fetch cloud browser downloads: %s', e)
		self.id = None
		return files

	async def download_files(self, dest: str | Path) -> list[Path]:
		"""Copy the files the cloud browser downloaded into dest. Returns the local paths."""
		if not self.id:
			return []
		dest, out, cursor = Path(dest), [], None
		while True:
			q = f'/browsers/{self.id}/downloads?includeUrls=true&limit=100' + (f'&cursor={cursor}' if cursor else '')
			page = await asyncio.to_thread(_cloud, q)
			for f in page.get('files', []):
				path = dest / Path(f['path']).name
				path.parent.mkdir(parents=True, exist_ok=True)
				data = await asyncio.to_thread(lambda u=f['url']: urllib.request.urlopen(u, timeout=120).read())  # noqa: ASYNC210 - in a thread
				path.write_bytes(data)
				out.append(path)
			cursor = page.get('nextCursor')
			if not page.get('hasMore') or not cursor:
				return out
