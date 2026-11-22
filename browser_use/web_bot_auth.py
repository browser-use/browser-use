"""Browser(web_bot_auth=WebBotAuth(...)): sign the browser's requests with Web Bot Auth, so a site can verify that a
request comes from your agent (draft-ietf-webbotauth-httpsig-protocol, on RFC 9421 HTTP Message Signatures).

Off unless you pass it. Each signed request gets three headers, under the label sig1:
  Signature-Agent: sig1="<signature_agent>"
  Signature-Input: sig1=("@authority" "signature-agent";key="sig1");created=...;keyid="<JWK thumbprint>";alg="ed25519";
                   expires=...;nonce="...";tag="web-bot-auth"
  Signature: sig1=:<Ed25519 signature>:
The signature covers the host the request goes to and the Signature-Agent URL, so a verifier fetches your public key
from that URL and checks it; Cloudflare, among others, verifies it. You host the key: WebBotAuth.directory() is the JSON
to serve at signature_agent (for the well-known path, with Content-Type
application/http-message-signatures-directory+json). browser-use never serves or uploads it.

Which requests: documents (main frames and iframes, redirects included), or every request with subresources=True, to
https URLs and to loopback http ones (localhost, *.localhost, 127.0.0.1, [::1]); never plain http to another host
(the draft: signatures over an unsecured channel can be replayed). domains= narrows it further, with the patterns of
Browser(allowed_domains=...). Not the REPL's own Python networking (http_get), which is not the browser.

How: domains.Guard's browser-level Fetch interception pauses each request, and Fetch.continueRequest sends it on with
the three headers added (one CDP round trip per request: why subresources are off by default). Fail-open: a request
that cannot be signed goes out unsigned.
"""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from browser_use.domains import canonical_host

LABEL = 'sig1'
TAG = 'web-bot-auth'
MAX_EXPIRES_IN = 86400  # the draft: RECOMMENDED no more than 24 hours after created
DIRECTORY_MEDIA_TYPE = 'application/http-message-signatures-directory+json'
SIGNED_HEADERS = ('signature', 'signature-input', 'signature-agent')  # replaced on a request this signs
_DEFAULT_PORT = {'http': 80, 'https': 443}


def _b64url(data: bytes) -> str:
	return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def _b64url_decode(text: str) -> bytes:
	return base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))


def _sf_string(value: str) -> str:
	"""An RFC 8941 sf-string: printable ASCII, with \\ and " escaped."""
	if not all(0x20 <= ord(c) <= 0x7E for c in value):
		raise ValueError(f'{value!r} is not printable ASCII, so it cannot be a structured-field string')
	return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def _host(url: str) -> tuple[str, str, int | None] | None:
	"""(scheme, host as the browser sends it, port) of an http(s) URL, else None. The host is canonical_host's:
	punycode for a Unicode name, as Chrome sends it (faß.de -> xn--fa-hia.de), dotted-decimal IPv4, IPv6 without
	brackets."""
	try:
		u = urlsplit(url)
		port = u.port
	except ValueError:
		return None
	if u.scheme not in _DEFAULT_PORT or not u.hostname:
		return None
	host = canonical_host(u.hostname)  # drops a trailing dot, which Chrome keeps in Host for a name (not an IP)
	if u.hostname.endswith('.') and not _ip(host):
		host += '.'
	return (u.scheme, host, port) if host.isascii() else None


def _ip(host: str) -> bool:
	try:
		ipaddress.ip_address(host)
	except ValueError:
		return False
	return True


def _loopback(host: str) -> bool:
	host = host.removesuffix('.')
	if host == 'localhost' or host.endswith('.localhost'):
		return True
	try:
		return ipaddress.ip_address(host).is_loopback
	except ValueError:  # a name, or not an address at all (127.999.999.999)
		return False


def authority(url: str) -> str | None:
	"""RFC 9421 @authority of an http(s) URL: the host as the browser sends it, with the port only when it is not the
	default. None for any other URL."""
	if (parts := _host(url)) is None:
		return None
	scheme, host, port = parts
	host = f'[{host}]' if ':' in host else host
	return host if port in (None, _DEFAULT_PORT[scheme]) else f'{host}:{port}'


def _load_key(key: Any):
	from cryptography.hazmat.primitives import serialization
	from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

	if isinstance(key, Ed25519PrivateKey):
		return key
	if isinstance(key, dict):  # a private JWK
		if key.get('kty') != 'OKP' or key.get('crv') != 'Ed25519' or not key.get('d'):
			raise ValueError('WebBotAuth(key=...) as a JWK must be a private Ed25519 key: kty "OKP", crv "Ed25519" and d')
		return Ed25519PrivateKey.from_private_bytes(_b64url_decode(key['d']))
	if isinstance(key, Path) or (isinstance(key, str) and '-----BEGIN' not in key):
		key = Path(key).expanduser().read_bytes()
	if isinstance(key, str):
		key = key.encode()
	if not isinstance(key, bytes):
		raise TypeError(
			f'WebBotAuth(key=...) takes an Ed25519 private key as PEM, a path to a PEM file, a private JWK dict or a '
			f'cryptography Ed25519PrivateKey, not {type(key).__name__}'
		)
	loaded = serialization.load_pem_private_key(key, password=None)
	if not isinstance(loaded, Ed25519PrivateKey):
		raise ValueError(f'WebBotAuth(key=...) must be an Ed25519 key, not {type(loaded).__name__}')
	return loaded


class WebBotAuth:
	"""Sign the browser's requests with Web Bot Auth (see the module docstring).

	key: your Ed25519 private key, as PEM text, a path to a PEM file, a private JWK dict or a cryptography
	  Ed25519PrivateKey. WebBotAuth.generate(signature_agent) makes a new one.
	signature_agent: the https URL where you serve directory(), usually
	  https://<your domain>/.well-known/http-message-signatures-directory.
	domains: sign only requests to these sites (Browser(allowed_domains=...) patterns); None signs every eligible one.
	expires_in: seconds each signature stays valid, 1 to 86400 (default 60).
	subresources: also sign scripts, images, fetch() and the rest, not just documents (one CDP round trip each).
	legacy_signature_agent: send Signature-Agent as a bare string, the form of earlier drafts, covered as
	  "signature-agent" without key=. The current draft requires the dictionary form (the default), but some verifiers
	  still accept only the string: Cloudflare's demo at http-message-signatures-example.research.cloudflare.com
	  rejected the dictionary form and accepted the string in November 2026 (cloudflare/web-bot-auth#199).
	"""

	def __init__(
		self,
		key: Any,
		signature_agent: str,
		*,
		domains: list[str] | None = None,
		expires_in: int = 60,
		subresources: bool = False,
		legacy_signature_agent: bool = False,
	):
		from browser_use.domains import DomainRules

		ok = isinstance(signature_agent, str) and signature_agent.startswith('https://') and authority(signature_agent)
		if not ok or not all(0x21 <= ord(c) <= 0x7E for c in signature_agent):  # an sf-string; punycode a non-ASCII host
			raise ValueError(
				f'WebBotAuth(signature_agent=...) must be the https URL of your key directory, such as '
				f"'https://example.com/.well-known/http-message-signatures-directory', not {signature_agent!r}"
			)
		if isinstance(expires_in, bool) or not isinstance(expires_in, int) or not 1 <= expires_in <= MAX_EXPIRES_IN:
			raise ValueError(f'WebBotAuth(expires_in=...) must be whole seconds from 1 to {MAX_EXPIRES_IN}, not {expires_in!r}')
		for name, flag in (('subresources', subresources), ('legacy_signature_agent', legacy_signature_agent)):
			if not isinstance(flag, bool):
				raise TypeError(f'WebBotAuth({name}=...) must be True or False, not {flag!r}')
		self._key = _load_key(key)
		self.signature_agent = signature_agent
		self.domains = DomainRules.of(domains) if domains else None
		self.expires_in = expires_in
		self.subresources, self.legacy_signature_agent = subresources, legacy_signature_agent
		x = self.public_bytes()
		# RFC 7638 / RFC 8037 A.3: SHA-256 over the required members, in lexicographic order, no whitespace
		thumbprint = json.dumps({'crv': 'Ed25519', 'kty': 'OKP', 'x': _b64url(x)}, separators=(',', ':'), sort_keys=True)
		self.keyid = _b64url(hashlib.sha256(thumbprint.encode()).digest())

	@classmethod
	def generate(cls, signature_agent: str, **options: Any) -> WebBotAuth:
		"""A new Ed25519 key. Save private_key_pem() somewhere safe and serve directory() at signature_agent."""
		from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

		return cls(Ed25519PrivateKey.generate(), signature_agent, **options)

	def __repr__(self) -> str:  # never the key
		return f'WebBotAuth(signature_agent={self.signature_agent!r}, keyid={self.keyid!r})'

	def public_bytes(self) -> bytes:
		from cryptography.hazmat.primitives import serialization

		return self._key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)

	def private_key_pem(self) -> str:
		from cryptography.hazmat.primitives import serialization

		return self._key.private_bytes(
			serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
		).decode('ascii')

	def directory(self) -> dict[str, Any]:
		"""The JWK Set to serve at signature_agent: your public key only."""
		return {'keys': [{'kty': 'OKP', 'crv': 'Ed25519', 'x': _b64url(self.public_bytes()), 'kid': self.keyid, 'use': 'sig'}]}

	def signs(self, url: str) -> bool:
		"""Whether a request to url gets signed: https, or http to a loopback host, and inside domains."""
		if (parts := _host(url)) is None:
			return False
		if parts[0] != 'https' and not _loopback(parts[1]):
			return False
		return self.domains is None or self.domains.blocked(url) is None

	def sign(self, url: str, *, created: int | None = None, nonce: str | None = None) -> dict[str, str] | None:
		"""The three headers for a request to url, or None when signs(url) is False."""
		if not self.signs(url):
			return None
		created = int(time.time()) if created is None else created
		nonce = base64.b64encode(os.urandom(64)).decode('ascii') if nonce is None else nonce
		agent = _sf_string(self.signature_agent)
		component = '"signature-agent"' if self.legacy_signature_agent else f'"signature-agent";key="{LABEL}"'
		params = (
			f'("@authority" {component});created={created};keyid={_sf_string(self.keyid)};'
			f'alg="ed25519";expires={created + self.expires_in};nonce={_sf_string(nonce)};tag="{TAG}"'
		)
		base = f'"@authority": {authority(url)}\n{component}: {agent}\n"@signature-params": {params}'
		signature = base64.b64encode(self._key.sign(base.encode('ascii'))).decode('ascii')
		return {
			'Signature-Agent': agent if self.legacy_signature_agent else f'{LABEL}={agent}',
			'Signature-Input': f'{LABEL}={params}',
			'Signature': f'{LABEL}=:{signature}:',
		}

	def headers(self, request: dict[str, Any]) -> list[dict[str, str]] | None:
		"""Fetch.continueRequest(headers=...) for a Fetch.requestPaused request: its own headers, minus any Signature,
		Signature-Input or Signature-Agent it had, plus ours. None: send it as it is (out of scope)."""
		signed = self.sign(str(request.get('url', '')))
		if signed is None:
			return None
		own = {k: v for k, v in (request.get('headers') or {}).items() if k.lower() not in SIGNED_HEADERS}
		return [{'name': k, 'value': str(v)} for k, v in {**own, **signed}.items()]
