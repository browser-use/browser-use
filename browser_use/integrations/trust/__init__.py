"""
AgentID Trust Provider for Browser Use

Provides trust verification for AI agents using the AgentID protocol.
Agents present Agent-Trust-Score JWTs that site operators can evaluate
against configurable policies before granting access.

Usage:
	from agentid_trust_provider import AgentIDTrustProvider, TrustPolicy

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
	from .agentid_trust_provider import AgentIDTrustProvider, TrustClaims, TrustProvider
	from .policy_engine import TrustPolicy
except ImportError:
	from agentid_trust_provider import AgentIDTrustProvider, TrustClaims, TrustProvider
	from policy_engine import TrustPolicy

__all__ = ['AgentIDTrustProvider', 'TrustClaims', 'TrustPolicy', 'TrustProvider']
