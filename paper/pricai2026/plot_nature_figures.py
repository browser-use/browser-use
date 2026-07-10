"""Publication-grade Nature-style figures for strict success and process metrics.

Reads merged experiment artifacts and writes fig2 / fig5 to ``figures/``.

Data inputs (repo-relative):
    tmp/daily_task_eval/all_runs.csv
    tmp/daily_task_eval/milestone_summary.csv

Statistics:
    - Fig. 2: binomial proportion with Wilson 95% CI (per task x condition).
    - Fig. 5: (a) coverage heatmap (mean % in cells); (b) stall burden point-range
      (mean + bootstrap 95% CI, R-A highlighted in green, no raw points).

Usage:
    uv run python paper/pricai2026/plot_nature_figures.py
"""

from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
# ---------------------------------------------------------------------------
# Experiment vocabulary
# ---------------------------------------------------------------------------
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
	'huggingface_model_constrained_selection': 'HuggingFace',
}
PAPER_ORDER = ['E', 'I', 'R-1', 'R-3', 'R-5', 'R-A']
PAPER_SHORT = {
	'E': 'E',
	'I': 'I',
	'R-1': 'R-1',
	'R-3': 'R-3',
	'R-5': 'R-5',
	'R-A': 'R-A',
}
PAPER_LEGEND = {
	'E': 'E (executor only)',
	'I': 'I (one-shot plan)',
	'R-1': 'R-1 (every step)',
	'R-3': 'R-3 (every 3 steps)',
	'R-5': 'R-5 (every 5 steps)',
	'R-A': 'R-A (adaptive)',
}

# Restrained NMI-style palette: one neutral + warm accent + teal replan family
PALETTE = {
	'E': '#6B7B8C',
	'I': '#D4845A',
	'R-1': '#3D6B8E',
	'R-3': '#5A8FB0',
	'R-5': '#7AAFC8',
	'R-A': '#2E8B7A',
}


def _repo_root() -> Path:
	return Path(__file__).resolve().parents[2]


def _default_data_dir() -> Path:
	return _repo_root() / 'tmp' / 'daily_task_eval'


def _read_csv(path: Path) -> list[dict[str, str]]:
	with path.open(encoding='utf-8-sig', newline='') as f:
		return [dict(row) for row in csv.DictReader(f)]


def _parse_bool(raw: str | None) -> bool | None:
	if raw is None:
		return None
	text = str(raw).strip().lower()
	if text in {'true', '1', 'yes'}:
		return True
	if text in {'false', '0', 'no'}:
		return False
	return None


def _parse_float(raw: str | None) -> float | None:
	if raw is None or str(raw).strip() == '':
		return None
	try:
		return float(raw)
	except ValueError:
		return None


def _paper_condition(row: dict[str, str]) -> str | None:
	cond = (row.get('paper_condition') or row.get('method') or '').strip()
	return cond if cond in PAPER_ORDER else None


def _setup_nature_style() -> None:
	mpl.rcParams.update(
		{
			'font.family': 'sans-serif',
			'font.sans-serif': ['Arial', 'Helvetica', 'DejaVu Sans', 'sans-serif'],
			'svg.fonttype': 'none',
			'pdf.fonttype': 42,
			'ps.fonttype': 42,
			'font.size': 7.5,
			'axes.titlesize': 8.5,
			'axes.labelsize': 8.0,
			'xtick.labelsize': 7.5,
			'ytick.labelsize': 7.5,
			'legend.fontsize': 6.8,
			'axes.linewidth': 0.7,
			'axes.spines.top': False,
			'axes.spines.right': False,
			'axes.edgecolor': '#333333',
			'axes.labelcolor': '#222222',
			'xtick.color': '#333333',
			'ytick.color': '#333333',
			'legend.frameon': False,
			'figure.facecolor': 'white',
			'axes.facecolor': 'white',
		}
	)


def _save_pub(fig: plt.Figure, output_dir: Path, stem: str) -> None:
	output_dir.mkdir(parents=True, exist_ok=True)
	fig.savefig(output_dir / f'{stem}.pdf', bbox_inches='tight', facecolor='white')
	fig.savefig(output_dir / f'{stem}.png', dpi=600, bbox_inches='tight', facecolor='white')
	plt.close(fig)


def _wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
	"""Wilson score interval for a binomial proportion."""
	if n <= 0:
		return 0.0, 0.0
	p = k / n
	z2 = z * z
	denom = 1.0 + z2 / n
	centre = p + z2 / (2.0 * n)
	margin = z * math.sqrt((p * (1.0 - p) + z2 / (4.0 * n)) / n)
	low = (centre - margin) / denom
	high = (centre + margin) / denom
	return max(0.0, low), min(1.0, high)


def _bootstrap_mean_ci(
	values: list[float],
	*,
	n_boot: int = 4000,
	alpha: float = 0.05,
	seed: int = 42,
) -> tuple[float, float, float]:
	"""Return (mean, ci_low, ci_high)."""
	if not values:
		return 0.0, 0.0, 0.0
	arr = np.asarray(values, dtype=float)
	rng = np.random.default_rng(seed)
	boot = np.empty(n_boot, dtype=float)
	n = len(arr)
	for i in range(n_boot):
		boot[i] = rng.choice(arr, size=n, replace=True).mean()
	mean = float(arr.mean())
	lo, hi = np.percentile(boot, [100.0 * alpha / 2.0, 100.0 * (1.0 - alpha / 2.0)])
	return mean, float(lo), float(hi)


def _style_axis(ax: plt.Axes) -> None:
	ax.yaxis.grid(True, color='#D8D8D8', linewidth=0.5, alpha=0.9)
	ax.set_axisbelow(True)
	ax.tick_params(axis='both', length=3.0, width=0.6, pad=2)


def _add_panel_label(ax: plt.Axes, label: str) -> None:
	ax.text(
		-0.12,
		1.06,
		label,
		transform=ax.transAxes,
		fontsize=9.5,
		fontweight='bold',
		va='top',
		ha='left',
		color='#111111',
	)


def _grouped_offsets(n_groups: int, width: float) -> list[float]:
	return [(i - (n_groups - 1) / 2.0) * width for i in range(n_groups)]


def _load_success_cells(rows: list[dict[str, str]]) -> dict[tuple[str, str], list[bool]]:
	cells: dict[tuple[str, str], list[bool]] = defaultdict(list)
	for row in rows:
		if (row.get('run_status') or '').lower() == 'script_failed':
			continue
		task_id = row.get('task_id') or ''
		cond = _paper_condition(row)
		success = _parse_bool(row.get('strict_success'))
		if task_id in TASK_ORDER and cond in PAPER_ORDER and success is not None:
			cells[(task_id, cond)].append(success)
	return cells


def plot_fig2_strict_success(rows: list[dict[str, str]], output_dir: Path) -> None:
	"""Grouped bar chart: strict success rate with Wilson 95% CI."""
	cells = _load_success_cells(rows)
	tasks = TASK_ORDER
	n_conds = len(PAPER_ORDER)
	width = 0.11
	offsets = _grouped_offsets(n_conds, width)
	x = np.arange(len(tasks))

	fig, ax = plt.subplots(figsize=(7.0, 2.85))

	for i, cond in enumerate(PAPER_ORDER):
		rates: list[float] = []
		err_lo: list[float] = []
		err_hi: list[float] = []
		labels_kn: list[str] = []
		positions = x + offsets[i]

		for task_id in tasks:
			values = cells.get((task_id, cond), [])
			k = sum(values)
			n = len(values)
			rate = k / n if n else 0.0
			lo, hi = _wilson_ci(k, n)
			rates.append(rate)
			err_lo.append(rate - lo)
			err_hi.append(hi - rate)
			labels_kn.append(f'{k}/{n}' if n else '—')

		bars = ax.bar(
			positions,
			rates,
			width=width * 0.92,
			color=PALETTE[cond],
			edgecolor='white',
			linewidth=0.6,
			label=PAPER_LEGEND[cond],
			zorder=2,
		)
		ax.errorbar(
			positions,
			rates,
			yerr=[err_lo, err_hi],
			fmt='none',
			ecolor='#333333',
			elinewidth=0.7,
			capsize=2.2,
			capthick=0.7,
			zorder=3,
		)

		for bar, label, rate in zip(bars, labels_kn, rates, strict=False):
			y_text = min(rate + 0.06, 1.02)
			ax.text(
				bar.get_x() + bar.get_width() / 2.0,
				y_text,
				label,
				ha='center',
				va='bottom',
				fontsize=5.8,
				color='#333333',
				zorder=4,
			)

	_style_axis(ax)
	_add_panel_label(ax, 'a')
	ax.set_ylabel('Strict success rate')
	ax.set_ylim(0, 1.12)
	ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0, decimals=0))
	ax.set_xticks(x)
	ax.set_xticklabels([TASK_LABELS[t] for t in tasks])
	ax.legend(
		loc='upper center',
		bbox_to_anchor=(0.5, 1.28),
		ncol=3,
		columnspacing=0.9,
		handlelength=1.2,
		handletextpad=0.4,
	)
	fig.subplots_adjust(top=0.78, bottom=0.16, left=0.08, right=0.99)
	_save_pub(fig, output_dir, 'fig2')


def _load_process_cells(
	rows: list[dict[str, str]],
) -> dict[tuple[str, str, str], list[float]]:
	"""Keys: (task_id, paper_condition, metric_name)."""
	cells: dict[tuple[str, str, str], list[float]] = defaultdict(list)
	for row in rows:
		task_id = row.get('task_id') or ''
		cond = (row.get('paper_condition') or '').strip()
		if task_id not in TASK_ORDER or cond not in PAPER_ORDER:
			continue
		for metric in ('milestone_coverage', 'stall_burden'):
			val = _parse_float(row.get(metric))
			if val is not None:
				cells[(task_id, cond, metric)].append(val)
	return cells


def _mean_matrix(
	cells: dict[tuple[str, str, str], list[float]],
	metric: str,
) -> np.ndarray:
	matrix = np.full((len(TASK_ORDER), len(PAPER_ORDER)), np.nan)
	for ri, task_id in enumerate(TASK_ORDER):
		for ci, cond in enumerate(PAPER_ORDER):
			vals = cells.get((task_id, cond, metric), [])
			if vals:
				matrix[ri, ci] = float(np.mean(vals))
	return matrix


def _plot_coverage_heatmap(ax: plt.Axes, cells: dict[tuple[str, str, str], list[float]]) -> None:
	"""Panel (a): task x condition heatmap with mean coverage annotated in cells."""
	matrix = _mean_matrix(cells, 'milestone_coverage')
	cmap = mpl.colormaps['Blues'].copy()
	cmap.set_bad(color='#F5F5F5')

	im = ax.imshow(
		matrix,
		aspect='auto',
		cmap=cmap,
		vmin=0.60,
		vmax=1.0,
		origin='upper',
	)
	_add_panel_label(ax, 'a')

	for ri in range(len(TASK_ORDER)):
		for ci in range(len(PAPER_ORDER)):
			val = matrix[ri, ci]
			if math.isnan(val):
				label = '—'
				text_color = '#666666'
			else:
				label = f'{val * 100:.0f}%'
				text_color = 'white' if val >= 0.82 else '#222222'
			ax.text(ci, ri, label, ha='center', va='center', fontsize=7.5, color=text_color, fontweight='bold')

	ax.set_xticks(np.arange(len(PAPER_ORDER)))
	ax.set_xticklabels([PAPER_SHORT[c] for c in PAPER_ORDER], rotation=0)
	ax.set_yticks(np.arange(len(TASK_ORDER)))
	ax.set_yticklabels([TASK_LABELS[t] for t in TASK_ORDER])
	ax.set_xlabel('Configuration')
	ax.set_title('Milestone coverage (mean)', fontsize=8.0, pad=8, loc='left', color='#333333')
	ax.tick_params(top=False, right=False, length=0)

	cbar = ax.figure.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
	cbar.ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0, decimals=0))
	cbar.ax.tick_params(labelsize=6.5)
	cbar.set_label('Coverage', fontsize=7.0)


def _plot_stall_point_range(ax: plt.Axes, cells: dict[tuple[str, str, str], list[float]]) -> None:
	"""Panel (b): stall burden mean + bootstrap 95% CI; per-condition colors, R-A solid green."""
	tasks = TASK_ORDER
	x = np.arange(len(tasks))
	offsets = _grouped_offsets(len(PAPER_ORDER), 0.075)

	for i, cond in enumerate(PAPER_ORDER):
		xs: list[float] = []
		means: list[float] = []
		err_lo: list[float] = []
		err_hi: list[float] = []
		for task_idx, task_id in enumerate(tasks):
			vals = cells.get((task_id, cond, 'stall_burden'), [])
			mean, lo, hi = _bootstrap_mean_ci(vals, seed=hash((task_id, cond, 'stall')) % 10_000)
			xs.append(float(task_idx + offsets[i]))
			means.append(mean)
			err_lo.append(mean - lo)
			err_hi.append(hi - mean)

		color = PALETTE[cond]
		is_hero = cond == 'R-A'
		ax.errorbar(
			xs,
			means,
			yerr=[err_lo, err_hi],
			fmt='o',
			color=color,
			markerfacecolor=color if is_hero else 'white',
			markeredgecolor=color,
			markersize=6.0 if is_hero else 4.2,
			markeredgewidth=1.5 if is_hero else 1.0,
			elinewidth=1.2 if is_hero else 0.85,
			capsize=2.4 if is_hero else 1.8,
			capthick=1.0 if is_hero else 0.65,
			label=PAPER_SHORT[cond],
			zorder=6 if is_hero else 3 + i,
			alpha=1.0,
		)

	_style_axis(ax)
	_add_panel_label(ax, 'b')
	ax.set_ylabel('Stall burden')
	ax.set_title('Stall burden (mean, bootstrap 95% CI)', fontsize=8.0, pad=22, loc='left', color='#333333')
	ax.set_ylim(0, 0.92)
	ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0, decimals=0))
	ax.set_xticks(x)
	ax.set_xticklabels([TASK_LABELS[t] for t in tasks])
	ax.legend(
		loc='lower left',
		bbox_to_anchor=(0.0, 1.02),
		ncol=3,
		columnspacing=0.45,
		handlelength=1.2,
		handletextpad=0.25,
		fontsize=6.5,
		borderaxespad=0.0,
	)


def plot_fig5_process_metrics(rows: list[dict[str, str]], output_dir: Path) -> None:
	"""Conclusion-driven process figure: coverage heatmap + stall point-range."""
	cells = _load_process_cells(rows)
	fig, axes = plt.subplots(1, 2, figsize=(7.4, 3.1), gridspec_kw={'width_ratios': [1.05, 1.35]})

	_plot_coverage_heatmap(axes[0], cells)
	_plot_stall_point_range(axes[1], cells)

	fig.subplots_adjust(top=0.88, bottom=0.14, left=0.09, right=0.96, wspace=0.42)
	_save_pub(fig, output_dir, 'fig5')


def main() -> int:
	parser = argparse.ArgumentParser(description='Generate Nature-style fig2 and fig5.')
	parser.add_argument('--data-dir', type=Path, default=_default_data_dir())
	parser.add_argument(
		'--output-dir',
		type=Path,
		default=Path(__file__).resolve().parent / 'figures',
	)
	args = parser.parse_args()

	all_runs_path = args.data_dir / 'all_runs.csv'
	milestone_path = args.data_dir / 'milestone_summary.csv'
	if not all_runs_path.exists():
		raise FileNotFoundError(f'Missing {all_runs_path}')
	if not milestone_path.exists():
		raise FileNotFoundError(f'Missing {milestone_path}')

	_setup_nature_style()
	run_rows = _read_csv(all_runs_path)
	milestone_rows = _read_csv(milestone_path)

	print(f'Loaded {len(run_rows)} runs, {len(milestone_rows)} milestone rows')
	print('Plotting fig2 (strict success, Wilson 95% CI) ...')
	plot_fig2_strict_success(run_rows, args.output_dir)
	print('Plotting fig5 (coverage heatmap + stall point-range) ...')
	plot_fig5_process_metrics(milestone_rows, args.output_dir)
	print(f'Done → {args.output_dir.resolve()}')
	return 0


if __name__ == '__main__':
	raise SystemExit(main())
