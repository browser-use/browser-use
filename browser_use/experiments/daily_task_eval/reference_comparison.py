"""Multi-reference human baseline comparison and human–human calibration stats."""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import combinations
from typing import Literal

from .human_reference import validate_reference_eligibility
from .models import AgentRunSummary, HumanRunRecord, TrajectoryComparable
from .task_registry import task_metadata_for
from .trajectory_metrics import PairwiseTrajectoryComparison, compare_trajectories

ComparisonStatus = Literal[
	'comparable',
	'partially_comparable',
	'no_human_reference',
	'agent_route_not_comparable',
	'no_comparable_reference',
	'task_card_mismatch',
]


@dataclass(frozen=True, slots=True)
class ReferenceSetComparison:
	comparison_status: ComparisonStatus
	comparison_exclusion_reason: str | None
	human_reference_count: int
	pairwise_results: tuple[tuple[str, PairwiseTrajectoryComparison], ...]

	raw_lcs_mean: float | None
	raw_lcs_median: float | None
	raw_lcs_min: float | None
	raw_lcs_max: float | None

	canonical_lcs_mean: float | None
	canonical_lcs_median: float | None
	canonical_lcs_min: float | None
	canonical_lcs_max: float | None

	navigation_lcs_mean: float | None
	navigation_lcs_median: float | None
	navigation_lcs_min: float | None
	navigation_lcs_max: float | None


@dataclass(frozen=True, slots=True)
class HumanReferenceSetStats:
	task_id: str
	scenario_id: str
	reference_count: int
	pair_count: int
	raw_lcs_mean: float | None
	canonical_lcs_mean: float | None
	navigation_lcs_mean: float | None


def _reference_label(run: HumanRunRecord, index: int) -> str:
	return f'{run.task_id}:{run.scenario_id}:ref{index}'


def get_reference_human_runs(
	human_runs: Sequence[HumanRunRecord],
	*,
	task_id: str,
	scenario_id: str,
) -> list[HumanRunRecord]:
	"""Eligible human references for one ``(task_id, scenario_id)`` pair."""

	meta = task_metadata_for(task_id)
	if not meta.include_in_reference_lcs:
		return []
	out: list[HumanRunRecord] = []
	for run in human_runs:
		if run.task_id != task_id or run.scenario_id != scenario_id:
			continue
		if not validate_reference_eligibility(run).eligible:
			continue
		if run.trajectory_comparable == 'low':
			continue
		out.append(run)
	return out


def _aggregate_scores(scores: list[float | None]) -> tuple[float | None, float | None, float | None, float | None]:
	present = [s for s in scores if s is not None]
	if not present:
		return None, None, None, None
	return (
		float(statistics.fmean(present)),
		float(statistics.median(present)),
		float(min(present)),
		float(max(present)),
	)


def _empty_reference_set_comparison(*, status: ComparisonStatus, reference_count: int = 0) -> ReferenceSetComparison:
	return ReferenceSetComparison(
		comparison_status=status,
		comparison_exclusion_reason=None,
		human_reference_count=reference_count,
		pairwise_results=(),
		raw_lcs_mean=None,
		raw_lcs_median=None,
		raw_lcs_min=None,
		raw_lcs_max=None,
		canonical_lcs_mean=None,
		canonical_lcs_median=None,
		canonical_lcs_min=None,
		canonical_lcs_max=None,
		navigation_lcs_mean=None,
		navigation_lcs_median=None,
		navigation_lcs_min=None,
		navigation_lcs_max=None,
	)


def _agent_trajectory_comparable(agent_run: AgentRunSummary) -> TrajectoryComparable | None:
	return getattr(agent_run, 'trajectory_comparable', None)


def compare_agent_to_human_references(
	agent_run: AgentRunSummary,
	human_runs: Sequence[HumanRunRecord],
) -> ReferenceSetComparison:
	"""Compare one Agent run against all eligible human references for its task/scenario."""

	agent_comparable = _agent_trajectory_comparable(agent_run)
	if agent_comparable == 'low':
		return ReferenceSetComparison(
			comparison_status='agent_route_not_comparable',
			comparison_exclusion_reason='agent trajectory marked low',
			human_reference_count=0,
			pairwise_results=(),
			raw_lcs_mean=None,
			raw_lcs_median=None,
			raw_lcs_min=None,
			raw_lcs_max=None,
			canonical_lcs_mean=None,
			canonical_lcs_median=None,
			canonical_lcs_min=None,
			canonical_lcs_max=None,
			navigation_lcs_mean=None,
			navigation_lcs_median=None,
			navigation_lcs_min=None,
			navigation_lcs_max=None,
		)

	references = get_reference_human_runs(
		human_runs,
		task_id=agent_run.task_id,
		scenario_id=agent_run.scenario_id,
	)
	if not references:
		return ReferenceSetComparison(
			comparison_status='no_human_reference',
			comparison_exclusion_reason='no eligible human reference',
			human_reference_count=0,
			pairwise_results=(),
			raw_lcs_mean=None,
			raw_lcs_median=None,
			raw_lcs_min=None,
			raw_lcs_max=None,
			canonical_lcs_mean=None,
			canonical_lcs_median=None,
			canonical_lcs_min=None,
			canonical_lcs_max=None,
			navigation_lcs_mean=None,
			navigation_lcs_median=None,
			navigation_lcs_min=None,
			navigation_lcs_max=None,
		)

	if agent_run.task_card_hash:
		hash_matched = [ref for ref in references if ref.task_card_hash == agent_run.task_card_hash]
		if not hash_matched:
			return ReferenceSetComparison(
				comparison_status='task_card_mismatch',
				comparison_exclusion_reason='task_card_hash mismatch between agent run and human references',
				human_reference_count=len(references),
				pairwise_results=(),
				raw_lcs_mean=None,
				raw_lcs_median=None,
				raw_lcs_min=None,
				raw_lcs_max=None,
				canonical_lcs_mean=None,
				canonical_lcs_median=None,
				canonical_lcs_min=None,
				canonical_lcs_max=None,
				navigation_lcs_mean=None,
				navigation_lcs_median=None,
				navigation_lcs_min=None,
				navigation_lcs_max=None,
			)
		references = hash_matched

	pairwise: list[tuple[str, PairwiseTrajectoryComparison]] = []
	raw_scores: list[float | None] = []
	canonical_scores: list[float | None] = []
	navigation_scores: list[float | None] = []

	for index, human in enumerate(references):
		result = compare_trajectories(agent_run.action_names, human.steps)
		label = _reference_label(human, index)
		pairwise.append((label, result))
		raw_scores.append(result.raw_lcs)
		canonical_scores.append(result.canonical_lcs)
		navigation_scores.append(result.navigation_lcs)

	has_partial = any(ref.trajectory_comparable == 'partial' for ref in references)
	status: ComparisonStatus
	if agent_comparable == 'partial' or has_partial:
		status = 'partially_comparable'
	else:
		status = 'comparable'

	raw_mean, raw_median, raw_min, raw_max = _aggregate_scores(raw_scores)
	can_mean, can_median, can_min, can_max = _aggregate_scores(canonical_scores)
	nav_mean, nav_median, nav_min, nav_max = _aggregate_scores(navigation_scores)

	if raw_mean is None and can_mean is None and nav_mean is None:
		return ReferenceSetComparison(
			comparison_status='no_comparable_reference',
			comparison_exclusion_reason='no comparable action trajectory',
			human_reference_count=len(references),
			pairwise_results=(),
			raw_lcs_mean=None,
			raw_lcs_median=None,
			raw_lcs_min=None,
			raw_lcs_max=None,
			canonical_lcs_mean=None,
			canonical_lcs_median=None,
			canonical_lcs_min=None,
			canonical_lcs_max=None,
			navigation_lcs_mean=None,
			navigation_lcs_median=None,
			navigation_lcs_min=None,
			navigation_lcs_max=None,
		)

	return ReferenceSetComparison(
		comparison_status=status,
		comparison_exclusion_reason=None,
		human_reference_count=len(references),
		pairwise_results=tuple(pairwise),
		raw_lcs_mean=raw_mean,
		raw_lcs_median=raw_median,
		raw_lcs_min=raw_min,
		raw_lcs_max=raw_max,
		canonical_lcs_mean=can_mean,
		canonical_lcs_median=can_median,
		canonical_lcs_min=can_min,
		canonical_lcs_max=can_max,
		navigation_lcs_mean=nav_mean,
		navigation_lcs_median=nav_median,
		navigation_lcs_min=nav_min,
		navigation_lcs_max=nav_max,
	)


def compare_human_reference_set(references: Sequence[HumanRunRecord]) -> HumanReferenceSetStats:
	"""Pairwise LCS means across eligible human references (calibration, not ranking)."""

	eligible = [run for run in references if validate_reference_eligibility(run).eligible and run.trajectory_comparable != 'low']
	task_id = eligible[0].task_id if eligible else (references[0].task_id if references else '')
	scenario_id = eligible[0].scenario_id if eligible else (references[0].scenario_id if references else '')

	if len(eligible) < 2:
		return HumanReferenceSetStats(
			task_id=task_id,
			scenario_id=scenario_id,
			reference_count=len(eligible),
			pair_count=0,
			raw_lcs_mean=None,
			canonical_lcs_mean=None,
			navigation_lcs_mean=None,
		)

	raw_scores: list[float] = []
	canonical_scores: list[float] = []
	navigation_scores: list[float] = []

	for left, right in combinations(eligible, 2):
		result = compare_trajectories(left.steps, right.steps)
		if result.raw_lcs is not None:
			raw_scores.append(result.raw_lcs)
		if result.canonical_lcs is not None:
			canonical_scores.append(result.canonical_lcs)
		if result.navigation_lcs is not None:
			navigation_scores.append(result.navigation_lcs)

	pair_count = len(list(combinations(eligible, 2)))
	raw_mean = float(statistics.fmean(raw_scores)) if raw_scores else None
	can_mean = float(statistics.fmean(canonical_scores)) if canonical_scores else None
	nav_mean = float(statistics.fmean(navigation_scores)) if navigation_scores else None

	return HumanReferenceSetStats(
		task_id=task_id,
		scenario_id=scenario_id,
		reference_count=len(eligible),
		pair_count=pair_count,
		raw_lcs_mean=raw_mean,
		canonical_lcs_mean=can_mean,
		navigation_lcs_mean=nav_mean,
	)
