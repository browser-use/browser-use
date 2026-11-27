"""Browser(tokens={...}): the model only ever sees and types a dummy value; the real one is written into a request's
body only when the request leaves the browser for a host the token allows.

	Browser(tokens={
		'card':   {'type': 'card', 'value': pan, 'cvc': cvc, 'exp': '08/29',
		           'hosts': ['shop.example.com', '*.stripe.com'], 'require': {'key': 'pk_live_...'}},
		'ssn':    {'type': 'ssn', 'value': ssn, 'hosts': ['secure.example.gov']},
		'street': {'type': 'text', 'value': '742 Evergreen Terrace', 'hosts': ['shop.example.com']},
	})

Each token gets a dummy per Browser (format-valid: a card keeps its BIN and length and passes Luhn, an SSN is a valid
SSN shape). The agent's prompt lists the dummies; the REPL worker never gets a real value. TokenSwap, in this process
on a browser-level CDP connection of its own (as domains.Guard), pauses requests to the token hosts and writes the real
value over the dummy in the body when all of these hold:
	1. the request's host matches one of the token's hosts ('shop.example.com' exactly, '*.example.com' subdomains
	   only; punycode, on dot boundaries; https, or http to loopback, localhost, *.localhost and *.test);
	2. its Origin (else the Referer's origin) matches one of them too: a page elsewhere that learned the dummy cannot
	   post it to an allowed host;
	3. every 'require' pin is in the form or JSON body or the URL query and equal wherever its name occurs (body,
	   query, a header of that name, duplicate JSON keys), and no credential header names another account; pinned
	   tokens are swapped in form and JSON bodies only. Mandatory for multi-tenant processors (Stripe, Braintree,
	   Adyen, ...): an attacker's own key there would tokenize the real card into the attacker's account.
Only the body is rewritten (a rewritten URL or header shows in the Network events the agent reads). Anything it cannot
match safely goes out as the dummy: a Content-Encoding body, a body without postData (blob, stream) or with a file part
Chrome gives without its bytes, base64 or client-side encrypted fields, a card split over several inputs, WebSocket
frames. A redirect that would re-send a swapped body to a host the token does not allow is failed. Responses of every
type on the token hosts' registrable domains are paused: textual ones masked back, real -> dummy, before the page sees
them; streams and binary bodies holding a real value failed; images, audio, video and fonts passed unread.

Scope: accidental exposure to an aligned model, not a sandbox against a prompt-injected one. Model code runs as your
user: it can talk to the browser-harness daemon socket or Chrome itself (around the worker's deny list), read Chrome's
disk cache or this process's memory. Browser Use Cloud's server-side secure tokens keep the real value out of the
browser entirely.
"""

from __future__ import annotations

import base64
import codecs
import contextlib
import html
import ipaddress
import json
import logging
import random
import re
import time
import urllib.parse
from collections import OrderedDict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from email.message import Message
from typing import TYPE_CHECKING, Any

from browser_use.domains import GUARD_START_S, BrowserFetch, canonical_host, is_ip

logger = logging.getLogger(__name__)
# 0.x's browser_use.tokens was a package (tokens.service, tokens.views): an empty __path__ lets those imports reach the
# 0.x import hook (browser_use/legacy.py), which names result.usage; without it Python stops at "not a package"
__path__: list[str] = []

KINDS = ('card', 'ssn', 'digits', 'iban', 'text')  # 'cvc' is a card's 'cvc' key
KEYS = {
	'card': {'type', 'value', 'hosts', 'require', 'cvc', 'exp'},
	**{k: {'type', 'value', 'hosts', 'require'} for k in KINDS if k != 'card'},
}
# Multi-tenant processors and vaults: anyone can post a card there with their own key. require= is mandatory on these.
# Not complete (no list can be): pin your account with require= on any processor.
MULTI_TENANT = re.compile(
	r'(^|\.)(stripe\.com|stripe\.network|adyen\.com|adyenpayments\.com|checkout\.com|paypal\.com|paypalobjects\.com|'
	r'braintreegateway\.com|braintree[a-z0-9-]*\.com|shopifycs\.com|squareup\.com|squareupsandbox\.com|squarecdn\.com|'
	r'authorize\.net|razorpay\.com|mollie\.com|worldpay\.com|spreedly\.com|verygoodvault\.com|vgs\.io|'
	r'cybersource\.com|recurly\.com|chargebee\.com|paddle\.com|gocardless\.com|klarna\.com|bluesnap\.com|'
	r'nmi\.com|globalpay\.com|paysafe\.com|payu\.com|mercadopago\.com|rapyd\.net|dlocal\.com|xendit\.co|'
	r'flutterwave\.com|paystack\.co|2checkout\.com|evervault\.com|basistheory\.com)$'
)
# '*.' at these is anyone's subdomain (a public suffix, or a hosting platform that hands subdomains to anyone)
OPEN_SUFFIXES = {
	'github.io',
	'gitlab.io',
	'vercel.app',
	'netlify.app',
	'pages.dev',
	'workers.dev',
	'herokuapp.com',
	'appspot.com',
	'web.app',
	'firebaseapp.com',
	'blogspot.com',
	'cloudfront.net',
	'azurewebsites.net',
	'amazonaws.com',
	'onrender.com',
	'fly.dev',
	'glitch.me',
	'repl.co',
	'ngrok.io',
	'ngrok-free.app',
	'trycloudflare.com',
	'surge.sh',
}
HTTP_OK = re.compile(r'(^|\.)(localhost|test)$')  # http (not https) is swapped only to these, loopback IPs and 'localhost'
SEP = r'(?:[ .\-+]|%20|%2[dD])'  # between two characters of a digit or IBAN token: '4242 4242', '123-45-6789', '+'
MAX_SEPS = 3
# Response masking matches more than requests: what servers format a value with. Whitespace (also U+00A0 and its
# entities), dashes (also U+2010-2015 and U+2212), ( ) / . +, JSON escapes and short inline tags ('<b>123</b>-45').
MASK_SEP = (
	r'(?:[\s.\-+()/_\u2010-\u2015\u2212]|%20|%2[dD]|%2[fF]|%28|%29|%C2%A0|%c2%a0|&nbsp;|&#160;|&#[xX]0*[aA]0;|'
	r'\\u00[aA]0|\\u0020|\\u002[dD]|\\[nrt]|</?[A-Za-z][^<>]{0,40}>)'
)
MASK_MAX_SEPS = 6
# between the words of a text value in a response: any run of whitespace, its encodings and inline tags
TEXT_SEP = r'(?:\s|&nbsp;|&#160;|&#[xX]0*[aA]0;|\\u00[aA]0|\\u0020|\\[nrt]|%20|%C2%A0|\+|</?[A-Za-z][^<>]{0,40}>)+'
TEXTUAL = re.compile(
	r'^(text/|application/(json|javascript|x-javascript|ecmascript|xml|xhtml\+xml|x-www-form-urlencoded|'
	r'x-ndjson|ndjson|jsonl|json-seq|x-json|graphql|graphql-response|csv|x-csv|rtf)$|'
	r'application/[\w.+-]+\+(json|xml)$)'
)
MEDIA = re.compile(r'^(image|audio|video|font)/')  # passed without reading the body: a value in pixels is not masked
STREAMING = {'text/event-stream', 'multipart/x-mixed-replace'}  # never complete: failed on the masked sites
# A credential in one of these headers picks the account; a pinned token is not swapped with one that is not pinned.
CREDENTIAL_HEADERS = ('authorization', 'proxy-authorization', 'x-api-key', 'api-key', 'x-auth-token', 'x-client-key')
SAFE_RAW = re.compile(r'[A-Za-z0-9 \-]*')  # needs no escaping in any body
SECOND_LEVEL = {'co', 'com', 'net', 'org', 'gov', 'edu', 'ac', 'or', 'ne', 'go', 'gob', 'mil'}  # example.co.uk

_rng = random.SystemRandom()


# ---------------------------------------------------------------------------------------------------- dummy values


def luhn_ok(digits: str) -> bool:
	total = 0
	for i, ch in enumerate(reversed(digits)):
		d = int(ch)
		if i % 2:
			d = d * 2 - 9 if d > 4 else d * 2
		total += d
	return total % 10 == 0


def _luhn_digit(body: str) -> str:
	"""The check digit that makes body + digit pass Luhn."""
	return next(str(d) for d in range(10) if luhn_ok(body + str(d)))


def _shape(real: str, dummy_chars: str) -> str:
	"""dummy_chars laid out with real's separators: '4242 4242 ...' -> '4242 42xx ...'."""
	it = iter(dummy_chars)
	return ''.join(next(it) if c.isalnum() else c for c in real)


def dummy_card(real: str, rng: random.Random = _rng) -> str:
	"""Same length, the real 6-digit BIN, random middle, a Luhn check digit, and a last 4 that differs from the real one."""
	digits = re.sub(r'\D', '', real)
	while True:
		body = digits[:6] + ''.join(str(rng.randrange(10)) for _ in range(len(digits) - 7))
		dummy = body + _luhn_digit(body)
		if dummy[-4:] != digits[-4:]:
			return _shape(real, dummy)


def dummy_cvc(real: str, rng: random.Random = _rng) -> str:
	while (dummy := ''.join(str(rng.randrange(10)) for _ in real)) == real:
		pass
	return dummy


def dummy_ssn(real: str, rng: random.Random = _rng) -> str:
	"""A valid SSN shape (area 001-899 but not 666, group 01-99, serial 0001-9999), with the input's separators."""
	digits = re.sub(r'\D', '', real)
	while True:
		area = rng.choice([a for a in range(1, 900) if a != 666])
		dummy = f'{area:03d}{rng.randrange(1, 100):02d}{rng.randrange(1, 10000):04d}'
		if dummy != digits:
			return _shape(real, dummy)


def dummy_digits(real: str, rng: random.Random = _rng) -> str:
	digits = re.sub(r'\D', '', real)
	while True:
		dummy = ''.join(str(rng.randrange(10)) for _ in digits)
		if digits[0] != '0' and dummy[0] == '0':
			continue
		if dummy != digits:
			return _shape(real, dummy)


def iban_ok(iban: str) -> bool:
	s = re.sub(r'\s', '', iban).upper()
	if not re.fullmatch(r'[A-Z]{2}\d{2}[A-Z0-9]{11,30}', s):
		return False
	return int(''.join(str(int(c, 36)) for c in s[4:] + s[:4])) % 97 == 1


def dummy_iban(real: str, rng: random.Random = _rng) -> str:
	"""The real country code, random characters of the same classes, and recomputed mod-97 check digits."""
	s = re.sub(r'\s', '', real).upper()
	while True:
		rest = ''.join(str(rng.randrange(10)) if c.isdigit() else rng.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ') for c in s[4:])
		check = 98 - int(''.join(str(int(c, 36)) for c in rest + s[:2] + '00')) % 97
		dummy = f'{s[:2]}{check:02d}{rest}'
		if dummy != s:
			return _shape(real, dummy)


def dummy_text(real: str, rng: random.Random = _rng) -> str:
	"""Words of the same shape in [A-Za-z0-9 -]: digits stay digits, letters keep their case, other characters become
	letters. '742 Evergreen Terrace' -> '318 Qmwpxzkrb Hvtdsqj'."""
	lower, upper = 'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
	while True:
		out = []
		for c in real.strip():
			if c.isspace():
				if out and out[-1] != ' ':
					out.append(' ')
			elif c == '-' or c.isdigit():
				out.append(str(rng.randrange(10)) if c.isdigit() else '-')
			else:
				out.append(rng.choice(upper if c.isupper() else lower))
		dummy = ''.join(out).strip()
		if dummy.lower() not in real.lower() and real.lower() not in dummy.lower():
			return dummy


# ---------------------------------------------------------------------------------------------------- host rules


@dataclass(frozen=True)
class Host:
	host: str  # canonical, without the '*.'
	subdomains: bool  # '*.example.com': subdomains only
	port: str  # '' = any port

	@classmethod
	def parse(cls, entry: Any, where: str) -> Host:
		if not isinstance(entry, str) or not entry.strip():
			raise TypeError(f"{where}: every host must be a non-empty string such as 'shop.example.com' or '*.stripe.com'")
		e = entry.strip().lower()
		if '://' in e or '/' in e or '@' in e:
			raise ValueError(f"{where}: {entry!r} must be a host ('shop.example.com', '*.stripe.com'), not a URL")
		subdomains = e.startswith('*.')
		if subdomains:
			e = e[2:]
		if m := re.fullmatch(r'\[([0-9a-f:.]+)\](?::(\d+))?', e):  # '[::1]', '[::1]:8443'
			host, port = m[1], m[2] or ''
		elif e.count(':') > 1:  # a bare IPv6 address has no port
			host, port = e, ''
		else:
			host, _, port = e.rpartition(':') if re.search(r':\d+$', e) else (e, '', '')
		if '*' in host or not host or (port and not port.isdigit()) or (':' in host and not is_ip(host)):
			raise ValueError(f"{where}: {entry!r}: only a leading '*.' is allowed ('*.stripe.com')")
		host = canonical_host(host)
		if subdomains and (is_ip(host) or '.' not in host or _open_suffix(host)):
			raise ValueError(
				f"{where}: {entry!r} would allow anyone's site: '*.' needs a domain you trust with every subdomain, "
				"such as '*.stripe.com', not a public suffix ('*.com', '*.co.uk') or a hosting platform ('*.github.io')"
			)
		return cls(host, subdomains, port)

	def pattern(self) -> str:
		"""The host as a Fetch urlPattern host part."""
		host = f'[{self.host}]' if ':' in self.host else self.host
		return f'{"*." if self.subdomains else ""}{host}{":" + self.port if self.port else ""}'

	def matches(self, host: str, port: str) -> bool:
		if self.port and port != self.port:
			return False
		return host.endswith(f'.{self.host}') if self.subdomains else host == self.host


def _open_suffix(host: str) -> bool:
	"""A public suffix ('com', 'co.uk', 'test') or a platform whose subdomains anyone can get ('github.io')."""
	labels = host.split('.')
	if len(labels) == 2 and len(labels[-1]) == 2 and labels[0] in SECOND_LEVEL:
		return True
	return host in OPEN_SUFFIXES or host.endswith('.amazonaws.com')  # s3, elb, ...: per-region buckets anyone can make


def http_ok(host: str) -> bool:
	"""http (not https) carries a real value only to the local machine or a reserved test name."""
	if is_ip(host):
		return ipaddress.ip_address(host).is_loopback
	return host == 'localhost' or bool(HTTP_OK.search(host))


def _url_host(url: str) -> tuple[str, str, str] | None:
	"""(scheme, canonical host, port with the scheme's default filled in) or None."""
	try:
		u = urllib.parse.urlsplit(url)
		port = u.port
	except ValueError:
		return None
	if not u.hostname or u.scheme not in ('http', 'https'):
		return None
	return u.scheme, canonical_host(u.hostname), str(port or (443 if u.scheme == 'https' else 80))


def hosts_allow(hosts: Iterable[Host], url: str) -> bool:
	parsed = _url_host(url)
	if parsed is None:
		return False
	scheme, host, port = parsed
	if scheme == 'http' and not http_ok(host):
		return False
	return any(h.matches(host, port) for h in hosts)


def registrable(host: str) -> str:
	"""The site a host belongs to, for response masking: 'api.shop.example.co.uk' -> 'example.co.uk'. A heuristic
	(no public suffix list): a wider guess only masks more responses."""
	if is_ip(host):
		return host
	labels = host.split('.')
	if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in SECOND_LEVEL:
		return '.'.join(labels[-3:])
	return '.'.join(labels[-2:])


# ---------------------------------------------------------------------------------------------------- bodies


def body_kind(content_type: str, text: str = '') -> str:
	"""form | json | multipart | xml | text | unknown. A text/plain body that parses as JSON (no-cors fetches and beacons
	send JSON that way) is json."""
	ct = content_type.split(';', 1)[0].strip().lower()
	if ct == 'application/x-www-form-urlencoded':
		return 'form'
	if ct == 'application/json' or ct.endswith('+json'):
		return 'json'
	if ct == 'multipart/form-data':
		return 'multipart'
	if ct in ('text/xml', 'text/html', 'application/xml', 'application/xhtml+xml') or ct.endswith('+xml'):
		return 'xml'
	if ct.startswith('text/'):
		if text.lstrip()[:1] in ('{', '['):
			with contextlib.suppress(ValueError):
				json.loads(text)
				return 'json'
		return 'text'
	return 'unknown'


def encode_for(kind: str, real: str, space: str | None) -> str | None:
	"""The real value as it must sit in a body of this kind; None when it cannot be written safely (plain text and
	unknown types: only a value that needs no escaping anywhere)."""
	if kind == 'form':
		quoted = urllib.parse.quote(real, safe='')
		return quoted.replace('%20', '+') if space in (None, '+') else quoted
	if kind == 'json':
		return json.dumps(real, ensure_ascii=False)[1:-1]
	if kind == 'xml':
		return html.escape(real, quote=True)
	if kind == 'multipart':
		return real
	return real if SAFE_RAW.fullmatch(real) else None


def _headers(headers: dict[str, Any]) -> dict[str, str]:
	return {str(k).lower(): str(v) for k, v in (headers or {}).items()}


def _form_pairs(text: str) -> list[tuple[str, str]]:
	"""Form pairs split on '&' and also on ';' (servers that split on both see 'a=1;key=x' as key=x)."""
	return [
		*urllib.parse.parse_qsl(text, keep_blank_values=True),
		*urllib.parse.parse_qsl(text, keep_blank_values=True, separator=';'),
	]


def field_values(kind: str, text: str) -> list[tuple[str, str]] | None:
	"""(name, value) of every field a server could read a pin from: form pairs, every top-level JSON key (a duplicate
	key is kept twice: servers differ on which one wins). None for a body a pin cannot be checked in."""
	if kind == 'form':
		return _form_pairs(text)
	if kind == 'json':
		try:
			data = json.loads(text, object_pairs_hook=lambda pairs: pairs)
		except ValueError:
			return None
		if not isinstance(data, list) or not all(isinstance(p, tuple) for p in data):
			return None  # a top-level array or scalar
		return [(k, v if isinstance(v, str) else json.dumps(v)) for k, v in data]
	return None


# ---------------------------------------------------------------------------------------------------- tokens


@dataclass
class Token:
	name: str  # 'card', 'card.cvc'
	kind: str  # card | cvc | ssn | digits | iban | text
	real: str = field(repr=False)  # digit kinds: digits only; iban: upper-case alphanumerics; text: as given
	dummy: str  # as the model sees and types it
	hosts: tuple[Host, ...]
	require: tuple[tuple[str, str], ...] = ()
	anchor: str | None = None  # cvc: swapped only in a request that also carries this card's number
	_find: re.Pattern = field(init=False, repr=False)  # the dummy in a request body
	_mask: re.Pattern | None = field(init=False, repr=False)  # the real value in a response

	def __post_init__(self) -> None:
		chars = re.sub(r'[^A-Za-z0-9]', '', self.dummy)
		if self.kind == 'text':
			self._find = _text_pattern(self.dummy)
			self._mask = _text_mask_pattern(self.real)
		else:
			self._find = _char_pattern(chars, alnum=self.kind == 'iban')
			self._mask = None if self.kind == 'cvc' else _mask_char_pattern(self.real, alnum=self.kind == 'iban')

	def __reduce__(self):  # pickle, copy: a real value never leaves this process in a pickle
		raise TypeError('Browser(tokens=...) values are not picklable')


def _char_pattern(chars: str, alnum: bool) -> re.Pattern:
	"""Each character a group, up to MAX_SEPS separators between them, on digit (or alphanumeric) boundaries."""
	edge = '[A-Za-z0-9]' if alnum else r'\d'
	parts = [f'([{c.lower()}{c.upper()}])' if c.isalpha() else f'({c})' for c in chars]
	return re.compile(rf'(?<!{edge})' + f'{SEP}{{0,{MAX_SEPS}}}'.join(parts) + rf'(?!{edge})')


def _mask_char_pattern(chars: str, alnum: bool) -> re.Pattern:
	"""As _char_pattern, for a response: each character also JSON-escaped ('\\u0031'), and MASK_SEP between."""

	def alts(c: str) -> str:
		codes = {f'{ord(v):04x}' for v in {c.lower(), c.upper()}}
		esc = '|'.join(rf'\\u{"".join(f"[{h.lower()}{h.upper()}]" if h.isalpha() else h for h in code)}' for code in codes)
		return f'([{c.lower()}{c.upper()}]|{esc})' if c.isalpha() else f'({c}|{esc})'

	edge = '[A-Za-z0-9]' if alnum else r'\d'
	return re.compile(rf'(?<!{edge})' + f'{MASK_SEP}{{0,{MASK_MAX_SEPS}}}'.join(map(alts, chars)) + rf'(?!{edge})')


def _char_forms(c: str) -> str:
	"""A regex for one character of a text value as a response may carry it: itself, JSON-, HTML- or URL-encoded."""
	o = ord(c)
	forms = {
		re.escape(c),
		re.escape(json.dumps(c)[1:-1]),
		re.escape(json.dumps(c, ensure_ascii=False)[1:-1]),
		rf'\\u0*{o:x}',
		re.escape(html.escape(c, quote=True)),
		f'&#0*{o};',
		f'&#x0*{o:x};',
		re.escape(urllib.parse.quote(c, safe='')),
	}
	forms |= {'&apos;'} if c == "'" else {r'\\/'} if c == '/' else set()
	return '(?:' + '|'.join(sorted(forms, key=len, reverse=True)) + ')'


def _text_mask_pattern(real: str) -> re.Pattern:
	"""A text value in a response: its words, each character in any encoding, case-insensitive; any run of whitespace
	(or its entities and escapes, '+', inline tags) between them. Each word is a group: masking keeps the separators."""
	words = real.split()
	body = TEXT_SEP.join('(' + ''.join(map(_char_forms, w)) + ')' for w in words)
	return re.compile(r'(?<![A-Za-z0-9])' + body + r'(?![A-Za-z0-9])', re.IGNORECASE)


def _text_pattern(dummy: str) -> re.Pattern:
	"""Case-insensitive; a space as ' ', '+' or '%20' (the first one is captured as 'space'), '-' also as %2D."""
	out, first = [], True
	for c in dummy:
		if c == ' ':
			out.append('(?P<space> |\\+|%20)' if first else '(?: |\\+|%20)')
			first = False
		elif c == '-':
			out.append('(?:-|%2[dD])')
		else:
			out.append(re.escape(c))
	return re.compile(r'(?<![A-Za-z0-9])' + ''.join(out) + r'(?![A-Za-z0-9])', re.IGNORECASE)


def _write_chars(m: re.Match, chars: str) -> str:
	"""The match with each character group replaced by the next of chars (letters in the matched case), separators
	kept."""
	text, start, out = m.group(0), m.start(), []
	pos = 0
	for i, c in enumerate(chars, 1):
		s, e = m.span(i)
		out.append(text[pos : s - start])
		got = text[s - start : e - start]
		out.append(c if got.startswith('\\') else c.lower() if got.islower() else c.upper() if c.isalpha() else c)
		pos = e - start
	out.append(text[pos:])
	return ''.join(out)


def _cased(matched: str, real: str) -> str:
	letters = [c for c in matched if c.isalpha()]
	if letters and all(c.isupper() for c in letters):
		return real.upper()
	if letters and all(c.islower() for c in letters) and any(c.isupper() for c in real):
		return real.lower()
	return real


def _write_words(m: re.Match, real: str, dummy: str) -> str:
	"""A text value's match with each word group replaced by the dummy's word, in the case of the whole match;
	the separators (whitespace, entities, tags) kept."""
	cased = _cased(re.sub(r'&#?\w+;|\\u[0-9a-fA-F]{4}|\\[nrt]|%[0-9a-fA-F]{2}|<[^>]*>', '', m.group(0)), dummy)
	words = cased.split(' ')
	if len(words) != len(m.groups()):  # not one dummy word per real word: the whole match
		return cased
	text, start, out, pos = m.group(0), m.start(), [], 0
	for i, word in enumerate(words, 1):
		s, e = m.span(i)
		out.append(text[pos : s - start])
		out.append(word)
		pos = e - start
	out.append(text[pos:])
	return ''.join(out)


def _whole_value(kind: str, dummy: str) -> re.Pattern | None:
	"""A cvc as a whole field value only."""
	d = re.escape(dummy)
	if kind == 'form':
		return re.compile(rf'(?<=[=])({d})(?=&|$)')
	if kind == 'json':
		return re.compile(rf'(?<=[:\[,])(\s*"?)({d})("?\s*)(?=[,}}\]])')
	if kind == 'multipart':
		return re.compile(rf'(?<=\r\n\r\n)({d})(?=\r\n--)')
	return None


class Tokens:
	"""The validated tokens= of one Browser, with their dummies."""

	def __init__(self, tokens: list[Token]):
		self.tokens = tokens
		self.exp: dict[str, str] = {}  # card name -> its expiry (not tokenized: the model gets the real one)

	def __bool__(self) -> bool:
		return bool(self.tokens)

	def __repr__(self) -> str:  # tracebacks with locals, debug logs: names and dummies only
		return f'Tokens({", ".join(f"{t.name}={t.dummy!r}" for t in self.tokens)})'

	def __reduce__(self):
		raise TypeError('Browser(tokens=...) values are not picklable')

	def named(self, names: Iterable[str]) -> list[Token]:
		want = set(names)
		return [t for t in self.tokens if t.name in want]

	@classmethod
	def of(cls, config: Any, rng: random.Random = _rng) -> Tokens:
		if config is None:
			return cls([])
		if not isinstance(config, dict):
			raise TypeError("Browser(tokens=...) takes a dict: {'card': {'type': 'card', 'value': '...', 'hosts': [...]}}")
		out: list[Token] = []
		exp: dict[str, str] = {}
		for name, spec in config.items():
			where = f'Browser(tokens={{{name!r}: ...}})'
			if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,40}', name):
				raise ValueError(f'Browser(tokens=...): token names are identifiers such as card or ssn, not {name!r}')
			if not isinstance(spec, dict):
				raise TypeError(f"{where} takes a dict with 'type', 'value' and 'hosts'")
			kind = spec.get('type')
			if kind not in KINDS:
				raise ValueError(f"{where}: 'type' must be one of {', '.join(KINDS)}, not {kind!r}")
			if unknown := set(spec) - KEYS[kind]:
				raise TypeError(f'{where}: unknown key(s) {", ".join(sorted(map(str, unknown)))} for type {kind!r}')
			value = spec.get('value')
			if not isinstance(value, str) or not value.strip():
				raise TypeError(f"{where}: 'value' must be a non-empty string")
			raw_hosts = spec.get('hosts')
			if isinstance(raw_hosts, str) or not isinstance(raw_hosts, list | tuple) or not raw_hosts:
				raise TypeError(f"{where}: 'hosts' must be a non-empty list such as ['shop.example.com', '*.stripe.com']")
			hosts = tuple(Host.parse(h, where) for h in raw_hosts)
			require = spec.get('require') or {}
			if not isinstance(require, dict) or not all(
				isinstance(k, str) and isinstance(v, str) and k and v for k, v in require.items()
			):
				raise TypeError(f"{where}: 'require' must map field names to exact values, e.g. {{'key': 'pk_live_...'}}")
			if not require and (tenant := next((h for h in hosts if MULTI_TENANT.search(h.host)), None)):
				raise ValueError(
					f"{where}: {tenant.host} is a multi-tenant payment processor: anyone's key there would get the real value. "
					"Pin your own account with require=, e.g. {'key': 'pk_live_...'} (an exact field or header value every "
					'request must carry).'
				)
			pins = tuple(require.items())
			real, dummy = _real_and_dummy(kind, value.strip(), where, rng)
			out.append(Token(name, kind, real, dummy, hosts, pins))
			if kind == 'card':
				cvc = spec.get('cvc')
				if cvc is not None:
					if not isinstance(cvc, str) or not re.fullmatch(r'\d{3,4}', cvc.strip()):
						raise ValueError(f"{where}: 'cvc' must be 3 or 4 digits")
					out.append(Token(f'{name}.cvc', 'cvc', cvc.strip(), dummy_cvc(cvc.strip(), rng), hosts, pins, anchor=name))
				if (e := spec.get('exp')) is not None:
					if not isinstance(e, str) or not e.strip():
						raise TypeError(f"{where}: 'exp' must be a string such as '08/29'")
					exp[name] = e.strip()
		dummies = [t.dummy for t in out]
		if len(set(dummies)) != len(dummies):  # 3-digit cvcs of two cards
			return cls.of(config, rng)
		tokens = cls(out)
		tokens.exp = exp
		return tokens

	# -------------------------------------------------------------------------------- what the model sees

	def dummies(self) -> dict[str, str]:
		"""{'card': '4242 4291 ...', 'card.cvc': '381', 'card.exp': '08/29' (real: not tokenized), ...}."""
		out = {t.name: t.dummy for t in self.tokens}
		out.update({f'{name}.exp': e for name, e in self.exp.items()})
		return out

	def prompt(self) -> str:
		"""One system-prompt paragraph; '' without tokens."""
		if not self:
			return ''
		lines = []
		for t in self.tokens:
			sites = ', '.join(h.pattern() for h in t.hosts)
			lines.append(f'{t.name} ({t.kind}): {json.dumps(t.dummy)} (only for {sites})')
		lines += [f'{name}.exp (card expiry, the real value): {json.dumps(e)}' for name, e in self.exp.items()]
		return (
			'Sensitive values the user provided, as stand-ins: type these exact values into the form fields with your '
			'normal typing helpers; the browser substitutes the real values when the form is submitted to the listed '
			'sites, and pages show the stand-ins back. Use them only on those sites. Never ask for, guess or look for the '
			'real values.\n' + '\n'.join(f'- {line}' for line in lines)
		)

	# -------------------------------------------------------------------------------- interception

	def fetch_patterns(self) -> list[dict[str, str]]:
		"""Fetch.enable patterns: every request to a token host (Request stage), and every response of any type on their
		registrable domains (Response stage: masking, and a swapped request's redirect). Glob patterns only narrow what
		pauses; every rule is checked again in code."""
		hosts = {h for t in self.tokens for h in t.hosts}
		patterns = [
			{'urlPattern': f'*://{h.pattern()}*', 'requestStage': 'Request'}
			for h in sorted(hosts, key=lambda h: (h.host, h.subdomains, h.port))
		]
		for site in sorted(self.mask_domains()):
			site = f'[{site}]' if ':' in site else site
			patterns += [{'urlPattern': f'*://{host}*', 'requestStage': 'Response'} for host in (site, f'*.{site}')]
		return patterns

	def mask_domains(self) -> set[str]:
		return {registrable(h.host) for t in self.tokens for h in t.hosts}

	def swap(self, url: str, headers: dict[str, Any], body: bytes) -> tuple[bytes, list[str]] | None:
		"""The body with real values over the dummies this request may carry, and their names; None to send it as it
		is (nothing to swap, or a rule refused)."""
		h = _headers(headers)
		if h.get('content-encoding', 'identity').strip().lower() not in ('', 'identity'):
			return None  # gzip/br: the dummy is not in the bytes we see
		origin = h.get('origin')
		if not origin or origin == 'null':
			ref = urllib.parse.urlsplit(h.get('referer', ''))
			origin = f'{ref.scheme}://{ref.netloc}' if ref.scheme and ref.netloc else ''
		text = body.decode('utf-8', 'surrogateescape')
		kind = body_kind(h.get('content-type', ''), text)
		fields: list[tuple[str, str]] | None = None
		swapped: list[str] = []
		for t in self.tokens:
			if t.anchor is not None or not t._find.search(text):
				continue
			if not (hosts_allow(t.hosts, url) and origin and hosts_allow(t.hosts, origin + '/')):
				continue
			if t.require:
				if fields is None:
					fields = field_values(kind, text)
				if fields is None or not _pins_ok(t.require, fields, _form_pairs(urllib.parse.urlsplit(url).query), h):
					continue
			new = self._swap_one(t, kind, text)
			if new is not None and new != text:
				text = new
				swapped.append(t.name)
		for t in self.tokens:  # cvcs: whole field values, in a request that carries their card
			if t.anchor in swapped and (p := _whole_value(kind, t.dummy)) and p.search(text):
				text = p.sub(lambda m: m.group(0).replace(t.dummy, t.real), text)
				swapped.append(t.name)
		if not swapped:
			return None
		return text.encode('utf-8', 'surrogateescape'), swapped

	@staticmethod
	def _swap_one(t: Token, kind: str, text: str) -> str | None:
		if t.kind == 'text':
			failed = False

			def write(m: re.Match) -> str:
				nonlocal failed
				real = encode_for(kind, _cased(m.group(0), t.real), m.groupdict().get('space'))
				if real is None:
					failed = True
					return m.group(0)
				return real

			new = t._find.sub(write, text)
			return None if failed else new
		return t._find.sub(lambda m: _write_chars(m, t.real), text)

	def mask_text(self, text: str) -> str:
		"""Real -> dummy in a response (or any text): digit runs with the separators servers format them with, text
		values word by word with any whitespace between, in any case; JSON-, HTML- and URL-encoded characters too."""
		for t in self.tokens:
			if t._mask is None:
				continue
			if t.kind == 'text':
				text = t._mask.sub(lambda m, t=t: _write_words(m, t.real, t.dummy), text)
			else:
				dummy_chars = re.sub(r'[^A-Za-z0-9]', '', t.dummy)
				text = t._mask.sub(lambda m, d=dummy_chars: _write_chars(m, d), text)
		return text

	def mask_bytes(self, body: bytes, charset: str | None = None) -> bytes:
		codec = 'utf-8'
		if charset:
			with contextlib.suppress(LookupError):
				codec = codecs.lookup(charset).name
		try:
			return self.mask_text(body.decode(codec, 'surrogateescape')).encode(codec, 'surrogateescape')
		except (UnicodeError, LookupError):  # a codec that cannot round-trip: the UTF-8 bytes directly
			return self.mask_text(body.decode('utf-8', 'surrogateescape')).encode('utf-8', 'surrogateescape')


def _pins_ok(
	require: tuple[tuple[str, str], ...], fields: list[tuple[str, str]], query: list[tuple[str, str]], headers: dict[str, str]
) -> bool:
	"""Every pin is in the body or the URL query (a credential header pin: in that header), equal wherever its name
	occurs (body, query, header); and no credential header the pins do not name: a server could pick the account from
	any of these, so all of them must agree."""
	pinned = {name.lower() for name, _ in require}
	if any(h in headers and h not in pinned for h in CREDENTIAL_HEADERS):
		return False
	for name, want in require:
		got = [v for k, v in (*fields, *query) if k == name]
		if name.lower() in CREDENTIAL_HEADERS and name.lower() not in headers:
			return False
		if not got and name.lower() not in CREDENTIAL_HEADERS:
			return False  # only in a header of its own name: a server need not read it there
		if name.lower() in headers:
			got.append(headers[name.lower()])
		if not got or any(v != want for v in got):
			return False
	return True


def _real_and_dummy(kind: str, value: str, where: str, rng: random.Random) -> tuple[str, str]:
	"""The real value as it is matched (digits only for digit kinds) and a dummy shaped like the input."""
	if kind in ('card', 'ssn', 'digits'):
		if not re.fullmatch(r'\d[\d \-.]*\d', value):
			raise ValueError(f"{where}: a {kind} value is digits, optionally with spaces, '-' or '.'")
		digits = re.sub(r'\D', '', value)
		if kind == 'card' and not 12 <= len(digits) <= 19:
			raise ValueError(f'{where}: a card number has 12 to 19 digits, not {len(digits)}')
		if kind == 'ssn' and len(digits) != 9:
			raise ValueError(f'{where}: an SSN has 9 digits, not {len(digits)}')
		if kind == 'digits' and len(digits) < 6:
			raise ValueError(f'{where}: a digits value needs at least 6 digits (a shorter one would match by chance)')
		make = {'card': dummy_card, 'ssn': dummy_ssn, 'digits': dummy_digits}[kind]
		return digits, make(value, rng)
	if kind == 'iban':
		if not iban_ok(value):
			raise ValueError(f'{where}: not a valid IBAN (country code, check digits, 11-30 characters)')
		return re.sub(r'\s', '', value).upper(), dummy_iban(value, rng)
	if len(re.sub(r'\s', '', value)) < 8:
		raise ValueError(f'{where}: a text value needs at least 8 non-space characters (a shorter one is not worth hiding)')
	return value, dummy_text(value, rng)


# ---------------------------------------------------------------------------------------------------- interceptor


class TokenSwap(BrowserFetch):
	"""Writes real values into request bodies to the token hosts and masks them out of responses, for every tab,
	iframe and service worker: browser-level Fetch.enable with patterns built only from the token hosts, on a CDP
	connection of its own.

	Chrome applies a browser-level interception only to documents loaded after it starts: on every (re)connect, before
	start() returns, tabs and iframes that show a page on a masked site are navigated again (a GET of their URL), so
	no page keeps fetching unmasked responses. Requests: anything this cannot handle goes out as it is (the dummy).
	Responses on the masked sites: textual ones are masked; images, audio, video and fonts pass unread; a stream, or a
	binary body that holds a real value, is failed; a masking error fails it. A redirect that would carry a swapped
	body (307, 308) to a host the token does not allow is failed."""

	what = 'Browser(tokens=...)'
	thread_name = 'browser-use-tokens'

	def __init__(self, ws_url: str, tokens: Tokens, on_response: Callable[[str, bytes], object] | None = None):
		super().__init__(ws_url)
		self.tokens = tokens
		self.swaps = 0  # requests that carried a real value
		self.masked = 0  # responses with a real value masked
		self.failed = 0  # responses and redirects failed instead of passed
		self.renavigated = 0  # tabs and frames navigated again on a (re)connect
		self._on_response = on_response  # tests and the live check: (url, body before masking)
		self._swapped: OrderedDict[str, tuple[str, ...]] = OrderedDict()  # requestId -> tokens written into it

	def _setup(self) -> list[tuple[str, dict[str, Any]]]:
		self._swapped.clear()
		return [('Fetch.enable', {'patterns': self.tokens.fetch_patterns()})]

	def _connected(self) -> None:
		"""Navigate again every tab and frame showing a page on a masked site: it was loaded before this interception
		(or during a reconnect) and Chrome would not intercept what it fetches."""
		sites = self.tokens.mask_domains()
		deadline = time.monotonic() + GUARD_START_S
		targets = self._call('Target.getTargets', deadline).get('targetInfos', [])
		for t in targets:
			url = str(t.get('url') or '')
			parsed = _url_host(url)
			if t.get('type') not in ('page', 'iframe') or parsed is None or registrable(parsed[1]) not in sites:
				continue
			try:
				sid = self._call('Target.attachToTarget', deadline, targetId=t['targetId'], flatten=True)['sessionId']
				self._send(
					'Page.navigate', sid, lambda _r, sid=sid: self._send('Target.detachFromTarget', sessionId=sid), url=url
				)
				self.renavigated += 1
			except Exception as e:  # - a tab that closed meanwhile
				logger.debug('Browser(tokens=...): could not navigate %s again (%s)', url[:80], e)
		if self.renavigated:
			logger.info(f'Browser(tokens=...): navigated {self.renavigated} open page(s) on the token sites again')

	def _call(self, method: str, deadline: float, session_id: str | None = None, **params: Any) -> dict:
		"""One command, answered before the next: while setting up, before the event loop runs."""
		mid = self._send(method, session_id, **params)
		while True:
			msg = json.loads(self._ws.recv(timeout=max(0.1, deadline - time.monotonic())))
			if msg.get('id') == mid:
				if 'error' in msg:
					raise RuntimeError(str(msg['error'].get('message', msg['error'])))
				return msg.get('result') or {}
			self._dispatch(msg)

	def _handle(self, msg: dict) -> None:
		if msg.get('method') != 'Fetch.requestPaused':
			return
		p = msg.get('params') or {}
		rid = p['requestId']
		try:
			if 'responseStatusCode' in p or 'responseErrorReason' in p:
				self._response(p)
			else:
				self._request(p)
		except Exception as e:  # - a request goes out as it is (the dummy); a response is failed (never unmasked)
			logger.warning('Browser(tokens=...): %s on %s', type(e).__name__, str(p.get('request', {}).get('url'))[:80])
			if 'responseStatusCode' in p:
				self._fail(rid)
			else:
				self._send('Fetch.continueRequest', requestId=rid)

	def _request(self, p: dict) -> None:
		req = p.get('request') or {}
		entries = req.get('postDataEntries') or []
		# a part Chrome gives without its bytes (a file chosen from disk): a rewritten body would drop it
		whole = all('bytes' in e for e in entries)
		body = _post_body(req) if whole else b''
		out = self.tokens.swap(str(req.get('url', '')), req.get('headers') or {}, body) if body else None
		inherited = self._swapped.get(str(p.get('redirectedRequestId') or ''), ())
		if out is None:
			if inherited:
				self._remember(p['requestId'], inherited)
			self._send('Fetch.continueRequest', requestId=p['requestId'])
			return
		new, names = out
		self._remember(p['requestId'], (*inherited, *names))
		with self._lock:
			self.swaps += 1
		host = (_url_host(str(req.get('url', ''))) or ('', '?', ''))[1]
		logger.info(f'Browser(tokens=...): wrote {", ".join(names)} into a request to {host}')
		self._send('Fetch.continueRequest', requestId=p['requestId'], postData=base64.b64encode(new).decode())

	def _remember(self, rid: str, names: tuple[str, ...]) -> None:
		self._swapped[rid] = names
		while len(self._swapped) > 1000:  # requests that never reached their response (aborted, failed)
			self._swapped.popitem(last=False)

	def _fail(self, rid: str) -> None:
		with self._lock:
			self.failed += 1
		self._send('Fetch.failRequest', requestId=rid, errorReason='BlockedByClient')

	def _redirect_leaks(self, p: dict, status: int, headers: list[dict]) -> bool:
		"""A redirect Chrome follows with the same body (307, 308; 301 and 302 except for a POST) to a URL the tokens in
		that body do not allow."""
		req = p.get('request') or {}
		method = str(req.get('method', 'GET')).upper()
		if not (status in (307, 308) or (status in (301, 302) and method != 'POST')):
			return False
		location = next((str(h.get('value', '')) for h in headers if str(h.get('name', '')).lower() == 'location'), '')
		if not location:
			return False
		target = urllib.parse.urljoin(str(req.get('url', '')), location)
		body = _post_body(req).decode('utf-8', 'surrogateescape')
		names = set(self._swapped.get(p['requestId'], ()))
		carried = [t for t in self.tokens.tokens if t.name in names or (body and t._mask is not None and t._mask.search(body))]
		return any(not hosts_allow(t.hosts, target) for t in carried)

	def _response(self, p: dict) -> None:
		rid, status = p['requestId'], int(p.get('responseStatusCode') or 0)
		headers = p.get('responseHeaders') or []
		if 'responseErrorReason' in p and 'responseStatusCode' not in p:
			self._swapped.pop(rid, None)
			self._send('Fetch.continueRequest', requestId=rid)
			return
		url = str((p.get('request') or {}).get('url', ''))
		if 300 <= status < 400 and self._redirect_leaks(p, status, headers):
			self._swapped.pop(rid, None)
			logger.warning(
				f'Browser(tokens=...): failed a {status} redirect from {url[:80]}: it would re-send real values elsewhere'
			)
			self._fail(rid)
			return
		if not 300 <= status < 400:
			self._swapped.pop(rid, None)
		# the body Fetch.getResponseBody returns is decoded: its length and encoding headers no longer apply
		kept = [h for h in headers if str(h.get('name', '')).lower() not in ('content-length', 'content-encoding')]
		masked_headers = [{'name': h['name'], 'value': self.tokens.mask_text(str(h.get('value', '')))} for h in kept]
		headers_changed = any(m['value'] != str(h.get('value', '')) for m, h in zip(masked_headers, kept, strict=True))
		masked_all = [{'name': h['name'], 'value': self.tokens.mask_text(str(h.get('value', '')))} for h in headers]
		ctype = next((str(h.get('value', '')) for h in headers if h['name'].lower() == 'content-type'), '')
		mime = ctype.split(';', 1)[0].strip().lower()

		def pass_unread() -> None:  # the body as it is; headers masked
			if headers_changed:
				self._send('Fetch.continueResponse', requestId=rid, responseCode=status, responseHeaders=masked_all)
			else:
				self._send('Fetch.continueRequest', requestId=rid)

		if 300 <= status < 400 or MEDIA.match(mime):  # a redirect's body is never shown; pixels are not masked
			pass_unread()
			return
		if mime in STREAMING:  # never complete: getResponseBody would hold it forever
			logger.warning(f'Browser(tokens=...): failed a {mime} response from {url[:80]}: a stream cannot be masked')
			self._fail(rid)
			return
		textual = not mime or bool(TEXTUAL.match(mime))
		m = Message()
		m['content-type'] = ctype or 'text/plain'
		charset = m.get_param('charset')

		def got(result: dict) -> None:
			try:
				raw = base64.b64decode(result['body']) if result.get('base64Encoded') else str(result['body']).encode()
				if self._on_response is not None:
					self._on_response(url, raw)
				body = self.tokens.mask_bytes(raw, charset if isinstance(charset, str) else None)
				if body == raw:
					pass_unread()
					return
				if not textual:  # a PDF, a zip, protobuf: a value in it cannot be rewritten safely
					logger.warning(f'Browser(tokens=...): failed a {mime} response from {url[:80]}: it holds a real value')
					self._fail(rid)
					return
				with self._lock:
					self.masked += 1
				self._fulfill(rid, status, masked_headers, body)
			except Exception as e:  # - failed, never passed through unmasked
				logger.warning('Browser(tokens=...): could not mask a response from %s (%s)', url[:80], type(e).__name__)
				self._fail(rid)

		def no_body(error: dict) -> None:  # 204, HEAD, a body Chrome no longer has: nothing to mask but headers
			pass_unread()

		self._send('Fetch.getResponseBody', reply=got, error=no_body, requestId=rid)

	def _fulfill(self, rid: str, status: int, headers: list[dict], body: bytes) -> None:
		self._send(
			'Fetch.fulfillRequest',
			requestId=rid,
			responseCode=status or 200,
			responseHeaders=headers,
			body=base64.b64encode(body).decode(),
		)


def _post_body(req: dict) -> bytes:
	"""A paused request's body, from its postDataEntries."""
	return b''.join(base64.b64decode(e.get('bytes') or '') for e in req.get('postDataEntries') or [])


if not TYPE_CHECKING:  # pyright would accept any name imported from here
	from browser_use.legacy import removed_names

	__getattr__ = removed_names(__name__)  # 0.x browser_use.tokens was cost tracking: from it, the removed error
