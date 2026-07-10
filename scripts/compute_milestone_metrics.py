"""Compute milestone-based process metrics for all agent runs.

Reads history.json for each run, parses milestones, and outputs:
- per_run_milestones.json: detailed milestone events per run
- milestone_summary.csv: aggregated metrics for analysis

Usage:
    uv run python scripts/compute_milestone_metrics.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from browser_use.experiments.daily_task_eval.task_registry import get_all_milestone_task_ids
from browser_use.experiments.daily_task_eval.trajectory_metrics import parse_history_for_milestones


def main() -> None:
	"""Compute milestone metrics for all completed runs."""

	base_dir = Path('tmp/daily_task_eval')
	all_runs_json = base_dir / 'all_runs.json'
	legacy_runs_json = base_dir / 'agent_runs.json'

	runs: list[dict] = []
	source_label = ''
	if all_runs_json.exists():
		with open(all_runs_json, encoding='utf-8') as f:
			payload = json.load(f)
		runs = payload.get('runs', []) if isinstance(payload, dict) else []
		source_label = 'all_runs.json'
	elif legacy_runs_json.exists():
		with open(legacy_runs_json, encoding='utf-8') as f:
			runs = json.load(f)
		source_label = 'agent_runs.json'
	else:
		print(f'Error: neither {all_runs_json} nor {legacy_runs_json} found')
		return
	print(f'Loaded {len(runs)} runs from {source_label}')

	milestone_task_ids = set(get_all_milestone_task_ids())
	print(f'Tasks with milestones: {sorted(milestone_task_ids)}')

	per_run_results = []
	summary_rows = []

	for run in runs:
		if run.get('run_status') == 'script_failed':
			continue
		task_id = run.get('task_id')
		if task_id not in milestone_task_ids:
			continue

		run_id = run.get('started_at', 'unknown')
		experiment_id = run.get('experiment_id')
		paper_condition = run.get('paper_condition')
		scenario_id = run.get('scenario_id', 'normal')

		history_path = Path(run.get('history_path') or '')

		if not history_path.exists():
			print(f'Warning: history not found for {task_id} {experiment_id} {run_id}')
			continue

		with open(history_path, encoding='utf-8') as f:
			history_data = json.load(f)
			history = history_data.get('history', [])

		if not history:
			print(f'Warning: empty history for {task_id} {experiment_id} {run_id}')
			continue

		# Parse milestones
		metrics = parse_history_for_milestones(history, task_id, run_id, experiment_id)

		# Store detailed per-run results
		per_run_results.append(
			{
				'run_id': run_id,
				'task_id': task_id,
				'experiment_id': experiment_id,
				'paper_condition': paper_condition,
				'scenario_id': scenario_id,
				'total_steps': metrics.total_steps,
				'milestones_achieved': list(metrics.milestones_achieved),
				'milestone_steps': metrics.milestone_steps,
				'milestone_coverage': metrics.milestone_coverage,
				'order_score': metrics.order_score,
				'stall_burden': metrics.stall_burden,
				'state_revisit_rate': metrics.state_revisit_rate,
				'post_intervention_recovery_yield': metrics.post_intervention_recovery_yield,
			}
		)

		# Store summary row
		summary_rows.append(
			{
				'run_id': run_id,
				'task_id': task_id,
				'experiment_id': experiment_id,
				'paper_condition': paper_condition,
				'scenario_id': scenario_id,
				'total_steps': metrics.total_steps,
				'milestones_achieved_count': len(metrics.milestones_achieved),
				'milestones_achieved_str': ','.join(metrics.milestones_achieved),
				'milestone_coverage': round(metrics.milestone_coverage, 3),
				'order_score': round(metrics.order_score, 3) if metrics.order_score is not None else None,
				'stall_burden': round(metrics.stall_burden, 3),
				'state_revisit_rate': round(metrics.state_revisit_rate, 3),
				'post_intervention_recovery_yield': (
					round(metrics.post_intervention_recovery_yield, 3)
					if metrics.post_intervention_recovery_yield is not None
					else None
				),
				'strict_success': run.get('strict_success'),
			}
		)

		print(
			f'  {task_id}/{experiment_id}: {len(metrics.milestones_achieved)} milestones, '
			f'coverage={metrics.milestone_coverage:.2f}, stall={metrics.stall_burden:.2f}'
		)

	# Write per_run_milestones.json
	output_json = base_dir / 'per_run_milestones.json'
	with open(output_json, 'w', encoding='utf-8') as f:
		json.dump(per_run_results, f, indent=2, ensure_ascii=False)
	print(f'\nWrote {len(per_run_results)} run results to {output_json}')

	# Write milestone_summary.csv
	df = pd.DataFrame(summary_rows)
	output_csv = base_dir / 'milestone_summary.csv'
	df.to_csv(output_csv, index=False)
	print(f'Wrote summary CSV with {len(df)} rows to {output_csv}')

	# Print aggregate stats by experiment
	print('\n=== Aggregate Stats by Experiment ===')
	if len(df) > 0:
		for exp_id in sorted(df['experiment_id'].unique()):
			exp_df = df[df['experiment_id'] == exp_id]
			print(f'\n{exp_id} (n={len(exp_df)}):')
			print(f'  Mean coverage: {exp_df["milestone_coverage"].mean():.3f}')
			print(f'  Mean order_score: {exp_df["order_score"].mean():.3f}')
			print(f'  Mean stall_burden: {exp_df["stall_burden"].mean():.3f}')
			print(f'  Mean revisit_rate: {exp_df["state_revisit_rate"].mean():.3f}')
			if exp_id.startswith('R-'):
				recovery = exp_df['post_intervention_recovery_yield'].dropna()
				if len(recovery) > 0:
					print(f'  Mean recovery_yield: {recovery.mean():.3f}')

		print('\n=== Coverage by Task ===')
		for task_id in sorted(df['task_id'].unique()):
			task_df = df[df['task_id'] == task_id]
			print(
				f'{task_id}: mean_coverage={task_df["milestone_coverage"].mean():.3f}, '
				f'mean_stall={task_df["stall_burden"].mean():.3f}'
			)

		if 'paper_condition' in df.columns and df['paper_condition'].notna().any():
			print('\n=== Aggregate Stats by Paper Condition (completed runs) ===')
			for cond in sorted(set(c for c in df['paper_condition'].dropna().unique())):
				cdf = df[df['paper_condition'] == cond]
				print(f'\n{cond} (n={len(cdf)}):')
				print(f'  Mean coverage: {cdf["milestone_coverage"].mean():.3f}')
				print(f'  Mean stall_burden: {cdf["stall_burden"].mean():.3f}')
				print(f'  Mean revisit_rate: {cdf["state_revisit_rate"].mean():.3f}')
	else:
		print('No runs processed successfully.')


if __name__ == '__main__':
	main()
