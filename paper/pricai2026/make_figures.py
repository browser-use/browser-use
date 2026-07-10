"""Generate PRICAI 2026 paper figures 2--7 from daily-task-eval artifacts.

Default inputs are read from ``../../tmp/daily_task_eval`` relative to this file.
Outputs are written to ``figures/`` next to ``main.tex`` as PDF and PNG.

Supports 5 conditions: E, I, R-1, R-3, R-5.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt


TASK_ORDER = [
	'shopping_price_compare',
	'nearby_hospital_phone_lookup',
	'github_clean_issue_audit',
	'huggingface_model_constrained_selection',
]
TASK_LABELS = {
	'shopping_price_compare': 'Shopping',
	'nearby_hospital_phone_lookup': 'Hospital',
	'github_clean_issue_audit': 'GitHub',
	'huggingface_model_constrained_selection': 'Hugging Face',
	'overall': 'Overall',
}
# experiment_id → paper condition label
CODE_TO_PAPER = {
	'C': 'E',
	'D': 'I',
	'C1': 'R-1',
	'C3': 'R-3',
	'C5': 'R-5',
	'CA': 'R-A',
}
PAPER_LABELS = {
	'E': 'E: executor only',
	'I': 'I: one-shot plan',
	'R-1': 'R-1: replan every step',
	'R-3': 'R-3: replan every 3 steps',
	'R-5': 'R-5: replan every 5 steps',
	'R-A': 'R-A: adaptive (stall replan)',
}
PAPER_ORDER = ['E', 'I', 'R-1', 'R-3', 'R-5', 'R-A']
COLORS = {
	'E': '#4E79A7',
	'I': '#F28E2B',
	'R-1': '#59A14F',
	'R-3': '#E15759',
	'R-5': '#B07AA1',
	'R-A': '#76B7B2',
}
# Distinguish R-* with hatching
HATCHES = {
	'E': '',
	'I': '',
	'R-1': '//',
	'R-3': '\\\\',
	'R-5': '..',
	'R-A': 'xx',
}


def _repo_root() -> Path:
	return Path(__file__).resolve().parents[2]


def _default_data_dir() -> Path:
	return _repo_root() / 'tmp' / 'daily_task_eval'


def _read_csv(path: Path) -> list[dict[str, str]]:
	with path.open(encoding='utf-8-sig', newline='') as f:
		return [dict(row) for row in csv.DictReader(f)]


def _read_json(path: Path) -> Any:
	return json.loads(path.read_text(encoding='utf-8'))


def _first_existing(paths: list[Path]) -> Path:
	for path in paths:
		if path.exists():
			return path
	raise FileNotFoundError('None of these files exists:\n' + '\n'.join(f'  - {p}' for p in paths))


def _parse_bool(raw: Any) -> bool | None:
	if isinstance(raw, bool):
		return raw
	if raw is None:
		return None
	text = str(raw).strip().lower()
	if text in {'true', '1', 'yes', 'success'}:
		return True
	if text in {'false', '0', 'no', 'failure'}:
		return False
	return None


def _parse_float(raw: Any) -> float | None:
	if raw is None or raw == '':
		return None
	try:
		value = float(raw)
	except (TypeError, ValueError):
		return None
	if math.isnan(value):
		return None
	return value


def _paper_condition(row: dict[str, Any]) -> str | None:
	raw = row.get('experiment_id') or row.get('stats_experiment_id') or row.get('analysis_experiment_id') or row.get('method')
	if raw is None:
		return None
	text = str(raw).strip().upper()
	if text.startswith('EXP-'):
		text = text.removeprefix('EXP-')
	return CODE_TO_PAPER.get(text)


def _paper_condition_direct(row: dict[str, Any]) -> str | None:
	"""Try paper_condition column first (from all_runs.csv), fall back to experiment_id mapping."""
	pc = row.get('paper_condition')
	if pc and str(pc).strip() in PAPER_ORDER:
		return str(pc).strip()
	return _paper_condition(row)


def _task_sort_key(task_id: str) -> tuple[int, str]:
	try:
		return (TASK_ORDER.index(task_id), task_id)
	except ValueError:
		return (len(TASK_ORDER), task_id)


def _mean(values: list[float]) -> float | None:
	return statistics.fmean(values) if values else None


def _std(values: list[float]) -> float | None:
	return statistics.stdev(values) if len(values) >= 2 else 0.0 if values else None


def _setup_style() -> None:
	plt.rcParams.update(
		{
			'font.family': 'DejaVu Sans',
			'font.size': 8.0,
			'axes.titlesize': 9.0,
			'axes.labelsize': 8.0,
			'xtick.labelsize': 7.0,
			'ytick.labelsize': 7.0,
			'legend.fontsize': 7.0,
			'pdf.fonttype': 42,
			'ps.fonttype': 42,
			'axes.spines.top': False,
			'axes.spines.right': False,
			'axes.grid': True,
			'grid.alpha': 0.22,
			'grid.linewidth': 0.6,
		}
	)


def _save(fig: plt.Figure, output_dir: Path, stem: str) -> None:
	output_dir.mkdir(parents=True, exist_ok=True)
	fig.savefig(output_dir / f'{stem}.pdf', bbox_inches='tight')
	fig.savefig(output_dir / f'{stem}.png', dpi=300, bbox_inches='tight')
	plt.close(fig)


def _load_run_rows(data_dir: Path) -> list[dict[str, str]]:
	candidates = [
		data_dir / 'all_runs.csv',
		data_dir / 'batch_20260624_runs.csv',
		data_dir / 'share_out' / 'batch_20260624_runs.csv',
		data_dir / 'share_out' / 'agent_runs_export.csv',
	]
	for path in candidates:
		if path.exists():
			return _read_csv(path)

	csv_dir = data_dir / 'csv_out'
	paths = sorted(csv_dir.glob('exp-*_runs.csv')) if csv_dir.exists() else []
	if paths:
		rows: list[dict[str, str]] = []
		for path in paths:
			rows.extend(_read_csv(path))
		return rows

	raise FileNotFoundError(
		'Could not find run-level CSV. Expected all_runs.csv, '
		'batch_20260624_runs.csv, or share_out/agent_runs_export.csv.'
	)


def _load_stats_rows(data_dir: Path) -> list[dict[str, str]]:
	candidates = [
		data_dir / 'share_out' / 'experiment_resource_report_stats.csv',
		data_dir / 'experiment_resource_report_stats.csv',
		data_dir / 'resource_summary.csv',
	]
	for path in candidates:
		if path.exists():
			return _read_csv(path)
	return _aggregate_stats_from_runs(_load_run_rows(data_dir))


def _aggregate_stats_from_runs(rows: list[dict[str, str]]) -> list[dict[str, str]]:
	buckets: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
	for row in rows:
		task_id = str(row.get('task_id') or '')
		cond = _paper_condition_direct(row)
		if task_id in TASK_ORDER and cond in PAPER_ORDER:
			buckets[(task_id, cond)].append(row)

	out: list[dict[str, str]] = []
	for (task_id, cond), bucket in sorted(buckets.items(), key=lambda item: (_task_sort_key(item[0][0]), item[0][1])):
		duration = [_parse_float(r.get('duration_seconds')) for r in bucket]
		steps = [_parse_float(r.get('number_of_steps')) for r in bucket]
		total_tokens = [
			_parse_float(r.get('total_tokens'))
			or ((_parse_float(r.get('tokens_executor')) or 0.0) + (_parse_float(r.get('tokens_navigator')) or 0.0))
			for r in bucket
		]
		cost = [_parse_float(r.get('full_run_cost_cny')) or _parse_float(r.get('total_cost')) for r in bucket]
		token_efficiency = [_parse_float(r.get('token_efficiency_score')) for r in bucket]
		out.append(
			{
				'task_id': task_id,
				'stats_experiment_id': cond,
				'stats_is_pooled': 'false',
				'run_count': str(len(bucket)),
				'duration_seconds_mean': str(_mean([v for v in duration if v is not None]) or ''),
				'duration_seconds_std': str(_std([v for v in duration if v is not None]) or ''),
				'number_of_steps_mean': str(_mean([v for v in steps if v is not None]) or ''),
				'total_tokens_mean': str(_mean([v for v in total_tokens if v is not None]) or ''),
				'total_tokens_std': str(_std([v for v in total_tokens if v is not None]) or ''),
				'total_cost_mean': str(_mean([v for v in cost if v is not None]) or ''),
				'total_cost_std': str(_std([v for v in cost if v is not None]) or ''),
				'token_efficiency_score_mean': str(_mean([v for v in token_efficiency if v is not None]) or ''),
			}
		)
	return out


def _bar_offsets(index: int, width: float) -> float:
	return (index - (len(PAPER_ORDER) - 1) / 2) * width


# =============================================================================
# fig2: Strict success rate by task × condition (grouped bar, k/n annotated)
# =============================================================================
def plot_fig2(data_dir: Path, output_dir: Path) -> None:
	rows = _load_run_rows(data_dir)
	counts: dict[tuple[str, str], list[bool]] = defaultdict(list)
	for row in rows:
		task_id = str(row.get('task_id') or '')
		cond = _paper_condition_direct(row)
		strict = _parse_bool(row.get('strict_success'))
		if task_id in TASK_ORDER and cond in PAPER_ORDER and strict is not None:
			counts[(task_id, cond)].append(strict)

	tasks = [*TASK_ORDER, 'overall']
	fig, ax = plt.subplots(figsize=(7.5, 3.0))
	width = 0.14
	xs = list(range(len(tasks)))
	for i, cond in enumerate(PAPER_ORDER):
		rates: list[float] = []
		labels: list[str] = []
		for task_id in tasks:
			values = []
			if task_id == 'overall':
				for tid in TASK_ORDER:
					values.extend(counts.get((tid, cond), []))
			else:
				values = counts.get((task_id, cond), [])
			successes = sum(values)
			total = len(values)
			rates.append(successes / total if total else 0.0)
			labels.append(f'{successes}/{total}' if total else 'n/a')

		positions = [x + _bar_offsets(i, width) for x in xs]
		kw = dict(color=COLORS[cond], label=PAPER_LABELS[cond])
		if HATCHES[cond]:
			kw['hatch'] = HATCHES[cond]
			kw['edgecolor'] = '#555555'
		ax.bar(positions, rates, width=width, **kw)
		for x, y, label in zip(positions, rates, labels, strict=False):
			ax.text(x, y + 0.02, label, ha='center', va='bottom', fontsize=5.8)

	ax.set_ylabel('Strict success rate')
	ax.set_ylim(0, 1.15)
	ax.set_xticks(xs)
	ax.set_xticklabels([TASK_LABELS[t] for t in tasks], rotation=18, ha='right')
	ax.legend(frameon=False, ncols=5, loc='upper left', fontsize=6.0)
	fig.tight_layout()
	_save(fig, output_dir, 'fig2')


# =============================================================================
# fig3: Median cost vs strict success rate (Pareto scatter by configuration)
# =============================================================================
def plot_fig3(data_dir: Path, output_dir: Path) -> None:
	rows = _load_run_rows(data_dir)
	fig, ax = plt.subplots(figsize=(4.5, 3.2))
	for cond in PAPER_ORDER:
		bucket = [r for r in rows if _paper_condition_direct(r) == cond]
		if not bucket:
			continue
		success_rate = sum(1 for r in bucket if _parse_bool(r.get('strict_success')) is True) / len(bucket)
		costs = [_parse_float(r.get('total_cost')) for r in bucket]
		costs = [c for c in costs if c is not None]
		median_cost = statistics.median(costs) if costs else 0.0
		marker = 's' if cond.startswith('R-') else 'o'
		ax.scatter(
			median_cost, success_rate,
			s=100, marker=marker,
			facecolors='none' if cond.startswith('R-') else COLORS[cond],
			edgecolors=COLORS[cond],
			linewidths=1.8,
			label=PAPER_LABELS[cond],
		)
		offset_y = 0.025 if cond != 'R-1' else -0.04
		ax.text(median_cost + 0.002, success_rate + offset_y, cond, fontsize=8, color=COLORS[cond], ha='center')

	ax.set_xlabel('Median total cost (USD)')
	ax.set_ylabel('Strict success rate')
	ax.set_xlim(left=0)
	ax.set_ylim(0, 1.08)
	ax.grid(alpha=0.2)
	ax.legend(frameon=False, fontsize=6.5, ncols=2, loc='lower right')
	fig.tight_layout()
	_save(fig, output_dir, 'fig3')


# =============================================================================
# fig4: Distribution panels — steps, total tokens, duration (box + strip)
# =============================================================================
def plot_fig4(data_dir: Path, output_dir: Path) -> None:
	rows = _load_run_rows(data_dir)
	# compute total_tokens for rows that don't have it
	for r in rows:
		if 'total_tokens' not in r or not r.get('total_tokens'):
			te = _parse_float(r.get('tokens_executor'))
			tn = _parse_float(r.get('tokens_navigator'))
			if te is not None:
				r['total_tokens'] = str(float(te) + float(tn or 0.0))

	import numpy as np
	rng = np.random.default_rng(42)
	metrics = [
		('number_of_steps', 'Number of steps'),
		('total_tokens', 'Total tokens'),
		('duration_seconds', 'Duration (s)'),
	]
	fig, axes = plt.subplots(1, 3, figsize=(7.5, 2.8))
	for ax, (col, label) in zip(axes, metrics):
		data = []
		for cond in PAPER_ORDER:
			vals = [_parse_float(r.get(col)) for r in rows if _paper_condition_direct(r) == cond]
			vals = [v for v in vals if v is not None]
			data.append(vals)
		bp = ax.boxplot(data, tick_labels=PAPER_ORDER, patch_artist=True, widths=0.5, showfliers=False)
		for patch, cond in zip(bp['boxes'], PAPER_ORDER):
			patch.set_facecolor(COLORS[cond])
			patch.set_alpha(0.7)
			if HATCHES[cond]:
				patch.set_hatch(HATCHES[cond])
		for i, (d, cond) in enumerate(zip(data, PAPER_ORDER)):
			if not d:
				continue
			jitter = rng.uniform(-0.12, 0.12, len(d))
			ax.scatter([i + 1] * len(d) + jitter, d, s=12, color=COLORS[cond], alpha=0.55, linewidths=0)
		ax.set_ylabel(label)
		ax.grid(axis='y', alpha=0.2)
	fig.tight_layout()
	_save(fig, output_dir, 'fig4')


# =============================================================================
# fig5: Agent-vs-human canonical LCS by task × condition (box + strip)
# =============================================================================
def _load_comparison_rows(data_dir: Path) -> list[dict[str, Any]]:
	path = _first_existing(
		[
			data_dir / 'comparison_report.json',
			data_dir / 'share_out' / 'comparison_report.json',
		]
	)
	data = _read_json(path)
	if isinstance(data, dict):
		for key in ('lcs_pairs', 'comparisons', 'comparison_records', 'outcome_table'):
			rows = data.get(key)
			if isinstance(rows, list):
				return [row for row in rows if isinstance(row, dict)]
		raise ValueError(f'Could not find a row list in comparison report object: {path}')
	if not isinstance(data, list):
		raise ValueError(f'Expected comparison report list/object, got {type(data).__name__}: {path}')
	return [row for row in data if isinstance(row, dict)]


def plot_fig5(data_dir: Path, output_dir: Path) -> None:
	rows = _load_comparison_rows(data_dir)
	values: dict[tuple[str, str], list[float]] = defaultdict(list)
	for row in rows:
		task_id = str(row.get('task_id') or '')
		cond = _paper_condition_direct(row)
		lcs = _parse_float(row.get('canonical_lcs_score'))
		if lcs is None:
			lcs = _parse_float(row.get('canonical_lcs'))
		if task_id in TASK_ORDER and cond in PAPER_ORDER and lcs is not None:
			values[(task_id, cond)].append(lcs)

	fig, ax = plt.subplots(figsize=(7.5, 3.0))
	width = 0.14
	base_positions = list(range(len(TASK_ORDER)))
	for i, cond in enumerate(PAPER_ORDER):
		positions = [x + _bar_offsets(i, width) for x in base_positions]
		data = [values.get((task_id, cond), []) for task_id in TASK_ORDER]
		box = ax.boxplot(
			data,
			positions=positions,
			widths=width * 0.75,
			patch_artist=True,
			showfliers=False,
			medianprops={'color': '#222222', 'linewidth': 1.0},
			boxprops={'linewidth': 0.7},
			whiskerprops={'linewidth': 0.7},
			capprops={'linewidth': 0.7},
		)
		for patch in box['boxes']:
			patch.set_facecolor(COLORS[cond])
			patch.set_alpha(0.28)
			patch.set_edgecolor(COLORS[cond])
			if HATCHES[cond]:
				patch.set_hatch(HATCHES[cond])

		for pos, points in zip(positions, data, strict=False):
			if not points:
				continue
			if len(points) == 1:
				jittered = [pos]
			else:
				step = min(0.06, width / max(2, len(points)))
				start = -step * (len(points) - 1) / 2
				jittered = [pos + start + step * j for j in range(len(points))]
			ax.scatter(jittered, points, s=10, color=COLORS[cond], alpha=0.75, linewidths=0)
			ax.text(pos, 1.03, f'n={len(points)}', ha='center', va='bottom', fontsize=5.5, color=COLORS[cond])

	ax.set_ylabel('Canonical LCS')
	ax.set_ylim(0, 1.15)
	ax.set_xticks(base_positions)
	ax.set_xticklabels([TASK_LABELS[t] for t in TASK_ORDER], rotation=15, ha='right')
	handles = [plt.Line2D([0], [0], color=COLORS[c], marker='s', linestyle='', markersize=6) for c in PAPER_ORDER]
	ax.legend(handles, [PAPER_LABELS[c] for c in PAPER_ORDER], frameon=False, ncols=5, loc='upper left', fontsize=5.8)
	fig.tight_layout()
	_save(fig, output_dir, 'fig5')


# =============================================================================
# fig6: Navigator overhead ratio and recovery yield by configuration
# =============================================================================
def plot_fig6(data_dir: Path, output_dir: Path) -> None:
	rows = _load_run_rows(data_dir)
	fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.6))

	# Panel (a): Navigator overhead ratio (r_overhead) by condition
	ax = axes[0]
	overhead_data: dict[str, list[float]] = defaultdict(list)
	for r in rows:
		cond = _paper_condition_direct(r)
		if cond not in PAPER_ORDER:
			continue
		ro = _parse_float(r.get('r_overhead'))
		if ro is not None:
			overhead_data[cond].append(ro)

	x = list(range(len(PAPER_ORDER)))
	# Bar chart of median r_overhead with individual points
	for i, cond in enumerate(PAPER_ORDER):
		vals = overhead_data.get(cond, [])
		if not vals:
			continue
		kw = dict(color=COLORS[cond])
		if HATCHES[cond]:
			kw['hatch'] = HATCHES[cond]
			kw['edgecolor'] = '#555555'
		ax.bar(i, statistics.median(vals), **kw, width=0.55, alpha=0.7)
		if len(vals) <= 1:
			jittered = [i]
		else:
			jitter = min(0.10, 0.5 / max(2, len(vals)))
			jittered = [i + jitter * (jj - (len(vals) - 1) / 2) for jj in range(len(vals))]
		ax.scatter(jittered, vals, s=15, color=COLORS[cond], alpha=0.6, linewidths=0)
	ax.set_xticks(x)
	ax.set_xticklabels(PAPER_ORDER)
	ax.set_ylabel('Median navigator overhead ratio')
	ax.grid(axis='y', alpha=0.2)
	ax.text(0.02, 0.98, '(a)', transform=ax.transAxes, fontsize=9, va='top', ha='left')

	# Panel (b): Post-intervention recovery yield
	ax = axes[1]
	# Load from milestone_summary if available
	milestone_path = data_dir / 'milestone_summary.csv'
	recovery_data: dict[str, list[float]] = defaultdict(list)
	if milestone_path.exists():
		ms_rows = _read_csv(milestone_path)
		for r in ms_rows:
			cond = r.get('paper_condition', '').strip()
			if cond not in PAPER_ORDER:
				continue
			ry = _parse_float(r.get('post_intervention_recovery_yield'))
			if ry is not None:
				recovery_data[cond].append(ry)

	if recovery_data:
		x2 = list(range(len(PAPER_ORDER)))
		for i, cond in enumerate(PAPER_ORDER):
			vals = recovery_data.get(cond, [])
			if not vals:
				continue
			kw = dict(color=COLORS[cond])
			if HATCHES[cond]:
				kw['hatch'] = HATCHES[cond]
				kw['edgecolor'] = '#555555'
			ax.bar(i, statistics.median(vals), **kw, width=0.55, alpha=0.7)
		ax.set_xticks(x2)
		ax.set_xticklabels(PAPER_ORDER)
		ax.set_ylabel('Median recovery yield')
	else:
		ax.text(0.5, 0.5,
			'Recovery yield not yet computed.\nRe-run compute_milestone_metrics.py after data update.',
			transform=ax.transAxes, fontsize=8, ha='center', va='center',
			style='italic', color='gray')
		ax.set_xlim(0, 1)
		ax.set_ylim(0, 1)
	ax.grid(axis='y', alpha=0.2)
	ax.text(0.02, 0.98, '(b)', transform=ax.transAxes, fontsize=9, va='top', ha='left')

	fig.tight_layout()
	_save(fig, output_dir, 'fig6')


# =============================================================================
# fig7: HuggingFace case study — dual timeline contrasting R-1 vs R-5
# =============================================================================
def plot_fig7(data_dir: Path, output_dir: Path) -> None:
	"""Find one R-1 and one R-5 HuggingFace run and plot step-level timelines."""
	rows = _load_run_rows(data_dir)

	def _find_run(cond: str, prefer_failure: bool = True) -> dict[str, str] | None:
		candidates = [
			r for r in rows
			if _paper_condition_direct(r) == cond
			and str(r.get('task_id', '')) == 'huggingface_model_constrained_selection'
		]
		if not candidates:
			return None
		if prefer_failure:
			failures = [r for r in candidates if _parse_bool(r.get('strict_success')) is False]
			if failures:
				return failures[0]
		successes = [r for r in candidates if _parse_bool(r.get('strict_success')) is True]
		return successes[0] if successes else candidates[0]

	r1_run = _find_run('R-1', prefer_failure=True)
	r5_run = _find_run('R-5', prefer_failure=False)

	if not r1_run or not r5_run:
		fig, ax = plt.subplots(figsize=(7, 2))
		ax.text(0.5, 0.5, 'Case study runs not yet available.\nRe-run after data update.',
			transform=ax.transAxes, fontsize=10, ha='center', va='center', style='italic', color='gray')
		ax.axis('off')
		_save(fig, output_dir, 'fig7')
		return

	def _classify_url(url: str) -> str:
		if not url or 'blank' in url.lower():
			return 'blank'
		if 'huggingface.co/models' in url:
			return 'filtered_list' if '?' in url else 'models_home'
		if 'huggingface.co/' in url and '/models' not in url:
			return 'model_detail'
		return 'blank'

	STATE_COLORS = {
		'blank': '#e0e0e0',
		'models_home': '#AEC7E8',
		'filtered_list': '#4E79A7',
		'model_detail': '#59A14F',
	}

	runs_to_plot = [
		('R-1', r1_run),
		('R-5', r5_run),
	]

	fig, axes = plt.subplots(2, 1, figsize=(7.5, 3.6), sharex=True)
	for idx, (label, run_info) in enumerate(runs_to_plot):
		ax = axes[idx]
		history_path_str = run_info.get('history_path', '')
		if not history_path_str:
			ax.text(0.5, 0.5, f'{label}: no history_path', transform=ax.transAxes,
				fontsize=8, ha='center', va='center', style='italic', color='gray')
			ax.set_ylim(-0.3, 0.3)
			continue

		history_path = Path(history_path_str)
		if not history_path.exists():
			# Try relative to repo root
			history_path = _repo_root() / history_path_str
		if not history_path.exists():
			ax.text(0.5, 0.5, f'{label}: history file not found', transform=ax.transAxes,
				fontsize=8, ha='center', va='center', style='italic', color='gray')
			ax.set_ylim(-0.3, 0.3)
			continue

		with open(history_path, encoding='utf-8') as f:
			history_data = json.load(f)
		history = history_data.get('history', [])

		n_steps = len(history)
		states = [_classify_url(step.get('state', {}).get('url', '')) for step in history]
		for i, state in enumerate(states):
			ax.barh(0, 1, left=i, color=STATE_COLORS.get(state, '#cccccc'), edgecolor='none', height=0.5)

		# Mark step 14 for R-1 (rollback)
		if label == 'R-1' and n_steps > 14:
			ax.axvspan(14, n_steps, alpha=0.08, color='red')
			ax.annotate('Step 14: navigator injects\nback-navigate → re-filter loop',
				xy=(13.5, 0), xytext=(17, 0.35), fontsize=7, color='red',
				arrowprops=dict(arrowstyle='->', color='red', lw=1))

		ax.set_yticks([0])
		ax.set_yticklabels([f'{label} ({n_steps} steps)'], fontsize=9, weight='bold', color=COLORS[label])
		ax.set_ylim(-0.3, 0.3)
		ax.set_xlim(0, max(35, n_steps + 2))
		ax.grid(axis='x', alpha=0.2)

	axes[1].set_xlabel('Step')
	axes[1].set_xticks(range(0, 36, 5))

	handles = [plt.Rectangle((0, 0), 1, 1, color=STATE_COLORS[s]) for s in ['blank', 'models_home', 'filtered_list', 'model_detail']]
	labels_legend = ['blank', 'models_home', 'filtered_list', 'model_detail']
	fig.legend(handles, labels_legend, ncol=4, loc='lower center', bbox_to_anchor=(0.5, -0.02),
		frameon=False, fontsize=7)
	fig.tight_layout()
	_save(fig, output_dir, 'fig7')


# =============================================================================
# fig1: Architecture diagram (schematic — placeholder until manually created)
# =============================================================================
def plot_fig1(output_dir: Path) -> None:
	"""Generate a basic architecture diagram as a placeholder for the manual schematic.

	The camera-ready figure should be a proper schematic (draw.io / TikZ / PPT).
	This function produces a best-effort matplotlib block diagram so the paper
	compiles without the placeholder box.
	"""
	fig, ax = plt.subplots(figsize=(8, 4))
	ax.set_xlim(0, 10)
	ax.set_ylim(0, 5)
	ax.axis('off')

	# --- Box positions ---
	boxes = [
		# (x, y, w, h, label, color)
		(0.3, 2.0, 1.8, 1.0, 'Task Card', '#E8E8E8'),
		(2.8, 2.0, 2.2, 1.0, 'Executor LLM\n(Doubao)', '#4E79A7'),
		(5.8, 2.0, 1.8, 1.0, 'CDP Browser\nSession', '#B07AA1'),
		(8.3, 2.0, 1.4, 1.0, 'Adjudicator\n→ strict_success', '#F28E2B'),
		(2.8, 3.5, 2.2, 0.7, 'Navigator (optional)\n(DeepSeek, one-shot plan)', '#59A14F'),
	]
	for x, y, w, h, label, color in boxes:
		rect = plt.Rectangle((x, y), w, h, linewidth=1.2, edgecolor='#333333',
			facecolor=color, alpha=0.6)
		ax.add_patch(rect)
		ax.text(x + w / 2, y + h / 2, label, ha='center', va='center', fontsize=7.5,
			fontweight='bold')

	# --- Arrows ---
	arrow_kw = dict(arrowstyle='->', color='#333333', lw=1.2, connectionstyle='arc3,rad=0')
	ax.annotate('', xy=(2.8, 2.5), xytext=(2.1, 2.5), arrowprops=arrow_kw)  # Task → Executor
	ax.annotate('', xy=(5.8, 2.5), xytext=(5.0, 2.5), arrowprops=arrow_kw)  # Executor → Browser
	ax.annotate('', xy=(4.7, 2.0), xytext=(4.7, 2.9), arrowprops=dict(arrowstyle='->', color='#333333', lw=1.2, connectionstyle='arc3,rad=0.3'))
	ax.annotate('', xy=(3.5, 1.7), xytext=(5.5, 1.7), arrowprops=dict(arrowstyle='->', color='#333333', lw=1.2, connectionstyle='arc3,rad=-0.3'))
	ax.annotate('', xy=(8.3, 2.5), xytext=(7.6, 2.5), arrowprops=arrow_kw)  # Browser → Adjudicator
	# Navigator → Executor (dashed)
	ax.annotate('', xy=(3.9, 3.0), xytext=(3.9, 3.5),
		arrowprops=dict(arrowstyle='->', color='#59A14F', lw=1.2, linestyle='dashed'))

	ax.set_title('System Architecture: CDP Browser Agent with Optional Navigator', fontsize=10, fontweight='bold')
	fig.tight_layout()
	_save(fig, output_dir, 'fig1')


# =============================================================================
def generate_all(data_dir: Path, output_dir: Path) -> None:
	_setup_style()
	print('Generating fig1 (architecture diagram)...')
	plot_fig1(output_dir)
	print('Generating fig2 (strict success)...')
	plot_fig2(data_dir, output_dir)
	print('Generating fig3 (Pareto cost–success)...')
	plot_fig3(data_dir, output_dir)
	print('Generating fig4 (distributions)...')
	plot_fig4(data_dir, output_dir)
	print('Generating fig5 (LCS comparison)...')
	plot_fig5(data_dir, output_dir)
	print('Generating fig6 (navigator overhead)...')
	plot_fig6(data_dir, output_dir)
	print('Generating fig7 (HF case study)...')
	plot_fig7(data_dir, output_dir)


def main() -> int:
	parser = argparse.ArgumentParser(description='Generate PRICAI 2026 figures 1--7.')
	parser.add_argument('--data-dir', type=Path, default=_default_data_dir())
	parser.add_argument('--output-dir', type=Path, default=Path(__file__).resolve().parent / 'figures')
	args = parser.parse_args()

	generate_all(args.data_dir, args.output_dir)
	print(f'Wrote fig1--fig7 PDF/PNG files to {args.output_dir.resolve()}')
	return 0


if __name__ == '__main__':
	raise SystemExit(main())
