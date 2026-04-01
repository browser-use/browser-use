"""
AgentID Trust Provider for Browser Use

Provides trust verification for AI agents using the AgentID protocol.
Agents present Agent-Trust-Score JWTs that site operators can evaluate
against configurable policies before granting access.

Usage:
	from browser_use.integrations.trust import AgentIDTrustProvider, TrustPolicy, TrustPolicyChain

	# Initialize provider
	provider = AgentIDTrustProvider()

	# Get a trust JWT for an agent
	jwt = await provider.get_trust_jwt("agent_abc123")

	# Verify and evaluate against policy
	claims = await provider.verify_trust_jwt(jwt)
	policy = TrustPolicy({"min_trust_score": 50})
	result = policy.evaluate(claims)
"""

try:
	from .policy import PolicyResult, TrustPolicy, TrustPolicyChain
except ImportError as e:
	if 'pydantic' in str(e):
		raise ImportError(
			'browser_use.integrations.trust requires pydantic. '
			'Install it with: pip install pydantic'
		) from e
	raise

try:
	from .service import AgentIDTrustProvider, TrustClaims, TrustProvider
except ImportError as e:
	if 'httpx' in str(e):
		raise ImportError(
			'browser_use.integrations.trust requires httpx. '
			'Install it with: pip install httpx'
		) from e
	raise

__all__ = [
	'AgentIDTrustProvider',
	'TrustClaims',
	'TrustProvider',
	'TrustPolicy',
	'TrustPolicyChain',
	'PolicyResult',
]
