"""Compare eval reports side by side.

Speed work is only meaningful as a delta against a baseline, and only trustworthy when the
accuracy column is shown next to it - a profile that is 40% faster and 30% less accurate is
a regression wearing a costume.

    python eval/compare.py eval/reports/matrix-*.json
    python eval/compare.py --baseline default eval/reports/matrix-*.json
"""

import argparse
import json
import statistics
from pathlib import Path
from typing import Any

METRICS = (
	('agent_seconds', 'wall'),
	('llm_seconds', 'llm'),
	('observation_seconds', 'dom'),
	('other_seconds', 'other'),
	('steps', 'steps'),
	('prompt_tokens', 'prompt_tok'),
	('completion_tokens', 'compl_tok'),
)


def load(path: Path) -> dict[str, Any]:
	report = json.loads(path.read_text())
	report['_name'] = report.get('meta', {}).get('profile') or path.stem
	return report


def median_of(report: dict[str, Any], key: str) -> float | None:
	values = [r[key] for r in report['results'] if isinstance(r.get(key), (int, float))]
	return statistics.median(values) if values else None


def fmt(value: float | None, key: str) -> str:
	if value is None:
		return '-'
	if key in ('steps', 'prompt_tokens', 'completion_tokens'):
		return f'{value:.0f}'
	return f'{value:.2f}s'


def fmt_delta(current: float | None, base: float | None) -> str:
	"""Percent change against baseline. Negative is faster/cheaper."""
	if current is None or base is None or base == 0:
		return '-'
	pct = (current - base) / base * 100
	return f'{pct:+.0f}%'


def main() -> int:
	parser = argparse.ArgumentParser(description='Compare eval reports')
	parser.add_argument('reports', nargs='+', type=Path)
	parser.add_argument('--baseline', default=None, help='Profile name to treat as the baseline')
	args = parser.parse_args()

	reports = [load(p) for p in args.reports if p.exists()]
	if not reports:
		print('No readable reports')
		return 1

	baseline = next((r for r in reports if r['_name'] == args.baseline), reports[0])

	headers = ['profile', 'pass', 'runs'] + [label for _, label in METRICS] + ['vs base']
	rows = []
	for report in reports:
		summary = report['summary']
		wall = median_of(report, 'agent_seconds')
		base_wall = median_of(baseline, 'agent_seconds')
		row = [
			report['_name'],
			f'{summary["passed"]}/{summary["total"]}',
			str(summary['total']),
		]
		row += [fmt(median_of(report, key), key) for key, _ in METRICS]
		row.append('baseline' if report is baseline else fmt_delta(wall, base_wall))
		rows.append(row)

	widths = [max(len(str(r[i])) for r in [headers] + rows) for i in range(len(headers))]
	print()
	print(' | '.join(headers[i].ljust(widths[i]) for i in range(len(headers))))
	print('-+-'.join('-' * w for w in widths))
	for row in rows:
		print(' | '.join(str(row[i]).ljust(widths[i]) for i in range(len(headers))))
	print('\n(medians across all runs; "vs base" is wall-clock change, negative is faster)')

	# Per-task detail makes a single pathological task visible instead of averaged away.
	print('\nper-task median wall seconds')
	tasks = sorted({r['file'] for report in reports for r in report['results']})
	headers2 = ['task'] + [r['_name'] for r in reports]
	rows2 = []
	for task in tasks:
		row = [task]
		for report in reports:
			values = [r['agent_seconds'] for r in report['results'] if r['file'] == task and r.get('agent_seconds')]
			ok = sum(1 for r in report['results'] if r['file'] == task and r.get('success'))
			total = sum(1 for r in report['results'] if r['file'] == task)
			row.append(f'{statistics.median(values):.1f}s {ok}/{total}' if values else f'- {ok}/{total}')
		rows2.append(row)

	widths2 = [max(len(str(r[i])) for r in [headers2] + rows2) for i in range(len(headers2))]
	print(' | '.join(headers2[i].ljust(widths2[i]) for i in range(len(headers2))))
	print('-+-'.join('-' * w for w in widths2))
	for row in rows2:
		print(' | '.join(str(row[i]).ljust(widths2[i]) for i in range(len(headers2))))
	print()
	return 0


if __name__ == '__main__':
	raise SystemExit(main())
