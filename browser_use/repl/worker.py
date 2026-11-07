"""Persistent Python REPL for one agent. Runs as a child process so a hung cell can be killed.

Namespace = browser-harness helpers + screenshot/show_image/checkpoint/type_secret/solve_captcha (+ bu in ultrafast mode,
see ax.py; + search when web search is on).
Protocol: connect to 127.0.0.1:BU_REPL_PORT, send BU_REPL_TOKEN, read one init line ({"secrets": [[name, value, domain|null], ...],
"search": bool}), then one JSON line per message. search() sends {"type": "search", "args": {...}} mid-cell and reads
the parent's one-line answer. Cell stdout/stderr (including subprocesses) go to a per-cell file, so a killed cell still leaves its
partial output on disk.
"""

import ast
import asyncio
import base64
import codecs
import contextlib
import functools
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
import threading
import time
import traceback
import urllib.request
from collections import Counter
from pathlib import Path

from browser_use import ax
from browser_use.domains import DomainRules
from browser_use.exceptions import BrowserConnectionLost
from browser_use.remote_upload import local_upload, remote_upload
from browser_use.repl.captcha import Captcha, EventPump
from browser_use.repl.session import MAX_OUTPUT_CHARS, clip, domain_matches, redact, redact_forms, secret_forms
from browser_use.telemetry.stats import error_class, host

MAX_IMAGES_PER_CELL = 4
MAX_IMAGE_SIDE = 2048  # full-page captures exceeded OpenAI's 30k-patch limit (bub2-002)
CDP_TIMEOUT_S = 20.0  # bu-pi cdp timeout; 30s/60s waits made each stall cost more (v1b: 114 Hard timeouts)
SCREENSHOT_TIMEOUT_S = 60.0  # browser-harness's own screenshot timeout: cloud screenshots routinely take longer
DIALOG_PROBE_S = 2.0  # while the daemon saw a JS dialog open: how long a page call may take before it is blamed
# What a page frozen by an alert/confirm/prompt never answers (Page.handleJavaScriptDialog is what unfreezes it)
FROZEN_BY_DIALOG = ('Runtime.evaluate', 'Runtime.callFunctionOn', 'Runtime.awaitPromise', 'Page.captureScreenshot')
HIDDEN_CAPTURE_TRY_S = 10.0  # a hidden tab's first capture try; Linux headless never answers it
# browser-harness's daemon reads each request as one JSON line with asyncio's default 64 KiB limit; a longer one broke
# the connection (BrokenPipeError). Characters of JSON (ASCII), less a margin for the token Windows adds.
MAX_IPC_REQUEST = 65_536 - 128
# The daemon's error once its websocket to the browser closed: Chrome crashed or quit ("no close frame received or
# sent"), or the cloud browser was stopped or timed out ("received 1001 (going away) browser session ended").
BROWSER_GONE = re.compile(r'no close frame|received 10\d\d \(|sent 10\d\d \(|ConnectionClosed|websocket.*closed', re.I)


def capture(raw_cdp, current_tab, session_id=None, *, activate=False, **params):
	"""Page.captureScreenshot. new_tab()/switch_tab() never activate a tab, and on Linux headless a hidden tab renders
	no frames, so its capture hangs. A hidden attached tab gets a short first try; only when that times out is it
	activated (made Chrome's visible tab) and captured again. A hidden tab that captures (macOS, headful Chrome) is
	never activated: local mode does not switch the user's visible tab. activate=True (a cloud browser: ours, and it
	never answers a hidden tab's capture) activates a hidden tab without the first try."""
	timeout = params.pop('_response_timeout', SCREENSHOT_TIMEOUT_S)
	hidden = False
	if session_id is None:  # the attached tab; another session's target is unknown here
		try:
			r = raw_cdp('Runtime.evaluate', expression='document.visibilityState', returnByValue=True, _response_timeout=5)
			hidden = r['result'].get('value') == 'hidden'
		except Exception:  # unknown: capture as for a visible tab
			pass
	if not hidden:
		return raw_cdp('Page.captureScreenshot', session_id, _response_timeout=timeout, **params)
	if not activate:
		try:
			return raw_cdp('Page.captureScreenshot', _response_timeout=min(timeout, HIDDEN_CAPTURE_TRY_S), **params)
		except TimeoutError:
			pass
	raw_cdp('Target.activateTarget', targetId=current_tab()['targetId'])
	return raw_cdp('Page.captureScreenshot', _response_timeout=timeout, **params)


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
DOWNLOAD_EVENTS = ('Browser.downloadWillBegin', 'Page.downloadWillBegin')  # cloud browsers send both for one download


class CellStats:
	"""Telemetry counts of one cell (TELEMETRY.md): helper and cdp() method names, hostnames, captcha and download
	events. Never arguments, URLs, page text or values. Sent with the cell's result, then reset."""

	def __init__(self) -> None:
		self.lock = threading.Lock()  # ultrafast reads CDP events on a background thread
		# Browser('chrome') attaches to a tab the user had open: a page read is only counted once this worker navigated
		self.navigated = False
		self.downloads: set[str | None] = set()  # guids seen: one download_started per download, whichever events announce it
		self.take()

	def count(self, kind: str, name: str) -> None:
		with self.lock:
			getattr(self, kind)[name] += 1

	def url(self, url, navigation: bool = False) -> None:
		"""A navigation's hostname, or (navigation=False) the hostname of a page the agent read."""
		if h := host(url):
			with self.lock:
				self.navigated = self.navigated or navigation
				if self.navigated:
					self.hosts.add(h)
				self.navigations += navigation

	def observe(self, events) -> None:
		for e in events if isinstance(events, list) else ():
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
				if key:
					_log_download({'name': params.get('suggestedFilename'), 'url': params.get('url')})
			elif method == 'Page.frameNavigated' and not (frame := params.get('frame') or {}).get('parentId'):
				mime = str(frame.get('mimeType') or '').lower()
				if mime in ('application/json', 'text/json') or mime.endswith('+json'):  # vnd.api+json, problem+json
					_log_download({'json_page': frame.get('url')})
			if key:
				self.count('events', key)

	def take(self) -> dict:
		with self.lock:
			out = {
				'helpers': dict(getattr(self, 'helpers', {})),
				'cdp': dict(getattr(self, 'cdp', {})),
				'events': dict(getattr(self, 'events', {})),
				'hosts': sorted(getattr(self, 'hosts', ())),
				'navigations': getattr(self, 'navigations', 0),
			}
			self.helpers, self.cdp, self.events, self.hosts, self.navigations = Counter(), Counter(), Counter(), set(), 0
		return out


def _log_download(record: dict) -> None:
	"""Download starts and JSON pages the tab displayed, for the parent (Browser.json_page_copies): a cloud browser also
	saves a JSON page it displays as a download."""
	with contextlib.suppress(OSError), open(STATE / 'downloads.jsonl', 'a', encoding='utf-8') as f:
		f.write(json.dumps(record) + '\n')


stats = CellStats()


def _counted(name: str, fn):
	"""fn, counted in stats under name. page_info()/current_tab() also record the attached tab's hostname, once the
	agent navigated."""

	@functools.wraps(fn)
	def counted(*args, **kwargs):
		stats.count('helpers', name)
		result = fn(*args, **kwargs)
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


def _check_redirects(check_url) -> None:
	"""http_get (urllib) follows redirects: every hop is checked too, for any urllib.request.urlopen in the worker."""

	class CheckedRedirects(urllib.request.HTTPRedirectHandler):
		def redirect_request(self, req, fp, code, msg, headers, newurl):
			check_url(newurl)
			return super().redirect_request(req, fp, code, msg, headers, newurl)

	urllib.request.install_opener(urllib.request.build_opener(CheckedRedirects))


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
	if len(data) > 5_000_000 or max(img.size) > MAX_IMAGE_SIDE:
		img = img.convert('RGB')
		img.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
		out = io.BytesIO()
		img.save(out, 'JPEG', quality=80)
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


ADMIN_LOCKED = (
	'browser-use owns this browser: the agent cannot start, restart, attach or approve browsers or daemons. '
	'If the browser is gone, finish with what you have.'
)


def _lock_browser_admin() -> None:
	"""A model must never reach another browser: browser-harness's admin calls can start a daemon on the user's own
	Chrome (and mac_approve clicks its "Allow remote debugging?" sheet). The worker never needs them."""
	from browser_harness import admin, macos

	def locked(*_args: object, **_kwargs: object) -> None:
		raise PermissionError(ADMIN_LOCKED)

	for name in (
		'ensure_daemon',
		'restart_daemon',
		'start_remote_daemon',
		'stop_remote_daemon',
		'sync_local_profile',
		'_launch_browser',
	):
		setattr(admin, name, locked)
	for name in ('approve_remote_debugging', 'run_cli'):
		setattr(macos, name, locked)


def _install(ns: dict, secrets: list) -> tuple[ax.AxHelpers | None, Captcha]:
	env = dict(os.environ)  # the allowlisted env the parent gave us
	from browser_harness import helpers  # loads .env files and agent_helpers.py into this process

	_lock_browser_admin()  # imports browser_harness.admin, which loads .env files too: before the env is reset
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
			raise BrowserConnectionLost() from None
		except RuntimeError as e:  # the daemon is up but its browser connection closed: the browser crashed or ended
			if BROWSER_GONE.search(str(e)):
				raise BrowserConnectionLost('the browser ended (crashed, stopped, or a cloud browser hit its timeout)') from None
			raise
		if isinstance(req, dict) and req.get('meta') == 'drain_events' and isinstance(r, dict):
			stats.observe(r.get('events'))
		return r

	helpers._send = send
	raw_cdp = helpers.cdp
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

	def cdp(method, session_id=None, **params):
		"""A JS dialog freezes the page: js() then took 20 s, click_at_xy 20 s and screenshot() 65 s, each with a timeout
		that did not say why. While the daemon saw one open, such a call gets DIALOG_PROBE_S and then says so; a call that
		opened the dialog itself says so when it times out."""
		dialog = pending_dialog(method, session_id)
		if dialog:
			params['_response_timeout'] = min(params.get('_response_timeout', SCREENSHOT_TIMEOUT_S), DIALOG_PROBE_S)
		try:
			return _cdp(method, session_id, **params)
		except TimeoutError:
			# a call that opened the dialog itself (a click on a button that alerts) times out first, then it is there
			dialog = dialog or pending_dialog(method, session_id)
			if not dialog:
				raise
			raise RuntimeError(
				f'A JavaScript {dialog.get("type") or "dialog"} is open ({str(dialog.get("message", ""))[:200]!r}): the page is '
				'frozen until it is handled. Accept or dismiss it: cdp("Page.handleJavaScriptDialog", accept=True) (or '
				'accept=False; promptText="..." for a prompt).'
			) from None

	def _cdp(method, session_id=None, **params):
		if method in NAVIGATING:
			check_url(params.get('url', ''))
			stats.url(params.get('url'), navigation=True)
		if method != 'Page.captureScreenshot':
			# browser-harness defaults to 5s IPC; heavy cloud pages (Maps, TripAdvisor) blew it on navigate/evaluate/input.
			params.setdefault('_response_timeout', CDP_TIMEOUT_S)
			result = raw_cdp(method, session_id, **params)
			if method == 'Target.createTarget' and tabs_file and isinstance(result, dict) and result.get('targetId'):
				with contextlib.suppress(OSError), open(tabs_file, 'a') as f:  # Browser._touched_tabs: the agent's tabs
					f.write(f'{result["targetId"]}\n')
			return result
		result = capture(raw_cdp, helpers.current_tab, session_id, activate=cloud, **params)
		# Every screenshot the agent takes is shown to the model as a native image.
		if isinstance(result, dict) and result.get('data'):
			fmt = params.get('format', 'png')
			_add_image(base64.b64decode(result['data']), f'image/{"jpeg" if fmt == "jpeg" else fmt}')
		return result

	cdp.__doc__ = raw_cdp.__doc__
	helpers.cdp = cdp  # capture_screenshot() and friends go through the wrapper too
	if rules:  # before the * import below, so the agent's names are the checked ones
		for name in ('new_tab', 'http_get'):  # new_tab: before it opens an empty tab; http_get: plain HTTP from here
			helpers.__dict__[name] = _checked(getattr(helpers, name), check_url)
		_check_redirects(check_url)
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
		"""URL of the frame typed text reaches, and the top document's focused node ({} when focus is in an iframe):
		focus followed from the top frame into nested frames, cross-site iframe targets included (the attached tab's own
		target would type into a focused attacker iframe). Raises when it cannot be established."""
		session: str | None = None
		frame_id = top = helpers.cdp('Page.getFrameTree')['frameTree']['frame']['id']
		attached: list[str] = []
		try:
			for _ in range(16):
				node = _focused(session, frame_id)
				if node is None or node.get('nodeName') not in ('IFRAME', 'FRAME'):
					url = _frame_url(session, frame_id)
					if url is None:
						raise RuntimeError('focused frame not found')
					# the node only for the top document: inside an iframe activeElement can read <body> while keys reach
					# a field the frame focused itself
					return url, (node if frame_id == top else {})
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

	def type_secret(name):
		"""Type the secret called `name` into the focused element. Its value is hidden from your text output.
		A domain-scoped secret types only while the frame that receives the text matches its domain. A secret whose
		name ends in 'bu_2fa_code' is a TOTP seed: the current 6-digit code is typed, never the seed (0.x)."""
		candidates = [(totp(v) if name.endswith('bu_2fa_code') else v, scope) for n, v, scope in secrets if n == name]
		if not candidates:
			raise KeyError(f'No secret named {name!r}; secret_names() lists them')
		scoped = [(v, scope) for v, scope in candidates if scope is not None]
		try:  # the browser's own records (frame trees, isolated worlds), never page JS
			url, node = _recipient()
		except Exception:  # unknown recipient: scoped secrets fail closed below
			url, node = '', {}

		def type_into_field(value: str) -> None:
			# node {}: focus is in an iframe, whose activeElement can read <body> while keys reach a field it focused
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
	ns['upload_file'] = remote_upload(ns['js']) if cloud else local_upload(helpers.upload_file)
	bu = None
	if os.environ.get('BU_MODE') != 'ultrafast':
		# One reader of the daemon's events, so solver events are never lost; wait_for_network_idle() reads through it.
		events = EventPump(helpers._send, captcha.observe)
		if cloud:  # only our cloud browsers send solver events; elsewhere the daemon is read when the agent asks
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
	own = {helpers.__name__, __name__, ax.__name__, Captcha.__module__, local_upload.__module__}
	for name, value in list(ns.items()):
		if name not in ('cdp', 'print') and not name.startswith('_') and inspect.isroutine(value):
			if getattr(value, '__module__', None) in own:
				ns[name] = _counted(name, value)
	return bu, captcha


def _search(rfile, wfile):
	"""search() for the cell: the parent makes the request (browser_use/search.py), so the API key never enters this
	process. Main thread only: it reads the answer off the control channel, which only the main thread reads (a thread
	that outlived its cell would take the next cell's message)."""

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
		if threading.current_thread() is not threading.main_thread():
			raise RuntimeError('search() runs on the main thread only: call it in sequence, not from threads.')
		args = {'query': query, 'num_results': num_results, 'category': category}
		wfile.write(json.dumps({'type': 'search', 'args': args}).encode() + b'\n')
		wfile.flush()
		line = rfile.readline()
		if not line:
			raise ConnectionError('the REPL parent closed the channel')
		answer = json.loads(line)
		if answer.get('error') is not None:
			raise RuntimeError(answer['error'])
		return answer['value']

	return search


def _write_atomic(path: Path, text: str) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	tmp = path.with_name(path.name + '.tmp')
	tmp.write_text(text, encoding='utf-8')
	os.replace(tmp, path)  # a kill mid-write leaves the old file, never a truncated one


def _pump(rfd: int, path: Path, secrets: list) -> None:
	"""Copy a cell's output pipe into its file, redacting on the way, so secret values never reach the disk even
	when the cell is killed. Holds back only the tail that could be the start of a secret."""
	forms = secret_forms(secrets)
	keep = max((len(f) for f, _ in forms), default=1) - 1
	by_line = not any('\n' in f for f, _ in forms)  # then a secret never spans a newline
	decoder, buf = codecs.getincrementaldecoder('utf-8')('replace'), ''
	with open(path, 'w', encoding='utf-8', newline='') as out:  # Windows: the cell already wrote \r\n; no \r\r\n
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
	# Drop worker and bu frames; keep the user's cell frames and the exception itself.
	keep = [lines[0]] + [
		line for line in lines[1:] if not line.lstrip().startswith(('File "' + __file__, 'File "' + ax.__file__))
	]
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
	ns: dict = {'__name__': '__main__', '__bu_display': _display}
	bu, captcha = _install(ns, secrets)
	if init.get('search'):
		ns['search'] = _counted('search', _search(rfile, wfile))
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
			sys.stdout.flush()
			sys.stderr.flush()
			os.dup2(saved[0], 1)
			os.dup2(saved[1], 2)
			os.close(saved[0])
			os.close(saved[1])
		pump.join(5)  # a background subprocess may hold the pipe open; its later output still lands in the file
		with open(out_path, encoding='utf-8', errors='replace') as f:
			output = clip(f.read(MAX_OUTPUT_CHARS + 1), out_path)
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
				'stats': stats.take(),
			}
		)


if __name__ == '__main__':
	main()
