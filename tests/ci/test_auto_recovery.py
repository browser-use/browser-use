"""Recovery framework tests.

Covers the RecoveryEngine dispatch (phase/cost ordering, capability filtering,
attempt budgeting), the concrete strategies, composite chains, and the
RecoveryStage retry loop integration.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from browser_use.agent.recovery import (
	ActionKind,
	BrowserCrashRecovery,
	CompositeRecovery,
	NavigationRecovery,
	OverlayRecovery,
	RecoveryContext,
	RecoveryEngine,
	RecoveryOutcome,
	RecoveryResult,
	RecoveryStrategy,
	RecoveryStage,
	RecoveryStats,
	RelocateRecovery,
	RetryRecovery,
	ScrollRecovery,
	TimeoutRecovery,
	WaitRecovery,
	default_strategies,
)
from browser_use.agent.views import ActionResult
from browser_use.browser.views import BrowserStateSummary
from browser_use.dom.views import SerializedDOMState
from browser_use.tools.registry.views import ActionModel


class _StubAction(ActionModel):
	"""ActionModel with a single fixed slot for recovery tests."""

	click: dict[str, Any] | None = None


def _make_state(url: str = 'https://example.com', pending: tuple = ()) -> BrowserStateSummary:
	return BrowserStateSummary(
		dom_state=SerializedDOMState(_root=None, selector_map={}),
		url=url,
		title='Example',
		tabs=[],
		pending_network_requests=list(pending),
	)


def _make_agent(**overrides: Any) -> MagicMock:
	agent = MagicMock()
	agent.logger = logging.getLogger('test_recovery')
	agent.settings.auto_recovery_max_attempts = 3
	agent.settings.auto_recovery_wait_seconds = 1.5
	agent.settings.page_extraction_llm = None
	agent.sensitive_data = None
	agent.available_file_paths = None
	agent.extraction_schema = None
	agent.file_system = None
	agent.browser_session = None
	for key, value in overrides.items():
		setattr(agent, key, value)
	return agent


def _make_context(
	agent: Any,
	error: str = 'boom',
	action: ActionModel | None = None,
	state: BrowserStateSummary | None = None,
	action_kind: ActionKind = ActionKind.CLICK,
) -> RecoveryContext:
	ctx = RecoveryContext(
		agent=agent,
		action=action or _StubAction(click={'index': 5}),
		action_name='click',
		failed_result=ActionResult(error=error),
		browser_state=state,
	)
	ctx.action_kind = action_kind
	return ctx


# ── Engine ────────────────────────────────────────────────────────────────
class _DummyStrategy(RecoveryStrategy):
	name = 'dummy'
	max_attempts = 2

	def __init__(self, name: str, phase, cost, outcome=RecoveryOutcome.RETRY) -> None:
		self.name = name
		self.phase = phase
		self.cost = cost
		self.outcome = outcome

	def can_handle(self, ctx: RecoveryContext) -> bool:
		return True

	async def recover(self, ctx: RecoveryContext) -> RecoveryResult:
		return RecoveryResult(outcome=self.outcome, chain=[], retry_action=None, reason='ok')


@pytest.mark.asyncio
async def test_engine_orders_by_phase_then_cost():
	"""Cheapest/least-disruptive strategies must be dispatched first."""
	from browser_use.agent.recovery.base import RecoveryCost, RecoveryPhase

	late = _DummyStrategy('retry_phase', RecoveryPhase.RETRY, RecoveryCost.LOW)
	early_env = _DummyStrategy('env_high', RecoveryPhase.ENVIRONMENT, RecoveryCost.HIGH)
	early_elem = _DummyStrategy('elem_low', RecoveryPhase.ELEMENT, RecoveryCost.LOW)
	engine = RecoveryEngine([late, early_env, early_elem])
	agent = _make_agent()
	ctx = _make_context(agent)

	assert [s.name for s in engine._candidates(ctx)] == ['env_high', 'elem_low', 'retry_phase']


@pytest.mark.asyncio
async def test_engine_filters_by_capability():
	"""Strategies declaring supports must not run for other action kinds."""
	from browser_use.agent.recovery.base import RecoveryCost, RecoveryPhase

	click_only = _DummyStrategy('click_only', RecoveryPhase.ELEMENT, RecoveryCost.LOW)
	click_only.supports = {ActionKind.CLICK}
	engine = RecoveryEngine([click_only])

	type_ctx = _make_context(_make_agent(), action_kind=ActionKind.TYPE)
	result = await engine.evaluate(type_ctx)
	assert result.outcome == RecoveryOutcome.GIVE_UP

	click_ctx = _make_context(_make_agent(), action_kind=ActionKind.CLICK)
	result = await engine.evaluate(click_ctx)
	assert result.outcome == RecoveryOutcome.RETRY


@pytest.mark.asyncio
async def test_engine_respects_per_strategy_attempt_budget():
	"""A strategy past its max_attempts must be skipped for the next round."""
	from browser_use.agent.recovery.base import RecoveryCost, RecoveryPhase

	strategy = _DummyStrategy('limited', RecoveryPhase.ACTION, RecoveryCost.LOW)
	strategy.max_attempts = 2
	engine = RecoveryEngine([strategy])
	agent = _make_agent()
	ctx = _make_context(agent)

	await engine.evaluate(ctx)
	await engine.evaluate(ctx)
	# Budget exhausted → next round gives up.
	result = await engine.evaluate(ctx)
	assert result.outcome == RecoveryOutcome.GIVE_UP
	assert ctx.attempts['limited'] == 2


@pytest.mark.asyncio
async def test_engine_gives_up_when_no_strategy_matches():
	"""No applicable strategy must yield GIVE_UP, preserving the original error."""
	engine = RecoveryEngine([])
	result = await engine.evaluate(_make_context(_make_agent()))
	assert result.outcome == RecoveryOutcome.GIVE_UP
	assert result.reason is not None


# ── Strategies ────────────────────────────────────────────────────────────
def test_wait_recovery_matches_loading():
	strategy = WaitRecovery()
	agent = _make_agent()
	assert strategy.can_handle(_make_context(agent, error='page is still loading'))
	assert strategy.can_handle(_make_context(agent, error='done', state=_make_state(pending=('req',))))
	assert not strategy.can_handle(_make_context(agent, error='boom'))


@pytest.mark.asyncio
@patch('browser_use.agent.recovery.strategies.asyncio.sleep', new_callable=AsyncMock)
async def test_wait_recovery_recover_returns_retry(mock_sleep):
	strategy = WaitRecovery()
	ctx = _make_context(_make_agent(), error='still loading')
	result = await strategy.recover(ctx)
	assert result.outcome == RecoveryOutcome.RETRY
	mock_sleep.assert_awaited_once()


def test_retry_recovery_is_fallback():
	strategy = RetryRecovery()
	assert strategy.can_handle(_make_context(_make_agent(), error='anything at all'))


@pytest.mark.asyncio
@patch('browser_use.agent.recovery.strategies.asyncio.sleep', new_callable=AsyncMock)
async def test_retry_recovery_backoff(mock_sleep):
	strategy = RetryRecovery()
	agent = _make_agent()
	ctx = _make_context(agent, error='boom')
	ctx.attempts['retry'] = 1
	result = await strategy.recover(ctx)
	assert result.outcome == RecoveryOutcome.RETRY
	# 2s * 2^(attempt-1) with attempt=1 → 2s
	mock_sleep.assert_awaited_once_with(2.0)


def test_timeout_recovery_matches_timeout():
	strategy = TimeoutRecovery()
	assert strategy.can_handle(_make_context(_make_agent(), error='operation timed out'))
	assert not strategy.can_handle(_make_context(_make_agent(), error='boom'))


@pytest.mark.asyncio
async def test_overlay_recovery_dismisses_overlay():
	strategy = OverlayRecovery()
	agent = _make_agent()
	agent.tools.registry.execute_action = AsyncMock(return_value=ActionResult(extracted_content='sent'))
	ctx = _make_context(agent, error='element click intercepted')
	result = await strategy.recover(ctx)
	assert result.outcome == RecoveryOutcome.RETRY
	agent.tools.registry.execute_action.assert_awaited_once()
	args = agent.tools.registry.execute_action.await_args
	assert args is not None
	assert args.kwargs['action_name'] == 'send_keys'
	assert args.kwargs['params'] == {'keys': 'Escape'}


@pytest.mark.asyncio
async def test_scroll_recovery_scrolls_toward_element():
	strategy = ScrollRecovery()
	agent = _make_agent()
	agent.tools.registry.execute_action = AsyncMock(return_value=ActionResult(extracted_content='scrolled'))
	state = _make_state()
	state.pixels_below = 500
	ctx = _make_context(agent, error='element not visible', state=state)
	result = await strategy.recover(ctx)
	assert result.outcome == RecoveryOutcome.RETRY
	args = agent.tools.registry.execute_action.await_args
	assert args is not None
	assert args.kwargs['action_name'] == 'scroll'
	assert args.kwargs['params']['down'] is True


@pytest.mark.asyncio
async def test_navigation_recovery_goes_back_on_404():
	strategy = NavigationRecovery()
	agent = _make_agent()
	agent.tools.registry.execute_action = AsyncMock(return_value=ActionResult(extracted_content='back'))
	ctx = _make_context(agent, error='404 page not found')
	result = await strategy.recover(ctx)
	assert result.outcome == RecoveryOutcome.RETRY
	agent.tools.registry.execute_action.assert_awaited_once_with(
		action_name='go_back', params={}, browser_session=None, page_extraction_llm=None,
		file_system=None, sensitive_data=None, available_file_paths=None, extraction_schema=None,
	)


@pytest.mark.asyncio
async def test_browser_crash_recovery_reconnects():
	strategy = BrowserCrashRecovery()
	session = MagicMock()
	session.cdp_url = 'ws://localhost:9222'
	session.is_cdp_connected = False
	session.reconnect = AsyncMock()
	agent = _make_agent()
	agent.browser_session = session
	ctx = _make_context(agent, error='websocket connection closed')
	result = await strategy.recover(ctx)
	assert result.outcome == RecoveryOutcome.RETRY
	session.reconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_browser_crash_recovery_escalates_without_cdp():
	strategy = BrowserCrashRecovery()
	agent = _make_agent()
	agent.browser_session = None
	ctx = _make_context(agent, error='browser has been closed')
	result = await strategy.recover(ctx)
	assert result.outcome == RecoveryOutcome.ESCALATE


@pytest.mark.asyncio
async def test_relocate_recovery_returns_updated_action():
	from browser_use.dom.views import DOMInteractedElement

	strategy = RelocateRecovery()
	agent = _make_agent()
	history_item = MagicMock()
	history_item.state.interacted_element = [MagicMock(spec=DOMInteractedElement)]
	agent.history.history = [history_item]
	executor = MagicMock()
	executor._update_action_indices = AsyncMock(return_value=_StubAction(click={'index': 12}))
	agent._pipeline.action_executor = executor
	state = _make_state()
	state.dom_state.selector_map = {12: MagicMock()}
	ctx = _make_context(agent, error='element index 5 not found', state=state)
	result = await strategy.recover(ctx)
	assert result.outcome == RecoveryOutcome.RETRY
	assert result.retry_action is not None
	executor._update_action_indices.assert_awaited_once()


@pytest.mark.asyncio
async def test_relocate_recovery_gives_up_when_element_gone():
	from browser_use.dom.views import DOMInteractedElement

	strategy = RelocateRecovery()
	agent = _make_agent()
	history_item = MagicMock()
	history_item.state.interacted_element = [MagicMock(spec=DOMInteractedElement)]
	agent.history.history = [history_item]
	executor = MagicMock()
	executor._update_action_indices = AsyncMock(return_value=None)
	agent._pipeline.action_executor = executor
	state = _make_state()
	state.dom_state.selector_map = {12: MagicMock()}
	ctx = _make_context(agent, error='element not found', state=state)
	result = await strategy.recover(ctx)
	assert result.outcome == RecoveryOutcome.GIVE_UP


# ── Composite ─────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_composite_chain_falls_through_strategies():
	"""Composite must try sub-strategies in order and expose the chain."""
	scroll = ScrollRecovery()
	relocate = RelocateRecovery()
	chain = CompositeRecovery([scroll, relocate], name='element_chain')
	agent = _make_agent()
	agent.tools.registry.execute_action = AsyncMock(return_value=ActionResult(extracted_content='scrolled'))
	# Relocate cannot handle non-element errors, so only scroll should fire.
	ctx = _make_context(agent, error='element not visible', state=_make_state())
	assert chain.can_handle(ctx)
	result = await chain.recover(ctx)
	assert result.outcome == RecoveryOutcome.RETRY
	assert result.chain == ['scroll']
	assert result.strategy == 'element_chain'


@pytest.mark.asyncio
async def test_composite_respects_sub_strategy_attempt_budget():
	from browser_use.agent.recovery.base import RecoveryCost, RecoveryPhase

	first = _DummyStrategy('first', RecoveryPhase.ELEMENT, RecoveryCost.LOW)
	second = _DummyStrategy('second', RecoveryPhase.ELEMENT, RecoveryCost.MEDIUM)
	chain = CompositeRecovery([first, second], name='chain')
	agent = _make_agent()
	ctx = _make_context(agent)

	for _ in range(first.max_attempts):
		result = await chain.recover(ctx)
		assert result.strategy == 'chain'
		assert result.chain == ['first']
	# First exhausted → second takes over.
	result = await chain.recover(ctx)
	assert result.chain == ['second']


# ── Stage integration ─────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_stage_recovers_and_returns_successful_result():
	"""Stage must re-run the action after recovery and return the good result."""
	agent = _make_agent()
	agent.tools.act = AsyncMock(
		side_effect=[
			ActionResult(error='element not visible'),
			ActionResult(extracted_content='clicked!'),
		]
	)
	async def fake_recover(_ctx: RecoveryContext) -> Any:
		return MagicMock(
			outcome=RecoveryOutcome.RETRY,
			chain=['scroll'],
			retry_action=None,
			reason='scrolled',
		)

	engine = RecoveryEngine([ScrollRecovery()])
	engine.strategies[0].recover = fake_recover  # type: ignore[method-assign]
	stage = RecoveryStage(engine=engine, max_rounds=3)
	attempt = await stage.recover(
		agent=agent,
		action=_StubAction(click={'index': 5}),
		action_name='click',
		failed_result=ActionResult(error='element not visible'),
		browser_state=_make_state(),
	)
	assert attempt.recovered is True
	assert attempt.result.extracted_content == 'clicked!'
	assert agent.tools.act.await_count == 2

@pytest.mark.asyncio
async def test_stage_gives_up_and_preserves_original_error():
	"""Exhausted recovery must hand the original error back to the LLM."""
	agent = _make_agent()
	agent.tools.act = AsyncMock(return_value=ActionResult(error='still failing'))
	stage = RecoveryStage(engine=RecoveryEngine([]), max_rounds=2)
	attempt = await stage.recover(
		agent=agent,
		action=_StubAction(click={'index': 5}),
		action_name='click',
		failed_result=ActionResult(error='original failure'),
		browser_state=_make_state(),
	)
	assert attempt.recovered is False
	assert attempt.outcome == RecoveryOutcome.GIVE_UP
	assert attempt.result.error == 'original failure'


@pytest.mark.asyncio
async def test_stage_budget_limits_retry_rounds():
	"""The stage must not retry more than max_rounds times."""
	agent = _make_agent()
	agent.tools.act = AsyncMock(return_value=ActionResult(error='never succeeds'))
	stage = RecoveryStage(engine=RecoveryEngine([]), max_rounds=1)
	attempt = await stage.recover(
		agent=agent,
		action=_StubAction(click={'index': 5}),
		action_name='click',
		failed_result=ActionResult(error='boom'),
		browser_state=_make_state(),
	)
	assert attempt.recovered is False
	agent.tools.act.assert_not_awaited()


# ── Stats ─────────────────────────────────────────────────────────────────
def test_stats_track_metrics():
	stats = RecoveryStats()
	stats.record_attempt('scroll')
	stats.record_attempt('scroll')
	stats.record_attempt('relocate')
	stats.record_success('scroll', chain_length=2)
	stats.record_give_up()

	assert stats.total_attempts == 3
	assert stats.recovered == 1
	assert stats.gave_up == 1
	assert stats.success_rate == pytest.approx(1 / 3)
	assert stats.avg_chain_length == 2.0
	assert stats.distribution() == {'scroll': 2, 'relocate': 1}
	assert 'success_rate=33%' in stats.summary()


# ── Defaults ──────────────────────────────────────────────────────────────
def test_default_strategies_registered_in_order():
	from browser_use.agent.recovery.base import RecoveryPhase

	names = [s.name for s in default_strategies()]
	assert names == [
		'browser_crash',
		'navigation',
		'overlay',
		'scroll',
		'relocate',
		'wait',
		'timeout',
		'retry',
	]
	# Environment-level repairs must come before element-level ones.
	phases = [s.phase for s in default_strategies()]
	assert phases == sorted(phases, key=lambda p: list(RecoveryPhase).index(p))
