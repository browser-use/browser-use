"""Persistent Python REPL for one agent. Runs as a child process so a hung cell can be killed.

Namespace = browser-harness helpers + screenshot/show_image/checkpoint/type_secret/solve_captcha (+ bu in ultrafast mode,
see ax.py; + search when web search is on; + downloads for a cloud browser or a Chrome the Browser launched).
Protocol: connect to 127.0.0.1:BU_REPL_PORT, send BU_REPL_TOKEN, read one init line ({"secrets": [[name, value, domain|null], ...],
"search": bool, "downloads": bool}), then one JSON line per message. search() and downloads() send {"type": "search" |
"downloads", "args": {...}} mid-cell and read the parent's one-line answer. Cell stdout/stderr (including subprocesses) go to a per-cell file, so a killed cell still leaves its
partial output on disk.
"""

import ast
import asyncio
import atexit
import base64
import codecs
import contextlib
import functools
import gzip
import hashlib
import hmac
import inspect
import io
import json
import os
import pprint
import re
import signal
import socket
import struct
import sys
import sysconfig
import threading
import time
import traceback
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

from browser_use import ax
from browser_use.domains import DomainRules
from browser_use.exceptions import BrowserConnectionLost
from browser_use.remote_upload import set_files, uploader
from browser_use.repl.captcha import Captcha, EventPump
from browser_use.repl.capture import SCREENSHOT_TIMEOUT_S, capture
from browser_use.repl.highlight import Highlighter
from browser_use.repl.network_idle import wait_for_network_idle
from browser_use.repl.page_info import install as install_page_info
from browser_use.repl.session import (
	MAX_OUTPUT_CHARS,
	SECRET_PLACEHOLDER,
	clip,
	domain_matches,
	redact,
	redact_forms,
	secret_forms,
)
from browser_use.telemetry.stats import error_class, host
from browser_use.utils import TLSHandler, install_tls_opener, name_download

MAX_IMAGES_PER_CELL = 4
MAX_IMAGE_SIDE = 2048  # full-page captures exceeded OpenAI's 30k-patch limit (bub2-002)
CDP_TIMEOUT_S = 20.0  # bu-pi cdp timeout; 30s/60s waits made each stall cost more (v1b: 114 Hard timeouts)
DIALOG_PROBE_S = 2.0  # while the daemon saw a JS dialog open: how long a page call may take before it is blamed
DIALOG_POLL_S = 0.25  # while a navigation runs: how often to ask whether a beforeunload prompt holds it
# What a page frozen by an alert/confirm/prompt never answers (Page.handleJavaScriptDialog is what unfreezes it)
FROZEN_BY_DIALOG = (
	'Runtime.evaluate',
	'Runtime.callFunctionOn',
	'Runtime.awaitPromise',
	'Page.captureScreenshot',
	'Page.navigate',
	'Page.reload',
)
# Of those, the calls that can open a dialog themselves and are then held until it is handled (plus Input.*)
HELD_BY_DIALOG = tuple(m for m in FROZEN_BY_DIALOG if m != 'Page.captureScreenshot')
# browser-harness's daemon reads each request as one JSON line with asyncio's default 64 KiB limit; a longer one broke
# the connection (BrokenPipeError). Characters of JSON (ASCII), less a margin for the token Windows adds.
MAX_IPC_REQUEST = 65_536 - 128
# Browser('chrome') shares a daemon it did not start; one started with browser-harness's default BH_TAB_MARKER prefixes
# the attached tab's document.title with a horse after every load, and the agent read it back as the title. In an
# isolated world (the page never sees it), strip that prefix as soon as it is set: a mutation observer's callback runs
# before the next CDP command, so page_info(), js(), current_tab(), list_tabs() and bu all read the page's own title.
UNMARK_JS = """(() => {
  const mark = '\\u{1F434} ';
  const strip = () => { if (document.title.startsWith(mark)) document.title = document.title.slice(mark.length); };
  new MutationObserver(strip).observe(document, {subtree: true, childList: true, characterData: true});
  strip();
})()"""
# The daemon's error once its websocket to the browser closed: Chrome crashed or quit ("no close frame received or
# sent"), or the cloud browser was stopped or timed out ("received 1001 (going away) browser session ended").
BROWSER_GONE = re.compile(r'no close frame|received 10\d\d \(|sent 10\d\d \(|ConnectionClosed|websocket.*closed', re.I)
# Traceback frame prefixes of installed code: the stdlib, site-packages and browser_use itself (an editable install).
INSTALLED = tuple(
	{'File "' + sysconfig.get_path(p) for p in ('stdlib', 'platstdlib', 'purelib', 'platlib')}
	| {'File "' + str(Path(ax.__file__).parent)}
)


def totp(seed: str, now: float | None = None) -> str:
	"""The current 6-digit TOTP code (RFC 6238: SHA-1, 30 s) for a base32 seed, as 0.x generated for secrets whose name
	ends in 'bu_2fa_code' (pyotp.TOTP(seed, digits=6).now())."""
	key = seed.replace(' ', '').upper()
	key = base64.b32decode(key + '=' * (-len(key) % 8))
	digest = hmac.new(key, struct.pack('>Q', int((time.time() if now is None else now) // 30)), hashlib.sha1).digest()
	offset = digest[-1] & 15
	return f'{(int.from_bytes(digest[offset : offset + 4], "big") & 0x7FFFFFFF) % 1_000_000:06d}'


STATE = Path(os.environ.get('BU_STATE_DIR', '.browser-use'))
images: list[dict] = []
NAVIGATING = ('Page.navigate', 'Target.createTarget')
STAT_EVENTS = {'BrowserUse.captchaSolverStarted': 'captcha_started'}
NET_ERROR = re.compile(r'net::(ERR_[A-Z0-9_]{1,40})')  # Page.navigate's errorText: Chrome's net error names
DOWNLOAD_EVENTS = ('Browser.downloadWillBegin', 'Page.downloadWillBegin')  # cloud browsers send both for one download
PROGRESS_EVENTS = ('Browser.downloadProgress', 'Page.downloadProgress')


class CellStats:
	"""Telemetry counts of one cell: helper and cdp() method names with call counts, errors and time,
	hostnames, captcha and download events. Never arguments, URLs, page text or values. Sent with the cell's result,
	then reset. Each update is a few dict operations under one lock (~1 us); helpers and CDP calls take milliseconds."""

	def __init__(self) -> None:
		self.lock = threading.Lock()  # ultrafast reads CDP events on a background thread
		# Browser('chrome') attaches to a tab the user had open: a page read is only counted once this worker navigated
		self.navigated = False
		self.downloads: set[str | None] = set()  # guids seen: one download_started per download, whichever events announce it
		self.started: list[str] = []  # names of downloads that started since the last cell output
		self.names: dict[str, str | None] = {}  # guid -> suggested file name: a finished download is renamed to it
		self.seen: set[int] = set()  # hashes of URLs this worker saw (loop detection); never leave this process
		self.json_pages: set[str] = set()  # top-frame JSON pages, without query: a cloud browser saves each as a download
		self.take()

	def count(self, kind: str, name: str) -> None:
		with self.lock:
			getattr(self, kind)[name] += 1

	def timed(self, kind: str, name: str, ns: int, failed: bool) -> None:
		"""One helper ('helper_t') or CDP ('cdp_t') call: [calls, errors, ns total, ns max] per name."""
		with self.lock:
			if kind == 'helper_t':
				self.helpers[name] += 1
			s = getattr(self, kind).get(name)
			if s is None:
				getattr(self, kind)[name] = [1, int(failed), ns, ns]
			else:
				s[0] += 1
				s[1] += failed
				s[2] += ns
				s[3] = max(s[3], ns)

	def url(self, url, navigation: bool = False) -> None:
		"""A navigation's hostname, or (navigation=False) the hostname of a page the agent read. A URL never seen before
		counts as a new page, a navigation to one already seen as a revisit (by hash; the URL is not kept). Chrome's own
		error page (chrome-error://chromewebdata/) is not a host: the page stays on the host that failed to load."""
		if str(url).startswith('chrome-error:'):
			return
		if h := host(url):
			with self.lock:
				self.navigated = self.navigated or navigation
				if self.navigated:
					self.hosts.add(h)
					self.host = h
					key = hash(str(url).split('#', 1)[0])
					if key in self.seen:
						self.revisits += navigation
					else:
						self.seen.add(key)
						self.new_pages += 1
				self.navigations += navigation

	def nav_failed(self, error_text) -> None:
		"""Page.navigate answered errorText (DNS, TLS, refused, aborted): the Chrome net error code, never the URL."""
		m = NET_ERROR.fullmatch(str(error_text))
		with self.lock:
			self.events['nav_failed'] += 1
			self.nav_errors[m[1] if m else 'other'] += 1

	def observe(self, events) -> None:
		events = events if isinstance(events, list) else []
		for e in events:  # first: the cloud browser's copy of a JSON page may come before the page's own event
			params = (e.get('params') if isinstance(e, dict) else None) or {}
			if isinstance(e, dict) and e.get('method') == 'Page.frameNavigated' and _json_page(params):
				with self.lock:
					self.json_pages.add(urllib.parse.urlsplit(params['frame'].get('url') or '')._replace(query='').geturl())
		for e in events:
			method = e.get('method') if isinstance(e, dict) else None
			params = (e.get('params') if isinstance(e, dict) else None) or {}
			key = STAT_EVENTS.get(method or '')
			if method == 'BrowserUse.captchaSolverFinished':
				key = 'captcha_solved' if params.get('success') else 'captcha_failed'
			elif method in DOWNLOAD_EVENTS:
				with self.lock:
					guid = params.get('guid')
					key = None if guid is not None and guid in self.downloads else 'download_started'
					self.downloads.add(guid)
					if guid:
						self.names.setdefault(guid, params.get('suggestedFilename'))
				if key:
					_log_download({'name': params.get('suggestedFilename'), 'url': params.get('url'), 'guid': guid})
					url = str(params.get('url') or '')  # the copy's URL: the page's + '.json', ' (n)' for a repeat
					copy = '?' not in url and re.sub(r'%20\(\d+\)$', '', url.removesuffix('.json')) in self.json_pages
					with self.lock:
						if not copy:  # the model never downloaded a page it only opened (Browser.json_page_copies)
							self.started.append(str(params.get('suggestedFilename') or params.get('url')))
			elif method in PROGRESS_EVENTS and params.get('state') in ('completed', 'canceled'):
				# either event: a tab another client attached sends only Page's. Browser.stop() waits for the rest
				_log_download({'done': params.get('guid'), 'state': params['state']})
				if params['state'] == 'completed':
					self.name_download(params)
			elif method == 'Page.frameNavigated' and _json_page(params):
				_log_download({'json_page': params['frame'].get('url')})
			if key:
				self.count('events', key)

	def name_download(self, params: dict) -> None:
		"""A Chrome Browser launched saves each download as downloads/<guid> (Browser._send_downloads): give it its own
		name now, so the cell that downloaded it finds it by that name. A cloud browser's files are not on this machine.
		Only the reader that drained the completed event renames it (Browser._finish_downloads after this worker)."""
		guid = str(params.get('guid') or '')
		if not guid or os.environ.get('BU_REMOTE_BROWSER') == '1':
			return
		path = Path(params['filePath']) if params.get('filePath') else STATE.absolute().parent / 'downloads' / guid
		if path.name != guid:  # Chrome named it itself (behavior 'allow', a browser this worker did not launch)
			return
		with self.lock:
			name = self.names.get(guid)
		if name is None:  # announced to an earlier worker of this REPL (a reset): its log has the name
			with contextlib.suppress(OSError):
				for line in (STATE / 'downloads.jsonl').read_text(encoding='utf-8').splitlines():
					with contextlib.suppress(ValueError, AttributeError):
						if (r := json.loads(line)).get('guid') == guid:
							name = r.get('name')
		with contextlib.suppress(OSError):  # - a file that cannot be renamed keeps its guid name, never lost
			name_download(path, name)

	def take(self) -> dict:
		with self.lock:
			out = {
				'helpers': dict(getattr(self, 'helpers', {})),
				'cdp': dict(getattr(self, 'cdp', {})),
				'events': dict(getattr(self, 'events', {})),
				'hosts': sorted(getattr(self, 'hosts', ())),
				'navigations': getattr(self, 'navigations', 0),
				'helper_t': getattr(self, 'helper_t', {}),
				'cdp_t': getattr(self, 'cdp_t', {}),
				'host': getattr(self, 'host', None),  # the last hostname this cell saw
				'new_pages': getattr(self, 'new_pages', 0),
				'revisits': getattr(self, 'revisits', 0),
				'nav_errors': dict(getattr(self, 'nav_errors', {})),
			}
			self.helpers, self.cdp, self.events, self.hosts, self.navigations = Counter(), Counter(), Counter(), set(), 0
			self.helper_t, self.cdp_t, self.host, self.new_pages, self.revisits = {}, {}, None, 0, 0
			self.nav_errors = Counter()
		return out


def _json_page(params: dict) -> bool:
	"""A Page.frameNavigated of a top frame that shows JSON (vnd.api+json, problem+json too)."""
	frame = params.get('frame') or {}
	mime = str(frame.get('mimeType') or '').lower()
	return not frame.get('parentId') and (mime in ('application/json', 'text/json') or mime.endswith('+json'))


def _log_download(record: dict) -> None:
	"""Download starts and JSON pages the tab displayed, for the parent (Browser.json_page_copies): a cloud browser also
	saves a JSON page it displays as a download."""
	with contextlib.suppress(OSError), open(STATE / 'downloads.jsonl', 'a', encoding='utf-8') as f:
		f.write(json.dumps(record) + '\n')


stats = CellStats()
# The tab the agent works in. A daemon browser-use started again (Browser.reattach) attaches a new blank tab of its own;
# the next cell attaches this one again, page and form state intact, and closes that blank tab.
AGENT_TAB: dict = {'id': None, 'lost': False}


def _back_to_agent_tab() -> None:
	if not (AGENT_TAB['lost'] and AGENT_TAB['id']):
		return
	AGENT_TAB['lost'] = False
	from browser_harness import helpers

	with contextlib.suppress(Exception):  # the tab is gone (closed, a new browser): the cell starts where the daemon is
		blank = helpers.current_tab()
		if blank['targetId'] != AGENT_TAB['id']:
			helpers.switch_tab(AGENT_TAB['id'])
			if blank['url'] == 'about:blank':
				helpers.cdp('Target.closeTarget', targetId=blank['targetId'])
				deadline = time.monotonic() + 3  # Chrome closes it after it answers: list_tabs() still showed it
				while time.monotonic() < deadline and any(
					t['targetId'] == blank['targetId'] for t in helpers.cdp('Target.getTargets')['targetInfos']
				):
					time.sleep(0.05)


def _counted(name: str, fn):
	"""fn, counted in stats under name. page_info()/current_tab() also record the attached tab's hostname, once the
	agent navigated."""

	@functools.wraps(fn)
	def counted(*args, **kwargs):
		started, failed = time.perf_counter_ns(), True
		try:
			result = fn(*args, **kwargs)
			failed = False
		finally:  # an error counts even when the model's code catches it
			stats.timed('helper_t', name, time.perf_counter_ns() - started, failed)
		if name in ('page_info', 'current_tab') and isinstance(result, dict):
			stats.url(result.get('url'))
		return result

	return counted


class CountedBu:
	"""The agent's `bu`: each public method call is counted as bu.<name>. The worker keeps the raw object, so its own
	state print after a cell is not counted."""

	def __init__(self, bu: ax.AxHelpers) -> None:
		object.__setattr__(self, '_bu', bu)

	def __getattr__(self, name: str):
		value = getattr(self._bu, name)
		public = not name.startswith('_') and hasattr(ax.AxHelpers, name)  # not a name the model's code set on bu
		return _counted(f'bu.{name}', value) if callable(value) and public else value

	def __setattr__(self, name: str, value) -> None:
		setattr(self._bu, name, value)

	def __dir__(self):
		return dir(self._bu)

	def __repr__(self) -> str:
		return repr(self._bu)


def _checked(fn, check_url):
	@functools.wraps(fn)
	def checked(*args, **kwargs):
		check_url(args[0] if args else kwargs.get('url', 'about:blank'))
		return fn(*args, **kwargs)

	return checked


def redirect_checking_opener(check_url) -> urllib.request.OpenerDirector:
	"""An opener that calls check_url on every redirect hop before following it."""

	class CheckedRedirects(urllib.request.HTTPRedirectHandler):
		def redirect_request(self, req, fp, code, msg, headers, newurl):
			check_url(newurl)
			return super().redirect_request(req, fp, code, msg, headers, newurl)

	return urllib.request.build_opener(CheckedRedirects, TLSHandler)


def _check_redirects(check_url) -> None:
	"""http_get (urllib) follows redirects: every hop is checked too, for any urllib.request.urlopen in the worker."""
	urllib.request.install_opener(redirect_checking_opener(check_url))


def http_get(url, headers=None, timeout=20.0):
	"""Plain HTTP from this machine, not the browser (no browser IP, cookies or proxy). Returns str, or bytes when the
	body is not UTF-8 text (zip, pdf, image). browser-harness's own decoded every body (UnicodeDecodeError on binary), and
	its fetch-use branch never runs here: the worker has no BROWSER_USE_API_KEY."""
	return _http_get(url, headers, timeout, urllib.request.urlopen)


def _http_get(url, headers, timeout, urlopen):
	"""http_get through urlopen. Not on http_get itself: the agent calls that, and passing its own opener skipped the
	redirect check (--cli-mcp passes its checked opener here)."""
	h = {'User-Agent': 'Mozilla/5.0', 'Accept-Encoding': 'gzip', **(headers or {})}
	with urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
		data = r.read()
		if r.headers.get('Content-Encoding') == 'gzip':
			data = gzip.decompress(data)
	try:
		return data.decode()
	except UnicodeDecodeError:
		return data


def _add_image(data: bytes, media_type: str = 'image/png') -> bool:
	if len(images) >= MAX_IMAGES_PER_CELL:
		print(f'[image dropped: {MAX_IMAGES_PER_CELL} per call max]')
		return False
	from PIL import Image

	try:  # providers 400 the whole request on an undecodable or oversized image
		img = Image.open(io.BytesIO(data))
		img.load()
	except Exception as e:
		print(f'[image dropped: not a decodable image ({type(e).__name__})]')
		return False
	# the decoded format, not the file name; MPO is a camera JPEG with an extra frame
	media_type = 'image/jpeg' if img.format == 'MPO' else img.get_format_mimetype() or media_type
	if img.format not in ('PNG', 'JPEG', 'MPO', 'WEBP') or img.mode in ('P', 'PA'):
		# xAI 400s GIF and palette PNGs ("not a valid JPG, PNG, WebP"; grok bub2-008 showed an EPC graph): plain PNG
		if img.mode not in ('1', 'L', 'LA', 'I', 'I;16', 'RGB', 'RGBA'):
			img = img.convert('RGBA' if img.has_transparency_data else 'RGB')
		out = io.BytesIO()
		img.save(out, 'PNG')
		data, media_type = out.getvalue(), 'image/png'
	if len(data) > 5_000_000 or max(img.size) > MAX_IMAGE_SIDE:
		if img.mode.startswith('I'):  # 16-bit gray: convert() clips it to white
			img = img.point(lambda v: v / 256).convert('L')
		img = img.convert('RGBA')
		img.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
		flat = Image.new('RGB', img.size, 'white')  # JPEG has no alpha: transparent pixels go white, not the black they hid
		flat.paste(img, mask=img)
		out = io.BytesIO()
		flat.save(out, 'JPEG', quality=80)
		data, media_type = out.getvalue(), 'image/jpeg'
	images.append({'data': base64.b64encode(data).decode(), 'media_type': media_type})
	return True


# Run on the focused element in an isolated world: whether typed keys edit it.
EDITABLE = """function () {
	if (this.isContentEditable) return true;
	if (this instanceof HTMLTextAreaElement) return !this.readOnly && !this.disabled;
	if (!(this instanceof HTMLInputElement)) return false;
	const keys = !['button', 'submit', 'reset', 'checkbox', 'radio', 'file', 'image', 'range', 'color', 'hidden'].includes(this.type);
	return keys && !this.readOnly && !this.disabled;
}"""


def _install(ns: dict, secrets: list) -> tuple[ax.AxHelpers | None, Captcha]:
	env = dict(os.environ)  # the allowlisted env the parent gave us
	from browser_harness import helpers  # loads .env files and agent_helpers.py into this process

	os.environ.clear()  # whatever those added (DATABASE_URL, ...) does not survive
	os.environ.update(env)

	raw_send = helpers._send

	def send(req, *args, **kwargs):  # every drain_events() read, also bu's background one, feeds the event counts
		if (size := len(json.dumps(req))) > MAX_IPC_REQUEST:
			label = req.get('method') or req.get('meta') or 'request'
			raise ValueError(
				f'{label}: the request is {size:,} bytes and browser-harness takes at most 64 KiB per request; send it '
				'in parts (upload_file() sends files in parts itself)'
			)
		try:
			r = raw_send(req, *args, **kwargs)
		except (FileNotFoundError, ConnectionRefusedError, ConnectionResetError, BrokenPipeError):
			AGENT_TAB['lost'] = True
			raise BrowserConnectionLost() from None
		except RuntimeError as e:  # the daemon is up but its browser connection closed: the browser crashed or ended
			if BROWSER_GONE.search(str(e)):
				AGENT_TAB['lost'] = True
				raise BrowserConnectionLost('the browser ended (crashed, stopped, or a cloud browser hit its timeout)') from None
			raise
		if isinstance(req, dict) and req.get('meta') == 'set_session' and req.get('target_id'):
			AGENT_TAB['id'] = req['target_id']
			unmark()
		if isinstance(req, dict) and req.get('meta') == 'drain_events' and isinstance(r, dict):
			stats.observe(r.get('events'))
		return r

	def unmark() -> None:
		"""Keep the attached tab's title free of a shared daemon's horse (UNMARK_JS), on this page and the next ones."""
		if os.environ.get('BU_SHARED_DAEMON') == '1':
			with contextlib.suppress(Exception):  # a tab that closed meanwhile; titles stay as they are
				raw_cdp(
					'Page.addScriptToEvaluateOnNewDocument', source=UNMARK_JS, worldName='browser-use-unmark', runImmediately=True
				)

	helpers._send = send
	raw_cdp = helpers.cdp
	with contextlib.suppress(Exception):  # no daemon yet
		AGENT_TAB['id'] = raw_send({'meta': 'current_tab'})['targetId']
		unmark()
	cloud = os.environ.get('BU_REMOTE_BROWSER') == '1'
	rules = DomainRules.from_json(os.environ.get('BU_DOMAINS'))
	tabs_file = os.environ.get('BU_TABS_FILE')  # Browser('chrome') with domain restrictions

	def check_url(url) -> None:
		"""Browser(allowed_domains=...): refuse a disallowed URL before anything navigates (Browser.domains)."""
		if rules and (why := rules.blocked(str(url))):
			stats.count('events', 'domain_blocked')
			raise PermissionError(why)

	def pending_dialog(method, session_id):
		if session_id is not None or not (method in FROZEN_BY_DIALOG or method.startswith('Input.')):
			return None
		try:
			return raw_send({'meta': 'pending_dialog'}).get('dialog')
		except Exception:  # - an older daemon, or none: no shortcut
			return None

	def attached_session():
		return raw_send({'meta': 'session'}).get('session_id')

	highlight = None
	if os.environ.get('BU_HIGHLIGHT_ACTIONS') == '1':
		highlight = Highlighter(raw_cdp, attached_session, lambda: pending_dialog('Runtime.callFunctionOn', None))

	def dialog_open(dialog: dict) -> RuntimeError:
		return RuntimeError(
			f'A JavaScript {dialog.get("type") or "dialog"} is open ({str(dialog.get("message", ""))[:200]!r}): the page is '
			'frozen until it is handled. Accept or dismiss it: cdp("Page.handleJavaScriptDialog", accept=True) (or '
			'accept=False; promptText="..." for a prompt).'
		)

	def cdp(method, session_id=None, **params):
		"""A JS dialog freezes the page: js() then took 20 s, click_at_xy 20 s and screenshot() 65 s, each with a timeout
		that did not say why. While the daemon saw one open, such a call gets DIALOG_PROBE_S and then says so; a call that
		opens one itself (a click on a confirm button, js("alert(1)"), a navigation a beforeunload prompt holds) says so
		as soon as it opens."""
		dialog = pending_dialog(method, session_id)
		if dialog:
			params['_response_timeout'] = min(params.get('_response_timeout', SCREENSHOT_TIMEOUT_S), DIALOG_PROBE_S)
			params['_frozen'] = True
		try:
			if not dialog and session_id is None and (method in HELD_BY_DIALOG or method.startswith('Input.')):
				return raced(method, params)
			return _cdp(method, session_id, **params)
		except RuntimeError as e:  # with the dialog open, Chrome may also answer an error ('Unable to capture screenshot')
			if not dialog:
				raise
			# the daemon's dialog is browser-wide: it may be in another tab, so the error itself stays
			raise RuntimeError(f'{e}. {dialog_open(dialog)}') from None
		except TimeoutError:
			# a call that opened the dialog itself (a click on a button that alerts) times out first, then it is there
			dialog = dialog or pending_dialog(method, session_id)
			if not dialog:
				raise
			raise dialog_open(dialog) from None

	def raced(method, params):
		"""A call on the attached tab that a dialog it opens would hold, racing a probe for that dialog: the call only
		returns once the dialog is handled, so a click on a confirm button, js("alert(1)") or a navigation that a
		beforeunload prompt holds (browser-3) took the full CDP_TIMEOUT_S, every time. Only a call that takes longer
		than DIALOG_POLL_S asks the daemon."""
		done, box = threading.Event(), {}

		def call():
			try:
				box['result'] = _cdp(method, None, **params)
			except BaseException as e:  # - handed to the cell below
				box['error'] = e
			finally:
				done.set()

		threading.Thread(target=call, daemon=True, name='browser-use-cdp').start()
		while not done.wait(DIALOG_POLL_S):
			if dialog := pending_dialog(method, None):  # the call stays queued: handling the dialog completes it
				raise dialog_open(dialog)
		if 'error' in box:
			raise box['error']
		return box['result']

	def timed(method, session_id=None, **params):
		"""Every CDP call from the worker (helpers, bu, the agent's cdp()), timed per method for telemetry."""
		started, failed = time.perf_counter_ns(), True
		try:
			result = dialog_aware(method, session_id, **params)
			failed = False
			return result
		finally:
			stats.timed('cdp_t', str(method)[:200], time.perf_counter_ns() - started, failed)

	known_secrets = {n for n, _, _ in secrets}

	def refuse_placeholder(method, params) -> None:
		"""0.x replaced <secret>name</secret> with the value, and cell output shows a typed value as <secret:name>: the
		model typed that text into the form, read it back (redacted the same way) and reported "Wrong credentials"."""
		text = json.dumps(params, default=str)
		if '<secret' not in text:
			return
		for m in SECRET_PLACEHOLDER.finditer(text):
			if (name := m[1] or m[2]) in known_secrets:
				raise ValueError(
					f'{method}: {m[0]} is not replaced with the secret: type it with type_secret({name!r}, id) (the '
					f"input's backendNodeId), or type_secret({name!r}) into the focused input. Nothing was sent."
				)

	def _cdp(method, session_id=None, **params):
		frozen = params.pop('_frozen', False)
		if known_secrets:
			refuse_placeholder(method, params)
		if method == 'DOM.setFileInputFiles':  # local paths, also on a remote browser (bu's recipe on the cloud default)
			set_input_files(session_id, params)
			return {}
		if method in NAVIGATING:
			check_url(params.get('url', ''))
			stats.url(params.get('url'), navigation=True)
		# browser-harness sends its Windows key code as nativeVirtualKeyCode; macOS Chrome reads it as a Mac one, so a
		# printable press_key() on a visible tab also opened chrome://settings/help. 0.x never sent it.
		params.pop('nativeVirtualKeyCode', None)
		if method != 'Page.captureScreenshot':
			# browser-harness defaults to 5s IPC; heavy cloud pages (Maps, TripAdvisor) blew it on navigate/evaluate/input.
			params.setdefault('_response_timeout', CDP_TIMEOUT_S)
			result = raw_cdp(method, session_id, **params)
			if method == 'Page.navigate' and isinstance(result, dict) and result.get('errorText'):
				stats.nav_failed(result['errorText'])
			if highlight:
				highlight.after(method, session_id, params)
			# Browser._touched_tabs: the agent's tabs are the ones it created or attached to (switch_tab), even one it
			# left within the same cell; a tab of yours it never touched is not swept
			tab = params.get('targetId') if method == 'Target.attachToTarget' else None
			if method == 'Target.createTarget' and isinstance(result, dict):
				tab = result.get('targetId')
			if tab and tabs_file:
				with contextlib.suppress(OSError), open(tabs_file, 'a') as f:
					f.write(f'{tab}\n')
			return result
		with highlight.hidden() if highlight else contextlib.nullcontext():  # the model never sees a highlight
			result = capture(raw_cdp, helpers.current_tab, session_id, activate=cloud, frozen=frozen, **params)
		# Every screenshot the agent takes is shown to the model as a native image.
		if isinstance(result, dict) and result.get('data'):
			fmt = params.get('format', 'png')
			_add_image(base64.b64decode(result['data']), f'image/{"jpeg" if fmt == "jpeg" else fmt}')
		return result

	def plain(method, session_id=None, **params):
		return raw_cdp(method, session_id, _response_timeout=params.pop('_response_timeout', CDP_TIMEOUT_S), **params)

	def set_input_files(session_id, params) -> int:
		object_id = params.get('objectId')
		if not object_id:
			node = {k: params[k] for k in ('backendNodeId', 'nodeId') if k in params}
			object_id = plain('DOM.resolveNode', session_id, **node)['object']['objectId']
		return set_files(functools.partial(plain, session_id=session_id), object_id, params.get('files') or [], cloud)

	dialog_aware, cdp = cdp, functools.wraps(raw_cdp)(timed)
	helpers.cdp = cdp  # capture_screenshot() and friends go through the wrapper too
	helpers.http_get = http_get
	helpers.wait_for_network_idle = wait_for_network_idle  # browser-4; delete with network_idle.py at harness >= 0.1.14
	install_page_info()  # cli-1: waits for a new document's <html>; delete with page_info.py
	if rules:  # before the * import below, so the agent's names are the checked ones
		for name in ('new_tab', 'http_get'):  # new_tab: before it opens an empty tab; http_get: plain HTTP from here
			helpers.__dict__[name] = _checked(getattr(helpers, name), check_url)
		_check_redirects(check_url)
	else:
		install_tls_opener()  # http_get and urllib in cells verify as the OS does, as with rules
	if os.environ.get('BU_OWN_BROWSER') == '1':  # a browser we launched or were given: the agent's tab is the visible one,
		# as in 0.x. A hidden tab never paints, so scroll() timed out and keys and clicks were dropped.
		helpers.switch_tab = functools.partial(helpers.switch_tab, activate=True)  # new_tab() calls it too
		with contextlib.suppress(Exception):  # the daemon attached to a background tab of its own
			cdp('Target.activateTarget', targetId=helpers.current_tab()['targetId'])
	captcha = Captcha(cdp, STATE / 'captcha.json', off=os.environ.get('BU_CAPTCHA_SOLVER') == 'off')
	exec('from browser_harness.helpers import *', ns)

	@functools.wraps(cdp)
	def agent_cdp(method, session_id=None, **params):  # the agent's own cdp() calls, counted by method
		stats.count('cdp', str(method))
		return cdp(method, session_id, **params)

	ns['cdp'] = agent_cdp

	shots = STATE / 'screenshots'

	def screenshot(full=False):
		"""Capture the current tab (JPEG q70, like bu-pi) and show it to the model. Returns the file path."""
		shots.mkdir(parents=True, exist_ok=True)
		r = cdp('Page.captureScreenshot', format='jpeg', quality=70, captureBeyondViewport=full)
		path = shots / f'{len(list(shots.iterdir())):04d}.jpg'
		path.write_bytes(base64.b64decode(r['data']))
		return str(path)

	def show_image(path):
		"""Show an image file (png/jpeg/webp/gif) to the model."""
		p = Path(path)
		ext = p.suffix.lower().lstrip('.').replace('jpg', 'jpeg')
		return _add_image(p.read_bytes(), f'image/{ext}')

	def checkpoint(filename, value, partial=False):
		"""Atomically save JSON to the workspace. partial=True also makes it the run's fallback result."""
		path = Path(filename)
		value = redact(
			json.loads(json.dumps(value, default=_jsonable)), secrets
		)  # the checkpoint file never holds a secret value
		_write_atomic(path, json.dumps(value, ensure_ascii=False, indent=1))
		if partial:
			_write_atomic(STATE / 'partial.json', json.dumps({'file': str(path), 'value': value}, ensure_ascii=False))
		return str(path)

	def _frame_url(session: str | None, frame_id: str) -> str | None:
		"""The browser's own record of a frame's URL, from its target's frame tree. None when the frame is not in it."""

		def find(tree: dict) -> str | None:
			if tree['frame']['id'] == frame_id:
				return str(tree['frame'].get('url') or '')
			return next((u for c in tree.get('childFrames') or [] if (u := find(c)) is not None), None)

		return find(helpers.cdp('Page.getFrameTree', session_id=session)['frameTree'])

	def _focused(session: str | None, frame_id: str) -> dict | None:
		"""DOM.describeNode of the focused element in a frame's document, through open and closed shadow roots, read
		in an isolated world: page JS cannot change what document.activeElement reports there. None when none.
		'_editable': whether typed keys edit it (an enabled, writable text field or contenteditable); None if unknown."""
		cdp_ = helpers.cdp

		def described(obj: str) -> dict:
			node = cdp_('DOM.describeNode', session_id=session, objectId=obj)['node']
			try:  # in the isolated world too: the page cannot fake readOnly or isContentEditable there
				r = cdp_(
					'Runtime.callFunctionOn', session_id=session, objectId=obj, functionDeclaration=EDITABLE, returnByValue=True
				)
				node['_editable'] = r['result'].get('value') if isinstance(r['result'].get('value'), bool) else None
			except Exception:  # - unknown: the nodeName check below still applies
				node['_editable'] = None
			return node

		world = cdp_('Page.createIsolatedWorld', session_id=session, frameId=frame_id, worldName='browser-use-secrets')
		ctx = world['executionContextId']
		obj = cdp_('Runtime.evaluate', session_id=session, expression='document.activeElement', contextId=ctx)['result']
		obj = obj.get('objectId')
		for _ in range(32):
			if not obj:
				return None
			node = cdp_('DOM.describeNode', session_id=session, objectId=obj)['node']
			if not node.get('shadowRoots'):
				return described(obj)
			root = cdp_(
				'DOM.resolveNode',
				session_id=session,
				backendNodeId=node['shadowRoots'][0]['backendNodeId'],
				executionContextId=ctx,
			)['object']['objectId']
			inner = cdp_(
				'Runtime.callFunctionOn',
				session_id=session,
				objectId=root,
				functionDeclaration='function () { return this.activeElement }',
			)
			if not inner['result'].get('objectId'):
				return described(obj)
			obj = inner['result']['objectId']
		raise RuntimeError('shadow roots nested too deep')

	def _recipient() -> tuple[str, dict | None]:
		"""URL of the frame typed text reaches, and the focused node in that frame (None when none): focus followed from
		the top frame into nested frames, cross-site iframe targets included (the attached tab's own target would type
		into a focused attacker iframe). Raises when it cannot be established."""
		session: str | None = None
		frame_id = helpers.cdp('Page.getFrameTree')['frameTree']['frame']['id']
		attached: list[str] = []
		try:
			for _ in range(16):
				node = _focused(session, frame_id)
				if node is None or node.get('nodeName') not in ('IFRAME', 'FRAME'):
					url = _frame_url(session, frame_id)
					if url is None:
						raise RuntimeError('focused frame not found')
					return url, node
				child = node.get('frameId')
				if not child:
					raise RuntimeError('focused frame has no id')
				if _frame_url(session, child) is None:  # another process: a cross-site iframe target, frame id = target id
					# listing the targets first also makes Chrome accept the attach ("No target with given id" without)
					targets = helpers.cdp('Target.getTargets')['targetInfos']
					if not any(t['targetId'] == child and t['type'] == 'iframe' for t in targets):
						raise RuntimeError('focused frame is neither in the frame tree nor an iframe target')
					sid = helpers.cdp('Target.attachToTarget', targetId=child, flatten=True)['sessionId']
					attached.append(sid)
					session = sid
				frame_id = child
			raise RuntimeError('frames nested too deep')
		finally:
			for attached_sid in attached:
				with contextlib.suppress(Exception):
					helpers.cdp('Target.detachFromTarget', sessionId=attached_sid)

	def _type_keys(value: str) -> None:
		# Key events per character, as 0.x typed sensitive_data: forms that react to keydown/keyup (enable the submit
		# button, validate) see the value. Input.insertText alone fires no key events. A newline is the Enter key (as in
		# 0.x); a tab or other control character goes in as text: as a key event a tab moves focus, and the rest of the
		# secret would land in the next field.
		for ch in value.replace('\r\n', '\n'):
			if ch in '\r\n':
				helpers.press_key('Enter')
			elif ch.isprintable():
				helpers.press_key(ch)
			else:
				helpers.cdp('Input.insertText', text=ch)

	def type_secret(name, id=None):
		"""Type the secret called `name` into the input with backendNodeId `id`, replacing its text, or into the focused
		element. Its value is hidden from your text output.
		A domain-scoped secret types only while the frame that receives the text matches its domain. A secret whose
		name ends in 'bu_2fa_code' is a TOTP seed: the current 6-digit code is typed, never the seed (0.x)."""
		candidates = [(totp(v) if name.endswith('bu_2fa_code') else v, scope) for n, v, scope in secrets if n == name]
		if not candidates:
			raise KeyError(f'No secret named {name!r}; secret_names() lists them')
		scoped = [(v, scope) for v, scope in candidates if scope is not None]
		if id is not None:  # Pi's fillSecret(name, backendNodeId); focus and select the text so the keys replace it, as bu.type
			helpers.cdp('DOM.focus', backendNodeId=id)
			a = {'key': 'a', 'code': 'KeyA', 'windowsVirtualKeyCode': 65, 'modifiers': 2}
			helpers.cdp('Input.dispatchKeyEvent', type='rawKeyDown', **a, commands=['selectAll'])
			helpers.cdp('Input.dispatchKeyEvent', type='keyUp', **a)
		try:  # the browser's own records (frame trees, isolated worlds), never page JS
			url, node = _recipient()
		except Exception:  # unknown recipient: scoped secrets fail closed below
			url, node = '', {}

		def type_into_field(value: str) -> None:
			attrs, editable = (node or {}).get('attributes') or [], (node or {}).get('_editable')
			page = node is not None and node.get('nodeName') in ('BODY', 'HTML')
			if node is None or (page and (not editable if editable is not None else 'contenteditable' not in attrs[::2])):
				# the keys went to the page itself and type_secret returned None: the agent believed it typed the value
				where = 'nothing' if node is None else f'the page <{node["nodeName"].lower()}>'
				raise RuntimeError(f'type_secret({name!r}): no field is focused ({where} is). Click or focus the input first.')
			if editable is False:  # a button, a read-only or disabled input, contenteditable="false"
				raise RuntimeError(
					f'type_secret({name!r}): the focused <{node["nodeName"].lower()}> is not an editable field. Click or focus '
					'the input first.'
				)
			_type_keys(value)

		if scoped:
			for value, scope in scoped:
				if url and domain_matches(url, scope):
					return type_into_field(value)
		for value, scope in candidates:
			if scope is None:
				return type_into_field(value)
		raise PermissionError(
			f'Secret {name!r} may only be typed on {", ".join(sorted({s for _, s in scoped}))}; the focused frame is '
			f'{url or "unknown"}. Focus a field on the right site first.'
		)

	def secret_names():
		"""Names of the secrets you can type with type_secret(name)."""
		return sorted({n for n, _, _ in secrets})

	ns.update(
		screenshot=screenshot,
		show_image=show_image,
		checkpoint=checkpoint,
		type_secret=type_secret,
		secret_names=secret_names,
		solve_captcha=captcha.solve,
	)
	ns['upload_file'] = uploader(plain, lambda: cloud)
	bu = None
	if os.environ.get('BU_MODE') != 'ultrafast':
		# One reader of the daemon's events, so solver events are never lost; wait_for_network_idle() reads through it.
		events = EventPump(helpers._send, captcha.observe)
		# Our cloud browsers send solver events, and a Chrome Browser launched names each finished download from its
		# events (CellStats.name_download): read continuously. The user's Chrome is read when the agent asks.
		if cloud or os.environ.get('BU_OWN_BROWSER') == '1':
			events.start()
		captcha.pump = events.pump
		helpers.drain_events = ns['drain_events'] = events.drain_events
	else:
		bu = ax.AxHelpers(cdp, on_event=captcha.observe)
		ns['bu'] = CountedBu(bu)
		captcha.pump = bu._pump
		helpers.drain_events = ns['drain_events'] = bu.drain_events  # bu reads the daemon's events; the agent still gets them

		def print_(*args, **kwargs):
			"""print() for the cell: a bu result is already printed, so it prints empty (Pi: console.log of it)."""
			print(*('' if isinstance(a, ax.Printed) else a for a in args), **kwargs)

		ns['print'] = print_
	# helpers and the ones above (solve_captcha, drain_events too); not stdlib names the * import brought
	own = {helpers.__name__, __name__, ax.__name__, Captcha.__module__, uploader.__module__, wait_for_network_idle.__module__}
	for name, value in list(ns.items()):
		if name not in ('cdp', 'print') and not name.startswith('_') and inspect.isroutine(value):
			if getattr(value, '__module__', None) in own:
				ns[name] = _counted(name, value)
	return bu, captcha


def _ask_parent(rfile, wfile):
	"""ask(type, args) -> the parent's answer to a message sent mid-cell (search(), downloads()): the parent holds what
	the worker must not (the API key). Main thread only: it reads the answer off the control channel, which only the main
	thread reads (a thread that outlived its cell would take the next cell's message)."""

	def ask(kind: str, args: dict | None = None):
		if threading.current_thread() is not threading.main_thread():
			raise RuntimeError(f'{kind}() runs on the main thread only: call it in sequence, not from threads.')
		wfile.write(json.dumps({'type': kind, 'args': args}).encode() + b'\n')
		wfile.flush()
		line = rfile.readline()
		if not line:
			raise ConnectionError('the REPL parent closed the channel')
		answer = json.loads(line)
		if answer.get('error') is not None:
			raise RuntimeError(answer['error'])
		return answer['value']

	return ask


def _search(ask):
	"""search() for the cell: the parent makes the request (browser_use/search.py), so the API key never enters this
	process."""

	def search(query, num_results=None, category=None):
		"""Search the web (Browser Use): -> {'query', 'count', 'results'}. results has one text entry per hit (title, URL,
		matching excerpts), [] when nothing matched. num_results: default 8, max 20. category: 'company', 'people',
		'news' or 'publication'. Raises with the HTTP status on failure (402: out of budget)."""
		if not isinstance(query, str) or not query.strip():
			raise ValueError('search(query) needs text.')
		if num_results is not None and (isinstance(num_results, bool) or not isinstance(num_results, int)):
			raise TypeError(f'num_results must be an int, not {type(num_results).__name__}')
		if category is not None and not isinstance(category, str):
			raise TypeError(f'category must be a str, not {type(category).__name__}')
		return ask('search', {'query': query, 'num_results': num_results, 'category': category})

	return search


def _downloads(ask):
	"""downloads() for the cell: the parent lists them (Browser.list_downloads), a cloud browser's through the API."""

	def downloads():
		"""The files the browser finished downloading so far: [{'name', 'size'}]."""
		return ask('downloads')

	return downloads


def _write_atomic(path: Path, text: str) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	tmp = path.with_name(path.name + '.tmp')
	tmp.write_text(text, encoding='utf-8')
	os.replace(tmp, path)  # a kill mid-write leaves the old file, never a truncated one


def _pump(rfd: int, path: Path, secrets: list, mode: str = 'w') -> None:
	"""Copy a cell's output pipe into its file, redacting on the way, so secret values never reach the disk even
	when the cell is killed. Holds back only the tail that could be the start of a secret."""
	forms = secret_forms(secrets)
	keep = max((len(f) for f, _ in forms), default=1) - 1
	by_line = not any('\n' in f for f, _ in forms)  # then a secret never spans a newline
	decoder, buf = codecs.getincrementaldecoder('utf-8')('replace'), ''
	with open(path, mode, encoding='utf-8', newline='') as out:  # Windows: the cell already wrote \r\n; no \r\r\n
		while True:
			chunk = os.read(rfd, 65536)
			buf = redact_forms(buf + decoder.decode(chunk, final=not chunk), forms)
			cut = max(len(buf) - keep, buf.rfind('\n') + 1 if by_line else 0) if chunk else len(buf)
			out.write(buf[:cut])
			out.flush()
			buf = buf[cut:]
			if not chunk:
				break
	os.close(rfd)


def _jsonable(value):
	"""json.dumps default for delivery: pydantic models, dataclasses, dates as JSON (str(model) is not the schema)."""
	from pydantic_core import to_jsonable_python

	return to_jsonable_python(value, fallback=str)


def _display(value) -> None:
	if value is None or isinstance(value, ax.Printed):  # bu already printed it
		return
	print(value if isinstance(value, str) else pprint.pformat(value, width=120, sort_dicts=False))


def _compile(code: str, n: int):
	flags = ast.PyCF_ALLOW_TOP_LEVEL_AWAIT
	tree = compile(code, f'<cell {n}>', 'exec', flags=ast.PyCF_ONLY_AST | flags)
	if tree.body and isinstance(tree.body[-1], ast.Expr):  # REPL-style: show the last expression
		last = tree.body[-1]
		call = ast.copy_location(ast.Call(ast.Name('__bu_display', ast.Load()), [last.value], []), last.value)
		tree.body[-1] = ast.copy_location(ast.Expr(call), last)
		ast.fix_missing_locations(tree)
	return compile(tree, f'<cell {n}>', 'exec', flags=flags)


def _run(code_obj, ns, loop):
	if code_obj.co_flags & inspect.CO_COROUTINE:
		return loop.run_until_complete(eval(code_obj, ns))
	return exec(code_obj, ns)


def _error(e: BaseException) -> str:
	if isinstance(e, BrowserConnectionLost):  # one line: the frames that hit it say nothing more
		return f'{type(e).__name__}: {e}'
	lines = traceback.format_exception(e)
	# Keep the cell's frames, the workspace's own modules and the exception; drop installed code (stdlib, packages,
	# browser_use): its absolute paths leak the user's home to the provider and cost tokens.
	keep = [lines[0]] + [line for line in lines[1:] if not line.lstrip().startswith(INSTALLED)]
	return ''.join(keep).strip()


def _watch_parent(parent: int) -> None:
	"""Exit when the parent dies (SIGKILL, crash), also mid-cell: its cell timeouts died with it, and a cell left
	running could keep driving the browser. POSIX kills this worker's process group (cell subprocesses too); on Windows
	the parent's kill-on-close job object does that (session._job_for)."""
	if sys.platform == 'win32':
		import ctypes

		kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
		kernel32.OpenProcess.restype = ctypes.c_void_p
		kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
		handle = kernel32.OpenProcess(0x00100000, False, parent)  # SYNCHRONIZE; None: already gone
		if handle:
			kernel32.WaitForSingleObject(handle, 0xFFFFFFFF)  # INFINITE
	else:
		while os.getppid() == parent:  # a dead parent's children are reparented
			time.sleep(1)
		if os.getpgrp() == os.getpid():  # we lead our group (start_new_session)
			with contextlib.suppress(OSError):
				os.killpg(os.getpid(), signal.SIGKILL)
	os._exit(1)


_OWN_JOB = None  # Windows: the worker's own kill-on-close job, held open for the worker's lifetime


def _redact_between_cells(secrets: list) -> None:
	"""Output written between cells (a thread or subprocess a cell left running, a warning) goes to worker.log through
	the redacting pump too: it went there raw, with any secret value a background thread printed."""
	rfd, wfd = os.pipe()
	pump = threading.Thread(target=_pump, args=(rfd, STATE / 'worker.log', secrets, 'a'), daemon=True)
	pump.start()
	log = os.dup(1), os.dup(2)
	os.dup2(wfd, 1)
	os.dup2(wfd, 2)
	os.close(wfd)

	def drain() -> None:  # exit: close the pipe so the pump writes what it holds (a crash traceback) and ends
		with contextlib.suppress(Exception):
			sys.stdout.flush()
			sys.stderr.flush()
			os.dup2(log[0], 1)
			os.dup2(log[1], 2)
			pump.join(2)

	atexit.register(drain)


def main() -> None:
	global _OWN_JOB
	if sys.platform == 'win32':  # processes a cell starts join this job, so they die with the worker however it dies
		from browser_use.repl.session import _job_for  # (the parent's job can miss them: a venv python.exe launcher

		_OWN_JOB = _job_for(os.getpid())  # starts the real interpreter before the parent assigns it)
	if parent := int(os.environ.pop('BU_REPL_PARENT_PID', '0')):
		threading.Thread(target=_watch_parent, args=(parent,), daemon=True).start()
	sock = socket.create_connection(('127.0.0.1', int(os.environ.pop('BU_REPL_PORT'))))
	rfile, wfile = sock.makefile('rb'), sock.makefile('wb')
	wfile.write(os.environ.pop('BU_REPL_TOKEN').encode() + b'\n')
	wfile.flush()
	init = json.loads(rfile.readline())
	secrets = init['secrets']
	cells = STATE / 'cells'
	cells.mkdir(parents=True, exist_ok=True)
	sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)  # type: ignore[attr-defined]
	sys.stderr.reconfigure(encoding='utf-8', line_buffering=True)  # type: ignore[attr-defined]
	_redact_between_cells(secrets)  # after reconfigure(): it seeks, which a pipe refuses
	ns: dict = {'__name__': '__main__', '__bu_display': _display}
	bu, captcha = _install(ns, secrets)
	ask = _ask_parent(rfile, wfile)
	if init.get('search'):
		ns['search'] = _counted('search', _search(ask))
	if init.get('downloads'):
		ns['downloads'] = _counted('downloads', _downloads(ask))
	sys.path.append(os.getcwd())  # after the imports (-P kept it off sys.path[0]): modules the agent writes still import
	loop = asyncio.new_event_loop()
	asyncio.set_event_loop(loop)

	def send(msg):
		wfile.write(json.dumps(msg).encode() + b'\n')
		wfile.flush()

	send({'type': 'ready'})
	for line in rfile:
		msg = json.loads(line)
		images.clear()
		out_path = cells / f'{msg["n"]:04d}.txt'
		error = value = error_type = None  # stats keeps events bu read between cells (a captcha solve while the model thinks)
		rfd, wfd = os.pipe()
		pump = threading.Thread(target=_pump, args=(rfd, out_path, secrets), daemon=True)
		pump.start()
		# Cell stdout/stderr, subprocesses included, go through the redacting pump into out_path.
		saved = os.dup(1), os.dup(2)
		os.dup2(wfd, 1)
		os.dup2(wfd, 2)
		os.close(wfd)
		try:
			_back_to_agent_tab()
			if msg['op'] == 'exec':
				_run(_compile(msg['code'], msg['n']), ns, loop)
			else:  # 'eval': read an existing value for delivery
				obj = compile(msg['code'], '<finish>', 'eval', flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
				value = _run(obj, ns, loop) if obj.co_flags & inspect.CO_COROUTINE else eval(obj, ns)
				value = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=_jsonable)
		except BaseException as e:  # - the agent sees every failure
			error_type = error_class(e)  # telemetry: a class the model's code defined is 'custom'
			if isinstance(e, (SystemExit, KeyboardInterrupt)):
				error = f'{type(e).__name__} ignored; the REPL keeps running.'
			else:
				error = _error(e)
		finally:
			# After a cell whose bu actions reached the page, show the resulting state without another model turn.
			if bu is not None and bu.acted:
				try:
					bu.state()
				except Exception as e:
					print(f'[state unavailable: {type(e).__name__}: {e}]')
			if notice := captcha.report():  # a solve that is running or ended: the agent waits instead of reloading
				print(notice)
			with contextlib.suppress(Exception):  # local: nothing else reads the daemon's events between cells
				captcha.pump()
			with stats.lock:
				started, stats.started = stats.started, []
			if started:  # 0.x told the model too; buried in drain_events() output, it clicked again ('x (1).csv')
				print(f'[download started: {", ".join(started)}]')
			sys.stdout.flush()
			sys.stderr.flush()
			os.dup2(saved[0], 1)
			os.dup2(saved[1], 2)
			os.close(saved[0])
			os.close(saved[1])
		pump.join(5)  # a background subprocess may hold the pipe open; its later output still lands in the file
		with open(out_path, encoding='utf-8', errors='replace') as f:
			raw = f.read(MAX_OUTPUT_CHARS + 1)
		output = clip(raw, out_path)
		cell_stats = stats.take()
		cell_stats['cut'] = len(raw) > MAX_OUTPUT_CHARS
		send(
			{
				'type': 'result',
				'n': msg['n'],
				'output': output,
				'error': error,
				'value': value,
				'images': list(images),
				'output_file': str(out_path),
				'error_type': error_type,
				'stats': cell_stats,
			}
		)


if __name__ == '__main__':
	main()
