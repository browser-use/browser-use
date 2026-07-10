"""Batch scheduling for the paper cadence matrix.

Within each task block, condition order is randomized (not fixed
E → I → R-1 → R-3 → R-5 → R-A), matching the PRICAI 2026 protocol.
Runs remain sequential (one browser session at a time).
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .experiment_presets import (
	PAPER_CONDITION_ADAPTIVE,
	PAPER_EXPERIMENT_CA,
	PAPER_EXPERIMENT_RUN_FLAGS,
)

# Canonical display / table order (not execution order).
PAPER_CONDITION_ORDER: tuple[str, ...] = ('E', 'I', 'R-1', 'R-3', 'R-5', PAPER_CONDITION_ADAPTIVE)

PAPER_EXPERIMENT_ID_BY_CONDITION: dict[str, str] = {
	'E': 'C',
	'I': 'D',
	'R-1': 'C1',
	'R-3': 'C3',
	'R-5': 'C5',
	PAPER_CONDITION_ADAPTIVE: PAPER_EXPERIMENT_CA,
}

DEFAULT_MAIN_TASK_IDS: tuple[str, ...] = (
	'shopping_price_compare',
	'nearby_hospital_phone_lookup',
	'github_clean_issue_audit',
	'huggingface_model_constrained_selection',
)

DEFAULT_REPS_PER_CONDITION = 10
DEFAULT_SCHEDULE_SEED = 42


@dataclass(frozen=True, slots=True)
class ScheduledRun:
	"""One cell in the 4 × 6 × n run matrix."""

	task_id: str
	paper_condition: str
	experiment_id: str
	repeat_id: int
	schedule_index: int


def build_randomized_task_schedule(
	*,
	task_id: str,
	reps_per_condition: int = DEFAULT_REPS_PER_CONDITION,
	seed: int = DEFAULT_SCHEDULE_SEED,
	schedule_index_offset: int = 0,
) -> list[ScheduledRun]:
	"""Return ``reps_per_condition`` runs for each paper condition, shuffled within ``task_id``.

	The shuffle is deterministic for a given ``seed`` and ``task_id`` so manifests
	can be reproduced without storing the full queue twice.
	"""
	assert reps_per_condition >= 1
	rng = random.Random(_task_seed(seed=seed, task_id=task_id))

	jobs: list[tuple[str, str, int]] = []
	for paper_condition in PAPER_CONDITION_ORDER:
		experiment_id = PAPER_EXPERIMENT_ID_BY_CONDITION[paper_condition]
		for repeat_id in range(1, reps_per_condition + 1):
			jobs.append((paper_condition, experiment_id, repeat_id))

	rng.shuffle(jobs)

	return [
		ScheduledRun(
			task_id=task_id,
			paper_condition=paper_condition,
			experiment_id=experiment_id,
			repeat_id=repeat_id,
			schedule_index=schedule_index_offset + idx,
		)
		for idx, (paper_condition, experiment_id, repeat_id) in enumerate(jobs)
	]


def build_randomized_full_eval_schedule(
	*,
	task_ids: tuple[str, ...] | list[str] = DEFAULT_MAIN_TASK_IDS,
	reps_per_condition: int = DEFAULT_REPS_PER_CONDITION,
	seed: int = DEFAULT_SCHEDULE_SEED,
) -> list[ScheduledRun]:
	"""Build the full paper matrix with independent shuffles per task block."""
	schedule: list[ScheduledRun] = []
	offset = 0
	for task_id in task_ids:
		block = build_randomized_task_schedule(
			task_id=task_id,
			reps_per_condition=reps_per_condition,
			seed=seed,
			schedule_index_offset=offset,
		)
		schedule.extend(block)
		offset += len(block)
	return schedule


def condition_order_for_task(*, task_id: str, seed: int = DEFAULT_SCHEDULE_SEED) -> list[str]:
	"""First occurrence order of paper conditions in the shuffled block (for manifests)."""
	seen: list[str] = []
	for run in build_randomized_task_schedule(task_id=task_id, seed=seed):
		if run.paper_condition not in seen:
			seen.append(run.paper_condition)
	return seen


def is_fixed_paper_condition_order(order: list[str]) -> bool:
	return list(order) == list(PAPER_CONDITION_ORDER)


def run_flags_for_paper_condition(paper_condition: str):
	flags = PAPER_EXPERIMENT_RUN_FLAGS[PAPER_EXPERIMENT_ID_BY_CONDITION[paper_condition]]
	assert flags.paper_condition == paper_condition
	return flags


def _task_seed(*, seed: int, task_id: str) -> int:
	import hashlib

	digest = hashlib.sha256(f'{seed}:{task_id}'.encode()).digest()
	return int.from_bytes(digest[:4], 'big')
