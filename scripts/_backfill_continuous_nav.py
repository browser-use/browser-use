"""One-off backfill: add `continuous_navigation` column to existing exp-{C,D}_runs.csv.

Per user direction (2026-05-24):
- All historic rows = false (continuous_navigation was NOT enabled).
- Only the LAST row of exp-D_runs.csv (most recent D run) = true.

After this runs, the CSV layout matches AGENT_RUN_CSV_HEADERS and future
`append_agent_run_csv_row` calls will pass through cleanly.
"""

from __future__ import annotations

import csv
from pathlib import Path

from browser_use.experiments.daily_task_eval.run_csv import AGENT_RUN_CSV_HEADERS

CSV_DIR = Path('tmp/daily_task_eval/csv_out')


def backfill_file(path: Path, last_row_is_true: bool) -> None:
	if not path.exists():
		print(f'skip (missing): {path}')
		return
	with path.open(encoding='utf-8', newline='') as f:
		reader = csv.DictReader(f)
		rows = list(reader)
	if not rows:
		print(f'skip (empty): {path}')
		return
	for i, r in enumerate(rows):
		if i == len(rows) - 1 and last_row_is_true:
			r['continuous_navigation'] = 'true'
		else:
			r['continuous_navigation'] = 'false'
	with path.open('w', encoding='utf-8', newline='') as f:
		writer = csv.DictWriter(f, fieldnames=AGENT_RUN_CSV_HEADERS, extrasaction='ignore')
		writer.writeheader()
		for r in rows:
			writer.writerow({k: r.get(k, '') for k in AGENT_RUN_CSV_HEADERS})
	print(f'rewrote {path}: {len(rows)} rows, last_row_continuous_navigation={last_row_is_true}')


def main() -> None:
	backfill_file(CSV_DIR / 'exp-C_runs.csv', last_row_is_true=False)
	backfill_file(CSV_DIR / 'exp-D_runs.csv', last_row_is_true=True)


if __name__ == '__main__':
	main()
