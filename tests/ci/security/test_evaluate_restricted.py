"""Tests for the evaluate() guard on restricted browser profiles.

The agent's `evaluate()` action calls `Runtime.evaluate` directly through CDP.
SecurityWatchdog only subscribes to navigation events, so JS running inside an
already-allowed page can `fetch()` arbitrary internal URLs, read cookies and
localStorage from any allowed origin's context, and otherwise act as if the
restrictions weren't there.

On profiles configured with `allowed_domains` or `block_ip_addresses`, the
operator has signalled "this agent is constrained" — exposing an unmediated
JS evaluation primitive contradicts that signal. The guard refuses
`evaluate()` outright on such profiles; agents that need JS can be run on an
unrestricted profile or the gate can be lifted explicitly later.
"""

from __future__ import annotations

from typing import Any

import pytest

from browser_use.agent.views import ActionResult
from browser_use.tools.service import Tools


class _StubProfile:
	def __init__(
		self,
		allowed_domains: Any = None,
		prohibited_domains: Any = None,
		block_ip_addresses: bool = False,
	) -> None:
		self.allowed_domains = allowed_domains
		self.prohibited_domains = prohibited_domains
		self.block_ip_addresses = block_ip_addresses


class _StubBrowserSession:
	is_local = True
	agent_focus_target_id: str | None = None
	session_manager: Any = None
	cdp_client: Any = None

	def __init__(self, profile: _StubProfile) -> None:
		self.browser_profile = profile

	async def get_current_page_url(self) -> str:
		return 'about:blank'

	async def get_or_create_cdp_session(self) -> Any:
		raise AssertionError('evaluate() must refuse before reaching CDP when restrictions are configured')


async def _run_evaluate(profile: _StubProfile, code: str = '1 + 1') -> ActionResult:
	tools = Tools()
	result = await tools.registry.execute_action(
		'evaluate',
		{'code': code},
		browser_session=_StubBrowserSession(profile),  # type: ignore[arg-type]
	)
	assert isinstance(result, ActionResult)
	return result


async def test_evaluate_refused_when_allowed_domains_set() -> None:
	"""A non-empty `allowed_domains` list signals a restricted profile — refuse."""
	result = await _run_evaluate(_StubProfile(allowed_domains=['example.com']))
	assert result.error is not None
	assert 'allowed_domains' in result.error.lower() or 'restricted' in result.error.lower()


async def test_evaluate_refused_when_block_ip_addresses_set() -> None:
	"""`block_ip_addresses=True` signals a restricted profile — refuse."""
	result = await _run_evaluate(_StubProfile(block_ip_addresses=True))
	assert result.error is not None
	assert 'block_ip_addresses' in result.error.lower() or 'restricted' in result.error.lower()


async def test_evaluate_refused_when_prohibited_domains_set() -> None:
	"""`prohibited_domains` is the deny-list counterpart of `allowed_domains`;
	SecurityWatchdog enforces both as navigation restrictions. Refuse evaluate()
	when either is set — otherwise an agent can fetch() into the blocked domains."""
	result = await _run_evaluate(_StubProfile(prohibited_domains=['evil.test']))
	assert result.error is not None
	assert 'prohibited_domains' in result.error.lower() or 'restricted' in result.error.lower()


async def test_evaluate_refused_when_both_restrictions_set() -> None:
	"""Belt and suspenders configuration — refuse."""
	result = await _run_evaluate(_StubProfile(allowed_domains=['x.test'], block_ip_addresses=True))
	assert result.error is not None


async def test_evaluate_reaches_cdp_when_unrestricted() -> None:
	"""No restrictions → evaluate() should proceed to CDP. Our stub raises
	when `get_or_create_cdp_session` is called, so we observe via the wrapped
	error that the guard did not short-circuit."""
	tools = Tools()
	with pytest.raises(RuntimeError, match='must refuse before reaching CDP'):
		await tools.registry.execute_action(
			'evaluate',
			{'code': '1 + 1'},
			browser_session=_StubBrowserSession(_StubProfile()),  # type: ignore[arg-type]
		)


async def test_evaluate_proceeds_when_allowed_domains_is_empty_list() -> None:
	"""Empty allowed_domains is treated as 'no restriction' elsewhere in the
	codebase (e.g. SecurityWatchdog). Be consistent: don't refuse evaluate()."""
	tools = Tools()
	with pytest.raises(RuntimeError, match='must refuse before reaching CDP'):
		await tools.registry.execute_action(
			'evaluate',
			{'code': '1 + 1'},
			browser_session=_StubBrowserSession(_StubProfile(allowed_domains=[])),  # type: ignore[arg-type]
		)
