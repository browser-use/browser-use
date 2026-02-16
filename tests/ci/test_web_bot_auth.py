"""Tests for Web Bot Auth (RFC 9421 HTTP Message Signatures) integration."""

import base64
import hashlib
import json
import re
from pathlib import Path

import pytest

from browser_use.browser.web_bot_auth import WebBotAuthConfig, WebBotAuthSigner, _b64url_encode

# ---------------------------------------------------------------------------
# Helper — only needed for JWK-specific tests
# ---------------------------------------------------------------------------


def _pem_to_jwk(pem: str) -> dict:
	"""Convert PEM private key to JWK dict."""
	from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
	from cryptography.hazmat.primitives.serialization import (
		Encoding,
		NoEncryption,
		PrivateFormat,
		PublicFormat,
		load_pem_private_key,
	)

	key = load_pem_private_key(pem.encode(), password=None)
	assert isinstance(key, Ed25519PrivateKey)
	d_bytes = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
	x_bytes = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
	return {
		'kty': 'OKP',
		'crv': 'Ed25519',
		'd': _b64url_encode(d_bytes),
		'x': _b64url_encode(x_bytes),
	}


# ---------------------------------------------------------------------------
# WebBotAuthConfig — validation
# ---------------------------------------------------------------------------


class TestWebBotAuthConfig:
	def test_no_key_rejects(self):
		with pytest.raises(Exception, match='Exactly one'):
			WebBotAuthConfig()

	def test_multiple_keys_rejects(self):
		config = WebBotAuthConfig.generate()
		assert config.private_key_pem is not None
		jwk = _pem_to_jwk(config.private_key_pem)
		with pytest.raises(Exception, match='Exactly one'):
			WebBotAuthConfig(private_key_pem=config.private_key_pem, private_key_jwk=jwk)

	def test_extra_fields_forbidden(self):
		with pytest.raises(Exception):
			WebBotAuthConfig(private_key_pem='dummy', bogus_field='nope')  # type: ignore[call-arg]

	def test_jwk_key_accepted_and_matches_pem_keyid(self):
		config = WebBotAuthConfig.generate()
		assert config.private_key_pem is not None
		jwk = _pem_to_jwk(config.private_key_pem)
		loaded = WebBotAuthConfig(private_key_jwk=jwk)
		assert loaded.keyid == config.keyid


# ---------------------------------------------------------------------------
# WebBotAuthConfig.generate() and derived properties
# ---------------------------------------------------------------------------


class TestWebBotAuthConfigGenerate:
	def test_generate_creates_valid_config(self):
		config = WebBotAuthConfig.generate()
		assert config.private_key_pem is not None
		assert config.private_key_pem.startswith('-----BEGIN PRIVATE KEY-----')
		assert config.private_key_jwk is None
		assert config.private_key_path is None

	def test_generate_with_options(self):
		url = 'https://bot.example.com/.well-known/http-message-signatures-directory'
		config = WebBotAuthConfig.generate(signature_agent_url=url, ttl_seconds=300)
		assert config.signature_agent_url == url
		assert config.ttl_seconds == 300

	def test_generate_unique_keys(self):
		assert WebBotAuthConfig.generate().keyid != WebBotAuthConfig.generate().keyid

	def test_public_jwk_format(self):
		jwk = WebBotAuthConfig.generate().public_jwk
		assert jwk['kty'] == 'OKP'
		assert jwk['crv'] == 'Ed25519'
		assert 'x' in jwk
		assert 'd' not in jwk  # must NOT contain private key

	def test_keyid_is_jwk_thumbprint(self):
		"""keyid = SHA-256 of canonical JWK JSON, base64url-encoded (RFC 7638)."""
		config = WebBotAuthConfig.generate()
		canonical = json.dumps(config.public_jwk, separators=(',', ':'), sort_keys=True)
		expected = _b64url_encode(hashlib.sha256(canonical.encode()).digest())
		assert config.keyid == expected

	def test_keyid_matches_signer(self):
		config = WebBotAuthConfig.generate()
		assert config.keyid == WebBotAuthSigner(config).keyid

	def test_save_and_load_private_key(self, tmp_path: Path):
		config = WebBotAuthConfig.generate()
		key_path = tmp_path / 'test-key.pem'
		config.save_private_key(key_path)

		loaded = WebBotAuthConfig(private_key_path=key_path)
		assert loaded.keyid == config.keyid


# ---------------------------------------------------------------------------
# WebBotAuthSigner — header generation and signature verification
# ---------------------------------------------------------------------------


class TestWebBotAuthSigner:
	def test_headers_present(self):
		signer = WebBotAuthSigner(WebBotAuthConfig.generate())
		headers = signer.sign_request_headers('https://example.com/page')
		assert 'Signature' in headers
		assert 'Signature-Input' in headers
		assert 'Signature-Agent' not in headers

	def test_signature_agent_header_included(self):
		url = 'https://bot.example.com/.well-known/http-message-signatures-directory'
		config = WebBotAuthConfig.generate(signature_agent_url=url)
		headers = WebBotAuthSigner(config).sign_request_headers('https://example.com/page')
		assert headers['Signature-Agent'] == url

	def test_signature_input_format(self):
		config = WebBotAuthConfig.generate()
		signer = WebBotAuthSigner(config)
		headers = signer.sign_request_headers('https://example.com/page')

		inner = headers['Signature-Input'][len('sig1=') :]
		assert '("@authority")' in inner
		assert ';created=' in inner
		assert ';expires=' in inner
		assert ';nonce="' in inner
		assert f';keyid="{config.keyid}"' in inner
		assert ';alg="ed25519"' in inner
		assert ';tag="web-bot-auth"' in inner

	def test_signature_input_with_agent_url(self):
		url = 'https://bot.example.com/.well-known/http-message-signatures-directory'
		config = WebBotAuthConfig.generate(signature_agent_url=url)
		inner = WebBotAuthSigner(config).sign_request_headers('https://example.com/')['Signature-Input']
		assert '("@authority" "signature-agent")' in inner

	def test_signature_is_64_byte_ed25519(self):
		headers = WebBotAuthSigner(WebBotAuthConfig.generate()).sign_request_headers('https://example.com/')
		sig = headers['Signature']
		assert sig.startswith('sig1=:') and sig.endswith(':')
		assert len(base64.b64decode(sig[len('sig1=:') : -1])) == 64

	def test_unique_nonce_per_request(self):
		signer = WebBotAuthSigner(WebBotAuthConfig.generate())
		h1 = signer.sign_request_headers('https://example.com/')
		h2 = signer.sign_request_headers('https://example.com/')

		nonce_re = re.compile(r';nonce="([^"]+)"')
		m1 = nonce_re.search(h1['Signature-Input'])
		m2 = nonce_re.search(h2['Signature-Input'])
		assert m1 and m2
		assert m1.group(1) != m2.group(1)

	def test_signature_verifies(self):
		"""Reconstruct signature base and verify Ed25519 signature."""
		from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
		from cryptography.hazmat.primitives.serialization import load_pem_private_key

		config = WebBotAuthConfig.generate()
		assert config.private_key_pem is not None
		headers = WebBotAuthSigner(config).sign_request_headers('https://example.com/page?foo=bar')

		sig_bytes = base64.b64decode(headers['Signature'][len('sig1=:') : -1])
		sig_input_str = headers['Signature-Input'][len('sig1=') :]
		sig_base = f'"@authority": example.com\n"@signature-params": {sig_input_str}'

		key = load_pem_private_key(config.private_key_pem.encode(), password=None)
		assert isinstance(key, Ed25519PrivateKey)
		key.public_key().verify(sig_bytes, sig_base.encode('utf-8'))

	def test_signature_with_agent_url_verifies(self):
		from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
		from cryptography.hazmat.primitives.serialization import load_pem_private_key

		agent_url = 'https://bot.example.com/.well-known/http-message-signatures-directory'
		config = WebBotAuthConfig.generate(signature_agent_url=agent_url)
		assert config.private_key_pem is not None
		headers = WebBotAuthSigner(config).sign_request_headers('https://target.example.com/api')

		sig_bytes = base64.b64decode(headers['Signature'][len('sig1=:') : -1])
		sig_input_str = headers['Signature-Input'][len('sig1=') :]
		sig_base = f'"@authority": target.example.com\n"signature-agent": {agent_url}\n"@signature-params": {sig_input_str}'

		key = load_pem_private_key(config.private_key_pem.encode(), password=None)
		assert isinstance(key, Ed25519PrivateKey)
		key.public_key().verify(sig_bytes, sig_base.encode('utf-8'))

	def test_non_standard_port_in_authority(self):
		from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
		from cryptography.hazmat.primitives.serialization import load_pem_private_key

		config = WebBotAuthConfig.generate()
		assert config.private_key_pem is not None
		headers = WebBotAuthSigner(config).sign_request_headers('https://example.com:8443/path')

		sig_bytes = base64.b64decode(headers['Signature'][len('sig1=:') : -1])
		sig_input_str = headers['Signature-Input'][len('sig1=') :]
		sig_base = f'"@authority": example.com:8443\n"@signature-params": {sig_input_str}'

		key = load_pem_private_key(config.private_key_pem.encode(), password=None)
		assert isinstance(key, Ed25519PrivateKey)
		key.public_key().verify(sig_bytes, sig_base.encode('utf-8'))


# ---------------------------------------------------------------------------
# BrowserSession integration
# ---------------------------------------------------------------------------


class TestWebBotAuthBrowserSession:
	def test_disabled_by_default(self):
		from browser_use.browser.profile import BrowserProfile
		from browser_use.browser.session import BrowserSession

		assert BrowserProfile().web_bot_auth is None
		assert BrowserSession(headless=True)._web_bot_auth_signer is None

	def test_browser_profile_accepts_config(self):
		from browser_use.browser.profile import BrowserProfile

		config = WebBotAuthConfig.generate()
		profile = BrowserProfile(web_bot_auth=config)
		assert profile.web_bot_auth is not None
		assert profile.web_bot_auth.keyid == config.keyid

	def test_direct_kwarg_on_browser_session(self):
		"""web_bot_auth can be passed directly to BrowserSession without BrowserProfile wrapper."""
		from browser_use.browser.session import BrowserSession

		config = WebBotAuthConfig.generate()
		session = BrowserSession(headless=True, web_bot_auth=config)
		assert session.browser_profile.web_bot_auth is not None
		assert session.browser_profile.web_bot_auth.keyid == config.keyid
