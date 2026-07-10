#!/usr/bin/env python3
"""Merge E/I (agent_runs.json) and R-* (agent_runs_planning_cadence.json) into one dataset.

Re-adjudicates complete runs with the current adjudicator, adds paper-friendly labels,
and writes comparison artifacts when outcomes change.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

from browser_use.experiments.daily_task_eval.models import (  # noqa: E402
	AgentRunSummary,
	HumanRunRecord,
	TaskCard,
	load_json_model_list,
	write_json,
)
from browser_use.experiments.daily_task_eval.reference_comparison import get_reference_human_runs  # noqa: E402
from browser_use.experiments.daily_task_eval.run_csv import (  # noqa: E402
	AGENT_RUN_CSV_HEADERS,
	build_agent_run_csv_row,
)
from browser_use.experiments.daily_task_eval.runner import adjudicate_agent_summary  # noqa: E402

DEFAULT_OUTPUT_DIR = REPO_ROOT / 'tmp' / 'daily_task_eval'
DEFAULT_TASK_CARDS = DEFAULT_OUTPUT_DIR / 'task_cards.json'
DEFAULT_AB_PATH = DEFAULT_OUTPUT_DIR / 'agent_runs.json'
DEFAULT_CADENCE_PATH = DEFAULT_OUTPUT_DIR / 'agent_runs_planning_cadence.json'
DEFAULT_ADAPTIVE_PATH = DEFAULT_OUTPUT_DIR / 'agent_runs_adaptive.json'
DEFAULT_ALL_RUNS_PATH = DEFAULT_OUTPUT_DIR / 'all_runs.json'
DEFAULT_DIFF_PATH = DEFAULT_OUTPUT_DIR / 'merge_adjudication_diff.json'

PAPER_CONDITION_ORDER = ['E', 'I', 'R-1', 'R-3', 'R-5', 'R-A']

_EXPERIMENT_TO_PAPER: dict[str, str] = {
	'C': 'E',
	'D': 'I',
	'C1': 'R-1',
	'C3': 'R-3',
	'C5': 'R-5',
	'CA': 'R-A',
}

_INTERVAL_FROM_PAPER: dict[str, int | None] = {
	'E': None,
	'I': None,
	'R-1': 1,
	'R-3': 3,
	'R-5': 5,
	'R-A': None,
}

_SUMMARY_CSV_HEADERS = [
	'paper_condition',
	'task_id',
	'scenario_id',
	'n_runs',
	'n_completed',
	'n_strict_success',
	'strict_success_rate',
	'n_partial_success',
	'n_environment_blocked',
	'n_script_failed',
	'mean_steps',
	'mean_duration_seconds',
	'mean_total_tokens',
]


def _repeat_id(row: dict[str, Any]) -> int | None:
	manifest = row.get('run_manifest') if isinstance(row.get('run_manifest'), dict) else {}
	value = row.get('repeat_id', manifest.get('repeat_id'))
	return int(value) if value is not None else None


def _run_key(row: dict[str, Any], *, data_source: str) -> str:
	exp = row.get('experiment_id') or '?'
	task = row.get('task_id') or '?'
	rep = _repeat_id(row)
	if rep is not None:
		return f'{data_source}:{task}:{exp}:rep{rep}'
	started = (row.get('started_at') or '')[:19]
	return f'{data_source}:{task}:{exp}:{started or "unknown"}'


def _paper_condition(row: dict[str, Any]) -> str | None:
	exp = str(row.get('experiment_id') or '').strip()
	return _EXPERIMENT_TO_PAPER.get(exp)


def _is_stub_run(row: dict[str, Any]) -> bool:
	return not row.get('history_path')


def _navigator_replan_interval(row: dict[str, Any], paper_condition: str) -> int | None:
	manifest = row.get('run_manifest') if isinstance(row.get('run_manifest'), dict) else {}
	if manifest.get('planning_cadence_interval') is not None:
		return int(manifest['planning_cadence_interval'])
	if manifest.get('navigator_replan_interval') is not None:
		return int(manifest['navigator_replan_interval'])
	return _INTERVAL_FROM_PAPER.get(paper_condition)


def _continuous_navigation(row: dict[str, Any], paper_condition: str) -> bool:
	if row.get('continuous_navigation') is not None:
		return bool(row['continuous_navigation'])
	return paper_condition.startswith('R-')


def _adjudication_snapshot(row: dict[str, Any]) -> dict[str, Any]:
	return {
		'strict_success': row.get('strict_success'),
		'adjudicated_outcome_label': row.get('adjudicated_outcome_label'),
		'adjudication_reason': row.get('adjudication_reason'),
		'criteria_checks': row.get('criteria_checks'),
	}


def _enrich_row(
	row: dict[str, Any],
	*,
	data_source: str,
	paper_condition: str,
) -> dict[str, Any]:
	out = dict(row)
	out['data_source'] = data_source
	out['paper_condition'] = paper_condition
	out['navigator_replan_interval'] = _navigator_replan_interval(row, paper_condition)
	out['continuous_navigation'] = _continuous_navigation(row, paper_condition)
	if _is_stub_run(row):
		out['run_status'] = 'script_failed'
	return out


def _tokens_total(row: dict[str, Any]) -> int:
	usage = row.get('usage_summary') or {}
	total = usage.get('total_tokens')
	if isinstance(total, int):
		return total
	by_model = usage.get('by_model') if isinstance(usage.get('by_model'), dict) else {}
	return sum(int(v.get('total_tokens') or 0) for v in by_model.values() if isinstance(v, dict))


def _compare_snapshots(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any] | None:
	changed = (
		before.get('strict_success') != after.get('strict_success')
		or before.get('adjudicated_outcome_label') != after.get('adjudicated_outcome_label')
		or before.get('adjudication_reason') != after.get('adjudication_reason')
		or before.get('criteria_checks') != after.get('criteria_checks')
	)
	if not changed:
		return None
	return {
		'before': before,
		'after': after,
	}


def merge_and_readjudicate(
	*,
	output_dir: Path,
	task_cards_path: Path,
	ab_path: Path,
	cadence_path: Path,
	adaptive_path: Path | None,
	all_runs_path: Path,
	diff_path: Path,
	write_csv: bool,
) -> dict[str, Any]:
	task_cards = {t.id: t for t in load_json_model_list(task_cards_path, TaskCard)}
	human_runs = load_json_model_list(output_dir / 'human_runs.json', HumanRunRecord)

	ab_rows = json.loads(ab_path.read_text(encoding='utf-8'))
	cadence_rows = json.loads(cadence_path.read_text(encoding='utf-8'))
	adaptive_rows: list[dict[str, Any]] = []
	if adaptive_path is not None and adaptive_path.exists():
		adaptive_rows = json.loads(adaptive_path.read_text(encoding='utf-8'))

	merged: list[dict[str, Any]] = []
	diffs: list[dict[str, Any]] = []
	skipped_unknown: list[str] = []

	for data_source, rows in (
		('ab', ab_rows),
		('cadence', cadence_rows),
		('adaptive', adaptive_rows),
	):
		for raw in rows:
			paper = _paper_condition(raw)
			if paper is None:
				skipped_unknown.append(_run_key(raw, data_source=data_source))
				continue

			raw = dict(raw)
			raw.pop('repeat_id', None)

			key = _run_key(raw, data_source=data_source)
			before = _adjudication_snapshot(raw)

			if _is_stub_run(raw):
				after_row = _enrich_row(raw, data_source=data_source, paper_condition=paper)
				merged.append(after_row)
				continue

			task = task_cards.get(raw['task_id'])
			if task is None:
				raise KeyError(f'Unknown task_id {raw["task_id"]!r} for run {key}')

			summary = AgentRunSummary.model_validate(raw)
			readjudicated = adjudicate_agent_summary(task, summary)
			after_row = _enrich_row(
				readjudicated.model_dump(mode='json'),
				data_source=data_source,
				paper_condition=paper,
			)
			after_row['run_status'] = 'completed'
			merged.append(after_row)

			change = _compare_snapshots(before, _adjudication_snapshot(after_row))
			if change is not None:
				diffs.append(
					{
						'run_key': key,
						'data_source': data_source,
						'paper_condition': paper,
						'task_id': raw.get('task_id'),
						'experiment_id': raw.get('experiment_id'),
						'repeat_id': _repeat_id(raw),
						**change,
					}
				)

	payload = {
		'generated_at': datetime.now(UTC).isoformat(),
		'paper_condition_map': _EXPERIMENT_TO_PAPER,
		'sources': {
			'ab': str(ab_path),
			'cadence': str(cadence_path),
			'adaptive': str(adaptive_path) if adaptive_path is not None else None,
			'task_cards': str(task_cards_path),
		},
		'counts': {
			'ab': len(ab_rows),
			'cadence': len(cadence_rows),
			'adaptive': len(adaptive_rows),
			'merged': len(merged),
			'adjudication_changes': len(diffs),
			'skipped_unknown_experiment': len(skipped_unknown),
		},
		'runs': merged,
	}
	write_json(all_runs_path, payload)

	diff_report = {
		'generated_at': payload['generated_at'],
		'total_changes': len(diffs),
		'changes': diffs,
		'skipped_unknown_experiment': skipped_unknown,
	}
	write_json(diff_path, diff_report)

	csv_paths: dict[str, Path] = {}
	if write_csv:
		csv_paths['all_runs'] = _write_all_runs_csv(
			output_dir / 'all_runs.csv',
			merged=merged,
			task_cards=task_cards,
			human_runs=human_runs,
		)
		csv_paths['all_summary'] = _write_all_summary_csv(output_dir / 'all_summary.csv', merged=merged)

	return {
		'all_runs_path': all_runs_path,
		'diff_path': diff_path,
		'csv_paths': csv_paths,
		'counts': payload['counts'],
		'diff_count': len(diffs),
	}


_ENRICHMENT_FIELDS = frozenset({'data_source', 'paper_condition', 'navigator_replan_interval', 'run_status'})


def _summary_fields_only(row: dict[str, Any]) -> dict[str, Any]:
	return {k: v for k, v in row.items() if k not in _ENRICHMENT_FIELDS}


def _write_all_runs_csv(
	path: Path,
	*,
	merged: list[dict[str, Any]],
	task_cards: dict[str, TaskCard],
	human_runs: list[HumanRunRecord],
) -> Path:
	extra_headers = ['paper_condition', 'data_source', 'run_status', 'navigator_replan_interval']
	headers = list(AGENT_RUN_CSV_HEADERS)
	for h in extra_headers:
		if h not in headers:
			headers.append(h)

	rows_out: list[dict[str, Any]] = []
	for raw in merged:
		paper = raw.get('paper_condition') or '?'
		if _is_stub_run(raw):
			row = {k: '' for k in headers}
			row.update(
				{
					'method': paper,
					'paper_condition': paper,
					'data_source': raw.get('data_source', ''),
					'run_status': raw.get('run_status', 'script_failed'),
					'task_id': raw.get('task_id', ''),
					'scenario_id': 'normal',
					'experiment_id': raw.get('experiment_id', ''),
					'strict_success': 'false',
					'adjudicated_outcome_label': 'environment_blocked',
					'navigator_replan_interval': raw.get('navigator_replan_interval', ''),
					'continuous_navigation': raw.get('continuous_navigation', False),
				}
			)
			rows_out.append(row)
			continue

		task = task_cards[raw['task_id']]
		summary = AgentRunSummary.model_validate(_summary_fields_only(raw))
		row = build_agent_run_csv_row(
			method=paper,
			task=task,
			summary=summary,
			human=None,
			human_runs=get_reference_human_runs(human_runs, task_id=task.id, scenario_id=summary.scenario_id),
		)
		row['paper_condition'] = paper
		row['data_source'] = raw.get('data_source', '')
		row['run_status'] = raw.get('run_status', 'completed')
		row['navigator_replan_interval'] = raw.get('navigator_replan_interval', '')
		rows_out.append(row)

	with path.open('w', encoding='utf-8', newline='') as f:
		writer = csv.DictWriter(f, fieldnames=headers, extrasaction='ignore')
		writer.writeheader()
		for row in rows_out:
			writer.writerow({k: row.get(k, '') for k in headers})
	return path


def _write_all_summary_csv(path: Path, *, merged: list[dict[str, Any]]) -> Path:
	groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
	for row in merged:
		paper = row.get('paper_condition') or '?'
		task = row.get('task_id') or '?'
		groups[(paper, task)].append(row)

	with path.open('w', encoding='utf-8', newline='') as f:
		writer = csv.DictWriter(f, fieldnames=_SUMMARY_CSV_HEADERS)
		writer.writeheader()
		for paper in PAPER_CONDITION_ORDER:
			for task_id in sorted({k[1] for k in groups}):
				bucket = groups.get((paper, task_id), [])
				if not bucket:
					continue
				completed = [r for r in bucket if r.get('run_status') != 'script_failed']
				strict_ok = [r for r in completed if r.get('strict_success') is True]
				partials = [r for r in completed if r.get('adjudicated_outcome_label') == 'partial_success']
				env_blocked = [r for r in completed if r.get('adjudicated_outcome_label') == 'environment_blocked']
				script_failed = [r for r in bucket if r.get('run_status') == 'script_failed']
				steps = [r.get('number_of_steps') for r in completed if isinstance(r.get('number_of_steps'), int)]
				durations = [r.get('duration_seconds') for r in completed if isinstance(r.get('duration_seconds'), (int, float))]
				tokens = [_tokens_total(r) for r in completed if _tokens_total(r) > 0]
				writer.writerow(
					{
						'paper_condition': paper,
						'task_id': task_id,
						'scenario_id': 'normal',
						'n_runs': len(bucket),
						'n_completed': len(completed),
						'n_strict_success': len(strict_ok),
						'strict_success_rate': f'{len(strict_ok) / len(completed):.3f}' if completed else '',
						'n_partial_success': len(partials),
						'n_environment_blocked': len(env_blocked),
						'n_script_failed': len(script_failed),
						'mean_steps': f'{statistics.fmean(steps):.1f}' if steps else '',
						'mean_duration_seconds': f'{statistics.fmean(durations):.1f}' if durations else '',
						'mean_total_tokens': f'{statistics.fmean(tokens):.0f}' if tokens else '',
					}
				)
	return path


def _print_summary_table(merged: list[dict[str, Any]]) -> None:
	print('\n=== strict_success by paper_condition × task (completed runs only) ===')
	for paper in PAPER_CONDITION_ORDER:
		subset = [r for r in merged if r.get('paper_condition') == paper and r.get('run_status') != 'script_failed']
		if not subset:
			continue
		by_task: dict[str, list[bool]] = defaultdict(list)
		for r in subset:
			by_task[r['task_id']].append(bool(r.get('strict_success')))
		parts = [f'{task}:{sum(v)}/{len(v)}' for task, v in sorted(by_task.items())]
		total = sum(1 for r in subset if r.get('strict_success'))
		print(f'{paper:4} overall {total}/{len(subset)}  |  ' + ', '.join(parts))


def main() -> None:
	parser = argparse.ArgumentParser(description='Merge and re-adjudicate all daily-task eval runs.')
	parser.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT_DIR)
	parser.add_argument('--task-cards', type=Path, default=None)
	parser.add_argument('--ab-path', type=Path, default=None)
	parser.add_argument('--cadence-path', type=Path, default=None)
	parser.add_argument('--adaptive-path', type=Path, default=None)
	parser.add_argument('--all-runs-path', type=Path, default=None)
	parser.add_argument('--diff-path', type=Path, default=None)
	parser.add_argument('--no-csv', action='store_true')
	args = parser.parse_args()

	output_dir = args.output_dir
	result = merge_and_readjudicate(
		output_dir=output_dir,
		task_cards_path=args.task_cards or (output_dir / 'task_cards.json'),
		ab_path=args.ab_path or DEFAULT_AB_PATH,
		cadence_path=args.cadence_path or DEFAULT_CADENCE_PATH,
		adaptive_path=args.adaptive_path or DEFAULT_ADAPTIVE_PATH,
		all_runs_path=args.all_runs_path or DEFAULT_ALL_RUNS_PATH,
		diff_path=args.diff_path or DEFAULT_DIFF_PATH,
		write_csv=not args.no_csv,
	)

	print(f'Wrote {result["all_runs_path"]} ({result["counts"]["merged"]} runs)')
	print(f'Wrote {result["diff_path"]} ({result["diff_count"]} adjudication changes)')
	if result['csv_paths']:
		for name, p in result['csv_paths'].items():
			print(f'Wrote {p} ({name})')

	merged = json.loads(result['all_runs_path'].read_text(encoding='utf-8'))['runs']
	_print_summary_table(merged)


if __name__ == '__main__':
	main()
