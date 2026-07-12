"""Tests for the Dempster-Shafer skill-fitness accumulator.

Real objects, no mocks — the fitness math is pure Python and deterministic.
Covers:
  - MassFunction normalisation + belief/plausibility/expected axes
  - from_score confidence gating (0 → pure ignorance, 1 → point mass on singleton)
  - Dempster combination reinforces agreeing observations
  - Dempster combination on total conflict falls back to maximum-ignorance
  - SkillFitnessTracker accumulates + ranks under all three selection modes
  - SkillService wiring records every execution result
"""

from __future__ import annotations

import pytest

from browser_use.skills.fitness import (
	MassFunction,
	SkillFitnessTracker,
	dempster_combine,
	score_from_execution,
)

_HIGH = frozenset({'HIGH'})
_LOW = frozenset({'LOW'})
_FULL = frozenset({'LOW', 'MID', 'HIGH'})


def test_mass_function_normalises_to_unit() -> None:
	m = MassFunction({_HIGH: 2.0, _FULL: 2.0})
	assert abs(sum(m.masses.values()) - 1.0) < 1e-9
	assert m.masses[_HIGH] == pytest.approx(0.5)
	assert m.masses[_FULL] == pytest.approx(0.5)


def test_mass_function_empty_collapses_to_max_ignorance() -> None:
	m = MassFunction({})
	assert m.masses == {_FULL: 1.0}
	assert m.belief() == 0.0
	assert m.plausibility() == 1.0


def test_from_score_confidence_gates_ignorance() -> None:
	certain = MassFunction.from_score(0.9, confidence=1.0)
	assert certain.masses.get(_HIGH) == pytest.approx(1.0)
	assert certain.belief() == pytest.approx(1.0)
	assert certain.plausibility() == pytest.approx(1.0)

	ignorant = MassFunction.from_score(0.9, confidence=0.0)
	assert ignorant.masses.get(_FULL) == pytest.approx(1.0)
	assert ignorant.belief() == 0.0
	assert ignorant.plausibility() == pytest.approx(1.0)

	mid = MassFunction.from_score(0.5, confidence=0.6)
	assert mid.belief(frozenset({'MID'})) == pytest.approx(0.6)


def test_score_boundaries_partition_correctly() -> None:
	low = MassFunction.from_score(0.0, confidence=1.0)
	assert _LOW in low.masses
	mid = MassFunction.from_score(0.5, confidence=1.0)
	assert frozenset({'MID'}) in mid.masses
	high = MassFunction.from_score(1.0, confidence=1.0)
	assert _HIGH in high.masses


def test_dempster_reinforces_agreement() -> None:
	m1 = MassFunction.from_score(0.9, confidence=0.6)
	m2 = MassFunction.from_score(0.9, confidence=0.6)
	combined = dempster_combine(m1, m2)
	# Two independent HIGH observations should push belief above either alone.
	assert combined.belief() > m1.belief()
	assert combined.belief() > 0.6


def test_dempster_total_conflict_reverts_to_ignorance() -> None:
	high_certain = MassFunction({_HIGH: 1.0})
	low_certain = MassFunction({_LOW: 1.0})
	combined = dempster_combine(high_certain, low_certain)
	# No mass on a shared subset → norm = 0 → fall back to full-frame ignorance.
	assert combined.masses == {_FULL: 1.0}


def test_score_from_execution_success_high_confidence_when_fast() -> None:
	score, confidence = score_from_execution(success=True, latency_ms=100, error=None)
	assert score >= 0.8
	assert confidence >= 0.9


def test_score_from_execution_failure_low_score() -> None:
	score, confidence = score_from_execution(success=False, latency_ms=None, error='boom')
	assert score < 0.3
	assert 0.5 < confidence < 1.0


def test_tracker_accumulates_belief_across_calls() -> None:
	tracker = SkillFitnessTracker()
	assert tracker.fitness('skill-a') is None
	assert tracker.invocations('skill-a') == 0

	for _ in range(3):
		tracker.record('skill-a', success=True, latency_ms=200)
	fitness = tracker.fitness('skill-a')
	assert fitness is not None
	# Three fast successes should give near-certain HIGH belief.
	assert fitness.belief() > 0.85
	assert tracker.invocations('skill-a') == 3


def test_tracker_ranks_by_selection_mode() -> None:
	tracker = SkillFitnessTracker()
	# Reliable skill: three fast successes.
	for _ in range(3):
		tracker.record('reliable', success=True, latency_ms=100)
	# Noisy skill: one success then one failure — high conflict, low belief but wide plausibility.
	tracker.record('noisy', success=True, latency_ms=100)
	tracker.record('noisy', success=False, error='transient')
	# Untried skill: never recorded.
	# Cold skill: one moderate-latency success.
	tracker.record('cold', success=True, latency_ms=5_000)

	belief_ranked = tracker.ranked('belief')
	plausibility_ranked = tracker.ranked('plausibility')
	expected_ranked = tracker.ranked('expected')

	# All three modes should list reliable first.
	assert belief_ranked[0][0] == 'reliable'
	assert plausibility_ranked[0][0] == 'reliable'
	assert expected_ranked[0][0] == 'reliable'

	# Rankings are proper permutations of what was recorded.
	assert {name for name, _ in belief_ranked} == {'reliable', 'noisy', 'cold'}


def test_tracker_reset_clears_state() -> None:
	tracker = SkillFitnessTracker()
	tracker.record('x', success=True, latency_ms=100)
	assert tracker.fitness('x') is not None
	tracker.reset()
	assert tracker.fitness('x') is None
	assert tracker.invocations('x') == 0
	assert tracker.ranked() == []


def test_service_exposes_fitness_and_ranking(monkeypatch: pytest.MonkeyPatch) -> None:
	"""SkillService should expose fitness() and ranked_by_fitness() and populate on record."""
	monkeypatch.setenv('BROWSER_USE_API_KEY', 'test-not-called')
	from browser_use.skills import SkillService

	svc = SkillService(skill_ids=['abc'])
	# No calls yet.
	assert svc.fitness('abc') is None
	assert svc.ranked_by_fitness() == []

	# Simulate what execute_skill's tail would do — feed the tracker directly.
	svc._fitness_tracker.record('abc', success=True, latency_ms=250)
	svc._fitness_tracker.record('abc', success=True, latency_ms=250)
	mf = svc.fitness('abc')
	assert mf is not None
	assert mf.belief() > 0.6

	svc._fitness_tracker.record('def', success=False, error='blocked')
	ranking = svc.ranked_by_fitness('belief')
	names = [name for name, _ in ranking]
	assert names.index('abc') < names.index('def')
