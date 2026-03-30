"""
Tests for AgentID TrustProvider and Policy Engine.

Tests use locally-constructed JWTs — no network calls or mocks required.
"""

import base64
import json
import time

import pytest

from agentid_trust_provider import AgentIDTrustProvider, TrustClaims
from policy_engine import PolicyResult, TrustPolicy, TrustPolicyChain


def _make_jwt(payload: dict) -> str:
	"""Build a fake JWT with the given payload (no real signature)."""
	header = base64.urlsafe_b64encode(json.dumps({'alg': 'HS256', 'typ': 'JWT'}).encode()).rstrip(b'=').decode()
	body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b'=').decode()
	sig = base64.urlsafe_b64encode(b'fakesig').rstrip(b'=').decode()
	return f'{header}.{body}.{sig}'


def _default_payload(**overrides) -> dict:
	"""Return a valid payload dict with sensible defaults."""
	payload = {
		'agent_id': 'agent_test_001',
		'trust_score': 75,
		'trust_level': 'L2',
		'scarring_score': 5,
		'risk_score': 10,
		'attestations': ['identity_verified', 'code_audit'],
		'attestation_count': 2,
		'provider': 'agentid',
		'iat': int(time.time()),
		'exp': int(time.time()) + 3600,
	}
	payload.update(overrides)
	return payload


# ---------------------------------------------------------------------------
# TrustClaims
# ---------------------------------------------------------------------------


class TestTrustClaims:
	def test_parse_valid_claims(self):
		claims = TrustClaims(**_default_payload())
		assert claims.agent_id == 'agent_test_001'
		assert claims.trust_score == 75
		assert claims.trust_level == 'L2'
		assert claims.scarring_score == 5
		assert claims.risk_score == 10
		assert 'identity_verified' in claims.attestations
		assert claims.attestation_count == 2
		assert claims.provider == 'agentid'

	def test_not_expired(self):
		claims = TrustClaims(**_default_payload())
		assert not claims.is_expired

	def test_expired(self):
		claims = TrustClaims(**_default_payload(exp=int(time.time()) - 100))
		assert claims.is_expired

	def test_meets_policy_passing(self):
		claims = TrustClaims(**_default_payload())
		assert claims.meets_policy({'min_trust_score': 50, 'max_risk_score': 20})

	def test_meets_policy_failing_trust(self):
		claims = TrustClaims(**_default_payload(trust_score=30))
		assert not claims.meets_policy({'min_trust_score': 50})

	def test_meets_policy_failing_attestation(self):
		claims = TrustClaims(**_default_payload())
		assert not claims.meets_policy({'required_attestations': ['sandbox_certified']})

	def test_invalid_trust_level_rejected(self):
		with pytest.raises(Exception):
			TrustClaims(**_default_payload(trust_level='INVALID'))

	def test_extra_fields_allowed(self):
		"""Extra fields in the JWT payload should not cause validation errors."""
		claims = TrustClaims(**_default_payload(custom_field='hello'))
		assert claims.agent_id == 'agent_test_001'


# ---------------------------------------------------------------------------
# AgentIDTrustProvider — verify_trust_jwt (local, no network)
# ---------------------------------------------------------------------------


class TestVerifyTrustJWT:
	async def test_verify_valid_jwt(self):
		provider = AgentIDTrustProvider()
		jwt = _make_jwt(_default_payload())
		claims = await provider.verify_trust_jwt(jwt)
		assert claims.agent_id == 'agent_test_001'
		assert claims.trust_score == 75
		assert claims.provider == 'agentid'

	async def test_verify_expired_jwt_raises(self):
		provider = AgentIDTrustProvider()
		jwt = _make_jwt(_default_payload(exp=int(time.time()) - 100))
		with pytest.raises(ValueError, match='expired'):
			await provider.verify_trust_jwt(jwt)

	async def test_verify_bad_format_raises(self):
		provider = AgentIDTrustProvider()
		with pytest.raises(ValueError, match='Invalid JWT format'):
			await provider.verify_trust_jwt('not.a.valid.jwt.at.all')

	async def test_verify_unknown_provider_raises(self):
		provider = AgentIDTrustProvider()
		jwt = _make_jwt(_default_payload(provider='unknown_provider'))
		with pytest.raises(ValueError, match='Unknown provider'):
			await provider.verify_trust_jwt(jwt)

	async def test_verify_empty_jwt_raises(self):
		provider = AgentIDTrustProvider()
		with pytest.raises(AssertionError):
			await provider.verify_trust_jwt('')

	async def test_verify_no_provider_field_ok(self):
		"""A JWT with empty provider should pass (backwards compatibility)."""
		provider = AgentIDTrustProvider()
		jwt = _make_jwt(_default_payload(provider=''))
		claims = await provider.verify_trust_jwt(jwt)
		assert claims.provider == ''


# ---------------------------------------------------------------------------
# AgentIDTrustProvider — cache behavior
# ---------------------------------------------------------------------------


class TestCache:
	def test_clear_cache(self):
		provider = AgentIDTrustProvider()
		provider._cache['agent_1'] = ('jwt_value', time.time() + 3600)
		assert 'agent_1' in provider._cache
		provider.clear_cache()
		assert len(provider._cache) == 0

	def test_remove_from_cache(self):
		provider = AgentIDTrustProvider()
		provider._cache['agent_1'] = ('jwt_value', time.time() + 3600)
		provider._cache['agent_2'] = ('jwt_value2', time.time() + 3600)
		provider.remove_from_cache('agent_1')
		assert 'agent_1' not in provider._cache
		assert 'agent_2' in provider._cache

	def test_custom_base_url(self):
		provider = AgentIDTrustProvider(base_url='https://custom.example.com/api')
		assert provider.BASE_URL == 'https://custom.example.com/api'


# ---------------------------------------------------------------------------
# TrustPolicy
# ---------------------------------------------------------------------------


class TestTrustPolicy:
	def test_default_policy_passes_everything(self):
		policy = TrustPolicy()
		claims = TrustClaims(**_default_payload())
		result = policy.evaluate(claims)
		assert result.passed
		assert result.action == 'allow'
		assert result.failures == []

	def test_min_trust_score_fail(self):
		policy = TrustPolicy({'min_trust_score': 90})
		claims = TrustClaims(**_default_payload(trust_score=50))
		result = policy.evaluate(claims)
		assert not result.passed
		assert 'trust_score' in result.failures[0]

	def test_max_scarring_score_fail(self):
		policy = TrustPolicy({'max_scarring_score': 3})
		claims = TrustClaims(**_default_payload(scarring_score=10))
		result = policy.evaluate(claims)
		assert not result.passed
		assert 'scarring_score' in result.failures[0]

	def test_max_risk_score_fail(self):
		policy = TrustPolicy({'max_risk_score': 5})
		claims = TrustClaims(**_default_payload(risk_score=20))
		result = policy.evaluate(claims)
		assert not result.passed
		assert 'risk_score' in result.failures[0]

	def test_required_attestation_missing(self):
		policy = TrustPolicy({'required_attestations': ['sandbox_certified']})
		claims = TrustClaims(**_default_payload())
		result = policy.evaluate(claims)
		assert not result.passed
		assert 'missing attestation' in result.failures[0]

	def test_required_attestation_present(self):
		policy = TrustPolicy({'required_attestations': ['identity_verified']})
		claims = TrustClaims(**_default_payload())
		result = policy.evaluate(claims)
		assert result.passed

	def test_action_on_fail_block(self):
		policy = TrustPolicy({'min_trust_score': 100, 'action_on_fail': 'block'})
		claims = TrustClaims(**_default_payload(trust_score=50))
		result = policy.evaluate(claims)
		assert result.action == 'block'

	def test_action_on_fail_degrade(self):
		policy = TrustPolicy({'min_trust_score': 100, 'action_on_fail': 'degrade'})
		claims = TrustClaims(**_default_payload(trust_score=50))
		result = policy.evaluate(claims)
		assert result.action == 'degrade'

	def test_multiple_failures(self):
		policy = TrustPolicy({
			'min_trust_score': 90,
			'max_risk_score': 5,
			'required_attestations': ['sandbox_certified'],
		})
		claims = TrustClaims(**_default_payload(trust_score=50, risk_score=20))
		result = policy.evaluate(claims)
		assert not result.passed
		assert len(result.failures) == 3

	def test_result_includes_metadata(self):
		policy = TrustPolicy()
		claims = TrustClaims(**_default_payload())
		result = policy.evaluate(claims)
		assert result.trust_level == 'L2'
		assert result.provider == 'agentid'


# ---------------------------------------------------------------------------
# TrustPolicyChain
# ---------------------------------------------------------------------------


class TestTrustPolicyChain:
	def test_all_pass(self):
		chain = TrustPolicyChain([
			TrustPolicy({'min_trust_score': 50}),
			TrustPolicy({'max_risk_score': 30}),
		])
		claims = TrustClaims(**_default_payload())
		result = chain.evaluate(claims)
		assert result.passed
		assert result.action == 'allow'

	def test_block_wins_over_degrade(self):
		chain = TrustPolicyChain([
			TrustPolicy({'min_trust_score': 100, 'action_on_fail': 'degrade'}),
			TrustPolicy({'max_risk_score': 1, 'action_on_fail': 'block'}),
		])
		claims = TrustClaims(**_default_payload(trust_score=50, risk_score=20))
		result = chain.evaluate(claims)
		assert not result.passed
		assert result.action == 'block'

	def test_degrade_wins_over_log(self):
		chain = TrustPolicyChain([
			TrustPolicy({'min_trust_score': 100, 'action_on_fail': 'log'}),
			TrustPolicy({'max_risk_score': 1, 'action_on_fail': 'degrade'}),
		])
		claims = TrustClaims(**_default_payload(trust_score=50, risk_score=20))
		result = chain.evaluate(claims)
		assert result.action == 'degrade'

	def test_failures_aggregated(self):
		chain = TrustPolicyChain([
			TrustPolicy({'min_trust_score': 100, 'action_on_fail': 'log'}),
			TrustPolicy({'max_risk_score': 1, 'action_on_fail': 'log'}),
		])
		claims = TrustClaims(**_default_payload(trust_score=50, risk_score=20))
		result = chain.evaluate(claims)
		assert len(result.failures) == 2

	def test_empty_chain_raises(self):
		chain = TrustPolicyChain()
		claims = TrustClaims(**_default_payload())
		with pytest.raises(AssertionError):
			chain.evaluate(claims)
