"""
Trust Provider integrations for Browser Use.

Provides trust verification for AI agents via the Agent-Trust-Score HTTP
header. Multiple providers cover different trust dimensions:

- **AgentID**: Identity resolution (is this agent who it claims to be?)
- **VeroQ Shield**: Output accuracy (is the agent's output actually correct?)

Usage:
	from browser_use.integrations.trust import (
		AgentIDTrustProvider,
		VeroQShieldTrustProvider,
		TrustPolicy,
		TrustPolicyChain,
	)

	# Identity check
	agentid = AgentIDTrustProvider(api_key="key_...")
	jwt = await agentid.get_trust_jwt("agent_abc123")

	# Output accuracy check
	shield = VeroQShieldTrustProvider(api_key="vq_...")
	jwt = await shield.get_trust_jwt(
		agent_id="agent_abc123",
		output_text="NVIDIA reported $22.1B in Q4 2024 revenue.",
	)

	# Evaluate against policy
	claims = await shield.verify_trust_jwt(jwt)
	policy = TrustPolicy({"min_trust_score": 50, "action_on_fail": "degrade"})
	result = policy.evaluate(claims)
"""

try:
	from .policy import PolicyResult, TrustPolicy, TrustPolicyChain
except ImportError as e:
	if 'pydantic' in str(e):
		raise ImportError('browser_use.integrations.trust requires pydantic. Install it with: pip install pydantic') from e
	raise

try:
	from .service import AgentIDTrustProvider, TrustClaims, TrustProvider
except ImportError as e:
	if 'httpx' in str(e):
		raise ImportError('browser_use.integrations.trust requires httpx. Install it with: pip install httpx') from e
	raise

from .veroq import ClaimVerdict, ShieldVerification, VeroQShieldTrustProvider

__all__ = [
	'AgentIDTrustProvider',
	'VeroQShieldTrustProvider',
	'TrustClaims',
	'TrustProvider',
	'TrustPolicy',
	'TrustPolicyChain',
	'PolicyResult',
	'ClaimVerdict',
	'ShieldVerification',
]
