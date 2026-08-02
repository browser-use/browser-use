"""Concrete recovery strategies + composite chain.

Each strategy is deterministic — no LLM calls. Strategies repair a failure
before it is escalated back to the planner LLM, cutting unnecessary LLM
round-trips on recoverable errors.
"""

from __future__ import annotations

import asyncio
import logging

from browser_use.agent.recovery.base import (
	ActionKind,
	RecoveryContext,
	RecoveryCost,
	RecoveryOutcome,
	RecoveryPhase,
	RecoveryResult,
	RecoveryStrategy,
)

logger = logging.getLogger(__name__)


# ── Environment ──────────────────────────────────────────────────────────
class BrowserCrashRecovery(RecoveryStrategy):
	"""Repair a dead CDP/browser connection by reconnecting the session."""

	name = 'browser_crash'
	phase = RecoveryPhase.ENVIRONMENT
	cost = RecoveryCost.HIGH
	destructive = True
	max_attempts = 1

	def can_handle(self, ctx: RecoveryContext) -> bool:
		session = ctx.browser_session
		if session is not None and session.cdp_url and not session.is_cdp_connected:
			return True
		return any(
			token in ctx.error
			for token in (
				'websocket connection closed',
				'connection closed',
				'browser has been closed',
				'browser closed',
				'disconnected',
				'no browser',
			)
		)

	async def recover(self, ctx: RecoveryContext) -> RecoveryResult:
		session = ctx.browser_session
		if session is None or not session.cdp_url:
			return RecoveryResult(
				outcome=RecoveryOutcome.ESCALATE,
				strategy=self.name,
				reason='browser unavailable and no CDP URL to reconnect',
			)
		try:
			logger.info('🔄 Auto-recovery: reconnecting browser session')
			await session.reconnect()
			return RecoveryResult(
				outcome=RecoveryOutcome.RETRY,
				strategy=self.name,
				reason='reconnected browser session',
			)
		except Exception as e:
			return RecoveryResult(
				outcome=RecoveryOutcome.ESCALATE,
				strategy=self.name,
				reason=f'reconnect failed: {type(e).__name__}: {e}',
			)


# ── Page ─────────────────────────────────────────────────────────────────
class NavigationRecovery(RecoveryStrategy):
	"""Repair page-level failures (404, redirect) by going back and retrying."""

	name = 'navigation'
	phase = RecoveryPhase.PAGE
	cost = RecoveryCost.MEDIUM
	max_attempts = 1
	supports = {ActionKind.NAVIGATE, ActionKind.CLICK, ActionKind.TYPE}

	def can_handle(self, ctx: RecoveryContext) -> bool:
		return any(
			token in ctx.error
			for token in ('404', 'page not found', 'redirect', 'navigation failed', 'no page found')
		)

	async def recover(self, ctx: RecoveryContext) -> RecoveryResult:
		try:
			await self.run_registered_action(ctx, 'go_back')
			return RecoveryResult(
				outcome=RecoveryOutcome.RETRY,
				strategy=self.name,
				reason='navigated back after page-level failure',
			)
		except Exception as e:
			return RecoveryResult(
				outcome=RecoveryOutcome.GIVE_UP,
				strategy=self.name,
				reason=f'go_back failed: {type(e).__name__}: {e}',
			)


# ── Element ──────────────────────────────────────────────────────────────
class OverlayRecovery(RecoveryStrategy):
	"""Dismiss an overlay (cookie banner, modal, GDPR popup) blocking the element."""

	name = 'overlay'
	phase = RecoveryPhase.ELEMENT
	cost = RecoveryCost.LOW
	max_attempts = 1
	supports = {ActionKind.CLICK, ActionKind.TYPE}

	def can_handle(self, ctx: RecoveryContext) -> bool:
		return any(
			token in ctx.error
			for token in (
				'intercepted',
				'covered',
				'obstructed',
				'overlapped',
				'element is obscured',
				'not clickable',
				'not visible',
			)
		)

	async def recover(self, ctx: RecoveryContext) -> RecoveryResult:
		try:
			await self.run_registered_action(ctx, 'send_keys', {'keys': 'Escape'})
			return RecoveryResult(
				outcome=RecoveryOutcome.RETRY,
				strategy=self.name,
				reason='dismissed overlay with Escape key',
			)
		except Exception as e:
			return RecoveryResult(
				outcome=RecoveryOutcome.GIVE_UP,
				strategy=self.name,
				reason=f'overlay dismissal failed: {type(e).__name__}: {e}',
			)


class ScrollRecovery(RecoveryStrategy):
	"""Scroll the element into the viewport before retrying."""

	name = 'scroll'
	phase = RecoveryPhase.ELEMENT
	cost = RecoveryCost.LOW
	max_attempts = 2
	supports = {ActionKind.CLICK, ActionKind.TYPE}

	def can_handle(self, ctx: RecoveryContext) -> bool:
		return any(
			token in ctx.error
			for token in ('not visible', 'outside viewport', 'not in viewport', 'offscreen', 'scrolled out', 'below the fold')
		)

	async def recover(self, ctx: RecoveryContext) -> RecoveryResult:
		state = ctx.browser_state
		scroll_down = True
		if state is not None:
			# pixels_above: content above the viewport → scroll up.
			# pixels_below: content below the viewport → scroll down.
			if state.pixels_above > 0 and state.pixels_below == 0:
				scroll_down = False
		try:
			await self.run_registered_action(
				ctx, 'scroll', {'down': scroll_down, 'pages': 1.0}
			)
			return RecoveryResult(
				outcome=RecoveryOutcome.RETRY,
				strategy=self.name,
				reason=f'scrolled {"down" if scroll_down else "up"} to reveal element',
			)
		except Exception as e:
			return RecoveryResult(
				outcome=RecoveryOutcome.GIVE_UP,
				strategy=self.name,
				reason=f'scroll failed: {type(e).__name__}: {e}',
			)


class RelocateRecovery(RecoveryStrategy):
	"""Relocate a detached/stale element using cascading selector matching."""

	name = 'relocate'
	phase = RecoveryPhase.ELEMENT
	cost = RecoveryCost.MEDIUM
	max_attempts = 2
	supports = {ActionKind.CLICK, ActionKind.TYPE, ActionKind.SCROLL, ActionKind.EXTRACT, ActionKind.OTHER}

	def can_handle(self, ctx: RecoveryContext) -> bool:
		return any(
			token in ctx.error
			for token in (
				'not found',
				'not available',
				'detached',
				'stale',
				'no element',
				'element index',
				'page may have changed',
			)
		)

	async def recover(self, ctx: RecoveryContext) -> RecoveryResult:
		history = ctx.agent.history
		if history is None or not history.history:
			return RecoveryResult(
				outcome=RecoveryOutcome.GIVE_UP,
				strategy=self.name,
				reason='no history to relocate from',
			)
		history_item = history.history[-1]
		interacted = history_item.state.interacted_element or []
		historical_element = next((el for el in reversed(interacted) if el is not None), None)
		if historical_element is None:
			return RecoveryResult(
				outcome=RecoveryOutcome.GIVE_UP,
				strategy=self.name,
				reason='no interacted element recorded for relocation',
			)

		state = ctx.browser_state
		if state is None or not state.dom_state or not state.dom_state.selector_map:
			return RecoveryResult(
				outcome=RecoveryOutcome.GIVE_UP,
				strategy=self.name,
				reason='no fresh browser state to relocate against',
			)

		executor = ctx.agent._pipeline.action_executor
		try:
			updated = await executor._update_action_indices(historical_element, ctx.action, state)
		except Exception as e:
			return RecoveryResult(
				outcome=RecoveryOutcome.GIVE_UP,
				strategy=self.name,
				reason=f'relocation failed: {type(e).__name__}: {e}',
			)
		if updated is None:
			return RecoveryResult(
				outcome=RecoveryOutcome.GIVE_UP,
				strategy=self.name,
				reason='element could not be relocated in current DOM',
			)
		return RecoveryResult(
			outcome=RecoveryOutcome.RETRY,
			strategy=self.name,
			retry_action=updated,
			reason=f'relocated element (index {ctx.action.get_index()} → {updated.get_index()})',
		)


# ── Action ───────────────────────────────────────────────────────────────
class WaitRecovery(RecoveryStrategy):
	"""Wait for the page to finish loading (spinner / network) before retrying."""

	name = 'wait'
	phase = RecoveryPhase.ACTION
	cost = RecoveryCost.LOW
	max_attempts = 2

	def can_handle(self, ctx: RecoveryContext) -> bool:
		if any(token in ctx.error for token in ('loading', 'still loading', 'not loaded', 'pending network')):
			return True
		state = ctx.browser_state
		return state is not None and bool(state.pending_network_requests)

	async def recover(self, ctx: RecoveryContext) -> RecoveryResult:
		seconds = ctx.agent.settings.auto_recovery_wait_seconds
		await asyncio.sleep(seconds)
		return RecoveryResult(
			outcome=RecoveryOutcome.RETRY,
			strategy=self.name,
			reason=f'waited {seconds}s for page load',
		)


class TimeoutRecovery(RecoveryStrategy):
	"""Repair a timed-out action by waiting and retrying once."""

	name = 'timeout'
	phase = RecoveryPhase.ACTION
	cost = RecoveryCost.MEDIUM
	max_attempts = 2

	def can_handle(self, ctx: RecoveryContext) -> bool:
		return 'timeout' in ctx.error or 'timed out' in ctx.error

	async def recover(self, ctx: RecoveryContext) -> RecoveryResult:
		seconds = ctx.agent.settings.auto_recovery_wait_seconds * 2
		await asyncio.sleep(seconds)
		return RecoveryResult(
			outcome=RecoveryOutcome.RETRY,
			strategy=self.name,
			reason=f'waited {seconds}s after timeout before retrying',
		)


# ── Retry ────────────────────────────────────────────────────────────────
class RetryRecovery(RecoveryStrategy):
	"""Final fallback — retry with exponential backoff before giving up."""

	name = 'retry'
	phase = RecoveryPhase.RETRY
	cost = RecoveryCost.LOW
	max_attempts = 3

	def can_handle(self, ctx: RecoveryContext) -> bool:
		# Anything not already claimed by a more specific strategy is retryable.
		return True

	async def recover(self, ctx: RecoveryContext) -> RecoveryResult:
		attempt = ctx.attempts.get(self.name, 1)
		delay = min(2.0 * (2 ** (attempt - 1)), 30.0)
		await asyncio.sleep(delay)
		return RecoveryResult(
			outcome=RecoveryOutcome.RETRY,
			strategy=self.name,
			reason=f'retrying with backoff delay {delay:.0f}s',
		)


# ── Composite ────────────────────────────────────────────────────────────
class CompositeRecovery(RecoveryStrategy):
	"""A chain of strategies exposed through the same interface.

	Sub-strategies are tried in order; each one gets its own attempt budget
	(``<composite>:<strategy>`` in the context) so repeated failures cascade
	naturally from one repair to the next. Because ``CompositeRecovery``
	subclasses ``RecoveryStrategy``, the engine treats it like any other
	strategy — it never needs to know a chain exists.
	"""

	name = 'composite'
	phase = RecoveryPhase.ELEMENT
	cost = RecoveryCost.LOW

	def __init__(self, strategies: list[RecoveryStrategy], name: str | None = None) -> None:
		self._strategies = list(strategies)
		if name:
			self.name = name
		else:
			self.name = '+'.join(s.name for s in strategies)

	def can_handle(self, ctx: RecoveryContext) -> bool:
		return any(s.can_handle(ctx) for s in self._strategies)

	async def recover(self, ctx: RecoveryContext) -> RecoveryResult:
		chain: list[str] = []
		for strategy in self._strategies:
			sub_key = f'{self.name}:{strategy.name}'
			if ctx.attempts.get(sub_key, 0) >= strategy.max_attempts:
				continue
			if not strategy.can_handle(ctx):
				continue
			ctx.attempts[sub_key] = ctx.attempts.get(sub_key, 0) + 1
			result = await strategy.recover(ctx)
			chain.append(strategy.name)
			if result.outcome in (RecoveryOutcome.GIVE_UP, RecoveryOutcome.ESCALATE):
				return RecoveryResult(
					outcome=result.outcome,
					strategy=self.name,
					chain=chain,
					reason=result.reason,
					explanation=result.explanation,
				)
			return RecoveryResult(
				outcome=result.outcome,
				strategy=self.name,
				chain=chain,
				retry_action=result.retry_action or ctx.action,
				reason=result.reason,
				explanation=result.explanation,
			)
		return RecoveryResult(
			outcome=RecoveryOutcome.GIVE_UP,
			strategy=self.name,
			chain=chain,
			reason='no sub-strategy available for this failure',
		)


def default_strategies() -> list[RecoveryStrategy]:
	"""The standard recovery registry in dispatch order."""
	return [
		BrowserCrashRecovery(),
		NavigationRecovery(),
		OverlayRecovery(),
		ScrollRecovery(),
		RelocateRecovery(),
		WaitRecovery(),
		TimeoutRecovery(),
		RetryRecovery(),
	]


def default_composite() -> CompositeRecovery:
	"""A ready-made element interaction chain: scroll → relocate → retry."""
	return CompositeRecovery(
		[ScrollRecovery(), RelocateRecovery(), RetryRecovery()],
		name='element_chain',
	)
