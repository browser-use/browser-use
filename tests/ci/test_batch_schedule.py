#!/usr/bin/env python3
"""Tests for randomized paper batch scheduling."""

from browser_use.experiments.daily_task_eval.batch_schedule import (
	DEFAULT_MAIN_TASK_IDS,
	PAPER_CONDITION_ORDER,
	build_randomized_full_eval_schedule,
	build_randomized_task_schedule,
	condition_order_for_task,
	is_fixed_paper_condition_order,
)


def test_randomized_schedule_covers_full_matrix():
	schedule = build_randomized_full_eval_schedule(reps_per_condition=2, seed=42)
	assert len(schedule) == len(DEFAULT_MAIN_TASK_IDS) * len(PAPER_CONDITION_ORDER) * 2

	for task_id in DEFAULT_MAIN_TASK_IDS:
		block = [run for run in schedule if run.task_id == task_id]
		assert len(block) == len(PAPER_CONDITION_ORDER) * 2
		for paper_condition in PAPER_CONDITION_ORDER:
			reps = [run for run in block if run.paper_condition == paper_condition]
			assert {run.repeat_id for run in reps} == {1, 2}


def test_randomized_schedule_is_reproducible():
	a = build_randomized_task_schedule(task_id='shopping_price_compare', seed=99)
	b = build_randomized_task_schedule(task_id='shopping_price_compare', seed=99)
	assert [(r.paper_condition, r.repeat_id) for r in a] == [(r.paper_condition, r.repeat_id) for r in b]


def test_randomized_schedule_differs_from_fixed_order_by_default():
	order = condition_order_for_task(task_id='nearby_hospital_phone_lookup', seed=42)
	# Seed 42 should not preserve canonical preset order for at least one task.
	assert not is_fixed_paper_condition_order(order)


def test_schedule_index_is_monotonic_within_full_eval():
	schedule = build_randomized_full_eval_schedule(reps_per_condition=1, seed=7)
	indices = [run.schedule_index for run in schedule]
	assert indices == list(range(len(schedule)))
