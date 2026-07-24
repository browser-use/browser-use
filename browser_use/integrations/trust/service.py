"""
AgentID Trust Provider — generates and verifies Agent-Trust-Score JWTs.

This module implements the TrustProvider interface for the AgentID protocol.
Browser-use agents attach these JWTs to requests so site operators can make
trust-based access decisions.

Protocol spec: https://getagentid.dev/docs/trust-protocol
"""

import base64
import json
import logging
import time
from abc import ABC, abstractmethod

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

# Ed25519 verification is optional at import time (mirrors the pydantic/httpx
# guard pattern in this package): we only need it when actually verifying a
# signed JWT, and we raise a clear, actionable error at that point if missing.
try:
	from cryptography.exceptions import InvalidSignature
	from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

	_HAS_CRYPTO = True
except ImportError:
	_HAS_CRYPTO = False

logger = logging.getLogger(__name__)


def _b64url_decode(segment: str) -> bytes:
	"""Decode a base64url JWT segment, restoring stripped padding."""
	return base64.urlsafe_b64decode(segment + '=' * (-len(segment) % 4))


class TrustClaims(BaseModel):
	"""Decoded trust claims from an Agent-Trust-Score JWT."""

	model_config = ConfigDict(extra='allow')

	agent_id: str = ''
	trust_score: int = 0
	trust_level: str = 'L1'
	scarring_score: int = 0
	risk_score: int = 0
	attestations: list[str] = Field(default_factory=list)
	attestation_count: int = 0
	provider: str = ''
	no_trust_data: bool = False
	reason: str = ''
	iat: int = 0
	exp: int = 0

	@field_validator('trust_level')
	@classmethod
	def validate_trust_level(cls, v: str) -> str:
		valid_levels = {'L0', 'L1', 'L2', 'L3', 'L4'}
		if v not in valid_levels:
			raise ValueError(f'Invalid trust level: {v}. Must be one of {valid_levels}')
		return v

	@property
	def is_expired(self) -> bool:
		return time.time() > self.exp

	def meets_policy(self, policy: dict) -> bool:
		"""Check if claims meet a threshold policy dict."""
		if policy.get('min_trust_score') is not None and self.trust_score < policy['min_trust_score']:
			return False
		if policy.get('max_scarring_score') is not None and self.scarring_score > policy['max_scarring_score']:
			return False
		if policy.get('max_risk_score') is not None and self.risk_score > policy['max_risk_score']:
			return False
		required = policy.get('required_attestations', [])
		for req in required:
			if req not in self.attestations:
				return False
		return True


class TrustProvider(ABC):
	"""Abstract base class for trust providers."""

	@abstractmethod
	async def get_trust_jwt(self, agent_id: str) -> str:
		"""Get a signed trust JWT for the given agent."""
		...

	@abstractmethod
	async def verify_trust_jwt(self, jwt: str) -> TrustClaims:
		"""Decode and verify a trust JWT, returning claims."""
		...


class AgentIDTrustProvider(TrustProvider):
	"""
	AgentID trust provider — generates and verifies Agent-Trust-Score JWTs.

	The provider fetches signed JWTs from the AgentID API and caches them.
	JWTs contain trust scores, scarring data, and attestation lists that
	site operators use to make access control decisions.

	Example:
		provider = AgentIDTrustProvider(api_key="key_...")
		jwt = await provider.get_trust_jwt("agent_abc123")
		claims = await provider.verify_trust_jwt(jwt)
		print(f"Trust score: {claims.trust_score}, Level: {claims.trust_level}")
	"""

	BASE_URL = 'https://getagentid.dev/api/v1'
	CACHE_TTL_SECONDS = 3500  # slightly under 1 hour

	JWKS_TTL_SECONDS = 86400  # cache the provider key for 24h (spec §4.1)

	def __init__(self, api_key: str | None = None, base_url: str | None = None, public_key_b64: str | None = None):
		"""
		Args:
			api_key: Optional bearer token for the AgentID API.
			base_url: Override the API base URL (defaults to the public endpoint).
			public_key_b64: Optional base64url Ed25519 public key (32 bytes) to verify
				signatures against. When omitted, the provider's key is fetched from its
				JWKS and cached. Inject it to verify offline / in tests without a network call.
		"""
		self.api_key = api_key
		if base_url:
			self.BASE_URL = base_url
		self._cache: dict[str, tuple[str, float]] = {}
		# Pinned/injected verification key, plus a (raw_key, expiry) JWKS cache.
		self._pinned_key_b64 = public_key_b64
		self._verify_key_cache: tuple[bytes, float] | None = None

	async def get_no_trust_header(self, reason: str = 'provider_unreachable') -> str:
		"""Return a minimal JWT indicating no trust data is available.

		Sites need to distinguish 'no data' from 'low trust'. This produces
		an unsigned JWT with ``no_trust_data: true`` so recipients can apply
		their ``action_on_fail`` policy immediately.

		Args:
			reason: Human-readable explanation (e.g. the exception message).

		Returns:
			An unsigned JWT string with ``alg: none``.
		"""
		payload = {
			'agent_id': 'unknown',
			'trust_score': 0,
			'trust_level': 'L0',
			'scarring_score': 0,
			'risk_score': 1.0,
			'attestations': [],
			'attestation_count': 0,
			'provider': 'agentid',
			'no_trust_data': True,
			'reason': reason,
			'iat': int(time.time()),
			'exp': int(time.time()) + 300,  # 5 min expiry for no-data headers
		}
		header = base64.urlsafe_b64encode(json.dumps({'alg': 'none', 'typ': 'Agent-Trust-Score'}).encode()).decode().rstrip('=')
		body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=')
		return f'{header}.{body}.'

	async def get_trust_jwt(self, agent_id: str) -> str:
		"""
		Get a signed Agent-Trust-Score JWT for an agent.

		Checks the local cache first. If the cached JWT is still valid, returns it.
		Otherwise fetches a fresh JWT from the AgentID API.

		If the provider is unreachable or any error occurs, returns a no-trust-data
		header instead of raising, so callers always get a usable JWT.

		Args:
			agent_id: The agent's unique identifier.

		Returns:
			A signed JWT string suitable for the Agent-Trust-Score header,
			or an unsigned no-trust-data JWT on failure.
		"""
		if not agent_id:
			raise ValueError('agent_id must not be empty')

		try:
			# Check cache
			if agent_id in self._cache:
				jwt, expiry = self._cache[agent_id]
				if time.time() < expiry:
					logger.debug(f'Cache hit for agent {agent_id}')
					return jwt

			headers = {}
			if self.api_key:
				headers['Authorization'] = f'Bearer {self.api_key}'

			async with httpx.AsyncClient() as client:
				resp = await client.get(
					f'{self.BASE_URL}/agents/trust-header',
					params={'agent_id': agent_id},
					headers=headers,
					timeout=10,
				)
				resp.raise_for_status()

				data = resp.json()
				jwt = data.get('header')
				if not jwt:
					raise Exception(f'API response missing "header" field: {data}')

				# Cache it
				self._cache[agent_id] = (jwt, time.time() + self.CACHE_TTL_SECONDS)
				logger.info(f'Fetched trust JWT for agent {agent_id}')

				return jwt
		except Exception as e:
			logger.warning(f'Failed to fetch trust JWT for agent {agent_id}: {e}')
			return await self.get_no_trust_header(reason=str(e))

	async def _resolve_verify_key(self) -> bytes:
		"""Return the provider's raw 32-byte Ed25519 public key.

		Uses the pinned/injected key if one was given; otherwise fetches the
		provider's JWKS (cached for JWKS_TTL_SECONDS) and extracts the Ed25519 key.
		"""
		if self._pinned_key_b64:
			return _b64url_decode(self._pinned_key_b64)
		now = time.time()
		if self._verify_key_cache and now < self._verify_key_cache[1]:
			return self._verify_key_cache[0]
		root = self.BASE_URL.split('/api/')[0].rstrip('/')
		jwks_url = f'{root}/.well-known/jwks.json'
		async with httpx.AsyncClient() as client:
			resp = await client.get(jwks_url, timeout=10)
			resp.raise_for_status()
			jwks = resp.json()
		keys = jwks.get('keys', []) if isinstance(jwks, dict) else []
		ed = next((k for k in keys if k.get('kty') == 'OKP' and k.get('crv') == 'Ed25519' and k.get('x')), None)
		if not ed:
			raise ValueError(f'No Ed25519 key found in provider JWKS at {jwks_url}')
		raw = _b64url_decode(ed['x'])
		if len(raw) != 32:
			raise ValueError(f'Provider Ed25519 key has wrong length: {len(raw)} bytes')
		self._verify_key_cache = (raw, now + self.JWKS_TTL_SECONDS)
		return raw

	async def verify_trust_jwt(self, jwt: str) -> TrustClaims:
		"""
		Decode and cryptographically verify an Agent-Trust-Score JWT.

		Decodes the header + payload, then for any signed JWT verifies the Ed25519
		signature against the provider's public key (injected, or fetched from its
		JWKS and cached) BEFORE trusting any field (spec CR-4). Unsigned JWTs
		(``alg: none`` / empty signature) are only accepted when the payload carries
		``no_trust_data: true``; a forged or unverifiable signature is rejected.

		Args:
			jwt: The raw JWT string (three dot-separated base64url segments).

		Returns:
			TrustClaims with decoded payload data.

		Raises:
			ValueError: If the JWT format is invalid, expired, or from an unknown provider.
		"""
		if not jwt:
			raise ValueError('jwt must not be empty')

		parts = jwt.split('.')
		if len(parts) != 3:
			raise ValueError(f'Invalid JWT format: expected 3 parts, got {len(parts)}')

		# Decode header to inspect alg
		header_b64 = parts[0]
		header_b64 += '=' * (-len(header_b64) % 4)
		try:
			header = json.loads(base64.urlsafe_b64decode(header_b64))
		except Exception as e:
			raise ValueError(f'Failed to decode JWT header: {e}')

		# Decode payload (base64url -> JSON)
		payload_b64 = parts[1]
		# Add padding for base64
		payload_b64 += '=' * (-len(payload_b64) % 4)
		try:
			payload_json = base64.urlsafe_b64decode(payload_b64)
			payload = json.loads(payload_json)
		except Exception as e:
			raise ValueError(f'Failed to decode JWT payload: {e}')

		alg = header.get('alg', '')
		signature_segment = parts[2]
		is_no_trust = payload.get('no_trust_data', False)

		if alg == 'none' or not signature_segment:
			# Unsigned: only ever acceptable as an explicit "no trust data" signal.
			if not is_no_trust:
				raise ValueError(
					'Unsigned JWT (alg=none / empty signature) is only accepted '
					'for no_trust_data payloads — refusing unverified trust claims'
				)
		else:
			# Signed trust claim — the signature MUST be verified before any field
			# is trusted (spec CR-4). Only Ed25519/EdDSA is supported.
			if alg not in ('EdDSA', 'Ed25519'):
				raise ValueError(f'Unsupported JWT alg {alg!r}: only Ed25519/EdDSA signatures are verifiable')
			if not _HAS_CRYPTO:
				raise ImportError(
					'Verifying signed Agent-Trust-Score JWTs requires the "cryptography" package. '
					'Install it with: pip install cryptography'
				)
			try:
				raw_key = await self._resolve_verify_key()
				signature = _b64url_decode(signature_segment)
				Ed25519PublicKey.from_public_bytes(raw_key).verify(signature, f'{parts[0]}.{parts[1]}'.encode('ascii'))
			except InvalidSignature:
				raise ValueError('JWT signature verification failed — refusing forged trust claims')

		claims = TrustClaims(**payload)

		if claims.is_expired:
			raise ValueError(f'JWT expired at {claims.exp}, current time is {int(time.time())}')

		if claims.provider and claims.provider != 'agentid':
			raise ValueError(f'Unknown provider: {claims.provider}')

		return claims

	def clear_cache(self) -> None:
		"""Clear the JWT cache."""
		self._cache.clear()

	def remove_from_cache(self, agent_id: str) -> None:
		"""Remove a specific agent from the cache."""
		self._cache.pop(agent_id, None)
