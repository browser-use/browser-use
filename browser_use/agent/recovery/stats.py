"""Recovery telemetry — counts, success rates and strategy distribution."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RecoveryStats:
	"""Aggregated metrics for recovery attempts.

	Collected by the engine and surfaced through ``summary()`` so recovery
	behaviour is observable and measurable (e.g. for a telemetry dashboard).
	"""

	total_attempts: int = 0
	recovered: int = 0
	gave_up: int = 0
	escalated: int = 0
	strategy_attempts: dict[str, int] = field(default_factory=dict)
	strategy_successes: dict[str, int] = field(default_factory=dict)
	chain_lengths: list[int] = field(default_factory=list)

	def record_attempt(self, strategy: str | None) -> None:
		self.total_attempts += 1
		if strategy:
			self.strategy_attempts[strategy] = self.strategy_attempts.get(strategy, 0) + 1

	def record_success(self, strategy: str | None, chain_length: int = 1) -> None:
		self.recovered += 1
		if strategy:
			self.strategy_successes[strategy] = self.strategy_successes.get(strategy, 0) + 1
		self.chain_lengths.append(chain_length)

	def record_give_up(self) -> None:
		self.gave_up += 1

	def record_escalation(self) -> None:
		self.escalated += 1

	@property
	def success_rate(self) -> float:
		"""Share of attempts that recovered before reaching the LLM."""
		if self.total_attempts == 0:
			return 0.0
		return self.recovered / self.total_attempts

	@property
	def avg_chain_length(self) -> float:
		"""Average number of strategies used per successful recovery."""
		if not self.chain_lengths:
			return 0.0
		return sum(self.chain_lengths) / len(self.chain_lengths)

	def distribution(self) -> dict[str, int]:
		"""Strategy usage distribution, most-used first."""
		return dict(sorted(self.strategy_attempts.items(), key=lambda item: item[1], reverse=True))

	def summary(self) -> str:
		"""One-line summary suitable for logs."""
		dist = ', '.join(f'{name}={count}' for name, count in self.distribution().items())
		return (
			f'recovery: attempts={self.total_attempts} recovered={self.recovered} '
			f'gave_up={self.gave_up} escalated={self.escalated} '
			f'success_rate={self.success_rate:.0%} avg_chain={self.avg_chain_length:.1f}'
			f'{f" ({dist})" if dist else ""}'
		)
