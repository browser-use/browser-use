#!/usr/bin/env python3
"""Rebuild R-A pilot summaries from disk + exp-CA_runs.csv.

The pilot batch (adaptive-pilot-20260627T084348Z, 8 runs) was overwritten in
agent_runs_adaptive.json when --full ran. This script re-exports it to
agent_runs_adaptive_pilot.json.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from browser_use.experiments.daily_task_eval.adaptive_replan import (
	AdaptiveReplanController,
	default_adaptive_replan_settings,
)
from browser_use.experiments.daily_task_eval.experiment_presets import (
	PAPER_CONDITION_ADAPTIVE,
	PAPER_EXPERIMENT_CA,
)
from browser_use.experiments.daily_task_eval.models import TaskCard, load_json_model_list, write_json
from browser_use.experiments.daily_task_eval.run_csv import agent_run_summary_from_csv_row
from browser_use.experiments.daily_task_eval.runner import adjudicate_agent_summary

OUTPUT_DIR = REPO_ROOT / 'tmp' / 'daily_task_eval'
TASK_CARDS_PATH = OUTPUT_DIR / 'task_cards.json'
CSV_PATH = OUTPUT_DIR / 'csv_out' / 'exp-CA_runs.csv'
OUT_PATH = OUTPUT_DIR / 'agent_runs_adaptive_pilot.json'

PILOT_BATCH_ID = 'adaptive-pilot-20260627T084348Z'
# First full-batch run started at 09:42:05 UTC; pilot rows are strictly before this.
FULL_BATCH_CUTOFF = '2026-06-27T09:42:05'
PILOT_EARLIEST = '2026-06-27T08:44:00'

MAIN_TASKS = [
	'shopping_price_compare',
	'nearby_hospital_phone_lookup',
	'github_clean_issue_audit',
	'huggingface_model_constrained_selection',
]


def _parse_history_loose(history_path: Path) -> dict:
	data = json.loads(history_path.read_text(encoding='utf-8'))
	steps = data.get('history') if isinstance(data.get('history'), list) else []
	urls: list[str] = []
	action_names: list[str] = []
	errors: list[str] = []
	final_result: str | None = None
	is_done = False
	success: bool | None = None

	for step in steps:
		if not isinstance(step, dict):
			continue
		state = step.get('state') if isinstance(step.get('state'), dict) else {}
		url = state.get('url')
		if isinstance(url, str) and url:
			urls.append(url)
		model_output = step.get('model_output') if isinstance(step.get('model_output'), dict) else {}
		for action in model_output.get('action') or []:
			if isinstance(action, dict) and action:
				action_names.append(next(iter(action.keys())))
				if 'done' in action and isinstance(action['done'], dict):
					done_text = action['done'].get('text')
					if isinstance(done_text, str) and done_text.strip():
						final_result = done_text.strip()
		for result in step.get('result') or []:
			if not isinstance(result, dict):
				continue
			if result.get('error'):
				errors.append(str(result['error']))
			if result.get('is_done') is True:
				is_done = True
				if result.get('success') is not None:
					success = bool(result['success'])
				for key in ('extracted_content', 'long_term_memory'):
					val = result.get(key)
					if isinstance(val, str) and val.strip() and 'Task completed:' not in val[:40]:
						final_result = val.strip()

	return {
		'steps': steps,
		'urls': urls,
		'action_names': action_names,
		'errors': errors,
		'final_result': final_result,
		'is_done': is_done,
		'success': success,
		'number_of_steps': len(steps),
	}


def _enrich_from_history(summary, history_path: Path):
	parsed = _parse_history_loose(history_path)
	updates: dict = {
		'urls': parsed['urls'] or summary.urls,
		'action_names': parsed['action_names'] or summary.action_names,
		'errors': parsed['errors'] or summary.errors,
		'final_result': parsed['final_result'] or summary.final_result,
		'is_done': parsed['is_done'] or summary.is_done,
		'number_of_steps': parsed['number_of_steps'] or summary.number_of_steps,
	}
	if parsed['success'] is not None:
		updates['success'] = parsed['success']
		updates['agent_declared_success'] = parsed['success']
	return summary.model_copy(update=updates), parsed['steps']


def _usage_from_csv_row(row: dict) -> dict:
	ex = int(float(row.get('tokens_executor') or 0))
	nav = int(float(row.get('tokens_navigator') or 0))
	cost = float(row.get('total_cost') or 0)
	out: dict = {}
	if ex or nav:
		out['usage_summary'] = {
			'total_tokens': ex + nav,
			'total_cost': cost,
			'by_model': {},
		}
		if ex:
			out['usage_executor_llm'] = {
				'model': row.get('executor_model') or 'doubao-seed-2-0-pro-260215',
				'total_tokens': ex,
				'cost': cost,
			}
	if nav:
		# CSV stores combined navigator tokens; attribute to initial plan for legacy round-trip.
		out['navigator_initial_plan_usage'] = {'total_tokens': nav}
	return out


def _replay_adaptive_metrics(*, task_id: str, steps: list[dict], run_dir: Path) -> dict:
	plan_path = run_dir / 'navigator_plan.md'
	initial_plan = plan_path.read_text(encoding='utf-8') if plan_path.exists() else ''
	settings = default_adaptive_replan_settings()
	ctrl = AdaptiveReplanController(task_id=task_id, initial_plan=initial_plan, settings=settings)

	for idx, step in enumerate(steps, start=1):
		if idx > 1:
			should, trigger_type, reason = ctrl.evaluate_before_step(current_step=idx, agent_done=False)
			if should and trigger_type is not None:
				ctrl.record_replan(step=idx, trigger_type=trigger_type, trigger_reason=reason)

		state = step.get('state') if isinstance(step.get('state'), dict) else {}
		model_output = step.get('model_output')
		results = step.get('result') if isinstance(step.get('result'), list) else []
		ctrl.observe_completed_step(
			step=idx,
			model_output=model_output,
			results=results,
			url=state.get('url') if isinstance(state.get('url'), str) else None,
			page_title=state.get('title') if isinstance(state.get('title'), str) else None,
			dom_snippet=step.get('state_message') if isinstance(step.get('state_message'), str) else None,
			state_message=step.get('state_message') if isinstance(step.get('state_message'), str) else None,
		)

	return ctrl.finalize_metrics().model_dump(mode='json')


def _load_pilot_csv_rows() -> list[dict]:
	with CSV_PATH.open(encoding='utf-8-sig', newline='') as f:
		rows = list(csv.DictReader(f))
	pilot = [
		r
		for r in rows
		if r.get('started_at', '') >= PILOT_EARLIEST and r.get('started_at', '') < FULL_BATCH_CUTOFF
	]
	pilot.sort(key=lambda r: r.get('started_at', ''))
	return pilot


def export_pilot(*, out_path: Path = OUT_PATH) -> list[dict]:
	assert CSV_PATH.exists(), f'Missing {CSV_PATH}'
	task_cards = {t.id: t for t in load_json_model_list(TASK_CARDS_PATH, TaskCard)}
	pilot_rows = _load_pilot_csv_rows()
	if len(pilot_rows) != 8:
		raise RuntimeError(f'Expected 8 pilot CSV rows, found {len(pilot_rows)}')

	rep_counters: dict[str, int] = defaultdict(int)
	summaries: list[dict] = []

	for row in pilot_rows:
		task_id = row['task_id']
		task = task_cards[task_id]
		rep_counters[task_id] += 1
		repeat_id = rep_counters[task_id]

		history_path = Path(row['history_path'])
		run_dir = history_path.parent
		assert history_path.exists(), f'Missing history: {history_path}'

		summary = agent_run_summary_from_csv_row(row)
		summary = summary.model_copy(
			update={
				'experiment_id': PAPER_EXPERIMENT_CA,
				'batch_id': PILOT_BATCH_ID,
				'continuous_navigation': True,
				'navigator_enabled': True,
				'navigator_model': row.get('navigator_model') or 'deepseek-chat',
				'navigator_plan_path': str(run_dir / 'navigator_plan.md') if (run_dir / 'navigator_plan.md').exists() else None,
				'conversation_path': str(run_dir / 'conversation.json') if (run_dir / 'conversation.json').exists() else row.get('conversation_path'),
				**_usage_from_csv_row(row),
			}
		)
		summary, steps = _enrich_from_history(summary, history_path)
		summary = adjudicate_agent_summary(task, summary)

		metrics = _replay_adaptive_metrics(task_id=task_id, steps=steps, run_dir=run_dir)
		summary = summary.model_copy(
			update={
				'replan_policy': 'event_triggered',
				'adaptive_replan_metrics': metrics,
			}
		)

		manifest = {
			'batch_id': PILOT_BATCH_ID,
			'task_id': task_id,
			'scenario_id': 'normal',
			'experiment_id': PAPER_EXPERIMENT_CA,
			'condition_id': PAPER_CONDITION_ADAPTIVE,
			'paper_condition': PAPER_CONDITION_ADAPTIVE,
			'repeat_id': repeat_id,
			'replan_policy': 'event_triggered',
			'adaptive_replan': True,
			'adaptive_replan_settings': default_adaptive_replan_settings().model_dump(mode='json'),
			'started_at_utc': row.get('started_at'),
		}
		out = summary.model_dump(mode='json')
		out['run_manifest'] = manifest
		summaries.append(out)

	# Stable task order then repeat_id
	order = {tid: i for i, tid in enumerate(MAIN_TASKS)}
	summaries.sort(key=lambda r: (order.get(r['task_id'], 99), r['run_manifest']['repeat_id']))

	write_json(out_path, summaries)
	return summaries


def main() -> None:
	summaries = export_pilot()
	strict_ok = sum(1 for s in summaries if s.get('strict_success'))
	print(f'Wrote {len(summaries)} pilot runs → {OUT_PATH}')
	print(f'strict_success: {strict_ok}/{len(summaries)}')
	for s in summaries:
		m = s.get('adaptive_replan_metrics') or {}
		print(
			f"  {s['task_id'][:20]:20} rep={s['run_manifest']['repeat_id']} "
			f"strict={s.get('strict_success')} replans={m.get('total_adaptive_replans', 0)}"
		)


if __name__ == '__main__':
	main()
