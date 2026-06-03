from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from browser_use.utils import match_url_with_domain_pattern

ActionRisk = Literal['read', 'navigation', 'interactive', 'transactional']

READ_ACTIONS = {
	'done',
	'extract',
	'find_elements',
	'get_dropdown_options',
	'go_back',
	'screenshot',
	'search_page',
	'scroll',
	'switch_tab',
	'wait',
}
NAVIGATION_ACTIONS = {'navigate', 'search'}
INTERACTIVE_ACTIONS = {'click', 'input', 'select_dropdown_option', 'send_keys'}
TRANSACTIONAL_ACTIONS = {'save_pdf', 'upload_file'}


class ActionPolicyDecision(BaseModel):
	"""Result of evaluating one browser action against an action policy."""

	allowed: bool
	action_name: str
	risk: ActionRisk
	reason: str
	current_url: str | None = None
	target_url: str | None = None
	matched_rule: str | None = None


class ActionPolicyViolation(RuntimeError):
	"""Raised when an action policy blocks an action before execution."""

	def __init__(self, decision: ActionPolicyDecision):
		self.decision = decision
		super().__init__(decision.reason)


class ActionPolicy(BaseModel):
	"""Pre-execution guardrails for browser actions.

	The policy is evaluated centrally in the action registry, so it applies to
	default browser actions, MCP-backed tools, and custom registered actions.
	"""

	read_only: bool = False
	allowed_actions: set[str] | None = None
	blocked_actions: set[str] = Field(default_factory=set)
	allowed_domains: list[str] | None = None
	blocked_domains: list[str] = Field(default_factory=list)
	block_interactive: bool = False
	block_transactional: bool = True
	custom_action_risks: dict[str, ActionRisk] = Field(default_factory=dict)

	def evaluate(
		self, action_name: str, params: BaseModel | dict[str, Any], current_url: str | None = None
	) -> ActionPolicyDecision:
		"""Evaluate whether an action should run."""

		params_dict = params.model_dump(mode='json') if isinstance(params, BaseModel) else params
		target_url = _target_url_for_action(action_name, params_dict)
		risk = self.custom_action_risks.get(action_name, _default_action_risk(action_name))

		decision = self._evaluate_action_name(action_name, risk, current_url, target_url)
		if decision is not None:
			return decision

		url_decision = self._evaluate_urls(action_name, risk, current_url, target_url)
		if url_decision is not None:
			return url_decision

		return ActionPolicyDecision(
			allowed=True,
			action_name=action_name,
			risk=risk,
			reason='Action allowed by policy.',
			current_url=current_url,
			target_url=target_url,
		)

	def assert_allowed(
		self, action_name: str, params: BaseModel | dict[str, Any], current_url: str | None = None
	) -> ActionPolicyDecision:
		"""Evaluate an action and raise if it is blocked."""

		decision = self.evaluate(action_name, params, current_url=current_url)
		if not decision.allowed:
			raise ActionPolicyViolation(decision)
		return decision

	def assert_current_url_available(self, action_name: str, params: BaseModel | dict[str, Any]) -> None:
		"""Fail closed when a domain-scoped policy cannot inspect the current page URL."""

		if not self.requires_current_url(action_name, params):
			return
		params_dict = params.model_dump(mode='json') if isinstance(params, BaseModel) else params
		raise ActionPolicyViolation(
			ActionPolicyDecision(
				allowed=False,
				action_name=action_name,
				risk=self.custom_action_risks.get(action_name, _default_action_risk(action_name)),
				reason='Current page URL is unavailable; domain-scoped action policy cannot be evaluated safely.',
				target_url=_target_url_for_action(action_name, params_dict),
				matched_rule='current_url_unavailable',
			)
		)

	def requires_current_url(self, action_name: str, params: BaseModel | dict[str, Any]) -> bool:
		"""Return whether this policy must inspect the current URL for this action."""

		if self.allowed_domains is None and not self.blocked_domains:
			return False
		params_dict = params.model_dump(mode='json') if isinstance(params, BaseModel) else params
		return _target_url_for_action(action_name, params_dict) is None

	def _evaluate_action_name(
		self, action_name: str, risk: ActionRisk, current_url: str | None, target_url: str | None
	) -> ActionPolicyDecision | None:
		if self.allowed_actions is not None and action_name not in self.allowed_actions:
			return _blocked(action_name, risk, 'Action is not in allowed_actions.', 'allowed_actions', current_url, target_url)
		if action_name in self.blocked_actions:
			return _blocked(action_name, risk, 'Action is listed in blocked_actions.', 'blocked_actions', current_url, target_url)
		if self.read_only and risk != 'read':
			return _blocked(action_name, risk, f'Read-only policy blocks {risk} actions.', 'read_only', current_url, target_url)
		if self.block_interactive and risk in {'interactive', 'transactional'}:
			return _blocked(action_name, risk, f'Policy blocks {risk} actions.', 'block_interactive', current_url, target_url)
		if self.block_transactional and risk == 'transactional':
			return _blocked(
				action_name, risk, 'Policy blocks transactional actions.', 'block_transactional', current_url, target_url
			)
		return None

	def _evaluate_urls(
		self, action_name: str, risk: ActionRisk, current_url: str | None, target_url: str | None
	) -> ActionPolicyDecision | None:
		for url, label in ((target_url, 'target_url'), (current_url, 'current_url')):
			if not url:
				continue
			if _matches_any(url, self.blocked_domains):
				return _blocked(
					action_name, risk, f'Policy blocks {label} domain: {url}', 'blocked_domains', current_url, target_url
				)
			if self.allowed_domains is not None and not _matches_any(url, self.allowed_domains):
				return _blocked(
					action_name,
					risk,
					f'Policy does not allow {label} domain: {url}',
					'allowed_domains',
					current_url,
					target_url,
				)
		return None


def _blocked(
	action_name: str,
	risk: ActionRisk,
	reason: str,
	matched_rule: str,
	current_url: str | None,
	target_url: str | None,
) -> ActionPolicyDecision:
	return ActionPolicyDecision(
		allowed=False,
		action_name=action_name,
		risk=risk,
		reason=reason,
		current_url=current_url,
		target_url=target_url,
		matched_rule=matched_rule,
	)


def _default_action_risk(action_name: str) -> ActionRisk:
	if action_name in READ_ACTIONS:
		return 'read'
	if action_name in NAVIGATION_ACTIONS:
		return 'navigation'
	if action_name in TRANSACTIONAL_ACTIONS:
		return 'transactional'
	if action_name in INTERACTIVE_ACTIONS:
		return 'interactive'
	return 'interactive'


def _target_url_for_action(action_name: str, params: dict[str, Any]) -> str | None:
	if action_name == 'navigate':
		url = params.get('url')
		return str(url) if url else None
	if action_name == 'search':
		engine = str(params.get('engine') or 'google').lower()
		search_domains = {
			'duckduckgo': 'https://duckduckgo.com',
			'google': 'https://www.google.com',
			'bing': 'https://www.bing.com',
		}
		return search_domains.get(engine)
	return None


def _matches_any(url: str, patterns: list[str]) -> bool:
	return any(match_url_with_domain_pattern(url, pattern) for pattern in patterns)
