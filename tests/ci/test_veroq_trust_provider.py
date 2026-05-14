"""
Tests for VeroQ Shield TrustProvider.

Tests use locally-constructed JWTs and direct object manipulation —
no network calls or mocks required. Follows browser-use test conventions:
real objects, async functions, tabs, no pytest.mark.asyncio needed.
"""

import base64
import hashlib
import hmac
import json
import time

import httpx
import pytest

from browser_use.integrations.trust.policy import TrustPolicy, TrustPolicyChain
from browser_use.integrations.trust.service import TrustClaims
from browser_use.integrations.trust.veroq import (
	ClaimVerdict,
	ShieldVerification,
	VeroQShieldTrustProvider,
)


def _make_veroq_jwt(payload: dict, api_key: str | None = 'test_key') -> str:
	"""Build a VeroQ Shield JWT with the given payload."""
	header = base64.urlsafe_b64encode(json.dumps({'alg': 'HS256', 'typ': 'Agent-Trust-Score'}).encode()).rstrip(b'=').decode()
	body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b'=').decode()
	if api_key:
		sig_input = f'{header}.{body}'.encode()
		sig = hmac.new(api_key.encode(), sig_input, hashlib.sha256).digest()
		sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b'=').decode()
	else:
		sig_b64 = base64.urlsafe_b64encode(b'unsigned').rstrip(b'=').decode()
	return f'{header}.{body}.{sig_b64}'


def _default_veroq_payload(**overrides) -> dict:
	"""Return a valid VeroQ Shield payload dict with sensible defaults."""
	payload = {
		'agent_id': 'agent_test_shield',
		'trust_score': 82,
		'trust_level': 'L3',
		'scarring_score': 0,
		'risk_score': 0,
		'attestations': ['output_verified', 'claims_supported', 'no_contradictions', 'receipt_available'],
		'attestation_count': 4,
		'provider': 'veroq_shield',
		'verification': {
			'overall_verdict': 'all_verified',
			'claims_extracted': 3,
			'claims_verified': 3,
			'claims_supported': 3,
			'claims_contradicted': 0,
			'receipt_ids': ['vr_test_001', 'vr_test_002', 'vr_test_003'],
			'summary': 'All 3 claims verified with 82% average confidence.',
			'claim_verdicts': [
				{
					'text': 'NVIDIA reported $22.1B in Q4 2024 revenue',
					'verdict': 'supported',
					'confidence': 0.91,
					'receipt_id': 'vr_test_001',
				},
				{
					'text': 'Revenue was up 265% year-over-year',
					'verdict': 'supported',
					'confidence': 0.87,
					'receipt_id': 'vr_test_002',
				},
				{
					'text': 'Data center revenue reached $18.4B',
					'verdict': 'supported',
					'confidence': 0.68,
					'receipt_id': 'vr_test_003',
				},
			],
		},
		'iat': int(time.time()),
		'exp': int(time.time()) + 1800,
	}
	payload.update(overrides)
	return payload


# ---------------------------------------------------------------------------
# VeroQShieldTrustProvider — constructor validation
# ---------------------------------------------------------------------------


class TestVeroQConstructor:
	def test_default_construction(self):
		provider = VeroQShieldTrustProvider()
		assert provider.BASE_URL == 'https://api.veroq.ai'
		assert provider.max_claims == 5
		assert provider.api_key is None

	def test_custom_api_key(self):
		provider = VeroQShieldTrustProvider(api_key='vq_test')
		assert provider.api_key == 'vq_test'

	def test_custom_base_url(self):
		provider = VeroQShieldTrustProvider(base_url='https://custom.veroq.ai')
		assert provider.BASE_URL == 'https://custom.veroq.ai'

	def test_custom_max_claims(self):
		provider = VeroQShieldTrustProvider(max_claims=3)
		assert provider.max_claims == 3

	def test_max_claims_bounds(self):
		with pytest.raises(ValueError):
			VeroQShieldTrustProvider(max_claims=0)
		with pytest.raises(ValueError):
			VeroQShieldTrustProvider(max_claims=11)


# ---------------------------------------------------------------------------
# VeroQShieldTrustProvider — verify_trust_jwt (local, no network)
# ---------------------------------------------------------------------------


class TestVeroQVerifyJWT:
	async def test_verify_valid_jwt(self):
		provider = VeroQShieldTrustProvider(api_key='test_key')
		jwt = _make_veroq_jwt(_default_veroq_payload())
		claims = await provider.verify_trust_jwt(jwt)
		assert claims.agent_id == 'agent_test_shield'
		assert claims.trust_score == 82
		assert claims.trust_level == 'L3'
		assert claims.provider == 'veroq_shield'
		assert 'output_verified' in claims.attestations
		assert 'receipt_available' in claims.attestations

	async def test_verify_expired_jwt_raises(self):
		provider = VeroQShieldTrustProvider(api_key='test_key')
		jwt = _make_veroq_jwt(_default_veroq_payload(exp=int(time.time()) - 100), api_key='test_key')
		with pytest.raises(ValueError, match='expired'):
			await provider.verify_trust_jwt(jwt)

	async def test_verify_wrong_provider_raises(self):
		provider = VeroQShieldTrustProvider(api_key='test_key')
		jwt = _make_veroq_jwt(_default_veroq_payload(provider='agentid'), api_key='test_key')
		with pytest.raises(ValueError, match='Wrong provider'):
			await provider.verify_trust_jwt(jwt)

	async def test_verify_empty_jwt_raises(self):
		provider = VeroQShieldTrustProvider()
		with pytest.raises(ValueError, match='jwt must not be empty'):
			await provider.verify_trust_jwt('')

	async def test_verify_bad_format_raises(self):
		provider = VeroQShieldTrustProvider()
		with pytest.raises(ValueError, match='Invalid JWT format'):
			await provider.verify_trust_jwt('not.a.valid.jwt.at.all')

	async def test_verify_hs256_without_api_key_raises(self):
		"""HS256 JWT cannot be verified without provider api_key."""
		provider = VeroQShieldTrustProvider()
		jwt = _make_veroq_jwt(_default_veroq_payload(), api_key='test_key')
		with pytest.raises(ValueError, match='Cannot verify HS256 JWT without api_key'):
			await provider.verify_trust_jwt(jwt)

	async def test_verify_empty_provider_ok(self):
		"""A JWT with empty provider should pass (backwards compatibility)."""
		provider = VeroQShieldTrustProvider(api_key='test_key')
		jwt = _make_veroq_jwt(_default_veroq_payload(provider=''), api_key='test_key')
		claims = await provider.verify_trust_jwt(jwt)
		assert claims.provider == ''

	async def test_verification_details_in_extra(self):
		"""The verification field should be accessible via model_extra."""
		provider = VeroQShieldTrustProvider(api_key='test_key')
		jwt = _make_veroq_jwt(_default_veroq_payload(), api_key='test_key')
		claims = await provider.verify_trust_jwt(jwt)
		assert claims.model_extra is not None
		verification = claims.model_extra.get('verification', {})
		assert verification['claims_extracted'] == 3
		assert verification['claims_supported'] == 3
		assert len(verification['receipt_ids']) == 3
		assert verification['claim_verdicts'][0]['verdict'] == 'supported'


# ---------------------------------------------------------------------------
# VeroQShieldTrustProvider — no-trust-data header
# ---------------------------------------------------------------------------


class TestVeroQNoTrustData:
	async def test_no_trust_header_structure(self):
		"""The no-trust header should be a valid 3-part JWT with empty signature."""
		provider = VeroQShieldTrustProvider()
		jwt = await provider.get_no_trust_header(reason='test_reason')
		parts = jwt.split('.')
		assert len(parts) == 3
		assert parts[2] == ''

	async def test_no_trust_header_payload(self):
		provider = VeroQShieldTrustProvider()
		jwt = await provider.get_no_trust_header(
			agent_id='agent_xyz',
			reason='api_timeout',
		)
		payload_b64 = jwt.split('.')[1]
		payload_b64 += '=' * (-len(payload_b64) % 4)
		payload = json.loads(base64.urlsafe_b64decode(payload_b64))
		assert payload['no_trust_data'] is True
		assert payload['reason'] == 'api_timeout'
		assert payload['agent_id'] == 'agent_xyz'
		assert payload['provider'] == 'veroq_shield'
		assert payload['trust_score'] == 0
		assert payload['trust_level'] == 'L0'

	async def test_no_trust_header_decodable_by_verify(self):
		provider = VeroQShieldTrustProvider()
		jwt = await provider.get_no_trust_header(reason='test')
		claims = await provider.verify_trust_jwt(jwt)
		assert claims.no_trust_data is True
		assert claims.reason == 'test'
		assert claims.trust_level == 'L0'

	async def test_get_trust_jwt_no_text_returns_no_trust(self):
		"""When no output_text is provided, should return no-trust-data."""
		provider = VeroQShieldTrustProvider()
		jwt = await provider.get_trust_jwt(agent_id='agent_test')
		claims = await provider.verify_trust_jwt(jwt)
		assert claims.no_trust_data is True
		assert 'no output text' in claims.reason

	async def test_get_trust_jwt_short_text_returns_no_trust(self):
		"""Text under 20 chars should return no-trust-data."""
		provider = VeroQShieldTrustProvider()
		jwt = await provider.get_trust_jwt(agent_id='agent_test', output_text='too short')
		claims = await provider.verify_trust_jwt(jwt)
		assert claims.no_trust_data is True

	async def test_get_trust_jwt_empty_agent_raises(self):
		provider = VeroQShieldTrustProvider()
		with pytest.raises(ValueError, match='agent_id must not be empty'):
			await provider.get_trust_jwt(agent_id='')

	async def test_get_trust_jwt_unreachable_api_returns_no_trust(self):
		"""When the API call fails, should fall back to no-trust-data."""
		provider = VeroQShieldTrustProvider(api_key='test')

		# Patch _call_shield to simulate a network failure without making a real HTTP call
		async def _failing_shield(*args, **kwargs):
			raise httpx.ConnectError('simulated connection failure')

		provider._call_shield = _failing_shield  # type: ignore[assignment]

		jwt = await provider.get_trust_jwt(
			agent_id='agent_test',
			output_text='This is a long enough text to trigger verification of claims.',
		)
		claims = await provider.verify_trust_jwt(jwt)
		assert claims.no_trust_data is True
		assert claims.agent_id == 'agent_test'


# ---------------------------------------------------------------------------
# VeroQShieldTrustProvider — cache behavior
# ---------------------------------------------------------------------------


class TestVeroQCache:
	def test_clear_cache(self):
		provider = VeroQShieldTrustProvider()
		provider._cache['agent_1:abc'] = ('jwt_value', time.time() + 3600)
		assert 'agent_1:abc' in provider._cache
		provider.clear_cache()
		assert len(provider._cache) == 0

	def test_remove_from_cache(self):
		provider = VeroQShieldTrustProvider()
		provider._cache['agent_1:abc'] = ('jwt_value', time.time() + 3600)
		provider._cache['agent_1:def'] = ('jwt_value2', time.time() + 3600)
		provider._cache['agent_2:ghi'] = ('jwt_value3', time.time() + 3600)
		provider.remove_from_cache('agent_1')
		assert 'agent_1:abc' not in provider._cache
		assert 'agent_1:def' not in provider._cache
		assert 'agent_2:ghi' in provider._cache


# ---------------------------------------------------------------------------
# VeroQShieldTrustProvider — score/level mapping
# ---------------------------------------------------------------------------


class TestScoreMapping:
	def test_confidence_to_trust_score(self):
		assert VeroQShieldTrustProvider._confidence_to_trust_score(0.0) == 0
		assert VeroQShieldTrustProvider._confidence_to_trust_score(0.5) == 50
		assert VeroQShieldTrustProvider._confidence_to_trust_score(0.82) == 82
		assert VeroQShieldTrustProvider._confidence_to_trust_score(1.0) == 100

	def test_confidence_clamped(self):
		assert VeroQShieldTrustProvider._confidence_to_trust_score(-0.5) == 0
		assert VeroQShieldTrustProvider._confidence_to_trust_score(1.5) == 100

	def test_score_to_level_L4(self):
		assert VeroQShieldTrustProvider._score_to_level(85) == 'L4'
		assert VeroQShieldTrustProvider._score_to_level(100) == 'L4'

	def test_score_to_level_L3(self):
		assert VeroQShieldTrustProvider._score_to_level(70) == 'L3'
		assert VeroQShieldTrustProvider._score_to_level(84) == 'L3'

	def test_score_to_level_L2(self):
		assert VeroQShieldTrustProvider._score_to_level(50) == 'L2'
		assert VeroQShieldTrustProvider._score_to_level(69) == 'L2'

	def test_score_to_level_L1(self):
		assert VeroQShieldTrustProvider._score_to_level(25) == 'L1'
		assert VeroQShieldTrustProvider._score_to_level(49) == 'L1'

	def test_score_to_level_L0(self):
		assert VeroQShieldTrustProvider._score_to_level(0) == 'L0'
		assert VeroQShieldTrustProvider._score_to_level(24) == 'L0'

	def test_text_hash_deterministic(self):
		h1 = VeroQShieldTrustProvider._text_hash('hello world')
		h2 = VeroQShieldTrustProvider._text_hash('hello world')
		assert h1 == h2
		assert len(h1) == 16

	def test_text_hash_different_inputs(self):
		h1 = VeroQShieldTrustProvider._text_hash('hello world')
		h2 = VeroQShieldTrustProvider._text_hash('hello world!')
		assert h1 != h2


# ---------------------------------------------------------------------------
# VeroQShieldTrustProvider — receipt URL
# ---------------------------------------------------------------------------


class TestReceiptURL:
	def test_receipt_url_default_base(self):
		provider = VeroQShieldTrustProvider()
		url = provider.get_receipt_url('vr_abc123')
		assert url == 'https://api.veroq.ai/api/v1/verify/receipt/vr_abc123'

	def test_receipt_url_custom_base(self):
		provider = VeroQShieldTrustProvider(base_url='https://custom.example.com')
		url = provider.get_receipt_url('vr_xyz')
		assert url == 'https://custom.example.com/api/v1/verify/receipt/vr_xyz'

	def test_receipt_url_empty_raises(self):
		provider = VeroQShieldTrustProvider()
		with pytest.raises(ValueError):
			provider.get_receipt_url('')


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class TestClaimVerdict:
	def test_defaults(self):
		v = ClaimVerdict(text='test claim')
		assert v.category == 'general'
		assert v.verdict == 'unverifiable'
		assert v.confidence == 0.0
		assert v.receipt_id is None
		assert v.correction is None

	def test_full_construction(self):
		v = ClaimVerdict(
			text='NVIDIA revenue was $22B',
			category='financial',
			verdict='supported',
			confidence=0.91,
			receipt_id='vr_001',
		)
		assert v.verdict == 'supported'
		assert v.confidence == 0.91


class TestShieldVerification:
	def test_defaults(self):
		v = ShieldVerification()
		assert v.claims == []
		assert v.claims_extracted == 0
		assert v.overall_verdict == 'unknown'

	def test_full_construction(self):
		v = ShieldVerification(
			claims=[ClaimVerdict(text='test', verdict='supported', confidence=0.9)],
			claims_extracted=1,
			claims_verified=1,
			claims_supported=1,
			overall_confidence=0.9,
			overall_verdict='all_verified',
			receipt_ids=['vr_001'],
		)
		assert len(v.claims) == 1
		assert v.overall_confidence == 0.9


# ---------------------------------------------------------------------------
# Policy integration — VeroQ Shield claims work with the standard policy engine
# ---------------------------------------------------------------------------


class TestPolicyIntegration:
	def test_shield_claims_pass_policy(self):
		"""VeroQ Shield claims should work with the standard TrustPolicy."""
		policy = TrustPolicy({'min_trust_score': 50, 'action_on_fail': 'block'})
		claims = TrustClaims(**_default_veroq_payload())
		result = policy.evaluate(claims)
		assert result.passed
		assert result.action == 'allow'
		assert result.provider == 'veroq_shield'

	def test_shield_low_score_fails_policy(self):
		policy = TrustPolicy({'min_trust_score': 90, 'action_on_fail': 'degrade'})
		claims = TrustClaims(**_default_veroq_payload(trust_score=45, trust_level='L1'))
		result = policy.evaluate(claims)
		assert not result.passed
		assert result.action == 'degrade'

	def test_shield_no_trust_data_triggers_policy(self):
		policy = TrustPolicy({'min_trust_score': 50, 'action_on_fail': 'block'})
		claims = TrustClaims(
			**_default_veroq_payload(
				no_trust_data=True,
				reason='api_timeout',
				trust_score=0,
				trust_level='L0',
			)
		)
		result = policy.evaluate(claims)
		assert not result.passed
		assert result.action == 'block'

	def test_shield_in_policy_chain(self):
		"""VeroQ Shield policy can be composed with identity policies."""
		identity_policy = TrustPolicy(
			{
				'min_trust_score': 50,
				'action_on_fail': 'log',
			}
		)
		accuracy_policy = TrustPolicy(
			{
				'min_trust_score': 70,
				'required_attestations': ['output_verified'],
				'action_on_fail': 'degrade',
			}
		)
		chain = TrustPolicyChain([identity_policy, accuracy_policy])

		# High-trust output
		claims = TrustClaims(**_default_veroq_payload())
		result = chain.evaluate(claims)
		assert result.passed
		assert result.action == 'allow'

	def test_shield_scarring_from_contradictions(self):
		"""Contradicted claims should produce scarring that triggers policy."""
		policy = TrustPolicy(
			{
				'max_scarring_score': 2,
				'action_on_fail': 'block',
			}
		)
		# Agent with contradictions: scarring_score = 6
		claims = TrustClaims(**_default_veroq_payload(scarring_score=6))
		result = policy.evaluate(claims)
		assert not result.passed
		assert result.action == 'block'
		assert 'scarring_score' in result.failures[0]

	def test_shield_required_attestation_output_verified(self):
		"""Policy can require the output_verified attestation."""
		policy = TrustPolicy(
			{
				'required_attestations': ['output_verified'],
				'action_on_fail': 'block',
			}
		)
		# Has output_verified
		claims = TrustClaims(**_default_veroq_payload())
		result = policy.evaluate(claims)
		assert result.passed

		# Missing output_verified
		claims_no_verify = TrustClaims(**_default_veroq_payload(attestations=['claims_supported']))
		result_no = policy.evaluate(claims_no_verify)
		assert not result_no.passed
