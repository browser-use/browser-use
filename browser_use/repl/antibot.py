"""Anti-bot block detection in the REPL worker: which vendor walled which page, and whether the page got through.

A port of the cloud driver's blockdetect rules (detector_version 1, the header and title/DOM subset), so cloud and local
runs use one vendor and outcome enum. It reads only what CDP gives without running script in the page: the main
document's status and headers (Network.responseReceived, already in the daemon's event stream), the tab's title
(Target.getTargetInfo) and selector and text hits (DOM.performSearch, CSS or XPath, which walks the DOM in Chrome and
never runs page JS). Our cloud browsers also classify each walled visit and send BrowserUse.blockDetected: its verdict
replaces the local one of that visit.

Outcomes: ok, passed (challenged, then got through), blocked, stuck (still on a challenge or captcha), rate_limited, geo,
auth_wall, queue. WALLS are the ones that left the user in front of a wall.
"""

from __future__ import annotations

import re
import threading
import time
import urllib.parse
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

DETECTOR_VERSION = 1
WALLS = ('blocked', 'stuck', 'rate_limited')
BLOCK_EVENT = 'BrowserUse.blockDetected'
MERGE_WINDOW_S = 30.0  # a same-site document this soon after a walled one is the same visit (the challenge clearing)
MAX_STATUSES = 8
MAX_VISITS = 200  # documents of frames never shown to be top frames (same-process iframes) are dropped past this
PROBE_BUDGET_S = 5.0  # one cell-end probe; a page too busy to answer in time is probed again after the next cell
PROBE_CALL_S = 3.0  # a loaded machine's daemon can take over 1 s to answer; a miss loses the verdict once the agent moves on
CHALLENGE_STATUSES = (202, 401, 403, 405, 428, 429, 503)
NAMES = {
	'akamai': 'Akamai',
	'amazon': 'Amazon',
	'arkose': 'Arkose Labs',
	'awswaf': 'AWS WAF',
	'cloudflare': 'Cloudflare',
	'datadome': 'DataDome',
	'f5': 'F5',
	'geetest': 'GeeTest',
	'google': 'Google',
	'hcaptcha': 'hCaptcha',
	'imperva': 'Imperva',
	'kasada': 'Kasada',
	'perimeterx': 'PerimeterX',
	'radware': 'Radware',
	'recaptcha': 'reCAPTCHA',
	'sucuri': 'Sucuri',
	'vercel': 'Vercel',
}

_VISIBLE = '//body//text()[not(ancestor::script or ancestor::style or ancestor::noscript or ancestor::template)]'
_LOWER = "translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')"
BOT_WORDS = ('access denied', 'forbidden', 'blocked', 'not a robot', 'not a bot', 'are you human', 'verify you are')
BOT_WORDS += ('unusual traffic', 'security check')


def _text(*phrases: str) -> str:
	"""A visible text node containing one of the (lower-case, quote-free) phrases."""
	return _VISIBLE + '[' + ' or '.join(f"contains({_LOWER}, '{p}')" for p in phrases) + ']'


def _src(tag: str, *parts: str) -> str:
	"""A tag whose src (action for a form) contains one of the parts."""
	attr = '@action' if tag == 'form' else '@src'
	return f'//{tag}[' + ' or '.join(f"contains({attr}, '{p}')" for p in parts) + ']'


def _class(*names: str) -> str:
	return ' | '.join(f"//*[contains(concat(' ', normalize-space(@class), ' '), ' {n} ')]" for n in names)


def _cf_code(*codes: int) -> str:
	element = "//*[contains(@class, 'cf-error-code')][" + ' or '.join(f"normalize-space()='{c}'" for c in codes) + ']'
	return f'{element} | {_text(*(f"error code: {c}" for c in codes))}'


# DOM.performSearch queries of one probe, all XPath so that one union of them tells whether any matched: the driver's
# deepSearch batch, its body-text regexes as text hits.
QUERIES: dict[str, str] = {
	'dd_captcha': _src('iframe', 'captcha-delivery.com/captcha'),
	'dd_ip_ban': "//iframe[contains(@src, 'captcha-delivery.com/captcha') and contains(@src, 't=bv')]",
	'dd_interstitial': _src('iframe', 'captcha-delivery.com/interstitial'),
	'px_captcha': "//*[@id='px-captcha'] | //div[contains(@aria-label, 'Press & Hold')]",
	'px_block': _src('script', 'captcha.js?a=b') + ' | ' + _src('iframe', 'captcha.js?a=b'),
	'turnstile': _src('iframe', 'challenges.cloudflare.com') + " | //input[@name='cf-turnstile-response']",
	'recaptcha': _src('iframe', 'recaptcha/api2/anchor', 'recaptcha/enterprise/anchor', 'recaptcha/api2/bframe'),
	'hcaptcha': _src('iframe', 'hcaptcha'),
	'geetest': _class('geetest_radar_btn', 'geetest_box', 'geetest_holder'),
	'arkose': _src('iframe', 'arkoselabs.com', 'funcaptcha.com'),
	'awswaf_captcha': _class('amzn-captcha-modal') + " | //*[@id='amzn-captcha-verify-button']",
	'amazon_captcha': _src('form', 'validateCaptcha'),
	'kasada_ips': _src('script', '/ips.js') + ' | ' + _src('iframe', '/ips.js'),
	'imperva_frame': _src('iframe', '_Incapsula_Resource'),
	'akamai_sec_cpt': "//*[@id='sec-cpt-if'] | " + _src('iframe', '/_sec/cp_challenge/'),
	'cf_1009': _cf_code(1009),
	'cf_1015': _cf_code(1015),
	'cf_deny_code': _cf_code(1005, 1006, 1007, 1008, 1010, 1011, 1012, 1020),
	't_blocked': _text('you have been blocked'),
	't_restricted': _text('access is temporarily restricted'),
	't_akamai_ref': _text('with the code: ', 'reference #', 'reference error: '),
	't_security_verification': _text('performing security verification'),
	't_incapsula': _text('incapsula incident'),
	't_rejected': _text('requested url was rejected'),
	't_radware': _text('unauthorized request blocked'),
	't_max_requests': _text('maximum requests limitation'),
	't_region': _text('not available in your country', 'not available in your region'),
	# WEAK: read only on a page another query matched, with an error status or a vendor title
	't_access_denied': _text('access denied'),
	't_went_wrong': _text('something went wrong'),
	't_support_id': _text('support id'),
	't_bot_words': _text(*BOT_WORDS),
	'text_nodes': f'({_VISIBLE}[normalize-space()])[position() <= 41]',  # SHORT_NODES + 1: only the thresholds matter
	'long_text': f'({_VISIBLE}[string-length(normalize-space()) > 150])[position() <= 4]',
}
WEAK = ('t_access_denied', 't_went_wrong', 't_support_id', 't_bot_words', 'text_nodes', 'long_text')
ANY_HIT = ' | '.join(q for name, q in QUERIES.items() if name not in WEAK)
# No script reads the text, so its length is estimated from text nodes: a deny page has a handful, none long.
THIN_NODES, SHORT_NODES = 6, 40
_AKAMAI_TIMING = re.compile(r'(^|[\s,])ak_p(;|,|\s|$)')
_UNKNOWN_BOT = re.compile('|'.join(BOT_WORDS))
_VENDOR_HEADERS = ('x-datadome', 'x-dd-b', 'x-kpsdk-ct', 'x-kpsdk-r', 'x-amzn-waf-action', 'x-iinfo', 'x-sucuri-id')
_VENDOR_HEADERS += ('x-sucuri-block', 'x-vercel-mitigated', 'cf-ray', 'cf-mitigated')
_WALL_HITS = ('dd_captcha', 'dd_interstitial', 'px_captcha', 'turnstile', 'kasada_ips', 'awswaf_captcha', 'akamai_sec_cpt')


@dataclass
class Doc:
	"""The main-document response of one loader. status 0: none seen (the event buffer overflowed, an older tab)."""

	status: int
	headers: dict[str, str]  # lower-case names
	url: str
	mime: str = ''


@dataclass
class Page:
	"""One probe of the page: title, URL and the names of QUERIES that matched; counts for text_nodes and long_text."""

	url: str
	title: str
	hits: dict[str, int] = field(default_factory=dict)
	read: bool = False  # the DOM is read: queries not in hits are asked through lookup (else none matched)
	lookup: Callable[[str], int] | None = field(default=None, repr=False)  # QUERIES name -> count, run on first use


@dataclass
class Verdict:
	outcome: str
	challenge: str = ''
	vendor: str = ''
	signal: str = ''
	confidence: int = 95
	persists: bool = False  # a challenge of a vendor that never clears it: still showing at the end, it is a block


def akamai_edge(headers: dict[str, str]) -> bool:
	"""Headers the Akamai edge adds; alone they only show presence. Server AkamaiGHost, or AkamaiNetStorage on a
	deny page served from NetStorage (adidas from a datacenter IP)."""
	return (
		headers.get('server', '').lower().startswith('akamai')
		or 'x-akamai-transformed' in headers
		or 'akamai-grn' in headers
		or bool(_AKAMAI_TIMING.search(headers.get('server-timing', '')))
	)


def akamai_blocked(status: int, headers: dict[str, str]) -> bool:
	"""A 403 through the Akamai edge, not DataDome's behind it (fingerprint-use akamai.go)."""
	return status == 403 and 'x-datadome' not in headers and akamai_edge(headers)


def vendors_present(headers: dict[str, str]) -> list[str]:
	"""Anti-bots whose headers show on the page: who defends the site. Never decides an outcome."""
	h, out = headers, []
	checks = (
		('akamai', akamai_edge(h)),
		('cloudflare', h.get('server', '').lower() == 'cloudflare' or 'cf-ray' in h),
		('datadome', 'x-datadome' in h or 'x-dd-b' in h or h.get('server', '').lower() == 'datadome'),
		('kasada', 'x-kpsdk-ct' in h or 'x-kpsdk-r' in h),
		('imperva', 'x-iinfo' in h or h.get('x-cdn', '').lower() == 'imperva'),
		('awswaf', 'x-amzn-waf-action' in h),
		('vercel', 'x-vercel-mitigated' in h),
		('sucuri', 'x-sucuri-id' in h),
	)
	return [v for v, ok in checks if ok]


def vendor_title(title: str) -> str:
	"""The vendor a challenge or block page title names, 'generic' for a plain deny title, '' for any other."""
	t = title
	if 'just a moment' in t or 'attention required' in t:
		return 'cloudflare'
	if 'access to this page has been denied' in t or 'it needs a human touch' in t:
		return 'perimeterx'
	if 'sorry! something went wrong' in t:
		return 'amazon'
	if 'vercel security checkpoint' in t:
		return 'vercel'
	generic = ('access denied', '403 forbidden', 'request rejected', 'radware captcha', 'sucuri website firewall', 'pardon our')
	if any(g in t for g in generic):
		return 'generic'
	return ''


class _View:
	"""The lower-cased fields the rules read."""

	def __init__(self, doc: Doc, page: Page | None):
		self.doc, self.page, self.status = doc, page, doc.status
		self.headers = {k: str(v).lower() for k, v in doc.headers.items()}
		self.url = (page.url if page and page.url else doc.url).lower()
		self.title = (page.title if page else '').lower().removeprefix('\U0001f434 ')
		self.host = urllib.parse.urlsplit(self.url).hostname or ''
		self.read = bool(page and page.read)

	def h(self, name: str) -> str:
		return self.headers.get(name, '')

	def count(self, name: str) -> int:
		"""A query's count, run when a rule first asks: the first matching rule ends the reads."""
		p = self.page
		if p is None:
			return 0
		if p.read and p.lookup and name not in p.hits:
			p.hits[name] = p.lookup(name)
		return p.hits.get(name, 0)

	def hit(self, name: str) -> bool:
		return self.count(name) > 0

	def host_is(self, domain: str) -> bool:
		return self.host == domain or self.host.endswith('.' + domain)

	def html(self) -> bool:
		return not self.doc.mime or 'html' in self.doc.mime.lower()

	def cloudflare(self) -> bool:
		return self.h('server') == 'cloudflare' or bool(self.h('cf-ray'))

	def amazon(self) -> bool:
		return self.host.startswith('amazon.') or '.amazon.' in self.host

	def nodes(self) -> tuple[int, int]:
		return self.count('text_nodes'), self.count('long_text')

	def bare(self) -> bool:
		n, long = self.nodes()
		return self.read and n <= THIN_NODES and not long

	def thin(self) -> bool:
		"""A near-empty page; text alone flagged a tiny test page, so it also needs an error or a vendor title."""
		return self.bare() and (self.status != 200 or vendor_title(self.title) != '')

	def deny_page(self) -> bool:
		"""Shaped like a deny page, so a deny phrase on it means one: an error status, a vendor title or near-empty."""
		return self.status >= 400 or vendor_title(self.title) != '' or self.bare()

	def short(self) -> bool:
		n, long = self.nodes()
		return self.read and n <= SHORT_NODES and long <= 3

	def walled(self) -> bool:
		"""A challenge header still describes the page: a page can clear without a new document."""
		if not self.page:
			return True
		if self.bare() or vendor_title(self.title):
			return True
		return any(self.hit(h) for h in _WALL_HITS)

	def widget_wall(self, widget: str) -> bool:
		return self.hit(widget) and (self.status >= 400 or self.thin())


class _Rules(_View):
	"""One method per rule id: DESIGN §3.3 as fingerprint-use blockdetect/rules.go has it."""

	def queueit_host(self):
		return self.host_is('queue-it.net')

	def cf_waiting_room(self):
		return 'waiting room' in self.title and self.cloudflare()

	def linkedin_authwall(self):
		return self.host_is('linkedin.com') and ('/authwall' in self.url or self.status == 999)

	def x_login_flow(self):
		return (self.host_is('x.com') or self.host_is('twitter.com')) and '/i/flow/login' in self.url

	def cf_access(self):
		return self.host_is('cloudflareaccess.com')

	def cf_1009(self):
		return self.hit('cf_1009')

	def status_451(self):
		return self.status == 451

	def region_text(self):
		return self.hit('t_region')

	def dd_ip_ban(self):
		return self.hit('dd_ip_ban')

	def dd_block_text(self):
		return self.hit('dd_captcha') and (self.hit('t_blocked') or self.hit('t_restricted'))

	def px_block(self):
		return self.hit('px_block')

	def cf_edge_deny(self):
		return self.status == 403 and self.cloudflare() and not self.h('cf-mitigated') and self.hit('cf_deny_code')

	def cf_block_page(self):
		title = 'attention required' in self.title and 'cloudflare' in self.title
		return title or (self.hit('t_blocked') and self.deny_page())

	def akamai_403(self):
		return akamai_blocked(self.status, self.doc.headers)

	def akamai_ref_code(self):
		# the driver matches the reference code's shape in the text; here the phrase on a deny page, behind the Akamai edge
		edge = akamai_edge(self.doc.headers) or self.hit('t_access_denied')
		return self.hit('t_akamai_ref') and edge and self.deny_page()

	def vercel_deny(self):
		return self.h('x-vercel-mitigated') == 'deny'

	def sucuri_block(self):
		return bool(self.h('x-sucuri-block')) or 'sucuri website firewall - access denied' in self.title

	def imperva_incident(self):
		return self.hit('t_incapsula') or (self.hit('imperva_frame') and self.thin())

	def f5_rejected(self):
		return self.hit('t_rejected') and self.hit('t_support_id')

	def radware_block(self):
		return self.hit('t_radware')

	def amazon_dog(self):
		dog = 'sorry! something went wrong'
		return self.amazon() and (dog in self.title or (self.status == 503 and self.hit('t_went_wrong')))

	def dd_captcha(self):
		return self.hit('dd_captcha')

	def px_captcha(self):
		return self.hit('px_captcha') or vendor_title(self.title) == 'perimeterx'

	def awswaf_captcha(self):
		return self.h('x-amzn-waf-action') == 'captcha' or self.hit('awswaf_captcha')

	def amazon_captcha(self):
		return self.hit('amazon_captcha') or (self.amazon() and '/errors/validatecaptcha' in self.url)

	def google_sorry(self):
		return 'google.' in self.host and '/sorry/' in self.url

	def radware_captcha(self):
		return self.host_is('validate.perfdrive.com') or 'radware captcha' in self.title

	def cf_turnstile_challenge(self):
		return self.h('cf-mitigated') == 'challenge' and self.hit('turnstile') and self.walled()

	def recaptcha_wall(self):
		return self.widget_wall('recaptcha')

	def hcaptcha_wall(self):
		return self.widget_wall('hcaptcha')

	def geetest_wall(self):
		return self.widget_wall('geetest')

	def arkose_wall(self):
		return self.widget_wall('arkose')

	def cf_challenge(self):
		header = self.h('cf-mitigated') == 'challenge' and self.walled()
		return header or 'just a moment' in self.title or self.hit('t_security_verification') or '__cf_chl_' in self.url

	def kasada_429(self):
		header = self.status == 429 and (bool(self.h('x-kpsdk-ct')) or self.h('x-kpsdk-r') == '1-aa')
		return (header and self.walled()) or (self.hit('kasada_ips') and self.thin())

	def awswaf_challenge(self):
		return self.status == 202 and self.h('x-amzn-waf-action') == 'challenge' and self.walled()

	def dd_interstitial(self):
		return (bool(self.h('x-dd-b')) and self.walled()) or self.hit('dd_interstitial')

	def akamai_sec_cpt(self):
		return (self.status == 428 and self.walled()) or self.hit('akamai_sec_cpt')

	def vercel_challenge(self):
		header = self.h('x-vercel-mitigated') == 'challenge' and self.walled()
		return header or 'vercel security checkpoint' in self.title

	def cf_1015(self):
		return self.hit('cf_1015')

	def px_rate_limit(self):
		return self.hit('t_max_requests')

	def status_429(self):
		return self.status == 429

	def unknown_block(self):
		words = self.hit('t_bot_words') or bool(_UNKNOWN_BOT.search(self.title))
		return self.status in (401, 403, 406, 429, 503) and self.short() and words


# (rule id, outcome, challenge, vendor, confidence, persists); the first match decides. persists: a challenge of a
# vendor that never clears one, still showing at the end, is a block.
RULES: list[tuple[str, str, str, str, int, bool]] = [
	('queueit_host', 'queue', '', 'queueit', 95, False),
	('cf_waiting_room', 'queue', '', 'cloudflare', 60, False),
	('linkedin_authwall', 'auth_wall', '', 'linkedin', 95, False),
	('x_login_flow', 'auth_wall', '', 'x', 80, False),
	('cf_access', 'auth_wall', '', 'cloudflare', 95, False),
	('cf_1009', 'geo', '', 'cloudflare', 95, False),
	('status_451', 'geo', '', '', 95, False),
	('region_text', 'geo', '', '', 60, False),
	('dd_ip_ban', 'blocked', '', 'datadome', 95, False),
	('dd_block_text', 'blocked', '', 'datadome', 80, False),
	('px_block', 'blocked', '', 'perimeterx', 80, False),
	('cf_edge_deny', 'blocked', '', 'cloudflare', 95, False),
	('cf_block_page', 'blocked', '', 'cloudflare', 95, False),
	('akamai_403', 'blocked', '', 'akamai', 95, False),
	('akamai_ref_code', 'blocked', '', 'akamai', 80, False),
	('vercel_deny', 'blocked', '', 'vercel', 95, False),
	('sucuri_block', 'blocked', '', 'sucuri', 60, False),
	('imperva_incident', 'blocked', '', 'imperva', 60, False),
	('f5_rejected', 'blocked', '', 'f5', 60, False),
	('radware_block', 'blocked', '', 'radware', 60, False),
	('amazon_dog', 'blocked', '', 'amazon', 80, False),
	('dd_captcha', 'stuck', 'captcha', 'datadome', 95, False),
	('px_captcha', 'stuck', 'captcha', 'perimeterx', 95, False),
	('awswaf_captcha', 'stuck', 'captcha', 'awswaf', 95, False),
	('amazon_captcha', 'stuck', 'captcha', 'amazon', 80, False),
	('google_sorry', 'stuck', 'captcha', 'google', 95, True),
	('radware_captcha', 'stuck', 'captcha', 'radware', 60, False),
	('cf_turnstile_challenge', 'stuck', 'captcha', 'cloudflare', 95, False),
	('recaptcha_wall', 'stuck', 'captcha', 'recaptcha', 80, False),
	('hcaptcha_wall', 'stuck', 'captcha', 'hcaptcha', 80, False),
	('geetest_wall', 'stuck', 'captcha', 'geetest', 80, False),
	('arkose_wall', 'stuck', 'captcha', 'arkose', 80, False),
	('cf_challenge', 'stuck', 'interstitial', 'cloudflare', 95, False),
	('kasada_429', 'stuck', 'interstitial', 'kasada', 95, True),
	('awswaf_challenge', 'stuck', 'interstitial', 'awswaf', 95, False),
	('dd_interstitial', 'stuck', 'interstitial', 'datadome', 95, False),
	('akamai_sec_cpt', 'stuck', 'interstitial', 'akamai', 80, False),
	('vercel_challenge', 'stuck', 'interstitial', 'vercel', 95, False),
	('cf_1015', 'rate_limited', '', 'cloudflare', 95, False),
	('px_rate_limit', 'rate_limited', '', 'perimeterx', 80, False),
	('status_429', 'rate_limited', '', '', 60, False),
	('unknown_block', 'blocked', '', 'unknown', 40, False),
]


def classify(doc: Doc, page: Page | None = None) -> Verdict:
	"""The first matching rule decides. A JSON or XML error is an API's answer, not a wall."""
	v = _Rules(doc, page)
	if doc.status >= 400 and not v.html():
		return Verdict('ok', signal='http_error')
	for rule_id, outcome, challenge, vendor, confidence, persists in RULES:
		if getattr(v, rule_id)():
			return Verdict(outcome, challenge, vendor, rule_id, confidence, persists)
	return Verdict('ok')


def site(host: str) -> str:
	"""The host without www.: documents of one visit stay on it (a challenge that clears reloads the same host)."""
	return host.removeprefix('www.')


def host_of(url: str) -> str:
	try:
		return (urllib.parse.urlsplit(url).hostname or '').lower()
	except ValueError:
		return ''


@dataclass
class Visit:
	"""The documents and probes of one main-frame visit, which can span a challenge and the document that clears it."""

	id: str  # the first document's loader id
	doc: Doc
	at: float  # the latest document's Network timestamp (s)
	statuses: list[int] = field(default_factory=list)
	docs: int = 0
	last: Verdict = field(default_factory=lambda: Verdict('ok'))
	worst: Verdict | None = None
	challenge: str = ''
	err_status: bool = False
	loader: str = ''  # the latest document's loader id
	probed: str = ''  # the loader the latest probe read
	reads: int = 0  # probes of the latest loader
	changed: bool = True
	counted: bool = False  # its vendors went into take()'s 'seen'
	vendors: set[str] = field(default_factory=set)

	def merges(self, at: float, doc: Doc) -> bool:
		"""A challenge clearing; never a block, which a later page of the site does not undo."""
		if site(host_of(doc.url)) != site(host_of(self.doc.url)) or at - self.at > MERGE_WINDOW_S:
			return False
		if self.last.outcome == 'ok':
			return self.doc.status in CHALLENGE_STATUSES
		return self.last.outcome in ('stuck', 'rate_limited')

	def add_doc(self, at: float, doc: Doc, loader: str) -> None:
		self.doc, self.at, self.loader, self.reads, self.changed = doc, at, loader, 0, True
		self.docs += 1
		if len(self.statuses) < MAX_STATUSES:
			self.statuses.append(doc.status)
		if doc.status in CHALLENGE_STATUSES:
			self.err_status = True
		self.vendors.update(vendors_present(doc.headers))
		self._observe(classify(doc))

	def add_page(self, page: Page, verdict: Verdict | None = None) -> None:
		self.probed, self.changed = self.loader, True
		self.reads += 1
		self._observe(verdict or classify(self.doc, page))

	def _observe(self, verdict: Verdict) -> None:
		self.last = verdict
		if verdict.outcome == 'ok':
			return
		if self.worst is None or _rank(verdict) > _rank(self.worst):
			self.worst = verdict
		if verdict.challenge == 'captcha' or (verdict.challenge == 'interstitial' and not self.challenge):
			self.challenge = verdict.challenge

	def result(self) -> dict:
		"""The visit's verdict so far: one that cleared a challenge is 'passed'."""
		last = self.last
		out = {
			'id': self.id,
			'host': host_of(self.doc.url),
			'url': _page_url(self.doc.url),
			'outcome': last.outcome,
			'challenge': self.challenge,
			'vendor': last.vendor,
			'signal': last.signal,
			'confidence': last.confidence,
			'statuses': list(self.statuses),
		}
		if last.outcome == 'ok' and self.worst is not None:
			w = self.worst
			out.update(outcome='passed', vendor=w.vendor, signal=w.signal, confidence=w.confidence)
			out['challenge'] = self.challenge or 'interstitial'
		elif last.outcome == 'ok' and self.err_status and self.docs > 1:
			# an anti-bot status a later document of the same site replaced was a challenge, even with no vendor rule
			out.update(outcome='passed', challenge='interstitial', vendor='unknown', signal='status_then_ok', confidence=40)
		elif last.outcome == 'stuck' and last.persists:
			out['outcome'] = 'blocked'
		return out


def _rank(v: Verdict) -> int:
	return v.confidence + (2 if v.challenge == 'captcha' else 1 if v.challenge == 'interstitial' else 0)


def _page_url(url: str) -> str:
	"""scheme://host/path: never the query or fragment."""
	try:
		u = urllib.parse.urlsplit(url)
	except ValueError:
		return ''
	netloc = (u.netloc or '').rpartition('@')[2]  # never a user or password
	return f'{u.scheme}://{netloc}{u.path}'[:300] if u.scheme in ('http', 'https') else ''


def _doc(params: dict) -> Doc:
	r = params.get('response') or {}
	headers = {str(k).lower(): str(v) for k, v in (r.get('headers') or {}).items()}
	return Doc(int(r.get('status') or 0), headers, str(r.get('url') or ''), str(r.get('mimeType') or ''))


class BlockLog:
	"""Visits of the worker's top frames, from the daemon's events and a probe at each cell's end. take() hands the
	visits that changed (their latest verdict, by visit id) to the cell's stats."""

	def __init__(self):
		self.visits: dict[str, Visit] = {}  # frame id -> its current visit
		self.done: list[tuple[str, Visit]] = []  # (frame, visit) a later document replaced before take() saw its end
		self.tops: set[str] = set()  # frames seen as top frames (no parent)
		self.reported: list[dict] = []  # cloud verdicts since the last take()
		self.cloud_ids: set[str] = set()  # visits a cloud browser decided: its verdict wins over the local one
		self.lock = threading.Lock()  # events arrive on the worker's background reader; probe() and take() on the main thread

	def observe(self, events) -> None:
		for e in events if isinstance(events, list) else []:
			if not isinstance(e, dict):
				continue
			method, params = e.get('method'), e.get('params') or {}
			with self.lock:
				if method == BLOCK_EVENT:
					self._cloud(params)
				elif method == 'Network.responseReceived' and params.get('type') == 'Document':
					self._document(params)
				elif method == 'Page.frameNavigated' and not (params.get('frame') or {}).get('parentId'):
					self.tops.add(str((params.get('frame') or {}).get('id')))

	def _cloud(self, p: dict) -> None:
		status, confidence = p.get('status'), p.get('confidence')
		visit_id = str(p.get('visitId') or p.get('targetId') or '')  # the driver's visitId is its first loader id, as ours
		self.cloud_ids.add(visit_id)
		self.reported.append(
			{
				'id': visit_id,
				'host': str(p.get('host') or '').lower(),
				'url': '',
				'outcome': str(p.get('outcome') or ''),
				'challenge': str(p.get('challenge') or ''),
				'vendor': str(p.get('vendor') or ''),
				'signal': str(p.get('signal') or ''),
				'confidence': confidence if isinstance(confidence, int) else 95,
				'statuses': [status] if isinstance(status, int) else [],
			}
		)

	def _document(self, params: dict) -> None:
		frame, loader = str(params.get('frameId') or ''), str(params.get('loaderId') or '')
		doc, r = _doc(params), params.get('response') or {}
		cached = r.get('fromDiskCache') or r.get('fromServiceWorker') or r.get('fromPrefetchCache')
		if not frame or cached or not doc.url.startswith(('http:', 'https:')):
			return
		at = float(params.get('timestamp') or time.monotonic())
		visit = self.visits.get(frame)
		if visit is None or not (visit.loader == loader or visit.merges(at, doc)):  # same loader: a probe saw it first
			visit = self._start(frame, Visit(loader or f'{frame}:{at}', doc, at))
		visit.add_doc(at, doc, loader)

	def _start(self, frame: str, visit: Visit) -> Visit:
		"""The frame's new visit. The one it replaces waits in done for take(), unless take() already has its verdict."""
		old = self.visits.pop(frame, None)  # re-inserted last: the oldest frames go first
		if old is not None and (old.changed or not old.counted):
			self.done.append((frame, old))
			if len(self.done) > MAX_VISITS:
				self.done.pop(next((i for i, (f, _) in enumerate(self.done) if f not in self.tops), 0))
		self.visits[frame] = visit
		if len(self.visits) > MAX_VISITS:
			self.visits.pop(next((f for f in self.visits if f not in self.tops), next(iter(self.visits))))
		return visit

	def probe(self, cdp: Callable[..., dict]) -> None:
		"""Read the attached tab, at most twice per document: frame tree and title, then on a page that could be a wall
		one union of the DOM queries; when that matched, or the page has an error status or a vendor title, the rules
		run the queries they need, in order, until one matches. cdp(method, **params) is the worker's raw CDP; a
		failure leaves the visit as it was."""
		deadline = time.monotonic() + PROBE_BUDGET_S

		def call(method: str, **params) -> dict:
			left = deadline - time.monotonic()
			if left <= 0:
				raise TimeoutError
			return cdp(method, **params, _response_timeout=min(PROBE_CALL_S, left))

		try:
			root = (call('Page.getFrameTree').get('frameTree') or {}).get('frame') or {}
			frame, loader, url = str(root.get('id') or ''), str(root.get('loaderId') or ''), str(root.get('url') or '')
			if not frame or not url.startswith(('http:', 'https:')):
				return
			with self.lock:
				self.tops.add(frame)
				visit = self.visits.get(frame)
				if visit is None or visit.loader != loader:  # no document event seen for this load (an older tab)
					doc = Doc(0, {}, url, str(root.get('mimeType') or ''))
					visit = self._start(frame, Visit(loader or url, doc, float('-inf'), loader=loader))
				if not _html(visit.doc.mime) or (visit.probed == loader and visit.reads >= 2):
					return
				doc = visit.doc
			# with no targetId the daemon answers for the browser target: a page's main frame id is its target id
			info = call('Target.getTargetInfo', targetId=frame).get('targetInfo') or {}
			page = Page(url, str(info.get('title') or ''))
			with self.lock:
				suspect = self._suspect(visit, page.title)
			matched = suspect and _count(call, ANY_HIT)
			if suspect and (matched or doc.status >= 400 or vendor_title(page.title.lower())):
				page.read = True
				page.hits = {} if matched else dict.fromkeys(set(QUERIES) - set(WEAK), 0)

				page.lookup = lambda name: _count(call, QUERIES[name])
			verdict = classify(doc, page)  # outside the lock: its queries are CDP calls; a page too busy raises
			with self.lock:
				if visit.loader == loader:  # no new document meanwhile
					visit.add_page(page, verdict)
		except Exception:  # - a closed tab, a dialog, a slow page: no verdict from this probe
			return

	@staticmethod
	def _suspect(visit: Visit, title: str) -> bool:
		"""Worth the DOM queries: no document seen, an error or challenge status, an anti-bot vendor's header, or a
		challenge-like title. A plain page of a site with no anti-bot header is read by title only."""
		headers = visit.doc.headers
		return (
			visit.doc.status == 0
			or any(s >= 400 or s in CHALLENGE_STATUSES for s in visit.statuses)
			or any(h in headers for h in _VENDOR_HEADERS)
			or headers.get('server', '').lower() in ('cloudflare', 'datadome')
			or akamai_edge(headers)
			or bool(vendor_title(title.lower()))
			or bool(_UNKNOWN_BOT.search(title.lower()))
		)

	def take(self) -> dict:
		"""{'visits': [result of each visit that changed and is not plainly ok], 'seen': {vendor: new visits}}. A cloud
		browser's verdicts come last and replace the local ones of their visits."""
		seen: Counter = Counter()
		visits: list[dict] = []
		with self.lock:
			for frame, visit in [*self.done, *self.visits.items()]:
				if not visit.changed or frame not in self.tops:
					continue
				visit.changed = False
				if not visit.counted:
					visit.counted = True
					seen.update(visit.vendors)
				r = visit.result()
				if r['outcome'] != 'ok' and r['id'] not in self.cloud_ids:
					visits.append(r)
			visits += self.reported
			self.done, self.reported = [], []
		return {'visits': visits, 'seen': dict(seen)}


def _html(mime: str) -> bool:
	return not mime or 'html' in mime.lower()


def _count(call: Callable[..., dict], query: str) -> int:
	r = call('DOM.performSearch', query=query, includeUserAgentShadowDOM=False)
	try:
		return int(r.get('resultCount') or 0)
	finally:
		if r.get('searchId'):
			call('DOM.discardSearchResults', searchId=r['searchId'])


@dataclass
class Block:
	"""Pages of one host that an anti-bot left walled: blocked, stuck on a challenge, or rate-limited."""

	vendor: str  # the §3.2 enum: datadome, cloudflare, akamai, ... ('unknown': a deny page with no vendor rule)
	host: str
	outcome: str  # blocked | stuck | rate_limited
	count: int  # visits (document loads, a challenge's own reloads merged), not cells
	challenge: str = ''  # '' | interstitial | captcha
	statuses: list[int] = field(default_factory=list)
	url: str = ''  # the first such page, without query

	def __str__(self) -> str:
		times = f' ({self.count}x)' if self.count > 1 else ''
		return f'{vendor_name(self.vendor, self.statuses)} on {self.host}{times}'


def vendor_name(vendor: str, statuses: list[int] | None = None) -> str:
	if vendor in NAMES:
		return NAMES[vendor]
	code = next((s for s in reversed(statuses or []) if s >= 400), None)
	return f'an anti-bot (HTTP {code})' if code else 'an anti-bot'


def blocks(visits: dict[str, dict]) -> list[Block]:
	"""Walled visits grouped by vendor, host and outcome, most first."""
	out: dict[tuple[str, str, str], Block] = {}
	for r in visits.values():
		if r.get('outcome') not in WALLS:
			continue
		key = (r.get('vendor') or 'unknown', r.get('host') or '', r['outcome'])
		b = out.get(key)
		if b is None:
			b = out[key] = Block(key[0], key[1], key[2], 0, r.get('challenge') or '', [], r.get('url') or '')
		b.count += 1
		b.statuses = sorted(set(b.statuses) | {int(s) for s in r.get('statuses') or [] if s})
	return sorted(out.values(), key=lambda b: -b.count)
