#!/usr/bin/env python3
"""Collect up to 6 cadence runs per task×interval from disk into one JSON manifest."""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from browser_use.experiments.daily_task_eval.models import AgentRunSummary, TaskCard, load_json_model_list, write_json
from browser_use.experiments.daily_task_eval.run_csv import agent_run_summary_from_csv_row
from browser_use.experiments.daily_task_eval.runner import adjudicate_agent_summary, _stable_sha256

OUTPUT_DIR = REPO_ROOT / 'tmp' / 'daily_task_eval'
TASK_CARDS_PATH = OUTPUT_DIR / 'task_cards.json'
AGENT_RUNS_ROOT = OUTPUT_DIR / 'agent_runs'
OLD_CADENCE_PATH = OUTPUT_DIR / 'agent_runs_planning_cadence.json'  # output only
TAIL5_PATH = OUTPUT_DIR / 'agent_runs_planning_cadence_tail5.json'
OUT_PATH = OUTPUT_DIR / 'agent_runs_planning_cadence.json'

TASKS = [
	'shopping_price_compare',
	'nearby_hospital_phone_lookup',
	'github_clean_issue_audit',
	'huggingface_model_constrained_selection',
]
INTERVALS = {'C1': 1, 'C3': 3, 'C5': 5}
N_REPS = 6

CADENCE_DEFAULTS = {
	'executor_backend': 'openai_compatible',
	'executor_model': 'doubao-seed-2-0-pro-260215',
	'navigator_backend': 'deepseek',
	'navigator_model': 'deepseek-chat',
	'executor_temperature': 0.0,
	'executor_use_vision': False,
	'navigator_temperature': 0.0,
	'max_steps': 35,
	'max_failures': 3,
	'llm_timeout': 120,
	'step_timeout': 150,
	'max_actions_per_step': 1,
	'heartbeat_seconds': 30,
	'headless': False,
	'browser_profile_mode': 'ephemeral_incognito',
	'browser_viewport': {'width': 1280, 'height': 720},
}


def _norm_path(p: str | Path) -> str:
	return str(Path(p).resolve()).lower()


def _load_json_summaries() -> dict[str, dict]:
	"""Prefer rich JSON summaries only from tail5 (full agent summaries)."""
	return _load_json_path(TAIL5_PATH)


def _load_json_path(path: Path) -> dict[str, dict]:
	if not path.exists():
		return {}
	rows = json.loads(path.read_text(encoding='utf-8'))
	out: dict[str, dict] = {}
	for r in rows:
		hp = r.get('history_path')
		if hp:
			row = dict(r)
			row.pop('repeat_id', None)
			out[_norm_path(hp)] = row
	return out


def _load_csv_index() -> dict[str, dict]:
	index: dict[str, dict] = {}
	csv_dir = OUTPUT_DIR / 'csv_out'
	for path in sorted(csv_dir.glob('exp-C*_runs.csv')):
		with path.open(encoding='utf-8', newline='') as f:
			for row in csv.DictReader(f):
				hp = row.get('history_path', '')
				if hp:
					index[_norm_path(hp)] = row
	return index


def _interval_from_exp(experiment_id: str) -> int:
	return INTERVALS[experiment_id]


def _parse_history_loose(history_path: Path) -> dict:
	"""Parse eval history.json without strict AgentOutput validation."""
	data = json.loads(history_path.read_text(encoding='utf-8'))
	steps = data.get('history') if isinstance(data.get('history'), list) else []
	urls: list[str] = []
	action_names: list[str] = []
	errors: list[str] = []
	final_result: str | None = None
	is_done = False
	success: bool | None = None
	start_ts: float | None = None
	end_ts: float | None = None

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
		meta = step.get('metadata') if isinstance(step.get('metadata'), dict) else {}
		if isinstance(meta.get('step_start_time'), (int, float)):
			start_ts = float(meta['step_start_time']) if start_ts is None else start_ts
		if isinstance(meta.get('step_end_time'), (int, float)):
			end_ts = float(meta['step_end_time'])
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

	duration = max(0.0, end_ts - start_ts) if start_ts is not None and end_ts is not None else 0.0
	return {
		'urls': urls,
		'action_names': action_names,
		'errors': errors,
		'final_result': final_result,
		'is_done': is_done,
		'success': success,
		'number_of_steps': len(steps),
		'duration_seconds': duration,
	}


def _enrich_summary_from_history(summary: AgentRunSummary, history_path: Path) -> AgentRunSummary:
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
	if parsed['duration_seconds'] > 0 and (summary.duration_seconds or 0) <= 0:
		updates['duration_seconds'] = parsed['duration_seconds']
	return summary.model_copy(update=updates)


def _build_manifest(*, task: TaskCard, experiment_id: str, repeat_id: int, ts: str) -> dict:
	interval = _interval_from_exp(experiment_id)
	manifest = {
		'batch_id': f'cadence-{ts}',
		'task_id': task.id,
		'scenario_id': 'normal',
		'experiment_id': experiment_id,
		'task_card_hash': _stable_sha256(task.model_dump(mode='json')),
		'continuous_navigation': True,
		'navigator_replan_interval': interval,
		'planning_cadence_interval': interval,
		'condition_id': f'C_interval_{interval}',
		'repeat_id': repeat_id,
		'started_at_utc': ts,
		**CADENCE_DEFAULTS,
	}
	return manifest


def _summary_from_csv_and_history(
	*,
	history_path: Path,
	task: TaskCard,
	experiment_id: str,
	repeat_id: int,
	ts: str,
	csv_index: dict[str, dict],
) -> dict:
	key = _norm_path(history_path)
	csv_row = csv_index.get(key, {})
	if csv_row:
		summary = agent_run_summary_from_csv_row(csv_row)
	else:
		summary = AgentRunSummary(
			task_id=task.id,
			scenario_id='normal',
			task_category=task.category,
			experiment_id=experiment_id,
			started_at=ts,
			finished_at=ts,
			success=None,
			is_done=False,
			duration_seconds=0.0,
			number_of_steps=0,
			history_path=str(history_path),
		)
	summary = _enrich_summary_from_history(summary, history_path)
	manifest = _build_manifest(task=task, experiment_id=experiment_id, repeat_id=repeat_id, ts=ts)
	summary = adjudicate_agent_summary(task, summary)
	out = summary.model_dump(mode='json')
	out['run_manifest'] = manifest
	out['continuous_navigation'] = True
	out['navigator_enabled'] = True
	return out


def _summary_for_run(
	*,
	history_path: Path,
	task: TaskCard,
	experiment_id: str,
	repeat_id: int,
	ts: str,
	json_index: dict[str, dict],
	csv_index: dict[str, dict],
) -> dict:
	key = _norm_path(history_path)
	if key in json_index:
		row = dict(json_index[key])
		row.pop('repeat_id', None)
		manifest = dict(row.get('run_manifest') or {})
		manifest['repeat_id'] = repeat_id
		row['run_manifest'] = manifest
		return row

	return _summary_from_csv_and_history(
		history_path=Path(history_path),
		task=task,
		experiment_id=experiment_id,
		repeat_id=repeat_id,
		ts=ts,
		csv_index=csv_index,
	)


def main() -> None:
	task_cards = {t.id: t for t in load_json_model_list(TASK_CARDS_PATH, TaskCard)}
	json_index = _load_json_summaries()
	csv_index = _load_csv_index()

	all_summaries: list[dict] = []
	for task_id in TASKS:
		task = task_cards[task_id]
		for experiment_id in ('C1', 'C3', 'C5'):
			exp_dir = AGENT_RUNS_ROOT / task_id / 'normal' / f'exp-{experiment_id}'
			if not exp_dir.exists():
				continue
			run_dirs = sorted(
				[d for d in exp_dir.iterdir() if d.is_dir() and (d / 'history.json').exists()],
				key=lambda d: d.name,
			)
			if len(run_dirs) < N_REPS:
				print(f'WARNING: {task_id} {experiment_id} has {len(run_dirs)} runs (expected {N_REPS})')
			selected = run_dirs[:N_REPS]
			for repeat_id, run_dir in enumerate(selected, start=1):
				history_path = run_dir / 'history.json'
				ts = run_dir.name
				summary = _summary_for_run(
					history_path=history_path,
					task=task,
					experiment_id=experiment_id,
					repeat_id=repeat_id,
					ts=ts,
					json_index=json_index,
					csv_index=csv_index,
				)
				all_summaries.append(summary)

	# Strip non-schema fields before persisting.
	for row in all_summaries:
		row.pop('repeat_id', None)

	assert len(all_summaries) == len(TASKS) * len(INTERVALS) * N_REPS, (
		f'expected {len(TASKS) * len(INTERVALS) * N_REPS} runs, got {len(all_summaries)}'
	)

	write_json(OUT_PATH, all_summaries)
	print(f'Wrote {len(all_summaries)} cadence summaries -> {OUT_PATH}')


if __name__ == '__main__':
	main()
