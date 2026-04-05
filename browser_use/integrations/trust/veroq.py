"""
VeroQ Shield Trust Provider — output accuracy verification for browser agents.

The other trust providers answer "should I engage with this agent?" (identity,
attestation, interaction history). This provider answers a different question:
"is the agent's output actually accurate?" — post-call verification that
catches hallucinations and factual drift even from well-identified, highly-
attested agents.

VeroQ Shield extracts verifiable claims from any LLM output, checks them
against live evidence, and returns per-claim verdicts with confidence scores.
Verification receipts provide a permanent, tamper-evident audit trail.

API docs: https://veroq.ai/docs
Python SDK: pip install veroq
GitHub: https://github.com/veroq-ai/shield

Usage:
	from browser_use.integrations.trust import VeroQShieldTrustProvider

	provider = VeroQShieldTrustProvider(api_key="vq_...")
	jwt = await provider.get_trust_jwt(
		agent_id="agent_abc123",
		output_text="NVIDIA reported $22.1B in Q4 2024 revenue, up 265% YoY.",
	)
	claims = await provider.verify_trust_jwt(jwt)
	print(f"Output trust: {claims.trust_score}/100, Level: {claims.trust_level}")
"""

import base64
import hashlib
import json
import logging
import time

import httpx
from pydantic import BaseModel, ConfigDict, Field

from .service import TrustClaims, TrustProvider

logger = logging.getLogger(__name__)


class ClaimVerdict(BaseModel):
	"""Individual claim verdict from VeroQ Shield verification."""

	model_config = ConfigDict(extra='allow')

	text: str
	category: str = 'general'
	verdict: str = 'unverifiable'
	confidence: float = 0.0
	receipt_id: str | None = None
	correction: str | None = None


class ShieldVerification(BaseModel):
	"""Full verification result from VeroQ Shield."""

	model_config = ConfigDict(extra='allow')

	claims: list[ClaimVerdict] = Field(default_factory=list)
	claims_extracted: int = 0
	claims_verified: int = 0
	claims_supported: int = 0
	claims_contradicted: int = 0
	overall_confidence: float = 0.0
	overall_verdict: str = 'unknown'
	summary: str = ''
	receipt_ids: list[str] = Field(default_factory=list)


class VeroQShieldTrustProvider(TrustProvider):
	"""
	VeroQ Shield trust provider — output accuracy verification.

	Unlike identity/attestation providers that gate *access*, Shield gates
	*content accuracy*. It extracts verifiable claims from LLM output, checks
	them against live evidence, and produces a trust score (0-100) reflecting
	how well the output holds up under scrutiny.

	The provider maps Shield's continuous confidence scores to the standard
	trust level scale:
		L4 (>= 85): all claims verified with high confidence
		L3 (>= 70): mostly verified, minor gaps
		L2 (>= 50): partially verified, some claims unverifiable
		L1 (>= 25): low confidence or contradictions found
		L0 (< 25):  output substantially contradicted or unverifiable

	Each JWT includes claim-level verdicts and receipt IDs. Receipts are
	permanent and publicly verifiable at:
		https://api.veroq.ai/api/v1/verify/receipt/{receipt_id}

	Example:
		provider = VeroQShieldTrustProvider(api_key="vq_...")
		jwt = await provider.get_trust_jwt(
			agent_id="agent_abc123",
			output_text="Tesla stock rose 8% after Q3 earnings beat.",
		)
		claims = await provider.verify_trust_jwt(jwt)
		if claims.trust_score >= 70:
			# output is trustworthy — act on it
			...
	"""

	BASE_URL = 'https://api.veroq.ai'
	CACHE_TTL_SECONDS = 1800  # 30 min — shorter than identity providers since outputs change
	REQUEST_TIMEOUT_SECONDS = 20  # Shield does LLM + web search per claim

	def __init__(
		self,
		api_key: str | None = None,
		base_url: str | None = None,
		max_claims: int = 5,
	):
		if api_key is not None and not isinstance(api_key, str):
			raise ValueError('api_key must be a string or None')
		if not (1 <= max_claims <= 10):
			raise ValueError('max_claims must be between 1 and 10')

		self.api_key = api_key
		if base_url:
			self.BASE_URL = base_url
		self.max_claims = max_claims
		self._cache: dict[str, tuple[str, float]] = {}

	@staticmethod
	def _text_hash(text: str) -> str:
		"""SHA-256 hash of text, used for cache keys and claim dedup."""
		return hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]

	@staticmethod
	def _confidence_to_trust_score(confidence: float) -> int:
		"""Map Shield's 0-1 confidence to 0-100 trust score."""
		return max(0, min(100, int(round(confidence * 100))))

	@staticmethod
	def _score_to_level(score: int) -> str:
		"""Map 0-100 trust score to L0-L4 trust level."""
		if score >= 85:
			return 'L4'
		if score >= 70:
			return 'L3'
		if score >= 50:
			return 'L2'
		if score >= 25:
			return 'L1'
		return 'L0'

	async def _call_shield(self, text: str, source: str | None = None) -> ShieldVerification:
		"""Call VeroQ Shield verify/output endpoint.

		Args:
			text: LLM output to verify (20-10000 chars).
			source: Optional LLM source identifier.

		Returns:
			ShieldVerification with claim-level verdicts.

		Raises:
			httpx.HTTPStatusError: On non-2xx response.
			httpx.TimeoutException: On timeout.
		"""
		if len(text) < 20: raise ValueError('text must be at least 20 characters')

		headers: dict[str, str] = {'Content-Type': 'application/json'}
		if self.api_key:
			headers['X-API-Key'] = self.api_key

		body: dict[str, str | int] = {
			'text': text[:10000],
			'max_claims': self.max_claims,
		}
		if source:
			body['source'] = source

		async with httpx.AsyncClient() as client:
			resp = await client.post(
				f'{self.BASE_URL}/api/v1/verify/output',
				headers=headers,
				json=body,
				timeout=self.REQUEST_TIMEOUT_SECONDS,
			)
			resp.raise_for_status()
			data = resp.json()

		# Parse claim verdicts
		claims = [
			ClaimVerdict(
				text=c.get('text', ''),
				category=c.get('category', 'general'),
				verdict=c.get('verdict', 'unverifiable'),
				confidence=c.get('confidence', 0.0),
				receipt_id=c.get('receipt_id'),
				correction=c.get('correction'),
			)
			for c in data.get('claims', [])
		]

		receipt_ids = [c.receipt_id for c in claims if c.receipt_id]

		return ShieldVerification(
			claims=claims,
			claims_extracted=data.get('claims_extracted', 0),
			claims_verified=data.get('claims_verified', 0),
			claims_supported=data.get('claims_supported', 0),
			claims_contradicted=data.get('claims_contradicted', 0),
			overall_confidence=data.get('overall_confidence', 0.0),
			overall_verdict=data.get('overall_verdict', 'unknown'),
			summary=data.get('summary', ''),
			receipt_ids=receipt_ids,
		)

	async def get_no_trust_header(self, agent_id: str = 'unknown', reason: str = 'provider_unreachable') -> str:
		"""Return a minimal JWT indicating no trust data is available.

		Follows the same convention as AgentIDTrustProvider: unsigned JWT
		with ``no_trust_data: true`` so the policy engine can apply
		``action_on_fail`` immediately.

		Args:
			agent_id: The agent ID (included in payload for diagnostics).
			reason: Human-readable explanation.

		Returns:
			An unsigned JWT string with ``alg: none``.
		"""
		payload = {
			'agent_id': agent_id,
			'trust_score': 0,
			'trust_level': 'L0',
			'scarring_score': 0,
			'risk_score': 100,
			'attestations': [],
			'attestation_count': 0,
			'provider': 'veroq_shield',
			'no_trust_data': True,
			'reason': reason,
			'iat': int(time.time()),
			'exp': int(time.time()) + 300,
		}
		header = base64.urlsafe_b64encode(
			json.dumps({'alg': 'none', 'typ': 'Agent-Trust-Score'}).encode()
		).decode().rstrip('=')
		body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=')
		return f'{header}.{body}.'

	async def get_trust_jwt(self, agent_id: str, output_text: str | None = None, source: str | None = None) -> str:  # type: ignore[override]  # extends base with optional output_text/source params
		"""
		Get an Agent-Trust-Score JWT based on output accuracy verification.

		If ``output_text`` is provided, Shield verifies its claims and produces
		a trust score reflecting accuracy. If omitted or too short, returns a
		no-trust-data header (since there's nothing to verify).

		Results are cached by SHA-256(agent_id + text) for CACHE_TTL_SECONDS.
		On any API failure, returns a no-trust-data JWT — never raises.

		Args:
			agent_id: The agent's unique identifier.
			output_text: The LLM output to verify.
			source: Optional LLM source identifier (e.g. "gpt-5.4").

		Returns:
			A signed JWT string suitable for the Agent-Trust-Score header,
			or an unsigned no-trust-data JWT on failure.
		"""
		if not agent_id:
			raise ValueError('agent_id must not be empty')

		# No text to verify — return no-trust-data
		if not output_text or len(output_text.strip()) < 20:
			return await self.get_no_trust_header(
				agent_id=agent_id,
				reason='no output text provided for verification',
			)

		# Cache key: agent + text content hash
		cache_key = f'{agent_id}:{self._text_hash(output_text)}'

		try:
			# Check cache
			if cache_key in self._cache:
				jwt, expiry = self._cache[cache_key]
				if time.time() < expiry:
					logger.debug(f'Cache hit for agent {agent_id} output verification')
					return jwt

			# Call Shield API
			verification = await self._call_shield(output_text, source=source)

			trust_score = self._confidence_to_trust_score(verification.overall_confidence)
			trust_level = self._score_to_level(trust_score)

			# Build attestation list from verification results
			attestations: list[str] = ['output_verified']
			if verification.claims_supported > 0:
				attestations.append('claims_supported')
			if verification.claims_contradicted == 0 and verification.claims_verified > 0:
				attestations.append('no_contradictions')
			if verification.receipt_ids:
				attestations.append('receipt_available')

			# Scarring: contradicted claims increase scarring score
			scarring = min(verification.claims_contradicted * 3, 10)

			# Risk: inverse of trust score, weighted by contradiction ratio
			contradiction_ratio = (
				verification.claims_contradicted / max(verification.claims_verified, 1)
			)
			risk_score = max(0, min(100, int(round(contradiction_ratio * 100))))

			payload = {
				'agent_id': agent_id,
				'trust_score': trust_score,
				'trust_level': trust_level,
				'scarring_score': scarring,
				'risk_score': risk_score,
				'attestations': attestations,
				'attestation_count': len(attestations),
				'provider': 'veroq_shield',
				'verification': {
					'overall_verdict': verification.overall_verdict,
					'claims_extracted': verification.claims_extracted,
					'claims_verified': verification.claims_verified,
					'claims_supported': verification.claims_supported,
					'claims_contradicted': verification.claims_contradicted,
					'receipt_ids': verification.receipt_ids,
					'summary': verification.summary,
					'claim_verdicts': [
						{
							'text': c.text,
							'verdict': c.verdict,
							'confidence': c.confidence,
							'receipt_id': c.receipt_id,
						}
						for c in verification.claims
					],
				},
				'iat': int(time.time()),
				'exp': int(time.time()) + self.CACHE_TTL_SECONDS,
			}

			# Build JWT (HMAC signed if api_key available, unsigned otherwise)
			header_data = {'alg': 'HS256', 'typ': 'Agent-Trust-Score'}
			header = base64.urlsafe_b64encode(
				json.dumps(header_data).encode()
			).decode().rstrip('=')
			body = base64.urlsafe_b64encode(
				json.dumps(payload).encode()
			).decode().rstrip('=')

			if self.api_key:
				import hmac
				sig_input = f'{header}.{body}'.encode()
				sig = hmac.new(
					self.api_key.encode(), sig_input, hashlib.sha256,
				).digest()
				sig_b64 = base64.urlsafe_b64encode(sig).decode().rstrip('=')
			else:
				sig_b64 = base64.urlsafe_b64encode(b'unsigned').decode().rstrip('=')

			jwt = f'{header}.{body}.{sig_b64}'

			# Cache it
			self._cache[cache_key] = (jwt, time.time() + self.CACHE_TTL_SECONDS)
			logger.info(
				f'Shield verification for agent {agent_id}: '
				f'score={trust_score}, level={trust_level}, '
				f'claims={verification.claims_verified}/{verification.claims_extracted}'
			)

			return jwt

		except Exception as e:
			logger.warning(f'Failed to verify output for agent {agent_id}: {e}')
			return await self.get_no_trust_header(agent_id=agent_id, reason=str(e))

	async def verify_trust_jwt(self, jwt: str) -> TrustClaims:
		"""
		Decode and verify a VeroQ Shield trust JWT.

		Decodes the JWT payload and validates structure. Accepts JWTs from the
		``veroq_shield`` provider. Unsigned JWTs (``alg: none``) are only
		accepted when ``no_trust_data: true``.

		The decoded claims include a ``verification`` extra field with
		claim-level verdicts and receipt IDs for audit trail.

		Args:
			jwt: The raw JWT string (three dot-separated base64url segments).

		Returns:
			TrustClaims with decoded payload data. Access ``verification``
			details via ``claims.model_extra['verification']``.

		Raises:
			ValueError: If the JWT format is invalid, expired, or wrong provider.
		"""
		if not jwt:
			raise ValueError('jwt must not be empty')

		parts = jwt.split('.')
		if len(parts) != 3:
			raise ValueError(f'Invalid JWT format: expected 3 parts, got {len(parts)}')

		# Decode header
		header_b64 = parts[0]
		header_b64 += '=' * (-len(header_b64) % 4)
		try:
			header = json.loads(base64.urlsafe_b64decode(header_b64))
		except Exception as e:
			raise ValueError(f'Failed to decode JWT header: {e}')

		# Decode payload
		payload_b64 = parts[1]
		payload_b64 += '=' * (-len(payload_b64) % 4)
		try:
			payload = json.loads(base64.urlsafe_b64decode(payload_b64))
		except Exception as e:
			raise ValueError(f'Failed to decode JWT payload: {e}')

		alg = header.get('alg', '')
		signature_segment = parts[2]
		is_no_trust = payload.get('no_trust_data', False)

		# Reject unsigned JWTs that claim to carry real trust data
		if alg == 'none' or not signature_segment:
			if not is_no_trust:
				raise ValueError(
					'Unsigned JWT (alg=none / empty signature) is only accepted '
					'for no_trust_data payloads — refusing unverified trust claims'
				)

		claims = TrustClaims(**payload)

		if claims.is_expired:
			raise ValueError(f'JWT expired at {claims.exp}, current time is {int(time.time())}')

		if claims.provider and claims.provider != 'veroq_shield':
			raise ValueError(f'Wrong provider: {claims.provider} (expected veroq_shield)')

		return claims

	def get_receipt_url(self, receipt_id: str) -> str:
		"""Get the public verification receipt URL.

		Receipts are permanent and tamper-evident. Anyone can verify the
		full evidence chain without an API key.

		Args:
			receipt_id: Receipt ID from a claim verdict (e.g. "vr_abc123").

		Returns:
			Public URL for the verification receipt.
		"""
		if not receipt_id: raise ValueError('receipt_id must not be empty')
		return f'{self.BASE_URL}/api/v1/verify/receipt/{receipt_id}'

	def clear_cache(self) -> None:
		"""Clear the verification cache."""
		self._cache.clear()

	def remove_from_cache(self, agent_id: str) -> None:
		"""Remove all cached entries for an agent."""
		keys_to_remove = [k for k in self._cache if k.startswith(f'{agent_id}:')]
		for k in keys_to_remove:
			del self._cache[k]
