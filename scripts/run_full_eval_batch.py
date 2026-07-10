#!/usr/bin/env python3
"""Full paper matrix: 4 tasks × 6 conditions × n reps with randomized condition order.

Within each task block, E / I / R-1 / R-3 / R-5 / R-A runs are shuffled (not executed
in fixed preset order), matching the PRICAI 2026 protocol. Runs remain sequential.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
if hasattr(sys.stdout, 'reconfigure'):
	sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
	sys.stderr.reconfigure(encoding='utf-8')

from dotenv import load_dotenv

from browser_use.experiments.daily_task_eval.batch_schedule import (
	DEFAULT_MAIN_TASK_IDS,
	DEFAULT_REPS_PER_CONDITION,
	DEFAULT_SCHEDULE_SEED,
	PAPER_CONDITION_ORDER,
	ScheduledRun,
	build_randomized_full_eval_schedule,
	condition_order_for_task,
	is_fixed_paper_condition_order,
	run_flags_for_paper_condition,
)
from browser_use.experiments.daily_task_eval.experiment_presets import (
	DailyExperimentId,
	experiment_preset,
	paper_experiment_preset,
)
from browser_use.experiments.daily_task_eval.models import TaskCard, load_json_model_list, write_json
from browser_use.experiments.daily_task_eval.navigator import build_navigator
from browser_use.experiments.daily_task_eval.runner import run_agent_task

OUTPUT_DIR = REPO_ROOT / 'tmp' / 'daily_task_eval'
TASK_CARDS_PATH = OUTPUT_DIR / 'task_cards.json'
CSV_DIR = OUTPUT_DIR / 'csv_out'

COMMON_KWARGS = dict(
	max_steps=35,
	max_failures=3,
	headless=False,
	llm_timeout=120,
	step_timeout=150,
	heartbeat_seconds=30,
	max_actions_per_step=1,
)


def make_batch_id() -> str:
	ts = datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
	return f'full-eval-{ts}'


async def run_scheduled(
	task: TaskCard,
	scheduled: ScheduledRun,
	batch_id: str,
	*,
	schedule_seed: int,
) -> dict:
	flags = run_flags_for_paper_condition(scheduled.paper_condition)
	if scheduled.experiment_id in ('C', 'D'):
		executor_cfg, nav_cfg = experiment_preset(DailyExperimentId(scheduled.experiment_id))
	else:
		executor_cfg, nav_cfg = paper_experiment_preset(scheduled.experiment_id)
	navigator = build_navigator(nav_cfg)

	summary = await run_agent_task(
		task=task,
		output_dir=OUTPUT_DIR,
		scenario_id='normal',
		executor_config=executor_cfg,
		navigator=navigator,
		navigator_config=nav_cfg,
		continuous_navigation=flags.continuous_navigation,
		navigator_replan_interval=flags.navigator_replan_interval,
		replan_policy=flags.replan_policy,
		adaptive_replan_settings=flags.adaptive_replan_settings,
		experiment_id=scheduled.experiment_id,
		batch_id=batch_id,
		csv_dir=CSV_DIR,
		run_manifest_extra={
			'paper_condition': scheduled.paper_condition,
			'repeat_id': scheduled.repeat_id,
			'schedule_index': scheduled.schedule_index,
			'schedule_seed': schedule_seed,
			'condition_order_mode': 'randomized_within_task',
			'fixed_condition_order': list(PAPER_CONDITION_ORDER),
			'actual_condition_order': condition_order_for_task(task_id=scheduled.task_id, seed=schedule_seed),
		},
		**COMMON_KWARGS,
	)

	return summary.model_dump(mode='json')


async def main() -> None:
	parser = argparse.ArgumentParser(description='Full paper eval batch with randomized condition order per task')
	parser.add_argument('--reps', type=int, default=DEFAULT_REPS_PER_CONDITION, help='Repetitions per task×condition cell')
	parser.add_argument('--seed', type=int, default=DEFAULT_SCHEDULE_SEED, help='Shuffle seed (deterministic per task block)')
	parser.add_argument('--dry-run', action='store_true', help='Print schedule only')
	parser.add_argument('--task-id', action='append', dest='task_ids', help='Restrict to task id (repeatable)')
	args = parser.parse_args()

	if args.reps < 1:
		print('❌ --reps must be >= 1')
		return

	load_dotenv()
	for env_var in ['ARK_API_KEY', 'DEEPSEEK_API_KEY']:
		if not os.getenv(env_var):
			print(f'❌ {env_var} is not set. Aborting.')
			return

	task_ids = tuple(args.task_ids) if args.task_ids else DEFAULT_MAIN_TASK_IDS
	schedule = build_randomized_full_eval_schedule(
		task_ids=task_ids,
		reps_per_condition=args.reps,
		seed=args.seed,
	)

	all_cards = load_json_model_list(TASK_CARDS_PATH, TaskCard)
	task_cards = {t.id: t for t in all_cards if t.id in task_ids}
	missing = set(task_ids) - set(task_cards.keys())
	if missing:
		print(f'❌ Missing task cards: {missing}')
		return

	batch_id = make_batch_id()
	print(f'\n🔬 Full eval batch: {batch_id}')
	print(f'   Tasks: {len(task_ids)} | Conditions: 6 | Reps/cell: {args.reps} | Total: {len(schedule)}')
	print(f'   Condition order: randomized within each task block (seed={args.seed})')
	for task_id in task_ids:
		order = condition_order_for_task(task_id=task_id, seed=args.seed)
		fixed = is_fixed_paper_condition_order(order)
		print(f'   {task_id}: first-seen order = {" → ".join(order)} {"[FIXED — check seed]" if fixed else ""}')

	if args.dry_run:
		print('\n[dry-run schedule]')
		for run in schedule:
			print(
				f'  #{run.schedule_index:3d} {run.task_id} '
				f'{run.paper_condition}({run.experiment_id}) rep={run.repeat_id}'
			)
		return

	manifest = {
		'batch_id': batch_id,
		'started_at_utc': datetime.now(UTC).isoformat(),
		'execution_mode': 'sequential_runs_randomized_condition_order',
		'schedule_seed': args.seed,
		'reps_per_condition': args.reps,
		'task_ids': list(task_ids),
		'fixed_condition_order': list(PAPER_CONDITION_ORDER),
		'condition_order_by_task': {
			task_id: condition_order_for_task(task_id=task_id, seed=args.seed) for task_id in task_ids
		},
		'schedule': [
			{
				'schedule_index': run.schedule_index,
				'task_id': run.task_id,
				'paper_condition': run.paper_condition,
				'experiment_id': run.experiment_id,
				'repeat_id': run.repeat_id,
			}
			for run in schedule
		],
	}
	manifest_dir = OUTPUT_DIR / 'batch_manifests'
	manifest_dir.mkdir(parents=True, exist_ok=True)
	write_json(manifest_dir / f'{batch_id}.json', manifest)

	all_summaries: list[dict] = []
	for idx, scheduled in enumerate(schedule, start=1):
		task = task_cards[scheduled.task_id]
		label = (
			f'{scheduled.task_id} {scheduled.paper_condition} '
			f'rep={scheduled.repeat_id} [{idx}/{len(schedule)}]'
		)
		print(f'  {label} ...', end=' ', flush=True)
		try:
			summary = await run_scheduled(task, scheduled, batch_id, schedule_seed=args.seed)
			status = '✅' if summary.get('strict_success') else '⚠️'
			outcome = summary.get('adjudicated_outcome_label', '?')
			steps = summary.get('number_of_steps', '?')
			dur = summary.get('duration_seconds', 0)
			print(f'{status} {outcome} steps={steps} dur={dur:.0f}s')
			all_summaries.append(summary)
		except Exception as exc:
			print(f'❌ ERROR: {exc}')
			all_summaries.append(
				{
					'task_id': scheduled.task_id,
					'experiment_id': scheduled.experiment_id,
					'paper_condition': scheduled.paper_condition,
					'repeat_id': scheduled.repeat_id,
					'error': str(exc),
				}
			)

	out_path = OUTPUT_DIR / 'agent_runs_full_eval.json'
	write_json(out_path, all_summaries)
	print(f'\n📦 Saved {len(all_summaries)} summaries → {out_path}')
	print(f'📋 Batch manifest → {manifest_dir / f"{batch_id}.json"}')
	print('✅ Batch complete.')


if __name__ == '__main__':
	asyncio.run(main())
