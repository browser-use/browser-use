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
import functools
import json
import logging
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from browser_use.auth import browser_use_api_key, cloud_error_text
from browser_use.browser import local as _local
from browser_use.config import load_env
from browser_use.domains import DomainRules, Guard, disallowed_tabs, sweep
from browser_use.exceptions import BrowserConfigError, removed
from browser_use.utils import file_names, name_download, tls_context, urlopen_keyed

logger = logging.getLogger(__name__)
load_env()  # 0.x read .env on import; credentials below resolve from it

CLOUD_API = 'https://api.browser-use.com/api/v4'
KINDS = ('cloud', 'chromium', 'chrome')
_STORAGE = "cloud_profile_id (cloud), Browser('chrome', profile=...) or Browser('chromium', user_data_dir=...)."
_IN_TASK = (  # measured: a cloud browser answers {} to device metrics and Network's UA override and changes nothing
	'say it in the task: the agent can send Emulation.setUserAgentOverride and, on a local browser, '
	"Emulation.setDeviceMetricsOverride itself; a cloud browser keeps its own viewport (Browser('chromium') for "
	'another one). Headless launches use a 1440x900 window.'
)
_RECORDING = 'result.messages is the transcript; live_view=True shows a cloud browser live.'
_ENGINE = 'it tuned the 0.x DOM engine: delete it.'
REMOVED = {  # 0.x BrowserSession/BrowserProfile options -> the 1.0 alternative (MIGRATING.md "Browser(...)")
	'profile_directory': "Browser('chrome', profile='Profile 1') (a copy of that Chrome profile).",
	'browser_profile': 'pass options to Browser(...).',
	'config': 'pass options to Browser(...).',
	'storage_state': _STORAGE,
	'cookie_whitelist_domains': _STORAGE,
	'proxy': 'cloud_proxy_country_code on cloud browsers.',
	'channel': 'executable_path=... (default: Chrome, Chromium or Edge, whichever is installed).',
	**dict.fromkeys(
		('args', 'ignore_default_args', 'env', 'chromium_sandbox', 'devtools', 'enable_default_extensions', 'is_local'),
		"Browser('chromium') launches Chrome with fixed flags (--no-sandbox only on Linux as root or in a container).",
	),
	'disable_security': 'none: the browser keeps its security features.',
	# 0.x sent them on the cdp_url connect request (e.g. SigV4); the pinned browser-harness daemon cannot send them on its
	# WebSocket handshake, so accepting them would fail there with a bare 401/403
	'headers': 'not yet: the browser daemon cannot send headers on the cdp_url WebSocket handshake. Use a cdp_url that '
	'needs no headers.',
	**dict.fromkeys(
		(
			'window_size',
			'window_width',
			'window_height',
			'window_position',
			'viewport',
			'no_viewport',
			'screen',
			'device_scale_factor',
			'user_agent',
		),
		_IN_TASK,
	),
	**dict.fromkeys(
		('downloads_path', 'accept_downloads', 'auto_download_pdfs'),
		'downloads land in agent.workspace/downloads (cloud: copied there when the browser stops).',
	),
	'permissions': 'say it in the task: the agent can send Browser.grantPermissions.',
	**dict.fromkeys(
		(
			'record_video_dir',
			'record_video_size',
			'record_video_framerate',
			'record_har_path',
			'record_har_content',
			'record_har_mode',
			'traces_dir',
		),
		_RECORDING,
	),
	**dict.fromkeys(
		(
			'dom_highlight_elements',
			'filter_highlight_ids',
			'paint_order_filtering',
			'cross_origin_iframes',
			'max_iframes',
			'max_iframe_depth',
			'minimum_wait_page_load_time',
			'wait_for_network_idle_page_load_time',
			'wait_between_actions',
			'deterministic_rendering',
			'demo_mode',
		),
		_ENGINE,
	),
	**dict.fromkeys(
		('highlight_elements', 'interaction_highlight_color', 'interaction_highlight_duration'),
		'actions are highlighted by default; Agent(highlight_actions=False) turns it off.',
	),
	'cloud_browser': 'Browser() is a cloud browser (the default).',
	'cloud_browser_params': 'cloud_profile_id, cloud_proxy_country_code, cloud_timeout.',
	'profile_id': 'cloud_profile_id.',
	'proxy_country_code': 'cloud_proxy_country_code.',
	'timeout': 'cloud_timeout (minutes).',
	'id': '',
	# 0.1.x and the 0.6 Playwright-era BrowserSession(...) options
	**dict.fromkeys(
		(
			'locale',
			'timezone_id',
			'color_scheme',
			'contrast',
			'forced_colors',
			'reduced_motion',
			'is_mobile',
			'has_touch',
			'extra_http_headers',
			'offline',
			'java_script_enabled',
			'bypass_csp',
			'ignore_https_errors',
			'service_workers',
			'base_url',
		),
		'say it in the task: the agent sends the CDP Emulation, Network or Security command itself.',
	),
	**dict.fromkeys(
		(
			'default_timeout',
			'default_navigation_timeout',
			'slow_mo',
			'strict_selectors',
			'maximum_wait_page_load_time',
			'cached_state',
			'include_dynamic_attributes',
			'viewport_expansion',
		),
		_ENGINE,
	),
	**dict.fromkeys(
		('handle_sigint', 'handle_sigterm', 'handle_sighup'), 'none: a browser 1.0 started is stopped when the process exits.'
	),
	**dict.fromkeys(('record_har_omit_content', 'record_har_url_filter'), _RECORDING),
	'cookies_file': _STORAGE,
	'context': 'pass options to Browser(...).',
	'stealth': 'Browser() (cloud browsers run with stealth settings).',
}
_STOP = 'await browser.stop() (Agent.run() stops it unless keep_alive=True).'
_IN_PYTHON = 'the agent drives pages in Python (browser-harness helpers and raw CDP).'
REMOVED_METHODS = {  # 0.x BrowserSession methods and attributes -> the 1.0 alternative
	'stop_session': _STOP,
	**dict.fromkeys(
		(
			'get_current_page',
			'new_page',
			'navigate_to',
			'navigate',
			'get_tabs',
			'switch_tab',
			'close_tab',
			'take_screenshot',
			'get_browser_state_summary',
			'get_page_html',
			'get_cookies',
			'export_storage_state',
			'cdp_client',
			'event_bus',
		),
		_IN_PYTHON,
	),
	'browser_profile': 'the options are Browser(...) arguments.',
}
CREATE_TIMEOUT_S = 120  # total for the cloud create; start() fails past it, and a browser that lands later is stopped
LOCAL_START_WAIT_S = 120  # Browser('chrome'): Chrome start plus the user clicking Allow on its remote-debugging prompt
DOWNLOADS_TIMEOUT_S = 300  # all download passes before a stop (and one after); a slow download never holds the billing longer
_LIVE: set[Browser] = set()  # browsers this process owns that still need stopping
_POOL = concurrent.futures.ThreadPoolExecutor(thread_name_prefix='browser-use-cloud')  # joined at exit
_atexit_installed = _signals_installed = False


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
		with urlopen_keyed(req, 60) as r:
			return json.loads(r.read() or b'{}')
	except urllib.error.HTTPError as e:
		detail = e.read().decode(errors='replace')
		try:  # {"detail": "..."}: the message itself, without JSON quoting and \u0026 escapes
			detail = str(json.loads(detail)['detail'])
		except (ValueError, TypeError, KeyError):
			pass
		raise RuntimeError(f'Browser Use Cloud {method} {path} failed: {cloud_error_text(e.code, detail)}') from None


def _download(url: str, dest: Path, name: str, deadline: float) -> Path:
	"""Stream url into a new file in dest, never over an existing one ('report (1).csv' next to 'report.csv'). Stops at
	the monotonic deadline, so the thread ends then: run_sync's loop and interpreter exit never wait on a slow transfer.
	A transfer that fails or runs out of time leaves no file."""
	if (left := deadline - time.monotonic()) <= 0:
		raise TimeoutError('download deadline passed')
	with urllib.request.urlopen(url, timeout=min(30.0, left), context=tls_context()) as r:  # the timeout bounds each read
		dest.mkdir(parents=True, exist_ok=True)
		for path in file_names(dest, name):
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


def download_records(lines: list[str]) -> list[dict]:
	"""The records of downloads.jsonl lines; unreadable lines are skipped."""
	records = []
	for line in lines:
		with contextlib.suppress(ValueError):
			if isinstance(r := json.loads(line), dict):
				records.append(r)
	return records


def json_page_copies(log: Path | list[dict]) -> set[str]:
	"""Names, as the cloud lists them, of the downloads in a REPL worker's downloads.jsonl (or its records, of every
	worker that used one cloud browser, in order) that only copy a JSON page the tab displayed: a cloud browser saves
	https://host/data?q=1, shown as a page, as the download https://host/data.json (application/json) or
	https://host/data (+json types), the query dropped, with any cookies the page echoed. Real downloads keep their own
	URL. A name used twice is listed as 'name (1).ext' for the later download, so the real file that shares a copy's
	name is kept, not dropped with it."""
	if isinstance(log, Path):
		try:
			log = download_records(log.read_text(encoding='utf-8').splitlines())
		except OSError:
			return set()
	records = log
	pages = {_no_query(str(r['json_page'])) for r in records if r.get('json_page')}
	taken: set[str] = set()
	copies: set[str] = set()
	for r in records:
		if not r.get('name'):
			continue
		name = str(r['name'])
		listed, stem, suffix = name, Path(name).stem, Path(name).suffix
		for i in range(1, 10_000):
			if listed not in taken:
				break
			listed = f'{stem} ({i}){suffix}'
		taken.add(listed)
		url = str(r.get('url') or '')
		base = re.sub(r'%20\(\d+\)$', '', url.removesuffix('.json'))  # the cloud numbers a repeated copy's URL too
		if '?' not in url and base in pages:
			copies.add(listed)
	return copies


def _no_query(url: str) -> str:
	return urllib.parse.urlsplit(url)._replace(query='', fragment='').geturl()


def _profile_id(profile: str) -> str:
	"""A cloud profile id, or the id of the one profile with exactly this name."""
	if re.fullmatch(r'[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}', profile, re.IGNORECASE):
		return profile.lower()
	items = _cloud(f'/profiles?pageSize=100&query={urllib.parse.quote(profile)}').get('items', [])
	ids = [p['id'] for p in items if p.get('name') == profile]
	if len(ids) != 1:
		raise BrowserConfigError(f'{len(ids)} cloud profiles are named {profile!r}; pass the profile id')
	return ids[0]


def _ws_url(cdp_url: str) -> str:
	if not cdp_url.startswith('http'):
		return cdp_url
	u = urllib.parse.urlsplit(cdp_url)  # a token in the query stays after /json/version
	with urllib.request.urlopen(
		u._replace(path=u.path.rstrip('/') + '/json/version').geturl(), timeout=30, context=tls_context()
	) as r:
		return json.load(r)['webSocketDebuggerUrl']


def _unreachable(cdp_url: str, cause: object) -> RuntimeError:
	"""Browser(cdp_url=...) found no browser: name the endpoint (scheme, host and port only: the path or query may hold a
	token) and what to check. browser-harness's own text points cloud users to start_remote_daemon()."""
	u = urllib.parse.urlsplit(cdp_url)
	cause = re.sub(r' -- remote browser WebSocket connection failed\..*', '', str(cause), flags=re.S).removeprefix('fatal: ')
	return RuntimeError(
		f'Browser(cdp_url=...) could not connect to a browser at {u.scheme}://{u.netloc.rpartition("@")[2]}: {cause}. '
		'Is the browser running with --remote-debugging-port, and is the URL current?'
	)


def _daemon_request(name: str, request: dict, timeout: float = 30) -> dict:
	from browser_harness import _ipc as ipc

	c, token = ipc.connect(name, timeout=5.0)
	try:
		c.settimeout(timeout)
		return ipc.request(c, token, request)
	finally:
		c.close()


def _daemon_cdp(name: str, method: str, session_id: str | None = None, **params) -> dict:
	"""One CDP command through our daemon (browser-harness cdp(), from this process)."""
	r = _daemon_request(name, {'method': method, 'params': params, 'session_id': session_id})
	if 'error' in r:
		raise RuntimeError(f'{method} failed: {r["error"]}')
	return r.get('result') or {}


def _kill_daemon(name: str) -> None:
	"""End our daemon's process with no shutdown request and no exit cleanup, so its cloud browser keeps running."""
	from browser_harness import _ipc as ipc

	pid = ipc.identify(name, timeout=5.0)  # the daemon reports its own pid over its authenticated socket
	if pid is None:
		return
	with contextlib.suppress(OSError):
		os.kill(pid, getattr(signal, 'SIGKILL', signal.SIGTERM))  # Windows: SIGTERM is TerminateProcess, no cleanup either
	deadline = time.monotonic() + 5.0
	while ipc.ping(name, timeout=0.5) and time.monotonic() < deadline:
		time.sleep(0.1)


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


def _check_runtime_dir() -> None:
	"""The daemon's socket (its only lock on POSIX), pid file and our .cloud marker live in browser-harness's runtime
	dir, its log and screenshots in its tmp dir. browser-harness makes a dir it creates 0700 but uses one that already
	exists as is, so another user's /tmp/bh could unlink the socket and serve a fake daemon (every CDP command,
	type_secret's text, the pid _kill_daemon kills). Refuse a dir not owned by this user or writable by others."""
	from browser_harness import _ipc as ipc

	if sys.platform == 'win32':  # TCP loopback with a token there
		return
	for var, path in (('BH_RUNTIME_DIR', ipc._RUNTIME), ('BH_TMP_DIR', ipc._TMP)):
		st = os.stat(path)
		if st.st_uid != os.getuid() or st.st_mode & 0o022:
			other = st.st_uid != os.getuid()  # only its owner can chmod it
			raise RuntimeError(
				f'The browser-harness dir {path} is {"owned by another user" if other else "writable by other users"} '
				f'(mode {st.st_mode & 0o7777:o}), who could take over its daemon. Use a dir only you can write to: '
				f'{"" if other else f"chmod 700 {path}, or "}set {var} to a new path such as ~/.bh.'
			)
		if os.environ.get(var):  # child daemons and workers use this checked path, never a symlink swapped after it
			os.environ[var] = str(path)


def _check_socket_path(name: str) -> None:
	"""The daemon listens on an AF_UNIX socket, whose path the OS caps (macOS 104 bytes, Linux 108). A longer one (a
	long BH_HOME, XDG_CONFIG_HOME or TMPDIR) failed inside the daemon with "AF_UNIX path too long", naming nothing; on
	cloud it read as a stopped remote browser. Raise before anything starts, naming the path and the fix."""
	from browser_harness import _ipc as ipc

	_check_runtime_dir()
	if sys.platform == 'win32':  # TCP loopback there
		return
	path = str(ipc._sock_path(name))
	limit = 103 if sys.platform == 'darwin' else 107
	if len(path.encode()) > limit:
		raise RuntimeError(
			f'The browser-harness socket path is {len(path.encode())} bytes, over the {limit}-byte limit of this OS: '
			f'{path}. Set BH_RUNTIME_DIR to a short directory only you can write to (e.g. ~/.bh), or shorten BH_HOME / XDG_CONFIG_HOME / TMPDIR.'
		)


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
	@classmethod
	def from_system_chrome(cls, *args, **kwargs) -> Browser:
		"""0.x: the Chrome installed on this machine."""
		raise AttributeError(removed('Browser.from_system_chrome()', "Browser('chrome') attaches to the Chrome you have open."))

	@classmethod
	def list_chrome_profiles(cls) -> list[dict[str, str]]:
		"""0.x: the profiles of the Chrome installed on this machine."""
		raise AttributeError(
			removed(
				'Browser.list_chrome_profiles()',
				"Browser('chrome', profile='Work') runs on a copy of that Chrome profile (display or directory name); a name "
				'that matches none raises with the list of your profiles.',
			)
		)

	def __getattr__(self, name: str):
		if name in REMOVED_METHODS:
			raise AttributeError(removed(f'Browser.{name}', REMOVED_METHODS[name]))
		from browser_use.legacy import BROWSER_MEMBERS

		if name in BROWSER_MEMBERS:
			raise AttributeError(removed(f'Browser.{name}', _IN_PYTHON))
		raise AttributeError(f'{type(self).__name__!r} object has no attribute {name!r}')

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
		captcha_solver: bool = True,
		allowed_domains: list[str] | None = None,
		prohibited_domains: list[str] | None = None,
		block_ip_addresses: bool = False,
		**kwargs,
	):
		"""kind: 'cloud' (default), 'chromium' (a fresh local browser; local=True is the same) or 'chrome' (the Chrome
		you have open; with profile='Work', a new Chrome on a temporary copy of that profile).
		headless (launched browsers; default: only without a display), executable_path (default: Chrome, Chromium or
		Edge, whichever is installed), user_data_dir ('chromium': a dedicated profile dir kept between runs instead of a
		temp one). keep_alive: Agent.run() leaves the browser running (stop it with `await browser.stop()`).
		cloud_profile_id: a cloud profile id or name (logins persist in it). cloud_proxy_country_code=None turns the
		proxy off. cloud_timeout: minutes (1-240, default 60). live_view: print and open the interactive live view URL
		(anyone with that link can drive the browser). captcha_solver=False: the cloud browser's automatic captcha solver
		is off from the start. The cloud_* options, live_view and captcha_solver=False raise on a local browser.
		allowed_domains / prohibited_domains (0.x patterns: 'example.com', '*.example.com', 'https://example.com') and
		block_ip_addresses limit where the browser navigates, in every mode (browser_use/domains.py; MIGRATING.md "Domain
		restrictions" says what is and is not blocked)."""
		if kwargs:
			name = next(iter(kwargs))
			if name in REMOVED:
				raise TypeError(removed(f'Browser({name}=...)', REMOVED[name]))
			raise TypeError(
				f'Browser({name}=...) is not a browser-use 1.0 option; MIGRATING.md lists the options and what replaced 0.x ones.'
			)
		self.kind = _kind(kind, local, use_cloud, cdp_url)
		if headless is None and os.environ.get('BROWSER_USE_HEADLESS'):
			logger.warning(
				'BROWSER_USE_HEADLESS is set but browser-use 1.0 does not read it: pass Browser(headless=...) instead '
				'(default: headless only without a display).'
			)
		# Checked here: the API answered a bad country with a 500-character validation dump, an int raised AttributeError,
		# cloud_timeout=0 became 60 and True 1 minute, and captcha_solver='no' counted as on.
		if cloud_proxy_country_code is not None and not (
			isinstance(cloud_proxy_country_code, str) and re.fullmatch(r'[A-Za-z]{2}', cloud_proxy_country_code)
		):
			raise ValueError(
				f"cloud_proxy_country_code must be a two-letter country code such as 'us' or 'de' (or None for no proxy), "
				f'not {cloud_proxy_country_code!r}'
			)
		if cloud_timeout is not None and (
			isinstance(cloud_timeout, bool) or not isinstance(cloud_timeout, int) or not 1 <= cloud_timeout <= 240
		):
			raise ValueError(f'cloud_timeout must be whole minutes from 1 to 240, not {cloud_timeout!r}')
		if not isinstance(captcha_solver, bool):
			raise TypeError(f'captcha_solver must be True or False, not {captcha_solver!r}')
		if os.environ.get('BROWSER_USE_ALLOWED_DOMAINS', '').strip():  # silently ignored, the browser went anywhere
			raise RuntimeError(
				removed(
					'The BROWSER_USE_ALLOWED_DOMAINS environment variable',
					'Browser(allowed_domains=[...]); unset the variable.',
				)
			)
		self.domains = DomainRules.of(allowed_domains, prohibited_domains, block_ip_addresses)
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
			('captcha_solver', captcha_solver is False, self.kind == 'cloud'),
		):
			if value and not ok:
				fix = {
					'profile': "Browser('chrome', profile=...) copies one of your Chrome profiles",
					'user_data_dir': "Browser('chromium', user_data_dir=...) keeps a dedicated profile dir",
					'cloud_profile_id': 'cloud profiles are for Browser() (a cloud browser)',
					'cloud_proxy_country_code': 'the proxy is for Browser() (a cloud browser); local browsers use your network',
					'cloud_timeout': 'the timeout is for Browser() (a cloud browser)',
					'live_view': 'live view is for Browser() (a cloud browser)',
					'captcha_solver': 'only Browser() (a cloud browser) has a captcha solver to turn off',
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
		self.keep_alive, self.live_view, self.captcha_solver = keep_alive, live_view, captcha_solver
		proxy = cloud_proxy_country_code.lower() if cloud_proxy_country_code else None  # the API takes 'de', rejects 'DE'
		self.profile, self.proxy, self.timeout = cloud_profile_id, proxy, cloud_timeout or 60
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
		# download records of every Agent that used this cloud session, in run order: the cloud numbers a repeated name
		# ('cookies (1).json') across the whole session, not per workspace
		self._download_records: list[dict] = []
		self._download_lines: dict[Path, int] = {}  # downloads.jsonl -> lines already read
		self._fetched: set[str] = set()  # remote paths of this cloud session already copied to a workspace
		self._lock = asyncio.Lock()  # one start or stop at a time: they never interleave
		self._creating: concurrent.futures.Future | None = None  # the cloud POST, which outlives a cancelled start
		self._create_deadline = 0.0  # monotonic time after which start() and stop() stop waiting for that POST
		self._stopping: asyncio.Future | None = None  # the stop thread, which outlives a cancelled stop
		# stop() and atexit/SIGTERM never run _stop_now at the same time; reentrant: SIGTERM during atexit cleanup runs
		# the handler on the thread that holds it
		self._stop_mutex = threading.RLock()
		self._guard: Guard | None = None  # domain restrictions' browser-level block, while started
		self._watchdog: subprocess.Popen | None = None  # cloud or cdp_url: cleans up if this process dies uncleanly
		# tab -> the disallowed URL it showed when this Browser first started (yours, in Browser('chrome')): sweep() leaves
		# it alone while it still shows that URL. Taken once: a follow-up run or a reattach must not exempt a tab the
		# agent left on a disallowed page.
		self._user_tabs: dict[str, str] | None = None
		# Browser('chrome') with domain restrictions: the tabs the agent created or attached to (switch_tab; the worker
		# appends their ids to _tabs_file), is attached to at the end of a cell, or opened popups from. The sweep
		# touches only these.
		self._agent_tabs: set[str] = set()
		self._tabs_file: str | None = None
		self._user: object | None = None  # the Agent whose run() uses this Browser now (one at a time)
		# the tab the last Agent run left attached (remember_tab): a daemon started again between runs attaches it again
		self._agent_tab: str | None = None
		# where stop() copies a cloud browser's downloads when not told: the workspace/downloads of the last Agent that
		# ran on it (keep_alive leaves the stop, and so the copy, to a later browser.stop())
		self._downloads_dir: Path | None = None
		self._downloads_session: str | None = None  # the browser-level CDP session that set where downloads go
		_install_cleanup()  # here too: the main thread, when start() runs on another

	async def start(self) -> dict[str, str]:
		"""Attach a browser-harness daemon (idempotent while started; a daemon that died is started again on the same
		browser); returns the env the REPL worker needs."""
		async with self._lock:
			return await self._start_locked(replace_gone_cloud=True)

	async def _start_locked(self, replace_gone_cloud: bool = False) -> dict[str, str]:
		"""start() under self._lock. replace_gone_cloud: a kept-alive cloud browser that ended between runs (cloud_timeout,
		a stop from the dashboard) is replaced by a new one, as a dead local Chrome is; mid-run (reattach) it raises."""
		await self._stopped()
		if self._env is None or not self.name:  # Browser('chrome'): ensuring the shared daemon is idempotent
			env = await self._start()
			if self.domains:  # the REPL helpers refuse disallowed URLs (worker.py)
				if self._user_tabs is None and self._attached():  # a browser of our own or cdp_url: every tab is swept
					self._user_tabs = await asyncio.to_thread(self._disallowed_tabs)
				env['BU_DOMAINS'] = self.domains.to_json()
				if self._attached():
					if self._tabs_file is None:
						fd, self._tabs_file = tempfile.mkstemp(prefix='browser-use-tabs-')
						os.close(fd)
					env['BU_TABS_FILE'] = self._tabs_file
			self._env = env
		elif self._local is not None and self._local.proc is not None and self._local.proc.poll() is not None:
			await self._stop()  # the Chrome this Browser launched died (crash, OOM, kill): launch a new one
			return await self._start_locked()
		else:
			try:
				await asyncio.to_thread(self._reattach)
			except RuntimeError:
				if not (replace_gone_cloud and self.use_cloud):
					raise
				logger.warning(f'The cloud browser {(self.id or "")[:8]} ended since the last run; starting a new one')
				await self._stop()  # every later start() raised until the caller ran browser.stop()
				return await self._start_locked()
		if self._local is not None and self._downloads_dir:  # Chrome forgets it when the connection that set it closes
			await asyncio.to_thread(self._send_downloads, self._downloads_dir)
		return self._env

	def _close_launch_tab(self) -> None:
		"""Our named daemon works in a tab of its own, so the about:blank tab Chrome launched with is left over."""
		try:
			own = _daemon_request(self._daemon_name(), {'meta': 'current_tab'})['targetId']
			closed = set()
			for t in self._cdp()('Target.getTargets')['targetInfos']:
				if t['type'] == 'page' and t['url'] == 'about:blank' and t['targetId'] != own:
					self._cdp()('Target.closeTarget', targetId=t['targetId'])
					closed.add(t['targetId'])
			# Linux Chrome still lists a tab for a moment after closeTarget answered: list_tabs() right after start() gave 2.
			deadline = time.monotonic() + 2
			while closed and time.monotonic() < deadline:
				closed &= {t['targetId'] for t in self._cdp()('Target.getTargets')['targetInfos']}
				if closed:
					time.sleep(0.02)
		except Exception as e:  # - a stray blank tab is harmless
			logger.debug('Could not close the launch tab: %s', e)

	def _send_downloads(self, downloads: Path) -> None:
		"""Downloads of a Chrome this Browser launched land in downloads (workspace/downloads), not the real ~/Downloads.
		Saved as <guid> and renamed once finished (utils.name_download): with 'allow' a repeated name overwrote the
		earlier file. The REPL worker renames what finishes during a run, _finish_downloads what finishes after it."""
		downloads.mkdir(parents=True, exist_ok=True)
		cdp, params = self._cdp(), {'behavior': 'allowAndName', 'downloadPath': str(downloads), 'eventsEnabled': True}
		try:
			# On a browser session: the daemon sends other calls on its tab's session, and Chrome then reports
			# Browser.download* only for that tab, so a download in the agent's second new_tab() stayed 'inProgress'
			# and stop() waited DOWNLOADS_TIMEOUT_S. One session per daemon: each one would repeat every event.
			with contextlib.suppress(RuntimeError):  # - the daemon that attached it is gone, and the setting with it
				if self._downloads_session:
					cdp('Browser.setDownloadBehavior', self._downloads_session, **params)
					return
			self._downloads_session = cdp('Target.attachToBrowserTarget')['sessionId']
			cdp('Browser.setDownloadBehavior', self._downloads_session, **params)
		except Exception as e:  # - downloads then go where Chrome puts them
			logger.warning('Could not send downloads to %s: %s', downloads, e)

	async def reattach(self) -> dict[str, str]:
		"""For the REPL, after a cell lost the daemon: start it again on the same browser (start()). Raises when this
		Browser was stopped meanwhile (browser.stop(), or another Agent's run on it): start() would create a new browser,
		billed, with none of the tabs or logins the agent was using."""
		async with self._lock:  # checked under the lock: a stop() that holds it clears _env before this looks
			await self._stopped()
			if self._env is None:
				raise RuntimeError(
					'The browser was stopped while the agent ran (browser.stop(), or another Agent using the same Browser)'
				)
			return await self._start_locked()

	def _reattach(self) -> None:
		"""Our daemon is gone (crash, OOM, kill) or lost its browser connection: start it again on the same browser.
		A daemon that answers but whose browser connection is stuck is killed, never shut down: a cloud daemon's shutdown
		(and browser-harness's own stale-daemon handling) stops the cloud browser this reattaches to."""
		from browser_harness import admin

		from browser_use.harness_cloud import daemon_healthy

		assert self.name
		if admin.daemon_alive(self.name):
			if daemon_healthy(self.name):
				return
			_kill_daemon(self.name)
		try:
			self._ensure_daemon()
		except Exception as e:
			raise RuntimeError(f'The browser is gone: its browser-harness daemon stopped and could not reattach: {e}') from None
		self._attach_agent_tab()

	def remember_tab(self) -> None:
		"""At the end of an Agent run on a keep_alive Browser: the tab the agent works in, for a daemon started again."""
		if self.name:
			with contextlib.suppress(Exception):  # the daemon is gone: the last tab known stays
				self._agent_tab = _daemon_request(self.name, {'meta': 'current_tab'}, timeout=5)['targetId']

	def _attach_agent_tab(self) -> None:
		"""A daemon started again attaches a new blank tab of its own, so the next run saw about:blank, the agent's page
		and form state out of reach. Attach the agent's tab instead and close that blank one."""
		if not (self.name and self._agent_tab):
			return
		try:
			own = _daemon_request(self.name, {'meta': 'current_tab'}, timeout=5)
			if own.get('targetId') in (None, self._agent_tab):
				return
			sid = _daemon_cdp(self.name, 'Target.attachToTarget', targetId=self._agent_tab, flatten=True)['sessionId']
			_daemon_request(self.name, {'meta': 'set_session', 'session_id': sid, 'target_id': self._agent_tab})
			if own.get('url') == 'about:blank':
				_daemon_cdp(self.name, 'Target.closeTarget', targetId=own['targetId'])
				# Chrome closes it after it answers: the run's first list_tabs() still showed it (busy machine)
				deadline = time.monotonic() + 3
				while time.monotonic() < deadline and any(
					t['targetId'] == own['targetId'] for t in _daemon_cdp(self.name, 'Target.getTargets')['targetInfos']
				):
					time.sleep(0.05)
		except Exception as e:  # - the tab is gone (closed): the run starts where the daemon is
			logger.debug('Could not attach the agent tab again: %s', e)

	def _ensure_daemon(self) -> None:
		"""Start our daemon on self._daemon_env. browser-harness blames any BU_CDP_WS failure on a remote browser and
		suggests start_remote_daemon(); for the Chrome this Browser launched, say that it exited instead."""
		from browser_harness import admin

		try:
			admin.ensure_daemon(name=self.name, env=self._daemon_env)
		except Exception:
			proc = self._local and self._local.proc
			if proc and proc.poll() is not None:
				raise RuntimeError(
					f'the local browser exited (code {proc.returncode}): it crashed, was killed or closed'
				) from None
			if self.cdp_url and 'CDP WS handshake failed' in str(sys.exc_info()[1]):
				raise _unreachable(self.cdp_url, sys.exc_info()[1]) from None
			raise

	async def _stopped(self) -> None:
		"""Wait for a stop thread a cancelled stop() left running, so a new start never overlaps it."""
		if self._stopping is not None:
			with contextlib.suppress(Exception):
				await asyncio.shield(self._stopping)
			self._stopping = None

	async def _start(self) -> dict[str, str]:
		from browser_harness import admin

		if self.kind == 'chrome' and self.chrome_profile is None:
			_check_runtime_dir()  # before anything connects to the default daemon's socket in it
			await asyncio.to_thread(_check_one_chrome)
			# Bounded: without a wait, browser-harness waits forever on Chrome's "Allow remote debugging?" prompt, and
			# run(timeout=) only starts counting after the browser started. BH_TAB_MARKER=0: browser-harness's default
			# prefixes every loaded page's document.title with a horse, which the agent then reads back as the title.
			try:
				await asyncio.to_thread(_local.require_debug_port_unless_attached)  # the default daemon, as below
				await asyncio.to_thread(admin.ensure_daemon, wait=LOCAL_START_WAIT_S, env={'BH_TAB_MARKER': '0'})
			except RuntimeError as e:
				if not str(e).startswith('permission-blocked'):
					raise RuntimeError(
						f"Browser('chrome') could not attach to your Chrome: {e}\nBrowser('chromium') starts a fresh browser "
						'that needs no setup.'
					) from None
				raise RuntimeError(
					f"Browser('chrome'): Chrome did not allow remote debugging within {LOCAL_START_WAIT_S:g}s. Click "
					'Allow on its "Allow remote debugging?" prompt (macOS: or run `browser-harness mac-approve` in another '
					f'shell), then run again. Detail: {e}'
				) from None
			# A daemon that was already running (started by `browser-use`, the MCP server, browser-harness itself or an
			# older browser-use) keeps its own BH_TAB_MARKER: the worker strips the horse it adds to the agent's tabs.
			return {'BU_SHARED_DAEMON': '1'}
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
		try:
			_check_socket_path(self.name)  # before a cloud browser is created and billed
		except RuntimeError:
			self.name = None
			raise
		_LIVE.add(self)
		try:
			if self.cdp_url:
				try:
					ws = await asyncio.to_thread(_ws_url, self.cdp_url)
				except (OSError, ValueError, KeyError) as e:  # URLError is an OSError
					raise _unreachable(self.cdp_url, getattr(e, 'reason', None) or e) from None
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
			await asyncio.to_thread(self._ensure_daemon)
			# this process dying uncleanly (SIGKILL, OOM) left the daemon, and Chrome or a cloud browser billing until its timeout
			from browser_harness import _ipc as ipc

			daemon_pid = await asyncio.to_thread(ipc.identify, self.name, 5.0)
			if self._local is not None:
				self._local.watch(self.name, daemon_pid)
				await asyncio.to_thread(self._close_launch_tab)
			else:
				self._watchdog = _local.start_watchdog(0, '', self.name, daemon_pid, (self.id or '') if self.use_cloud else '')
			if self.domains:
				self._guard = Guard(ws, self.domains)
				await asyncio.to_thread(self._guard.start)
			if self.use_cloud and not self.captcha_solver:
				await asyncio.to_thread(_daemon_cdp, self.name, 'BrowserUse.setCaptchaSolverEnabled', enabled=False)
		except BaseException:
			await self._stop()
			raise
		if self.live_view and self.live_url:
			print(f'Live view: {self.live_url}')
			webbrowser.open(self.live_url, new=2)
		# BU_OWN_BROWSER: not the user's Chrome, so the agent's tab may be the visible one (repl/worker.py)
		env = {'BU_NAME': self.name, 'BU_OWN_BROWSER': '1', **({'BU_REMOTE_BROWSER': '1'} if self.use_cloud else {})}
		if self.use_cloud and not self.captcha_solver:
			env['BU_CAPTCHA_SOLVER'] = 'off'  # solve_captcha() must not turn it back on (repl/captcha.py)
		return env

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
		# Never log live_url or the whole id: each grants control of the browser (the id is its CDP hostname)
		proxy = f'{self.proxy} proxy' if self.proxy else 'no proxy'
		logger.info(
			f"Browser Use cloud browser {info['id'][:8]} ({proxy}, billed until it stops). Browser('chromium') runs a local one."
		)

	def _daemon_name(self) -> str:
		return self.name or os.environ.get('BU_NAME') or 'default'  # Browser('chrome'): the shared daemon

	def _cdp(self) -> functools.partial[dict]:
		return functools.partial(_daemon_cdp, self._daemon_name())

	def _attached(self) -> bool:
		"""Browser('chrome') on your open Chrome: tabs in it are yours too."""
		return self.kind == 'chrome' and self.chrome_profile is None

	def _touched_tabs(self) -> set[str]:
		if self._tabs_file:
			with contextlib.suppress(OSError):
				self._agent_tabs.update(Path(self._tabs_file).read_text().split())
		with contextlib.suppress(Exception):  # - no attached tab yet
			self._agent_tabs.add(str(_daemon_request(self._daemon_name(), {'meta': 'current_tab'})['targetId']))
		return self._agent_tabs

	def _sweep(self) -> list[str]:
		only = self._touched_tabs() if self._attached() else None
		return sweep(self._cdp(), self.domains, self._user_tabs or {}, only)

	def _disallowed_tabs(self) -> dict[str, str]:
		return {target: url for target, (url, _) in disallowed_tabs(self._cdp(), self.domains).items()}

	async def after_cell(self) -> tuple[list[str], int]:
		"""Domain restrictions after each REPL cell: what the browser blocked since the last cell, then every tab that
		still shows a disallowed page goes to about:blank. Returns (notices for the model, blocks)."""
		if not self.domains:
			return [], 0
		notices, blocks = self._guard.take() if self._guard else ([], 0)
		try:
			reset = await asyncio.to_thread(self._sweep)
		except Exception as e:  # - the daemon is gone; the next cell reports and reattaches it
			logger.debug('domain sweep failed: %s', e)
			reset = []
		return notices + reset, blocks + len(reset)

	def _stop_now(self) -> bool:
		"""Stop our daemon, then the cloud browser (PATCH stop ends billing and saves the profile).
		False when the cloud browser could not be stopped: it stays owned, so stop() again or process exit retries."""
		with self._stop_mutex:
			self._env = None
			watchdog, self._watchdog = self._watchdog, None
			if watchdog is not None:  # first: a normal stop must not race it
				with contextlib.suppress(OSError):
					watchdog.kill()
				with contextlib.suppress(Exception):  # reaped, as LocalBrowser.stop does: else a zombie until GC
					watchdog.wait(5)
			guard, self._guard = self._guard, None
			if guard is not None:
				guard.close()
			tabs_file, self._tabs_file = self._tabs_file, None
			if tabs_file:
				with contextlib.suppress(OSError):
					self._agent_tabs.update(Path(tabs_file).read_text().split())  # a follow-up run's sweep still knows them
				with contextlib.suppress(OSError):
					os.unlink(tabs_file)
			name, self.name, self._agent_tab = self.name, None, None
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
		downloads_dir: copy what the cloud browser downloaded there (default: the workspace/downloads of the last Agent
		that ran on this Browser). Returns the local paths."""
		async with self._lock:
			await self._stopped()
			return await self._stop(downloads_dir or self._downloads_dir)

	async def kill(self) -> list[Path]:
		"""0.x: the last line of a keep_alive script, after the runs. It cannot fail before a browser starts, so it
		stops the browser as stop() does (raising left a keep_alive cloud browser billed until the process exited)."""
		return await self.stop()

	close = kill  # 0.x BrowserSession.close()

	async def _stop(self, downloads_dir: str | Path | None = None) -> list[Path]:
		files: list[Path] = []
		fetched = self._fetched
		browser_id = self.id
		try:
			ending = self.name and (self.use_cloud or self._local is not None)  # a browser this stop ends
			# no wait when cancelled (task.cancel(), Ctrl-C: the stop must be prompt, a cloud browser bills) or when the
			# Chrome this Browser launched died (its downloads never send progress again)
			cancelled = (task := asyncio.current_task()) is not None and task.cancelling() > 0
			dead = self._local is not None and self._local.proc is not None and self._local.proc.poll() is not None
			completed = await self._finish_downloads() if ending and not cancelled and not dead else 0
			# before the stop too: the API may not list a stopped session's files. The cloud lists a download about a
			# second after it completes: retry until it lists them all, within one DOWNLOADS_TIMEOUT_S for all passes (a
			# copy that kept failing, each pass with a deadline of its own, held the stop and the billing ~15 min)
			if downloads_dir and self.use_cloud:
				deadline = time.monotonic() + DOWNLOADS_TIMEOUT_S
				for _ in range(30):
					await self._fetch_downloads(downloads_dir, fetched, files, browser_id, deadline)
					if len(fetched) >= completed or time.monotonic() >= deadline:
						break
					await asyncio.sleep(min(1, max(deadline - time.monotonic(), 0)))
		finally:  # even when cancelled mid-download: the stop always starts, and its thread always finishes
			self._stopping = asyncio.ensure_future(asyncio.to_thread(self._stop_now))
			stopped = await asyncio.shield(self._stopping)
			self._stopping = None
		if downloads_dir and self.use_cloud:  # and after: files that finished while the browser stopped
			await self._fetch_downloads(downloads_dir, fetched, files, browser_id)
		if stopped and self.id == browser_id:
			self.id = None
			self._download_records, self.json_page_copies, self._fetched = [], set(), set()  # the next session starts anew
		return files

	async def _finish_downloads(self) -> int:
		"""Wait, up to DOWNLOADS_TIMEOUT_S, for downloads still running, which the stop would lose (cloud: never listed;
		local: a .crdownload). Their state: the REPL workers' logs and the daemon's download progress events, both
		read on every poll. Returns how many downloads of the session completed."""
		state: dict[str, str | None] = {}
		names: dict[str, str | None] = {}
		logged: set[str] = set()  # downloads a worker announced: it knows their names and renames them itself
		read, deadline, waiting = 0, time.monotonic() + DOWNLOADS_TIMEOUT_S, False
		try:
			while True:
				r = await asyncio.to_thread(_daemon_request, self._daemon_name(), {'meta': 'drain_events'})
				# then the workers' logs: what they logged after their run's note_downloads. A keep_alive Agent's worker
				# still runs and drains the daemon's events, so it, not the read above, may take a download's events (read
				# after it: an event the worker took before that read is in its log by now)
				for log in list(self._download_lines):
					self.note_downloads(log)
				finished = []  # downloads a worker saw complete
				for rec in self._download_records[read:]:
					if rec.get('guid'):
						logged.add(rec['guid'])
						names.setdefault(rec['guid'], rec.get('name'))
						state.setdefault(rec['guid'], 'inProgress')
					if rec.get('done'):
						state[rec['done']] = rec.get('state')
						if rec.get('state') == 'completed':
							finished.append(rec['done'])
				read = len(self._download_records)
				for e in r.get('events', []):
					method, p = e.get('method'), e.get('params') or {}
					if not p.get('guid'):
						continue
					if method in ('Browser.downloadWillBegin', 'Page.downloadWillBegin'):  # began after the worker closed
						names.setdefault(p['guid'], p.get('suggestedFilename'))
						state.setdefault(p['guid'], 'inProgress')  # its first downloadProgress may come in a later drain
					# either event (a tab the daemon attached sends only Page's); a finished download never runs again
					progress = method in ('Browser.downloadProgress', 'Page.downloadProgress')
					if progress and state.get(p['guid']) in (None, 'inProgress'):
						state[p['guid']] = p.get('state')
					# finished after the worker closed: only this read saw the event, so no one else renames it
					if progress and p.get('state') == 'completed':
						path = Path(p['filePath']) if p.get('filePath') else (self._downloads_dir or Path()) / p['guid']
						if self._local is not None and path.name == p['guid']:  # a cloud browser's files are remote
							name_download(path, names.get(p['guid']))
				for guid in finished:  # a worker that never saw its downloadWillBegin (this read took it) cannot name it
					if guid not in logged and self._local is not None:
						name_download((self._downloads_dir or Path()) / guid, names.get(guid))
				if not (running := sum(s == 'inProgress' for s in state.values())):
					break
				if time.monotonic() > deadline:
					logger.warning('Stopping the browser with %d download(s) unfinished: they are lost', running)
					break
				if not waiting:
					logger.info('Waiting for %d download(s) to finish before stopping the browser', running)
				waiting = True
				await asyncio.sleep(1)
		except Exception as e:  # - the daemon is gone, and its downloads with it
			logger.debug('Could not wait for downloads: %s', e)
		return sum(s == 'completed' for s in state.values())

	def note_downloads(self, log: Path) -> None:
		"""Add what a run's REPL worker logged since the last call (log: its workspace's downloads.jsonl) and update
		json_page_copies. Agents use a Browser one at a time, so appending keeps the session's order."""
		try:  # complete lines only: downloads() reads it while the worker may be writing one
			lines = log.read_text(encoding='utf-8').split('\n')[:-1]
		except OSError:  # none yet: _finish_downloads still reads what the worker of a keep_alive run logs later
			self._download_lines.setdefault(log, 0)
			return
		seen, self._download_lines[log] = self._download_lines.get(log, 0), len(lines)
		self._download_records += download_records(lines[seen:])
		self.json_page_copies |= json_page_copies(self._download_records)

	async def list_downloads(self) -> list[dict]:
		"""The files the browser finished downloading so far, [{'name', 'size'}]: the REPL's downloads(). A cloud browser:
		as the API lists them, about a second after each completes (names in json_page_copies left out). A Chrome this
		Browser launched: its downloads dir (workspace/downloads), without Chrome's unfinished .crdownload files."""
		if not self.use_cloud:
			d = self._downloads_dir
			files = sorted(p for p in d.iterdir() if p.is_file() and p.suffix != '.crdownload') if d and d.is_dir() else []
			return [{'name': p.name, 'size': p.stat().st_size} for p in files]
		out, cursor = [], None
		while self.id:
			q = f'/browsers/{self.id}/downloads?limit=100' + (f'&cursor={cursor}' if cursor else '')
			page = await asyncio.to_thread(_cloud, q)
			for f in page.get('files', []):
				if (name := Path(f['path']).name) not in self.json_page_copies:
					out.append({'name': name, 'size': f.get('size')})
			cursor = page.get('nextCursor')
			if not page.get('hasMore') or not cursor:
				break
		return out

	async def _fetch_downloads(
		self, dest: str | Path, skip: set[str], out: list[Path], browser_id: str | None, deadline: float | None = None
	) -> None:
		deadline = deadline or time.monotonic() + DOWNLOADS_TIMEOUT_S  # the transfer threads stop on it too
		try:
			async with asyncio.timeout(max(deadline - time.monotonic(), 0)):
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
				if f['path'] in skip or Path(f['path']).name in self.json_page_copies:
					skip.add(f['path'])  # listed, so stop() stops waiting for it
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


if not TYPE_CHECKING:  # pyright would accept any name imported from here
	from browser_use.legacy import removed_names

	__getattr__ = removed_names(__name__)  # 0.1.x: from browser_use.browser.browser import BrowserConfig (removed error)
