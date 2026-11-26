"""Browser(web_bot_auth=WebBotAuth(...)) (browser_use/web_bot_auth.py): Web Bot Auth signatures on the browser's
requests, added by the domain Guard's Fetch interception.

The signer is checked against the Ed25519 test vector of draft-ietf-webbotauth-httpsig-protocol (appendix "EdDSA Using
Curve edwards25519", key from RFC 9421 B.1.4). The Chrome tests verify what a site actually receives with a verifier
written here from the RFC, not with the signer's own code."""

import base64
import http.server
import re
import threading

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from pydantic_ai.messages import ModelRequest, ToolReturnPart

import browser_use.web_bot_auth as wba
from browser_use import Agent, Browser, WebBotAuth
from browser_use.domains import DomainRules, Guard
from browser_use.repl import Repl
from tests.ci.conftest import script

RFC9421_JWK = {  # RFC 9421 B.1.4 test-key-ed25519: a published test key, never a real one
	'kty': 'OKP',
	'crv': 'Ed25519',
	'x': 'JrQLj5P_89iXES9-vFgrIy29clF9CC_oPPsw3c5D0bs',
	'd': 'n4Ni-HpISpVObnQMW0wOhCKROaIKqKtW_2ZYb2p9KcU',
}
RFC9421_ED25519 = (  # the same key as PEM, built here so no key file sits in the repo
	Ed25519PrivateKey.from_private_bytes(base64.urlsafe_b64decode(RFC9421_JWK['d'] + '='))
	.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
	.decode()
)
DIRECTORY = 'https://signature-agent.test/.well-known/http-message-signatures-directory'


def test_signs_the_drafts_ed25519_vector(monkeypatch):
	"""Byte for byte: Ed25519 is deterministic, so the same base gives the draft's Signature."""
	monkeypatch.setattr(wba, 'LABEL', 'sig2')  # the vector's label
	signer = WebBotAuth(RFC9421_ED25519, DIRECTORY)
	signer.expires_in = 4889289600 - 1735689600  # the vector's 100-year window, past what the constructor allows
	nonce = 'n9p433xm+NJ3ph3upfBIGmsuwHw387YV7Q/F+6BSpGCVjYCqQw6rznNA8PVVLySrAWsv0hQtFioQb6E1YsauiA=='
	assert signer.sign('https://example.com/path?q=1', created=1735689600, nonce=nonce) == {
		'Signature-Agent': f'sig2="{DIRECTORY}"',
		'Signature-Input': 'sig2=("@authority" "signature-agent";key="sig2");created=1735689600;'
		'keyid="poqkLGiymh_W0uP6PZFw-dvez3QJT5SolqXBCW38r0U";alg="ed25519";expires=4889289600;'
		f'nonce="{nonce}";tag="web-bot-auth"',
		'Signature': 'sig2=:K/yVRxeBAr93LLpXNu+7VJysBLJzHbx5ei/qkTDFY2qm0ogzJaAWn0p8j/7NoG3VpFpBehIHOGDkczVCm2epDw==:',
	}


def test_signs_the_drafts_legacy_vector(monkeypatch):
	"""legacy_signature_agent=True: the bare-string Signature-Agent of earlier drafts, covered without key=."""
	monkeypatch.setattr(wba, 'LABEL', 'sig2')
	signer = WebBotAuth(RFC9421_ED25519, DIRECTORY, expires_in=3600, legacy_signature_agent=True)
	nonce = 'e8N7S2MFd/qrd6T2R3tdfAuuANngKI7LFtKYI/vowzk4lAZYadIX6wW25MwG7DCT9RUKAJ0qVkU0mEeLElW1qg=='
	assert signer.sign('https://example.com/', created=1735689600, nonce=nonce) == {
		'Signature-Agent': f'"{DIRECTORY}"',
		'Signature-Input': 'sig2=("@authority" "signature-agent");created=1735689600;'
		'keyid="poqkLGiymh_W0uP6PZFw-dvez3QJT5SolqXBCW38r0U";alg="ed25519";expires=1735693200;'
		f'nonce="{nonce}";tag="web-bot-auth"',
		'Signature': 'sig2=:RgpOdhNGFX7UR38+uNNf79CsAQ/ll8H7FvrSoQyjUHMg0apFVJ691/TZIu4boservbg7ciRcoDnY0XLI4j/AAA==:',
	}


def test_key_forms_directory_and_repr():
	"""PEM text, a PEM file, a private JWK and a generated key; the directory has the public key only."""
	jwk = RFC9421_JWK
	signer = WebBotAuth(jwk, DIRECTORY)
	assert signer.keyid == WebBotAuth(RFC9421_ED25519, DIRECTORY).keyid == 'poqkLGiymh_W0uP6PZFw-dvez3QJT5SolqXBCW38r0U'
	assert signer.directory() == {'keys': [{'kty': 'OKP', 'crv': 'Ed25519', 'x': jwk['x'], 'kid': signer.keyid, 'use': 'sig'}]}
	assert jwk['d'] not in str(signer.directory()) and jwk['d'] not in repr(signer)
	fresh = WebBotAuth.generate(DIRECTORY, expires_in=300)
	assert WebBotAuth(fresh.private_key_pem(), DIRECTORY).keyid == fresh.keyid != signer.keyid


def test_key_from_a_pem_file(tmp_path):
	(tmp_path / 'agent.pem').write_text(RFC9421_ED25519)
	assert WebBotAuth(str(tmp_path / 'agent.pem'), DIRECTORY).keyid == 'poqkLGiymh_W0uP6PZFw-dvez3QJT5SolqXBCW38r0U'
	assert WebBotAuth(tmp_path / 'agent.pem', DIRECTORY).keyid == 'poqkLGiymh_W0uP6PZFw-dvez3QJT5SolqXBCW38r0U'


def test_bad_options_raise_before_any_browser_starts():
	from cryptography.hazmat.primitives.asymmetric import ec

	for agent in ('http://example.com/keys', 'example.com', '/.well-known/x', 'https://exämple.com/keys', None):
		with pytest.raises(ValueError, match='signature_agent'):
			WebBotAuth(RFC9421_ED25519, agent)  # type: ignore[arg-type]
	for expires in (0, 86401, 1.5, True):
		with pytest.raises(ValueError, match='expires_in'):
			WebBotAuth(RFC9421_ED25519, DIRECTORY, expires_in=expires)  # type: ignore[arg-type]
	ec_pem = ec.generate_private_key(ec.SECP256R1()).private_bytes(
		serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
	)
	with pytest.raises(ValueError, match='must be an Ed25519 key'):
		WebBotAuth(ec_pem, DIRECTORY)
	with pytest.raises(ValueError, match='private Ed25519 key'):
		WebBotAuth({'kty': 'OKP', 'crv': 'Ed25519', 'x': 'JrQLj5P_89iXES9-vFgrIy29clF9CC_oPPsw3c5D0bs'}, DIRECTORY)
	with pytest.raises(TypeError, match='legacy_signature_agent'):
		WebBotAuth(RFC9421_ED25519, DIRECTORY, legacy_signature_agent='yes')  # type: ignore[arg-type]
	with pytest.raises(TypeError, match='takes a WebBotAuth'):
		Browser('chromium', web_bot_auth={'key': RFC9421_ED25519})  # type: ignore[arg-type]
	with pytest.raises(ValueError, match='sign your own tabs'):
		Browser('chrome', web_bot_auth=WebBotAuth(RFC9421_ED25519, DIRECTORY))


def test_which_urls_are_signed():
	"""https, or http to a loopback host (the draft: signatures over an unsecured channel can be replayed); domains=
	narrows it with the allowed_domains patterns."""
	signer = WebBotAuth(RFC9421_ED25519, DIRECTORY)
	for url in ('https://example.com/', 'https://EXAMPLE.com:443/a', 'http://localhost:8080/', 'http://a.localhost/',
				'http://127.0.0.1:9/', 'http://[::1]:9/'):  # fmt: skip
		assert signer.signs(url), url
	for url in ('http://example.com/', 'http://10.0.0.1/', 'ws://localhost/', 'data:text/html,x', 'about:blank', 'file:///x'):
		assert not signer.signs(url), url
	assert wba.authority('https://EXAMPLE.com:443/a') == 'example.com'
	assert wba.authority('https://example.com:8443/') == 'example.com:8443'
	assert wba.authority('http://[::1]:80/') == '[::1]'
	scoped = WebBotAuth(RFC9421_ED25519, DIRECTORY, domains=['*.shop.test'])
	assert scoped.signs('https://www.shop.test/cart') and not scoped.signs('https://other.test/')
	request = {'url': 'https://www.shop.test/', 'headers': {'Accept': 'text/html', 'signature': 'sig1=:forged:'}}
	headers = {h['name']: h['value'] for h in scoped.headers(request) or []}
	assert headers['Accept'] == 'text/html' and 'signature' not in headers and headers['Signature'].startswith('sig1=:')
	assert scoped.headers({'url': 'https://other.test/', 'headers': {}}) is None


def test_only_real_loopback_addresses_get_http_signatures():
	"""Review: '127(.d{1,3}){3}' matched 127.999.999.999, which is no address, so plain http to it was signed."""
	signer = WebBotAuth(RFC9421_ED25519, DIRECTORY)
	assert not signer.signs('http://127.999.999.999/') and not signer.signs('http://127.0.0.1.example.com/')
	assert signer.signs('http://127.0.0.2/') and signer.signs('http://127.1/')  # Chrome sends 127.1 as 127.0.0.1


def test_unicode_hosts_are_signed_as_the_browser_sends_them():
	"""Review: a Unicode host passed signs() but failed the ASCII signature base, so the request went out unsigned.
	@authority is now the punycode Host the browser sends."""
	signer = WebBotAuth(RFC9421_ED25519, DIRECTORY)
	assert wba.authority('https://faß.de/') == 'xn--fa-hia.de' == wba.authority('https://xn--fa-hia.de/')
	# Review: canonical_host drops a name's trailing dot, which Chrome keeps in Host (an IPv4 address loses it)
	assert wba.authority('https://faß.de.:8443/') == 'xn--fa-hia.de.:8443' and wba.authority('http://127.0.0.1./') == '127.0.0.1'
	assert signer.signs('http://localhost./') and signer.signs('http://shop.localhost./')
	headers = signer.sign('https://bücher.example:8443/', created=1735689600, nonce='n')
	assert headers is not None
	same = signer.sign('https://xn--bcher-kva.example:8443/', created=1735689600, nonce='n')
	assert headers == same


def test_a_guard_that_cannot_start_names_every_feature_it_carries():
	"""Review: with both options on, a startup failure named only domain restrictions."""
	signer = WebBotAuth(RFC9421_ED25519, DIRECTORY)
	dead = 'ws://127.0.0.1:9/devtools/browser/x'  # nothing listens on port 9
	with pytest.raises(RuntimeError, match='^Domain restrictions and Web Bot Auth signing could not start'):
		Guard(dead, DomainRules.of(['shop.test']), signer).start()
	with pytest.raises(RuntimeError, match='^Web Bot Auth signing could not start'):
		Guard(dead, DomainRules(), signer).start()


# Against a real Chrome


def verify(headers: dict[str, str], public: bytes) -> str:
	"""An RFC 9421 verifier for what this signer sends: rebuilds the base from the received request and checks the
	Ed25519 signature. Returns the Signature-Agent URL."""
	label, inner, params = re.fullmatch(r'(\w+)=\(([^)]*)\)(.*)', headers['signature-input']).groups()  # type: ignore[union-attr]
	assert inner == f'"@authority" "signature-agent";key="{label}"'
	assert 'tag="web-bot-auth"' in params and 'alg="ed25519"' in params
	agent = re.fullmatch(rf'{label}=("[^"]*")', headers['signature-agent']).group(1)  # type: ignore[union-attr]
	sig = re.fullmatch(rf'{label}=:([A-Za-z0-9+/=]+):', headers['signature']).group(1)  # type: ignore[union-attr]
	base = f'"@authority": {headers["host"]}\n"signature-agent";key="{label}": {agent}\n"@signature-params": ({inner}){params}'
	Ed25519PublicKey.from_public_bytes(public).verify(base64.b64decode(sig), base.encode())  # raises when it does not
	return agent.strip('"')


class Site(http.server.BaseHTTPRequestHandler):
	"""shop.localhost and other.localhost (Chrome resolves *.localhost to loopback); records each request's headers."""

	seen: list[tuple[str, dict[str, str]]] = []

	def log_message(self, *args):
		pass

	def do_GET(self):
		host, port = self.headers['Host'].split(':')
		Site.seen.append((f'{host}{self.path}', {k.lower(): v for k, v in self.headers.items()}))
		other = f'http://other.localhost:{port}'
		if self.path == '/redirect':
			self.send_response(302)
			self.send_header('Location', f'{other}/landed')
			self.end_headers()
			return
		body = {
			'/': f'<img src="/pixel.png"><iframe src="{other}/frame"></iframe>',
			'/cookie': '<p>set</p>',
		}.get(self.path, f'<title>{host}{self.path}</title>')
		self.send_response(200)
		self.send_header('Content-Type', 'text/html')
		if self.path == '/cookie':
			self.send_header('Set-Cookie', 'session=kept; Path=/')
		self.end_headers()
		self.wfile.write(body.encode())


@pytest.fixture(scope='module')
def site():
	server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Site)
	threading.Thread(target=server.serve_forever, daemon=True).start()
	port = server.server_address[1]
	yield {'shop': f'http://shop.localhost:{port}', 'other': f'http://other.localhost:{port}'}
	server.shutdown()


def received(path: str) -> list[dict[str, str]]:
	return [h for p, h in Site.seen if p == path]


async def visit(daemon, tmp_path, guard: Guard, *urls: str, blocked: str = '') -> None:
	"""Load each URL, then blocked (no wait_for_load: the guard resets that tab to about:blank under it)."""
	guard.start()
	repl = Repl(tmp_path, daemon)
	try:
		cells = [f'goto_url({url!r}); wait_for_load(); wait(0.5)' for url in urls]
		for url, code in zip([*urls, blocked], [*cells, f'goto_url({blocked!r}); wait(1)'] if blocked else cells):
			r = await repl.call('exec', code, 30)
			assert r['error'] is None, (url, r['error'])
	finally:
		await repl.close()
		guard.close()


async def test_navigations_are_signed_and_verify(chrome, daemon, site, tmp_path):
	"""Main frame, iframe and both hops of a cross-host redirect carry a signature that verifies for the host each one
	went to; images are not signed (documents only by default); cookies and other headers still arrive."""
	Site.seen.clear()
	signer = WebBotAuth.generate(DIRECTORY)
	shop = site['shop']
	dotted = shop.replace('shop.localhost', 'shop.localhost.') + '/dotted'  # Chrome keeps the trailing dot in Host
	await visit(
		daemon, tmp_path, Guard(chrome['ws'], DomainRules(), signer), f'{shop}/cookie', f'{shop}/', f'{shop}/redirect', dotted
	)
	public = signer.public_bytes()
	for path in ('shop.localhost/cookie', 'shop.localhost/', 'other.localhost/frame', 'shop.localhost/redirect',
				 'other.localhost/landed', 'shop.localhost./dotted'):  # fmt: skip
		hits = received(path)
		assert hits, (path, [p for p, _ in Site.seen])
		assert all(verify(h, public) == DIRECTORY for h in hits), path
	assert received('other.localhost/frame')[0]['host'].startswith('other.localhost:')  # signed for its own host
	assert all('signature' not in h for h in received('shop.localhost/pixel.png'))
	page = received('shop.localhost/')[-1]
	assert page.get('cookie') == 'session=kept' and 'mozilla' in page.get('user-agent', '').lower()
	nonces = [re.search(r'nonce="([^"]+)"', h['signature-input']).group(1) for h in received('shop.localhost/')]  # type: ignore[union-attr]
	assert len(set(nonces)) == len(nonces)


async def test_subresources_and_domains_options(chrome, daemon, site, tmp_path):
	"""subresources=True signs the image too; domains= leaves other hosts unsigned."""
	Site.seen.clear()
	signer = WebBotAuth.generate(DIRECTORY, subresources=True, domains=['shop.localhost'])
	await visit(daemon, tmp_path, Guard(chrome['ws'], DomainRules(), signer), f'{site["shop"]}/')
	verify(received('shop.localhost/pixel.png')[0], signer.public_bytes())
	verify(received('shop.localhost/')[0], signer.public_bytes())
	assert received('other.localhost/frame') and all('signature' not in h for h in received('other.localhost/frame'))


async def test_domain_restrictions_still_block_with_signing(chrome, daemon, site, tmp_path):
	"""One interception for both: an allowed page is signed, a disallowed iframe still loads (iframes pass, as without
	signing), a disallowed main-frame navigation is still blocked, also when every request is paused."""
	Site.seen.clear()
	signer = WebBotAuth.generate(DIRECTORY, subresources=True)
	guard = Guard(chrome['ws'], DomainRules.of(['shop.localhost']), signer)
	await visit(daemon, tmp_path, guard, f'{site["shop"]}/', blocked=f'{site["shop"]}/redirect')
	verify(received('shop.localhost/')[0], signer.public_bytes())
	verify(received('shop.localhost/pixel.png')[0], signer.public_bytes())
	assert received('other.localhost/frame') and not received('other.localhost/landed')
	_, blocks = guard.take()
	assert blocks == 1


async def test_browser_chromium_signs_an_agent_run(chrome_binary, site, tmp_path):
	"""Browser('chromium', web_bot_auth=...) end to end: the agent's navigation reaches the site signed."""
	Site.seen.clear()
	signer = WebBotAuth.generate(DIRECTORY)
	model, _ = script(
		('python', {'code': f'new_tab({site["shop"] + "/agent"!r}); wait_for_load(); print(page_info()["title"])'}),
		('finish', {'success': True, 'result': 'done'}),
	)
	browser = Browser('chromium', headless=True, executable_path=chrome_binary, web_bot_auth=signer)
	result = await Agent('Visit the shop', model, browser=browser, workspace=tmp_path).run()
	assert result.status == 'completed', result.error
	returns = [
		p.content for m in result.messages if isinstance(m, ModelRequest) for p in m.parts if isinstance(p, ToolReturnPart)
	]
	assert 'shop.localhost/agent' in str(returns[0])
	assert verify(received('shop.localhost/agent')[0], signer.public_bytes()) == DIRECTORY
