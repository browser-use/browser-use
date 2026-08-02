"""RecoveryEngine — filters, orders and dispatches recovery strategies."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from browser_use.agent.recovery.base import (
	RecoveryContext,
	RecoveryOutcome,
	RecoveryPhase,
	RecoveryResult,
	RecoveryStrategy,
)
from browser_use.agent.recovery.stats import RecoveryStats
from browser_use.agent.views import ActionResult

if TYPE_CHECKING:
	from browser_use.agent.service import Agent

logger = logging.getLogger(__name__)

_PHASE_ORDER = {
	RecoveryPhase.ENVIRONMENT: 0,
	RecoveryPhase.PAGE: 1,
	RecoveryPhase.ELEMENT: 2,
	RecoveryPhase.ACTION: 3,
	RecoveryPhase.RETRY: 4,
}

_COST_ORDER = {'low': 0, 'medium': 1, 'high': 2}


class RecoveryEngine:
	"""Deterministic recovery dispatcher.

	The engine owns the strategy registry. For each failure it:

	1. Filters strategies by capability (``supports``) and applicability
	   (``can_handle``).
	2. Orders them by phase, then by cost — cheapest repairs first, most
	   disruptive last.
	3. Dispatches to the first strategy that has not exhausted its attempts.

	Strategies are interchangeable: composite chains implement the same
	``RecoveryStrategy`` interface, so the engine never knows whether it is
	dispatching a single repair or a chain.
	"""

	def __init__(
		self,
		strategies: Iterable[RecoveryStrategy] | None = None,
		stats: RecoveryStats | None = None,
		max_attempts: int = 3,
	) -> None:
		self.strategies: list[RecoveryStrategy] = list(strategies or [])
		self.stats = stats or RecoveryStats()
		self.max_attempts = max_attempts

	def add_strategy(self, strategy: RecoveryStrategy) -> None:
		"""Register a strategy; the registry is re-ordered lazily on dispatch."""
		self.strategies.append(strategy)

	def _candidates(self, ctx: RecoveryContext) -> list[RecoveryStrategy]:
		"""Strategies that apply to this failure, cheapest/least disruptive first."""
		candidates = []
		for strategy in self.strategies:
			if strategy.supports is not None and ctx.action_kind not in strategy.supports:
				continue
			if not strategy.can_handle(ctx):
				continue
			if ctx.attempts.get(strategy.name, 0) >= strategy.max_attempts:
				continue
			candidates.append(strategy)
		candidates.sort(
			key=lambda s: (_PHASE_ORDER[s.phase], _COST_ORDER[s.cost.value])
		)
		return candidates

	async def evaluate(self, ctx: RecoveryContext) -> RecoveryResult:
		"""Run the first applicable strategy and return its decision.

		Per-strategy attempt counts are incremented here so consecutive
		failures naturally cascade to the next strategy (attempt 1: wait,
		attempt 2: relocate, attempt 3: retry, ...).
		"""
		for strategy in self._candidates(ctx):
			attempt = ctx.attempts.get(strategy.name, 0) + 1
			ctx.attempts[strategy.name] = attempt
			self.stats.record_attempt(strategy.name)
			try:
				result = await strategy.recover(ctx)
			except Exception as e:
				logger.error(f'⚠️ Recovery strategy {strategy.name} raised {type(e).__name__}: {e}')
				self.stats.record_give_up()
				continue
			result.attempts = attempt
			logger.info(
				f'🔄 Recovery: {strategy.name} → {result.outcome.value} '
				f'(attempt {attempt}/{strategy.max_attempts}, reason: {result.reason})'
			)
			if result.outcome == RecoveryOutcome.ESCALATE:
				self.stats.record_escalation()
			elif result.outcome == RecoveryOutcome.GIVE_UP:
				self.stats.record_give_up()
			return result
		return RecoveryResult(
			outcome=RecoveryOutcome.GIVE_UP,
			reason='no recovery strategy matched or attempts exhausted',
		)

	def ordered_strategy_names(self) -> list[str]:
		"""Strategy names in dispatch order — used for logging and tests."""
		return [s.name for s in self.strategies]


@dataclass
class RecoveryAttempt:
	"""Outcome of a recovery run: the final action result plus diagnostics."""

	result: ActionResult
	outcome: RecoveryOutcome
	recovered: bool
	chain: list[str]
	strategy: str | None = None
	attempts: int = 0
	reason: str | None = None


class RecoveryStage:
	"""Recovery execution stage used by the action executor.

	Wraps the engine with the retry loop: evaluate → execute the suggested
	retry action → re-evaluate until the action succeeds, the attempt budget
	is exhausted, or recovery escalates back to the pipeline/LLM.
	"""

	def __init__(
		self,
		engine: RecoveryEngine | None = None,
		max_rounds: int = 3,
	) -> None:
		self.engine = engine or RecoveryEngine()
		self.max_rounds = max_rounds

	def _build_context(
		self,
		agent: Agent,
		action,
		action_name: str,
		failed_result,
		browser_state,
	) -> RecoveryContext:
		return RecoveryContext(
			agent=agent,
			action=action,
			action_name=action_name,
			failed_result=failed_result,
			browser_state=browser_state,
			step_id=agent.state.n_steps,
			page_hash_before=RecoveryContext.page_hash(browser_state),
		)

	async def recover(
		self,
		agent: Agent,
		action,
		action_name: str,
		failed_result,
		browser_state,
	) -> RecoveryAttempt:
		"""Attempt to repair the failure and return the final action result.

		If recovery succeeds, ``attempt.recovered`` is True and
		``attempt.result`` is the successful ``ActionResult``. Otherwise the
		original error is preserved and the LLM becomes the fallback.
		"""
		ctx = self._build_context(agent, action, action_name, failed_result, browser_state)
		chain: list[str] = []
		for _ in range(self.max_rounds):
			decision = await self.engine.evaluate(ctx)
			chain.extend(decision.chain or [])
			if decision.outcome in (RecoveryOutcome.GIVE_UP, RecoveryOutcome.ESCALATE):
				return RecoveryAttempt(
					result=failed_result,
					outcome=decision.outcome,
					recovered=False,
					chain=chain,
					strategy=decision.strategy,
					attempts=decision.attempts,
					reason=decision.reason,
				)
			# SUCCESS / RETRY → re-execute the (possibly updated) action.
			retry_action = decision.retry_action or ctx.action
			try:
				session = agent.browser_session
				new_result = await agent.tools.act(
					action=retry_action,
					browser_session=session,
					file_system=agent.file_system,
					page_extraction_llm=agent.settings.page_extraction_llm,
					sensitive_data=agent.sensitive_data,
					available_file_paths=agent.available_file_paths,
					extraction_schema=agent.extraction_schema,
				)
			except Exception as e:
				new_result = ActionResult(error=f'{type(e).__name__}: {e}')
			ctx.failed_result = new_result
			ctx.page_hash_after = RecoveryContext.page_hash(browser_state)
			if not new_result.error:
				self.engine.stats.record_success(decision.strategy, max(len(chain), 1))
				logger.info(
					f'✅ Recovery succeeded ({len(chain)} step(s)): '
					f'{"+".join(chain) or decision.strategy}: {decision.reason}'
				)
				return RecoveryAttempt(
					result=new_result,
					outcome=RecoveryOutcome.SUCCESS,
					recovered=True,
					chain=chain,
					strategy=decision.strategy,
					attempts=decision.attempts,
					reason='recovered after retry',
				)
		# Budget exhausted — hand the original error back to the LLM.
		self.engine.stats.record_give_up()
		logger.info(f'❌ Recovery gave up after {len(chain)} step(s): {ctx.error or "unknown failure"}')
		return RecoveryAttempt(
			result=failed_result,
			outcome=RecoveryOutcome.GIVE_UP,
			recovered=False,
			chain=chain,
			reason='recovery attempt budget exhausted',
		)
