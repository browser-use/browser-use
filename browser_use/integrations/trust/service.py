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

logger = logging.getLogger(__name__)


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
		if policy.get('min_trust_score') and self.trust_score < policy['min_trust_score']:
			return False
		if policy.get('max_scarring_score') and self.scarring_score > policy['max_scarring_score']:
			return False
		if policy.get('max_risk_score') and self.risk_score > policy['max_risk_score']:
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

	def __init__(self, api_key: str | None = None, base_url: str | None = None):
		self.api_key = api_key
		if base_url:
			self.BASE_URL = base_url
		self._cache: dict[str, tuple[str, float]] = {}

	async def get_trust_jwt(self, agent_id: str) -> str:
		"""
		Get a signed Agent-Trust-Score JWT for an agent.

		Checks the local cache first. If the cached JWT is still valid, returns it.
		Otherwise fetches a fresh JWT from the AgentID API.

		Args:
			agent_id: The agent's unique identifier.

		Returns:
			A signed JWT string suitable for the Agent-Trust-Score header.

		Raises:
			httpx.HTTPStatusError: If the API returns a non-200 status.
			Exception: If the response is missing the expected 'header' field.
		"""
		assert agent_id, 'agent_id must not be empty'

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

	async def verify_trust_jwt(self, jwt: str) -> TrustClaims:
		"""
		Decode and verify an Agent-Trust-Score JWT.

		Performs local decoding of the JWT payload (base64url) and validates
		basic structural requirements. Does NOT verify the cryptographic
		signature — that should be done server-side or with the public key.

		Args:
			jwt: The raw JWT string (three dot-separated base64url segments).

		Returns:
			TrustClaims with decoded payload data.

		Raises:
			ValueError: If the JWT format is invalid, expired, or from an unknown provider.
		"""
		assert jwt, 'jwt must not be empty'

		parts = jwt.split('.')
		if len(parts) != 3:
			raise ValueError(f'Invalid JWT format: expected 3 parts, got {len(parts)}')

		# Decode payload (base64url -> JSON)
		payload_b64 = parts[1]
		# Add padding for base64
		payload_b64 += '=' * (-len(payload_b64) % 4)
		try:
			payload_json = base64.urlsafe_b64decode(payload_b64)
			payload = json.loads(payload_json)
		except Exception as e:
			raise ValueError(f'Failed to decode JWT payload: {e}')

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
