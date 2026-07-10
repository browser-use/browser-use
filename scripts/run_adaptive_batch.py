#!/usr/bin/env python3
"""R-A adaptive navigator pilot / batch (event-triggered replanning).

Pilot (default): 4 tasks × 2 reps = 8 runs — verify trigger logs before full batch.
Full batch: pass --full for 4 tasks × 6 reps.
Append pilot: pass --append-pilot to add more reps per task into agent_runs_adaptive_pilot.json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
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

from browser_use.experiments.daily_task_eval.adaptive_replan import default_adaptive_replan_settings
from browser_use.experiments.daily_task_eval.experiment_presets import (
	PAPER_CONDITION_ADAPTIVE,
	PAPER_EXPERIMENT_CA,
	deepseek_navigator_config,
	doubao_executor_config,
)
from browser_use.experiments.daily_task_eval.models import TaskCard, load_json_model_list, write_json
from browser_use.experiments.daily_task_eval.navigator import build_navigator
from browser_use.experiments.daily_task_eval.runner import run_agent_task

OUTPUT_DIR = REPO_ROOT / 'tmp' / 'daily_task_eval'
TASK_CARDS_PATH = OUTPUT_DIR / 'task_cards.json'
CSV_DIR = OUTPUT_DIR / 'csv_out'
PILOT_JSON_PATH = OUTPUT_DIR / 'agent_runs_adaptive_pilot.json'
FULL_JSON_PATH = OUTPUT_DIR / 'agent_runs_adaptive.json'

MAIN_TASKS = [
	'shopping_price_compare',
	'nearby_hospital_phone_lookup',
	'github_clean_issue_audit',
	'huggingface_model_constrained_selection',
]

EXECUTOR_CONFIG = doubao_executor_config()
NAVIGATOR_CONFIG = deepseek_navigator_config()
ADAPTIVE_SETTINGS = default_adaptive_replan_settings()

COMMON_KWARGS = dict(
	max_steps=35,
	max_failures=3,
	headless=False,
	llm_timeout=120,
	step_timeout=150,
	heartbeat_seconds=30,
	max_actions_per_step=1,
)


def make_batch_id(*, pilot: bool) -> str:
	ts = datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
	return f'adaptive-{"pilot" if pilot else "full"}-{ts}'


async def run_one(task: TaskCard, rep: int, batch_id: str) -> dict:
	navigator = build_navigator(NAVIGATOR_CONFIG)

	summary = await run_agent_task(
		task=task,
		output_dir=OUTPUT_DIR,
		scenario_id='normal',
		executor_config=EXECUTOR_CONFIG,
		navigator=navigator,
		navigator_config=NAVIGATOR_CONFIG,
		continuous_navigation=True,
		replan_policy='event_triggered',
		adaptive_replan_settings=ADAPTIVE_SETTINGS,
		experiment_id=PAPER_EXPERIMENT_CA,
		batch_id=batch_id,
		csv_dir=CSV_DIR,
		run_manifest_extra={
			'condition_id': PAPER_CONDITION_ADAPTIVE,
			'paper_condition': PAPER_CONDITION_ADAPTIVE,
			'repeat_id': rep,
			'replan_policy': 'event_triggered',
			'adaptive_replan': True,
		},
		**COMMON_KWARGS,
	)

	return summary.model_dump(mode='json')


def _print_adaptive_audit(summary: dict) -> None:
	metrics = summary.get('adaptive_replan_metrics') or {}
	events = metrics.get('trigger_events') or []
	if not events:
		print('    adaptive: 0 replans (opening plan only)')
		return
	for ev in events:
		print(f"    adaptive: step={ev.get('step')} type={ev.get('trigger_type')} reason={ev.get('trigger_reason')}")


def _repeat_id_from_summary(row: dict) -> int | None:
	manifest = row.get('run_manifest') if isinstance(row.get('run_manifest'), dict) else {}
	value = row.get('repeat_id', manifest.get('repeat_id'))
	return int(value) if value is not None else None


def _load_pilot_summaries() -> list[dict]:
	if not PILOT_JSON_PATH.exists():
		return []
	return json.loads(PILOT_JSON_PATH.read_text(encoding='utf-8'))


def _max_repeat_id_by_task(existing: list[dict]) -> dict[str, int]:
	out: dict[str, int] = {}
	for row in existing:
		task_id = row.get('task_id')
		rep = _repeat_id_from_summary(row)
		if not task_id or rep is None:
			continue
		out[task_id] = max(out.get(task_id, 0), rep)
	return out


def _merge_pilot_summaries(existing: list[dict], new_rows: list[dict]) -> list[dict]:
	by_key: dict[tuple[str, int], dict] = {}
	for row in existing + new_rows:
		task_id = row.get('task_id')
		rep = _repeat_id_from_summary(row)
		if not task_id or rep is None:
			continue
		by_key[(task_id, rep)] = row
	order = {tid: i for i, tid in enumerate(MAIN_TASKS)}
	return sorted(by_key.values(), key=lambda r: (order.get(r.get('task_id', ''), 99), _repeat_id_from_summary(r) or 0))


async def main() -> None:
	parser = argparse.ArgumentParser(description='R-A adaptive navigator batch runner')
	parser.add_argument('--full', action='store_true', help='Full batch: 6 reps/task (default pilot: 2 reps/task)')
	parser.add_argument(
		'--append-pilot',
		action='store_true',
		help='Append new reps to agent_runs_adaptive_pilot.json (does not overwrite agent_runs_adaptive.json)',
	)
	parser.add_argument(
		'--extra-reps',
		type=int,
		default=2,
		help='When --append-pilot: new repetitions per task (default 2 → rep 3–4 if pilot already has 1–2)',
	)
	args = parser.parse_args()

	if args.full and args.append_pilot:
		print('❌ Use either --full or --append-pilot, not both.')
		return
	if args.extra_reps < 1:
		print('❌ --extra-reps must be >= 1')
		return

	load_dotenv()
	for env_var in ['ARK_API_KEY', 'DEEPSEEK_API_KEY']:
		if not os.getenv(env_var):
			print(f'❌ {env_var} is not set. Aborting.')
			return

	all_cards = load_json_model_list(TASK_CARDS_PATH, TaskCard)
	task_cards = {t.id: t for t in all_cards if t.id in MAIN_TASKS}
	missing = set(MAIN_TASKS) - set(task_cards.keys())
	if missing:
		print(f'❌ Missing task cards: {missing}')
		return

	existing_pilot = _load_pilot_summaries() if args.append_pilot else []
	max_rep_by_task = _max_repeat_id_by_task(existing_pilot)

	if args.append_pilot:
		n_reps = args.extra_reps
		rep_ranges = {
			task_id: range(max_rep_by_task.get(task_id, 0) + 1, max_rep_by_task.get(task_id, 0) + n_reps + 1)
			for task_id in MAIN_TASKS
		}
		total = sum(len(rep_ranges[tid]) for tid in MAIN_TASKS)
	else:
		n_reps = 6 if args.full else 2
		rep_ranges = {task_id: range(1, n_reps + 1) for task_id in MAIN_TASKS}
		total = len(MAIN_TASKS) * n_reps

	batch_id = make_batch_id(pilot=not args.full)
	print(f'\n🔬 R-A adaptive batch: {batch_id}')
	if args.append_pilot:
		print(f'   Mode: append pilot → {PILOT_JSON_PATH.name}')
		print(f'   Existing pilot runs: {len(existing_pilot)}')
		for tid in MAIN_TASKS:
			start = min(rep_ranges[tid]) if rep_ranges[tid] else '?'
			end = max(rep_ranges[tid]) if rep_ranges[tid] else '?'
			print(f'   {tid}: reps {start}–{end}')
	else:
		print(f'   Reps per task: {n_reps}')
	print(f'   Policy: event_triggered (phase + recovery, max 2/run)')
	print(f'   Navigator: {NAVIGATOR_CONFIG.model} | Executor: {EXECUTOR_CONFIG.model}')
	print(f'   New runs this session: {total}\n')

	all_summaries: list[dict] = []
	run_idx = 0

	for task_id in MAIN_TASKS:
		task = task_cards[task_id]
		print(f'── {task_id} ──')
		for rep in rep_ranges[task_id]:
			run_idx += 1
			label = f'{task_id} rep={rep} [{run_idx}/{total}]'
			print(f'  {label} ...', end=' ', flush=True)
			try:
				summary = await run_one(task, rep, batch_id)
				status = '✅' if summary.get('strict_success') else '⚠️'
				outcome = summary.get('adjudicated_outcome_label', '?')
				steps = summary.get('number_of_steps', '?')
				dur = summary.get('duration_seconds', 0)
				replans = (summary.get('adaptive_replan_metrics') or {}).get('total_adaptive_replans', 0)
				print(f'{status} {outcome} steps={steps} replans={replans} dur={dur:.0f}s')
				_print_adaptive_audit(summary)
				all_summaries.append(summary)
			except Exception as exc:
				print(f'❌ ERROR: {exc}')
				all_summaries.append(
					{
						'task_id': task_id,
						'experiment_id': PAPER_EXPERIMENT_CA,
						'paper_condition': PAPER_CONDITION_ADAPTIVE,
						'repeat_id': rep,
						'error': str(exc),
					}
				)

	if args.append_pilot:
		merged = _merge_pilot_summaries(existing_pilot, all_summaries)
		write_json(PILOT_JSON_PATH, merged)
		out_path = PILOT_JSON_PATH
		print(f'\n📦 Pilot total: {len(merged)} runs ({len(existing_pilot)} existing + {len(all_summaries)} new)')
	else:
		out_path = FULL_JSON_PATH
		write_json(out_path, all_summaries)

	activated = sum(1 for s in all_summaries if (s.get('adaptive_replan_metrics') or {}).get('had_adaptive_replan'))
	completed = [s for s in all_summaries if s.get('history_path')]
	print(f'\n📊 adaptive_activation_rate (this session): {activated}/{len(completed)}')
	if completed:
		mean_replans = sum((s.get('adaptive_replan_metrics') or {}).get('total_adaptive_replans', 0) for s in completed) / len(
			completed
		)
		zero_rate = sum(
			1 for s in completed if (s.get('adaptive_replan_metrics') or {}).get('total_adaptive_replans', 0) == 0
		) / len(completed)
		print(f'   mean_replans_per_run: {mean_replans:.2f}')
		print(f'   zero_trigger_rate: {zero_rate:.2%}')

	print(f'\n📦 Saved session summaries → {out_path}')
	print('✅ Batch complete.')


if __name__ == '__main__':
	asyncio.run(main())
