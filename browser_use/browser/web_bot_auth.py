"""Web Bot Auth — RFC 9421 HTTP Message Signatures for bot identity verification.
Signs outgoing browser requests with Ed25519 so that sites can verify the bot's identity.

Spec: https://www.kernel.sh/docs/browsers/bot-detection/web-bot-auth
"""

import base64
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Self
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _b64url_encode(data: bytes) -> str:
	"""Base64url encode without padding (RFC 4648 §5)."""
	return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def _load_ed25519_private_key(config: 'WebBotAuthConfig'):
	"""Load an Ed25519 private key from whichever source the config provides.

	Returns a cryptography Ed25519PrivateKey instance.
	"""
	from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
	from cryptography.hazmat.primitives.serialization import load_pem_private_key

	if config.private_key_pem:
		key = load_pem_private_key(config.private_key_pem.encode(), password=None)
	elif config.private_key_path:
		key = load_pem_private_key(config.private_key_path.read_bytes(), password=None)
	elif config.private_key_jwk:
		jwk = config.private_key_jwk
		assert jwk.get('kty') == 'OKP' and jwk.get('crv') == 'Ed25519', 'JWK must be Ed25519 (kty=OKP, crv=Ed25519)'
		d_bytes = base64.urlsafe_b64decode(jwk['d'] + '==')
		key = Ed25519PrivateKey.from_private_bytes(d_bytes)
	else:
		raise ValueError('No key source provided')

	assert isinstance(key, Ed25519PrivateKey), f'Key must be Ed25519, got {type(key).__name__}'
	return key


def _derive_public_jwk_and_keyid(config: 'WebBotAuthConfig') -> tuple[dict, str]:
	"""Derive (public_jwk, keyid) from a config's private key.

	Returns (jwk_dict, keyid_string) where keyid is the JWK Thumbprint (RFC 7638).
	"""
	from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

	key = _load_ed25519_private_key(config)
	pub_bytes = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
	x_b64url = _b64url_encode(pub_bytes)

	jwk = {'kty': 'OKP', 'crv': 'Ed25519', 'x': x_b64url}
	canonical = json.dumps(jwk, separators=(',', ':'), sort_keys=True)
	keyid = _b64url_encode(hashlib.sha256(canonical.encode()).digest())

	return jwk, keyid


class WebBotAuthConfig(BaseModel):
	"""Configuration for Web Bot Auth (RFC 9421 HTTP Message Signatures).

	Enables cryptographic bot identity verification on outgoing browser requests.

	Quick start:
	    from browser_use import BrowserSession, WebBotAuthConfig

	    # Generate a fresh identity
	    config = WebBotAuthConfig.generate()

	    # Use it — all requests are signed automatically
	    session = BrowserSession(headless=True, web_bot_auth=config)

	    # Host this at /.well-known/http-message-signatures-directory
	    print(config.public_jwk)  # {'kty': 'OKP', 'crv': 'Ed25519', 'x': '...'}
	    print(config.keyid)       # JWK Thumbprint string
	"""

	model_config = ConfigDict(extra='forbid')

	private_key_pem: str | None = Field(
		default=None,
		description='PEM-encoded Ed25519 private key string.',
	)
	private_key_path: Path | None = Field(
		default=None,
		description='Path to a PEM-encoded Ed25519 private key file.',
	)
	private_key_jwk: dict | None = Field(
		default=None,
		description='Ed25519 private key in JWK format (dict with kty, crv, d, x fields).',
	)
	signature_agent_url: str | None = Field(
		default=None,
		description='URL to the public key directory (Signature-Agent header).',
	)
	ttl_seconds: int = Field(
		default=3600,
		ge=1,
		description='Signature TTL in seconds (default: 1 hour).',
	)

	@model_validator(mode='after')
	def validate_exactly_one_key_source(self) -> Self:
		sources = sum(
			[
				self.private_key_pem is not None,
				self.private_key_path is not None,
				self.private_key_jwk is not None,
			]
		)
		assert sources == 1, 'Exactly one of private_key_pem, private_key_path, or private_key_jwk must be provided'
		return self

	# ── Factory methods ───────────────────────────────────────────────

	@classmethod
	def generate(
		cls,
		signature_agent_url: str | None = None,
		ttl_seconds: int = 3600,
	) -> 'WebBotAuthConfig':
		"""Generate a fresh Ed25519 identity and return a ready-to-use config.

		Usage:
		    config = WebBotAuthConfig.generate()
		    session = BrowserSession(headless=True, web_bot_auth=config)
		"""
		from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
		from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

		key = Ed25519PrivateKey.generate()
		pem = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()
		return cls(
			private_key_pem=pem,
			signature_agent_url=signature_agent_url,
			ttl_seconds=ttl_seconds,
		)

	# ── Derived properties ────────────────────────────────────────────

	@property
	def public_jwk(self) -> dict:
		"""Public JWK dict for hosting in a key directory.

		Host this at /.well-known/http-message-signatures-directory:
		    {"keys": [config.public_jwk]}
		"""
		jwk, _ = _derive_public_jwk_and_keyid(self)
		return jwk

	@property
	def keyid(self) -> str:
		"""JWK Thumbprint (RFC 7638) used as keyid in signatures."""
		_, keyid = _derive_public_jwk_and_keyid(self)
		return keyid

	# ── Utility methods ───────────────────────────────────────────────

	def save_private_key(self, path: str | Path) -> None:
		"""Save the private key as a PEM file for reuse across sessions."""
		from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

		key = _load_ed25519_private_key(self)
		pem_bytes = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
		Path(path).write_bytes(pem_bytes)


class WebBotAuthSigner:
	"""Signs HTTP requests per the Web Bot Auth / RFC 9421 HTTP Message Signatures spec.

	Produces Signature, Signature-Input, and optionally Signature-Agent headers
	using Ed25519 over a deterministic signature base string.
	"""

	def __init__(self, config: WebBotAuthConfig) -> None:
		self._private_key = _load_ed25519_private_key(config)

		jwk, keyid = _derive_public_jwk_and_keyid(config)
		self._pub_b64url = jwk['x']
		self._keyid = keyid

		self._signature_agent_url = config.signature_agent_url
		self._ttl_seconds = config.ttl_seconds

	@property
	def keyid(self) -> str:
		"""The JWK Thumbprint used as keyid in signatures."""
		return self._keyid

	def sign_request_headers(self, url: str) -> dict[str, str]:
		"""Generate Web Bot Auth headers for a request URL.

		Returns a dict with 'Signature', 'Signature-Input', and optionally
		'Signature-Agent' headers ready to be added to the request.
		"""
		parsed = urlparse(url)
		authority = parsed.hostname or ''
		if parsed.port and parsed.port not in (80, 443):
			authority += f':{parsed.port}'

		now = int(time.time())
		expires = now + self._ttl_seconds
		nonce = _b64url_encode(os.urandom(64))

		# Determine signed components
		components = ['@authority']
		if self._signature_agent_url:
			components.append('signature-agent')

		# Build the signature-input string (inner list of RFC 8941 dictionary)
		component_list = ' '.join(f'"{c}"' for c in components)
		sig_input = (
			f'({component_list})'
			f';created={now}'
			f';expires={expires}'
			f';nonce="{nonce}"'
			f';keyid="{self._keyid}"'
			f';alg="ed25519"'
			f';tag="web-bot-auth"'
		)

		# Build the signature base (the exact bytes that get signed)
		lines = [f'"@authority": {authority}']
		if self._signature_agent_url:
			lines.append(f'"signature-agent": {self._signature_agent_url}')
		lines.append(f'"@signature-params": {sig_input}')
		sig_base = '\n'.join(lines)

		# Ed25519 sign
		signature_bytes = self._private_key.sign(sig_base.encode('utf-8'))
		sig_b64 = base64.b64encode(signature_bytes).decode()

		headers: dict[str, str] = {
			'Signature': f'sig1=:{sig_b64}:',
			'Signature-Input': f'sig1={sig_input}',
		}
		if self._signature_agent_url:
			headers['Signature-Agent'] = self._signature_agent_url

		return headers
