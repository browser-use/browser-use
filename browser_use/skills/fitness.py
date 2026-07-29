"""Dempster-Shafer skill-fitness accumulator.

Ports the numpy-free subset of evoforge/bio_evolution.py's uncertainty layer:
each skill invocation (success + latency + error) becomes a MassFunction over
{LOW, MID, HIGH}; repeated invocations combine via Dempster's rule, giving a
belief/plausibility interval per skill rather than a point estimate.

Downstream selectors can pick by:
  belief       — conservative (max lower bound; avoid unproven skills)
  plausibility — exploratory (max upper bound; try promising-but-noisy skills)
  expected     — pignistic Bayesian collapse (spread ignorance uniformly)

No numpy dependency — this ships in the core install.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import Any, Literal

FrozenFrame = frozenset[str]

_LOW: FrozenFrame = frozenset({'LOW'})
_MID: FrozenFrame = frozenset({'MID'})
_HIGH: FrozenFrame = frozenset({'HIGH'})
_FULL: FrozenFrame = frozenset({'LOW', 'MID', 'HIGH'})

SelectionMode = Literal['belief', 'plausibility', 'expected']


@dataclass(frozen=True)
class MassFunction:
	"""Mass assignment over subsets of {LOW, MID, HIGH}. Masses sum to 1.

	Mass on the full frame represents pure ignorance — the feature that
	distinguishes Dempster-Shafer from Bayesian probability.
	"""

	masses: dict[FrozenFrame, float] = field(default_factory=dict)

	def __post_init__(self) -> None:
		total = sum(self.masses.values())
		if total <= 0:
			object.__setattr__(self, 'masses', {_FULL: 1.0})
			return
		if abs(total - 1.0) > 1e-9:
			object.__setattr__(self, 'masses', {k: v / total for k, v in self.masses.items()})

	@classmethod
	def from_score(cls, score: float, confidence: float = 0.7) -> MassFunction:
		"""Map a [0,1] point score to a mass function.

		confidence ∈ [0,1]: mass placed on the singleton hypothesis; the
		remainder (1 - confidence) is assigned to the full frame as ignorance.
		"""
		score = max(0.0, min(1.0, float(score)))
		confidence = max(0.0, min(1.0, float(confidence)))
		if score < 1.0 / 3.0:
			singleton = _LOW
		elif score < 2.0 / 3.0:
			singleton = _MID
		else:
			singleton = _HIGH
		return cls({singleton: confidence, _FULL: 1.0 - confidence})

	def belief(self, hypothesis: FrozenFrame = _HIGH) -> float:
		"""Lower probability bound: sum of masses on subsets of the hypothesis."""
		return sum(m for s, m in self.masses.items() if s.issubset(hypothesis))

	def plausibility(self, hypothesis: FrozenFrame = _HIGH) -> float:
		"""Upper probability bound: sum of masses on subsets intersecting the hypothesis."""
		return sum(m for s, m in self.masses.items() if s & hypothesis)

	def expected_value(self) -> float:
		"""Pignistic expectation: non-singleton mass spread uniformly over members."""
		values = {'LOW': 0.15, 'MID': 0.5, 'HIGH': 0.85}
		total = 0.0
		for subset, m in self.masses.items():
			if not subset:
				continue
			per = m / len(subset)
			for hypothesis in subset:
				total += per * values[hypothesis]
		return total

	def score(self, mode: SelectionMode = 'belief') -> float:
		"""One-shot scalar for ranking. Belief = conservative, plausibility = exploratory."""
		if mode == 'belief':
			return self.belief()
		if mode == 'plausibility':
			return self.plausibility()
		return self.expected_value()

	def to_dict(self) -> dict[str, float]:
		"""JSON-safe wire format. Frozenset keys become sorted comma-joined strings."""
		return {','.join(sorted(subset)): mass for subset, mass in self.masses.items()}

	@classmethod
	def from_dict(cls, data: dict[str, float]) -> MassFunction:
		"""Inverse of to_dict — accepts the sorted-comma-joined key form."""
		masses: dict[FrozenFrame, float] = {}
		for key, mass in data.items():
			subset = frozenset(part for part in key.split(',') if part)
			if not subset:
				continue
			masses[subset] = float(mass)
		return cls(masses)


def dempster_combine(m1: MassFunction, m2: MassFunction) -> MassFunction:
	"""Dempster's rule of combination — normalises out the conflict mass.

	Falls back to maximum-ignorance on total conflict (norm ≈ 0), which happens
	when two mass functions place all their weight on disjoint singletons.
	"""
	combined: dict[FrozenFrame, float] = {}
	conflict = 0.0
	for s1, v1 in m1.masses.items():
		for s2, v2 in m2.masses.items():
			inter = s1 & s2
			if not inter:
				conflict += v1 * v2
			else:
				combined[inter] = combined.get(inter, 0.0) + v1 * v2
	norm = 1.0 - conflict
	if norm <= 1e-9:
		return MassFunction({_FULL: 1.0})
	return MassFunction({k: v / norm for k, v in combined.items()})


def score_from_execution(success: bool, latency_ms: int | None, error: str | None) -> tuple[float, float]:
	"""Turn one skill-execution result into a (score, confidence) pair.

	success maps to a hard 0/1 anchor; latency modulates confidence (fast +
	successful → very confident; slow + successful → less confident because
	we can't tell if the skill just got lucky).
	"""
	if success and error is None:
		if latency_ms is None:
			return 0.8, 0.6
		# Latency curve: <500ms full confidence, >30s minimum confidence.
		latency_conf = max(0.4, min(0.95, 1.0 - (latency_ms / 30_000.0)))
		return 0.9, latency_conf
	# Failure — high-confidence LOW score, but leave a sliver of ignorance in
	# case the failure was environmental (blocked cookie, transient 5xx).
	return 0.1, 0.7


@dataclass
class SkillFitnessTracker:
	"""Per-skill Dempster-Shafer fitness accumulator.

	Records every execution result, combines belief across the history via
	Dempster's rule, and exposes rankings under three selection modes.
	"""

	_fitness: dict[str, MassFunction] = field(default_factory=dict)
	_invocations: dict[str, int] = field(default_factory=dict)

	def record(
		self,
		skill_id: str,
		success: bool,
		latency_ms: int | None = None,
		error: str | None = None,
	) -> MassFunction:
		"""Fold this execution into the skill's belief interval; return the updated function."""
		score, confidence = score_from_execution(success, latency_ms, error)
		observation = MassFunction.from_score(score, confidence)
		prior = self._fitness.get(skill_id)
		combined = dempster_combine(prior, observation) if prior is not None else observation
		self._fitness[skill_id] = combined
		self._invocations[skill_id] = self._invocations.get(skill_id, 0) + 1
		return combined

	def fitness(self, skill_id: str) -> MassFunction | None:
		"""Return the accumulated mass function for a skill, or None if unseen."""
		return self._fitness.get(skill_id)

	def invocations(self, skill_id: str) -> int:
		"""How many times this skill has been recorded. Zero if unseen."""
		return self._invocations.get(skill_id, 0)

	def ranked(self, mode: SelectionMode = 'belief') -> list[tuple[str, float]]:
		"""Skill IDs sorted by the chosen selection mode, best first."""
		return sorted(
			((skill_id, mf.score(mode)) for skill_id, mf in self._fitness.items()),
			key=lambda pair: pair[1],
			reverse=True,
		)

	def reset(self) -> None:
		"""Drop all accumulated fitness. Useful for scoped experiments."""
		self._fitness.clear()
		self._invocations.clear()

	def to_dict(self) -> dict[str, Any]:
		"""JSON-safe snapshot of the full accumulator state. Round-trips via from_dict."""
		return {
			'fitness': {skill_id: mf.to_dict() for skill_id, mf in self._fitness.items()},
			'invocations': dict(self._invocations),
		}

	@classmethod
	def from_dict(cls, data: dict[str, Any]) -> SkillFitnessTracker:
		"""Restore a tracker from to_dict output. Unknown keys are ignored."""
		fitness_raw = data.get('fitness', {}) or {}
		invocations_raw = data.get('invocations', {}) or {}
		fitness = {skill_id: MassFunction.from_dict(mf) for skill_id, mf in fitness_raw.items()}
		invocations = {skill_id: int(count) for skill_id, count in invocations_raw.items()}
		return cls(_fitness=fitness, _invocations=invocations)


def _cli(argv: list[str] | None = None) -> int:
	"""Read (skill_id, success, latency_ms, error) records as JSONL from stdin, print rankings.

	Pipe from any tool that emits skill-execution results — kafcade steps, CI runs,
	agent traces. Load prior state with --state; persist accumulated state with --save.

	Examples:
	    cat runs.jsonl | python -m browser_use.skills.fitness
	    python -m browser_use.skills.fitness --mode plausibility --state prior.json --save next.json
	"""
	import argparse

	parser = argparse.ArgumentParser(
		prog='python -m browser_use.skills.fitness',
		description='Accumulate Dempster-Shafer skill fitness from JSONL records on stdin.',
	)
	parser.add_argument(
		'--mode',
		choices=('belief', 'plausibility', 'expected'),
		default='belief',
		help='Ranking mode (default: belief).',
	)
	parser.add_argument('--state', type=str, default=None, help='Load prior tracker state from this JSON file.')
	parser.add_argument('--save', type=str, default=None, help='Write updated tracker state to this JSON file.')
	parser.add_argument('--top', type=int, default=0, help='Show only the top N skills (0 = all).')
	args = parser.parse_args(argv)

	if args.state:
		with open(args.state, encoding='utf-8') as f:
			tracker = SkillFitnessTracker.from_dict(json.load(f))
	else:
		tracker = SkillFitnessTracker()

	for line_num, line in enumerate(sys.stdin, start=1):
		line = line.strip()
		if not line:
			continue
		try:
			record = json.loads(line)
		except json.JSONDecodeError as e:
			print(f'line {line_num}: skipping malformed JSON: {e}', file=sys.stderr)
			continue
		skill_id = record.get('skill_id')
		if not skill_id:
			print(f'line {line_num}: skipping record without skill_id', file=sys.stderr)
			continue
		tracker.record(
			skill_id=str(skill_id),
			success=bool(record.get('success', False)),
			latency_ms=record.get('latency_ms'),
			error=record.get('error'),
		)

	ranked = tracker.ranked(args.mode)
	if args.top > 0:
		ranked = ranked[: args.top]
	for skill_id, score in ranked:
		invocations = tracker.invocations(skill_id)
		print(f'{score:.4f}\t{invocations}\t{skill_id}')

	if args.save:
		with open(args.save, 'w', encoding='utf-8') as f:
			json.dump(tracker.to_dict(), f, indent=2, sort_keys=True)
	return 0


if __name__ == '__main__':
	sys.exit(_cli())
