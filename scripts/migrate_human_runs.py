"""Conservative migration for ``human_runs.json`` reference-eligibility fields."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_PLACEHOLDER_STEP = 'Replace this with the exact manual steps you took.'
_PLACEHOLDER_NOTES = 'Fill this after the human baseline run.'
_PENDING_EVIDENCE_MARKERS = ('待补充',)


def _has_pending_evidence(record: dict[str, Any]) -> bool:
	for item in record.get('final_evidence') or []:
		text = str(item)
		if any(marker in text for marker in _PENDING_EVIDENCE_MARKERS):
			return True
	final_answer = record.get('final_answer')
	if isinstance(final_answer, dict):
		text = str(final_answer.get('text', ''))
		if any(marker in text for marker in _PENDING_EVIDENCE_MARKERS):
			return True
	return False


def _steps_contain_placeholder(steps: list[Any]) -> bool:
	return any(str(step).strip() == _PLACEHOLDER_STEP for step in steps)


def migrate_record(record: dict[str, Any]) -> dict[str, Any]:
	out = dict(record)
	steps = list(out.get('steps') or [])
	task_id = str(out.get('task_id', ''))

	if _steps_contain_placeholder(steps):
		out['run_status'] = 'not_started'
		out['outcome_label'] = None
		out['reference_eligible'] = False
		out['steps'] = []
		return out

	if task_id == 'complex_travel_package_booking':
		out['run_status'] = 'completed'
		out['outcome_label'] = 'partial_success'
		out['reference_eligible'] = False
		out['trajectory_comparable'] = 'low'
		out['route_relation'] = 'off_target_flow'
		return out

	run_status = out.get('run_status', 'completed')
	outcome = out.get('outcome_label')
	if run_status == 'completed' and outcome != 'failure' and _has_pending_evidence(out):
		out['outcome_label'] = 'partial_success'
		out['reference_eligible'] = False

	if out.get('trajectory_comparable') == 'full':
		out['trajectory_comparable'] = 'high'

	for key in ('domains_visited', 'criteria_checks', 'milestone_outcomes', 'step_annotations'):
		if key not in out or out[key] is None:
			out[key] = []

	return out


def summarize(records: list[dict[str, Any]]) -> dict[str, int]:
	counts = {
		'total_records': len(records),
		'not_started': 0,
		'completed_success': 0,
		'completed_partial_success': 0,
		'completed_failure': 0,
		'reference_eligible_count': 0,
	}
	for record in records:
		status = record.get('run_status')
		outcome = record.get('outcome_label')
		if status == 'not_started':
			counts['not_started'] += 1
		elif status == 'completed' and outcome == 'success':
			counts['completed_success'] += 1
		elif status == 'completed' and outcome == 'partial_success':
			counts['completed_partial_success'] += 1
		elif status == 'completed' and outcome == 'failure':
			counts['completed_failure'] += 1
		if record.get('reference_eligible') is True:
			counts['reference_eligible_count'] += 1
	return counts


def main() -> int:
	parser = argparse.ArgumentParser(description='Migrate human_runs.json reference metadata.')
	parser.add_argument('input', type=Path, nargs='?', default=Path('tmp/daily_task_eval/human_runs.json'))
	parser.add_argument(
		'--output',
		type=Path,
		default=None,
		help='Output path (default: human_runs.migrated.json beside input).',
	)
	parser.add_argument('--in-place', action='store_true', help='Overwrite the input file.')
	args = parser.parse_args()

	input_path: Path = args.input
	if not input_path.exists():
		print(f'Input not found: {input_path}', file=sys.stderr)
		return 1

	raw = json.loads(input_path.read_text(encoding='utf-8'))
	if not isinstance(raw, list):
		print('Expected a JSON array of human run records.', file=sys.stderr)
		return 1

	migrated = [migrate_record(item) for item in raw]
	summary = summarize(migrated)

	if args.in_place:
		output_path = input_path
	else:
		output_path = args.output or input_path.with_name('human_runs.migrated.json')

	output_path.write_text(json.dumps(migrated, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')

	for key, value in summary.items():
		print(f'{key}: {value}')
	print(f'written: {output_path}')
	return 0


if __name__ == '__main__':
	raise SystemExit(main())
