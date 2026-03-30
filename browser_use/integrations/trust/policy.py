"""
Policy engine for evaluating trust claims against site operator thresholds.

Site operators define policies specifying minimum trust scores, maximum risk
thresholds, and required attestations. The engine evaluates incoming agent
trust claims against these policies and returns allow/block/degrade decisions.

Example:
	policy = TrustPolicy({
		"min_trust_score": 60,
		"max_risk_score": 30,
		"required_attestations": ["identity_verified"],
		"action_on_fail": "block",
	})
	result = policy.evaluate(claims)
	if result["action"] == "block":
		# deny the agent
"""

import logging
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .service import TrustClaims

logger = logging.getLogger(__name__)

ActionType = Literal['allow', 'block', 'degrade', 'log']


class PolicyResult(BaseModel):
	"""Result of evaluating trust claims against a policy."""

	model_config = ConfigDict(extra='forbid')

	passed: bool
	action: ActionType
	failures: list[str] = Field(default_factory=list)
	trust_level: str = ''
	provider: str = ''


class TrustPolicy:
	"""
	Evaluates TrustClaims against configurable thresholds.

	Supports four failure actions:
	- block: reject the agent entirely
	- degrade: allow with reduced capabilities
	- log: allow but log the policy violation
	- allow: (only returned on pass)
	"""

	VALID_ACTIONS: set[str] = {'allow', 'block', 'degrade', 'log'}

	def __init__(self, config: dict | None = None):
		config = config or {}
		self.min_trust_score: int = config.get('min_trust_score', 0)
		self.max_scarring_score: int = config.get('max_scarring_score', 999)
		self.max_risk_score: int = config.get('max_risk_score', 100)
		self.required_attestations: list[str] = config.get('required_attestations', [])
		action = config.get('action_on_fail', 'log')
		if action not in self.VALID_ACTIONS:
			raise ValueError(f'Invalid action_on_fail: {action!r}. Must be one of {self.VALID_ACTIONS}')
		self.action_on_fail: ActionType = action

		if not isinstance(self.min_trust_score, int):
			raise TypeError(f'min_trust_score must be int, got {type(self.min_trust_score).__name__}')
		if not isinstance(self.max_scarring_score, int):
			raise TypeError(f'max_scarring_score must be int, got {type(self.max_scarring_score).__name__}')
		if not isinstance(self.max_risk_score, int):
			raise TypeError(f'max_risk_score must be int, got {type(self.max_risk_score).__name__}')
		if not isinstance(self.required_attestations, list):
			raise TypeError(f'required_attestations must be list, got {type(self.required_attestations).__name__}')

	def evaluate(self, claims: TrustClaims) -> PolicyResult:
		"""
		Evaluate trust claims against this policy.

		Args:
			claims: Decoded TrustClaims from a verified JWT.

		Returns:
			PolicyResult indicating whether the agent passed and what action to take.
		"""
		failures: list[str] = []

		if claims.trust_score < self.min_trust_score:
			failures.append(f'trust_score {claims.trust_score} < min {self.min_trust_score}')

		if claims.scarring_score > self.max_scarring_score:
			failures.append(f'scarring_score {claims.scarring_score} > max {self.max_scarring_score}')

		if claims.risk_score > self.max_risk_score:
			failures.append(f'risk_score {claims.risk_score} > max {self.max_risk_score}')

		for req in self.required_attestations:
			if req not in claims.attestations:
				failures.append(f'missing attestation: {req}')

		passed = len(failures) == 0

		if not passed:
			logger.info(f'Policy check failed for agent {claims.agent_id}: {", ".join(failures)} -> action={self.action_on_fail}')

		return PolicyResult(
			passed=passed,
			action='allow' if passed else self.action_on_fail,
			failures=failures,
			trust_level=claims.trust_level,
			provider=claims.provider,
		)


class TrustPolicyChain:
	"""
	Evaluate claims against multiple policies in sequence.

	The most restrictive result wins — if any policy returns 'block',
	the overall result is 'block'. 'degrade' takes precedence over 'log'.
	"""

	ACTION_PRIORITY: dict[ActionType, int] = {
		'allow': 0,
		'log': 1,
		'degrade': 2,
		'block': 3,
	}

	def __init__(self, policies: list[TrustPolicy] | None = None):
		self.policies = policies or []

	def add(self, policy: TrustPolicy) -> None:
		self.policies.append(policy)

	def evaluate(self, claims: TrustClaims) -> PolicyResult:
		"""Evaluate all policies and return the most restrictive result."""
		if not self.policies:
			raise ValueError('Policy chain must have at least one policy')

		results = [p.evaluate(claims) for p in self.policies]

		# Merge: collect all failures, use most restrictive action
		all_failures: list[str] = []
		worst_action: ActionType = 'allow'

		for result in results:
			all_failures.extend(result.failures)
			if self.ACTION_PRIORITY.get(result.action, 0) > self.ACTION_PRIORITY.get(worst_action, 0):
				worst_action = result.action

		passed = worst_action == 'allow'

		return PolicyResult(
			passed=passed,
			action=worst_action,
			failures=all_failures,
			trust_level=claims.trust_level,
			provider=claims.provider,
		)
