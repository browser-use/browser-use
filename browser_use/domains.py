"""Browser(allowed_domains=..., prohibited_domains=..., block_ip_addresses=...): where the browser may navigate.

Patterns follow 0.x (browser_use/browser/watchdogs/security_watchdog.py, _is_url_allowed / _is_url_match):
  'example.com'           example.com and www.example.com (www only for a one-dot domain), http and https, any port
  'mail.example.com'      exactly that host (no www added)
  '*.example.com'         example.com and every subdomain, http and https
  'https://example.com'   that scheme and host on its default port (a path in the pattern is a path prefix)
  'https://*.example.com', 'http*://example.com/*', 'brave://*'   globs on scheme, host and path
  'localhost:8080'        a host with a port (new in 1.0; 0.x never matched it)
about:blank, the new tab page, data: and blob: are always allowed. A URL without a host (file:, javascript:) is not.
When allowed_domains is set, prohibited_domains is ignored, as in 0.x. block_ip_addresses blocks IP-literal hosts first.

Enforcement (MIGRATING.md "Domain restrictions"): the REPL helpers refuse a disallowed URL (worker.py), Guard fails
main-frame document requests to disallowed hosts on its own CDP connection, and sweep() resets tabs that still show a
disallowed page after each cell. A guard for an aligned model, not a sandbox: subresources (fetch, images, iframes) are
not filtered, and the REPL's own Python networking is not the browser.
"""

from __future__ import annotations

import contextlib
import ipaddress
import json
import logging
import re
import socket
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Any, NamedTuple
from urllib.parse import unquote, urlsplit

logger = logging.getLogger(__name__)

ALWAYS_ALLOWED = ('about:blank', 'chrome://new-tab-page/', 'chrome://new-tab-page', 'chrome://newtab/')  # 0.x list
NO_HOST_ALLOWED = ('data', 'blob')
WEB = ('http', 'https')
DEFAULT_PORT = {'http': '80', 'https': '443', 'ws': '80', 'wss': '443'}
GUARD_START_S = 15.0  # connect + Target.setDiscoverTargets + Fetch.enable
NOTICES_PER_CELL = 5


class Url(NamedTuple):
	scheme: str
	host: str
	port: str  # explicit port, '' when the URL has none
	path: str  # path + '?query'


def canonical_host(host: str) -> str:
	"""As the browser sends it: lowercase, punycode, no trailing dot, IPv4 in dotted decimal (0x7f.1 -> 127.0.0.1)."""
	h = unquote(host).strip().strip('[]').lower().removesuffix('.')
	with contextlib.suppress(ValueError):
		return str(ipaddress.ip_address(h))
	labels = h.split('.')
	if re.fullmatch(r'\d+|0x[0-9a-f]*', labels[-1]):  # WHATWG: a host ending in a number is an IPv4 address
		with contextlib.suppress(OSError):
			return socket.inet_ntoa(socket.inet_aton(h))
	with contextlib.suppress(UnicodeError):
		return h.encode('idna').decode('ascii')
	return h


def parse_url(url: str) -> Url | None:
	"""None for a URL without a host. Backslashes count as slashes in http(s) URLs, as in the browser."""
	url = re.sub(r'[\t\n\r]', '', url.strip())
	if url.split(':', 1)[0].lower() in WEB:
		url = url.replace('\\', '/')
	try:
		u = urlsplit(url)
		port = '' if u.port is None else str(u.port)
	except ValueError:
		return None
	if not u.hostname:
		return None
	return Url(u.scheme.lower(), canonical_host(u.hostname), port, (u.path or '/') + (f'?{u.query}' if u.query else ''))


def _split_port(host: str) -> tuple[str, str]:
	if ':' in host and not host.endswith(']'):
		host, _, port = host.rpartition(':')
		return host, port
	return host, ''


def _host_matches(host: str, pattern: str) -> bool:
	return fnmatchcase(host, pattern.lower()) if '*' in pattern else host == canonical_host(pattern)


def pattern_matches(pattern: str, u: Url) -> bool:
	"""0.x _is_url_match, with the parsed URL instead of string prefixes: 'https://example.com' no longer matches
	https://example.com.evil.com or https://example.com@evil.com."""
	p = pattern.strip()
	if '://' in p:
		p_scheme, rest = p.split('://', 1)
		p_host, slash, p_path = rest.partition('/')
		p_host, p_port = _split_port(p_host)
		if not fnmatchcase(u.scheme, p_scheme.lower()) or not (p_host == '*' or _host_matches(u.host, p_host)):
			return False
		port = u.port or DEFAULT_PORT.get(u.scheme, '')
		if p_port:
			if not fnmatchcase(port, p_port):
				return False
		elif u.port and u.port != DEFAULT_PORT.get(u.scheme):  # 0.x: 'https://site' was a prefix of 'https://site/...'
			return False
		if not slash:
			return True
		return fnmatchcase(u.path, f'/{p_path}') if '*' in p_path else u.path.startswith(f'/{p_path}')
	if u.scheme not in WEB:  # 0.x: a pattern without a scheme never matches chrome://, file:, ...
		return False
	p_host, p_port = _split_port(p)
	if p_port and (u.port or DEFAULT_PORT[u.scheme]) != p_port:
		return False
	if p_host.startswith('*.'):
		base = canonical_host(p_host[2:])
		return u.host == base or u.host.endswith(f'.{base}')
	if '*' in p_host:
		return fnmatchcase(u.host, p_host.lower())
	h = canonical_host(p_host)
	return u.host == h or (p_host.count('.') == 1 and u.host == f'www.{h}')  # 0.x _is_root_domain: www for a.b only


def is_ip(host: str) -> bool:
	try:
		ipaddress.ip_address(host)
		return True
	except ValueError:
		return False


def _patterns(value: Any, option: str) -> tuple[str, ...]:
	if value is None:
		return ()
	if isinstance(value, str) or not isinstance(value, Iterable):
		raise TypeError(f"Browser({option}=...) takes a list of domain patterns, e.g. ['example.com', '*.example.org']")
	patterns = tuple(value)
	if not all(isinstance(p, str) and p.strip() for p in patterns):
		raise TypeError(f'Browser({option}=...): every pattern must be a non-empty string')
	return patterns


@dataclass(frozen=True)
class DomainRules:
	allowed: tuple[str, ...] = ()
	prohibited: tuple[str, ...] = ()
	block_ips: bool = False

	@classmethod
	def of(cls, allowed: Any = None, prohibited: Any = None, block_ips: bool = False) -> DomainRules:
		"""Validated rules from the Browser() options. [] is no restriction, as in 0.x."""
		rules = cls(_patterns(allowed, 'allowed_domains'), _patterns(prohibited, 'prohibited_domains'), bool(block_ips))
		if rules.allowed and rules.prohibited:
			logger.warning('Browser(): prohibited_domains is ignored because allowed_domains is set (as in 0.x)')
		return rules

	def __bool__(self) -> bool:
		return bool(self.allowed or self.prohibited or self.block_ips)

	def blocked(self, url: str) -> str | None:
		"""None when the browser may open url, else the one-line reason the model sees."""
		url = str(url)
		if not self or url in ALWAYS_ALLOWED or url.startswith('about:blank#'):
			return None
		if url.split(':', 1)[0].strip().lower() in NO_HOST_ALLOWED:
			return None
		u = parse_url(url)
		if u is None:
			return f'blocked: {url[:100]!r} has no host, and the browser is limited to {self._scope()}'
		if self.block_ips and is_ip(u.host):
			return f'blocked: {u.host} is an IP address (block_ip_addresses=True)'
		if self.allowed:
			ok = any(pattern_matches(p, u) for p in self.allowed)
			return None if ok else f'blocked: {u.host} is not in allowed_domains ({self._list(self.allowed)})'
		if any(pattern_matches(p, u) for p in self.prohibited):
			return f'blocked: {u.host} is in prohibited_domains ({self._list(self.prohibited)})'
		return None

	@staticmethod
	def _list(patterns: tuple[str, ...]) -> str:
		return ', '.join(patterns[:10]) + (f', ... ({len(patterns)} patterns)' if len(patterns) > 10 else '')

	def _scope(self) -> str:
		if self.allowed:
			return f'allowed_domains ({self._list(self.allowed)})'
		if self.prohibited:
			return f'sites outside prohibited_domains ({self._list(self.prohibited)})'
		return 'hosts that are not IP addresses'

	def prompt(self) -> str:
		"""One system-prompt line; '' without restrictions."""
		if not self:
			return ''
		parts = []
		if self.allowed:
			parts.append(f'The browser may only open these domains: {self._list(self.allowed)}.')
		elif self.prohibited:
			parts.append(f'The browser must not open these domains: {self._list(self.prohibited)}.')
		if self.block_ips:
			parts.append('IP-address URLs are blocked.')
		return ' '.join(parts) + ' Other navigation is blocked by the browser; do not try to get around it.'

	def to_json(self) -> str:
		return json.dumps({'allowed': self.allowed, 'prohibited': self.prohibited, 'block_ips': self.block_ips})

	@classmethod
	def from_json(cls, text: str | None) -> DomainRules:
		if not text:
			return cls()
		d = json.loads(text)
		return cls(tuple(d.get('allowed') or ()), tuple(d.get('prohibited') or ()), bool(d.get('block_ips')))


class Guard:
	"""Fails main-frame document requests to disallowed hosts, for every tab: browser-level Fetch.enable (Document
	requests, Request stage) on a CDP connection of its own. Catches link clicks, redirects, target=_blank,
	window.open, meta refresh, JS location changes and Target.createTarget(url=...): the request never leaves the
	browser (net::ERR_BLOCKED_BY_CLIENT). Its own connection: the agent's cdp('Fetch.disable') through the daemon does
	not turn it off. Iframes and subresources pass. When the connection drops, Chrome stops intercepting until it
	reconnects (sweep() still runs after each cell)."""

	def __init__(self, ws_url: str, rules: DomainRules):
		self.ws_url, self.rules = ws_url, rules
		self.pages: set[str] = set()  # page target ids: a page's main frame id is its target id
		self.blocks = 0
		self._notices: list[str] = []
		self._lock = threading.Lock()
		self._ws: Any = None
		self._id = 0
		self._closed = threading.Event()
		self._ready = threading.Event()
		self._error: str | None = None
		self._thread = threading.Thread(target=self._run, daemon=True, name='browser-use-domains')

	def start(self) -> None:
		self._thread.start()
		if not self._ready.wait(GUARD_START_S) or self._error:
			self.close()
			why = self._error or f'no answer within {GUARD_START_S:g}s'
			raise RuntimeError(f'Domain restrictions could not start on this browser ({why}); nothing was left running.')

	def close(self) -> None:
		self._closed.set()
		ws, self._ws = self._ws, None
		if ws is not None:
			with contextlib.suppress(Exception):
				ws.close()

	def take(self) -> tuple[list[str], int]:
		"""Notices for the model since the last call, and how many requests were blocked."""
		with self._lock:
			notices, self._notices = self._notices, []
			blocks, self.blocks = self.blocks, 0
		unique = list(dict.fromkeys(notices))
		if len(unique) > NOTICES_PER_CELL:
			unique = [*unique[:NOTICES_PER_CELL], f'[... {len(unique) - NOTICES_PER_CELL} more blocked navigations]']
		return unique, blocks

	def _send(self, method: str, **params: Any) -> int:
		self._id += 1
		self._ws.send(json.dumps({'id': self._id, 'method': method, 'params': params}))
		return self._id

	def _connect(self) -> None:
		from websockets.sync.client import connect

		self._ws = connect(self.ws_url, max_size=None, open_timeout=GUARD_START_S, close_timeout=1)
		self.pages.clear()
		pending = {
			self._send('Target.setDiscoverTargets', discover=True),
			self._send('Fetch.enable', patterns=[{'urlPattern': '*', 'resourceType': 'Document', 'requestStage': 'Request'}]),
		}
		deadline = time.monotonic() + GUARD_START_S
		while pending:
			msg = json.loads(self._ws.recv(timeout=max(0.1, deadline - time.monotonic())))
			if msg.get('id') in pending:
				if 'error' in msg:
					raise RuntimeError(f'{msg["error"].get("message", msg["error"])}')
				pending.discard(msg['id'])
			else:
				self._handle(msg)

	def _run(self) -> None:
		backoff = 0.5
		while not self._closed.is_set():
			try:
				self._connect()
				self._ready.set()
				backoff = 0.5
				for raw in self._ws:
					self._handle(json.loads(raw))
			except Exception as e:  # - start() reports the first failure; later ones reconnect
				if not self._ready.is_set():
					self._error = str(e) or type(e).__name__
					self._ready.set()
					return
				if not self._closed.is_set():
					logger.debug('domain guard connection lost (%s); reconnecting', e)
			if self._closed.wait(backoff):
				return
			backoff = min(backoff * 2, 5.0)

	def _handle(self, msg: dict) -> None:
		method, params = msg.get('method'), msg.get('params') or {}
		if method in ('Target.targetCreated', 'Target.targetInfoChanged'):
			info = params.get('targetInfo') or {}
			if info.get('type') == 'page':
				self.pages.add(info['targetId'])
		elif method == 'Target.targetDestroyed':
			self.pages.discard(str(params.get('targetId')))
		elif method == 'Fetch.requestPaused':
			url = str((params.get('request') or {}).get('url', ''))
			why = self.rules.blocked(url) if params.get('frameId') in self.pages else None  # iframes pass
			if why:
				with self._lock:
					self.blocks += 1
					self._notices.append(f'[{why}. The browser did not load {url[:120]}]')
				self._send('Fetch.failRequest', requestId=params['requestId'], errorReason='BlockedByClient')
			else:
				self._send('Fetch.continueRequest', requestId=params['requestId'])


def disallowed_tabs(cdp: Callable[..., dict], rules: DomainRules) -> dict[str, str]:
	"""Page tabs that show a disallowed URL -> why. cdp(method, session_id=None, **params) sends one browser command."""
	out = {}
	for t in cdp('Target.getTargets').get('targetInfos', []):
		url = t.get('url') or 'about:blank'  # '': a tab before its first navigation commits
		if t.get('type') == 'page' and (why := rules.blocked(url)):
			out[str(t['targetId'])] = why
	return out


def sweep(cdp: Callable[..., dict], rules: DomainRules, keep: set[str]) -> list[str]:
	"""After a cell: every page tab that shows a disallowed URL is navigated to about:blank (0.x did the same after a
	navigation). keep: tabs that were already open on such a page when the browser started (yours, in
	Browser('chrome')): left alone."""
	notes = []
	for target, why in disallowed_tabs(cdp, rules).items():
		if target in keep:
			continue
		try:
			sid = cdp('Target.attachToTarget', targetId=target, flatten=True)['sessionId']
			try:
				cdp('Page.navigate', session_id=sid, url='about:blank')
			finally:
				with contextlib.suppress(Exception):
					cdp('Target.detachFromTarget', sessionId=sid)
			notes.append(f'[{why}. Tab {target[:8]} showed it; browser-use navigated that tab to about:blank]')
		except Exception as e:
			notes.append(f'[{why}. Tab {target} shows it and could not be reset ({str(e)[:100]}); close it]')
	return notes
