"""Hospital cadence sweep: strict success + stall burden (dual-axis line chart).

Scheme B for the PRICAI compact paper — shows non-monotonic replan effects on
the clearest diagnostic task. Values match Table 2 / Table 4 in the compact draft.

Usage:
    uv run python paper/pricai2026/plot_hospital_cadence.py
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

# Paper order along the cadence sweep axis
CONDITIONS = ['E', 'I', 'R-1', 'R-3', 'R-5', 'R-A']
X_LABELS = [
	'E\n(no nav.)',
	'I\n(one-shot)',
	'R-1\n(every step)',
	'R-3\n(every 3)',
	'R-5\n(every 5)',
	'R-A\n(adaptive)',
]

# Hospital strict success (k/10) — compact paper Table 2
STRICT_SUCCESS = [3 / 10, 10 / 10, 10 / 10, 7 / 10, 9 / 10, 10 / 10]
# Hospital median stall burden — compact paper Table 4
STALL_BURDEN = [0.71, 0.29, 0.44, 0.50, 0.44, 0.17]

PALETTE = {
	'success': '#2E6B8E',
	'stall': '#D4845A',
	'hero': '#2E8B7A',
}


def _setup_style() -> None:
	mpl.rcParams.update(
		{
			'font.family': 'sans-serif',
			'font.sans-serif': ['Arial', 'Helvetica', 'DejaVu Sans', 'sans-serif'],
			'svg.fonttype': 'none',
			'pdf.fonttype': 42,
			'ps.fonttype': 42,
			'font.size': 8.0,
			'axes.titlesize': 8.5,
			'axes.labelsize': 8.5,
			'xtick.labelsize': 7.0,
			'ytick.labelsize': 7.5,
			'axes.linewidth': 0.7,
			'axes.spines.top': False,
			'figure.facecolor': 'white',
			'axes.facecolor': 'white',
		}
	)


def _save(fig: plt.Figure, output_dir: Path, stem: str) -> None:
	output_dir.mkdir(parents=True, exist_ok=True)
	fig.savefig(output_dir / f'{stem}.pdf', bbox_inches='tight', facecolor='white')
	fig.savefig(output_dir / f'{stem}.png', dpi=600, bbox_inches='tight', facecolor='white')
	plt.close(fig)


def plot_hospital_cadence(output_dir: Path) -> None:
	_setup_style()
	x = np.arange(len(CONDITIONS))

	fig, ax1 = plt.subplots(figsize=(6.2, 2.9))

	# Left axis: strict success rate
	line_success = ax1.plot(
		x,
		STRICT_SUCCESS,
		color=PALETTE['success'],
		marker='o',
		markersize=7.0,
		markerfacecolor='white',
		markeredgewidth=1.6,
		markeredgecolor=PALETTE['success'],
		linewidth=1.8,
		label='Strict success rate',
		zorder=3,
	)
	ax1.set_ylabel('Strict success rate', color=PALETTE['success'])
	ax1.set_ylim(0.0, 1.08)
	ax1.yaxis.set_major_formatter(mticker.PercentFormatter(1.0, decimals=0))
	ax1.tick_params(axis='y', labelcolor=PALETTE['success'])
	ax1.grid(axis='y', color='#D8D8D8', linewidth=0.5, alpha=0.9)
	ax1.set_axisbelow(True)

	# Annotate k/n above success points
	kn_labels = ['3/10', '10/10', '10/10', '7/10', '9/10', '10/10']
	for xi, yi, label in zip(x, STRICT_SUCCESS, kn_labels, strict=False):
		ax1.annotate(
			label,
			xy=(xi, yi),
			xytext=(0, 8),
			textcoords='offset points',
			ha='center',
			va='bottom',
			fontsize=6.5,
			color=PALETTE['success'],
		)

	# Right axis: stall burden
	ax2 = ax1.twinx()
	line_stall = ax2.plot(
		x,
		STALL_BURDEN,
		color=PALETTE['stall'],
		marker='s',
		markersize=6.0,
		markerfacecolor='white',
		markeredgewidth=1.4,
		markeredgecolor=PALETTE['stall'],
		linewidth=1.6,
		linestyle='--',
		label='Median stall burden',
		zorder=2,
	)
	ax2.set_ylabel('Median stall burden', color=PALETTE['stall'])
	ax2.set_ylim(0.0, 0.85)
	ax2.yaxis.set_major_formatter(mticker.PercentFormatter(1.0, decimals=0))
	ax2.tick_params(axis='y', labelcolor=PALETTE['stall'])
	ax2.spines['top'].set_visible(False)

	# Highlight R-A (last point)
	ax1.scatter(
		[x[-1]],
		[STRICT_SUCCESS[-1]],
		s=120,
		facecolors=PALETTE['hero'],
		edgecolors=PALETTE['hero'],
		zorder=5,
		linewidths=0,
	)
	ax2.scatter(
		[x[-1]],
		[STALL_BURDEN[-1]],
		s=90,
		facecolors=PALETTE['hero'],
		edgecolors=PALETTE['hero'],
		marker='s',
		zorder=5,
		linewidths=0,
	)

	ax1.set_xticks(x)
	ax1.set_xticklabels(X_LABELS)
	ax1.set_xlabel('Navigator cadence (Hospital lookup)')

	lines = line_success + line_stall
	labels = [line.get_label() for line in lines]
	ax1.legend(
		lines,
		labels,
		loc='upper center',
		bbox_to_anchor=(0.5, 1.22),
		ncol=2,
		frameon=False,
		fontsize=7.0,
		handlelength=2.0,
	)

	fig.subplots_adjust(top=0.82, bottom=0.20, left=0.10, right=0.90)
	_save(fig, output_dir, 'fig_hospital_cadence')


def main() -> int:
	parser = argparse.ArgumentParser(description='Plot Hospital cadence sweep (scheme B).')
	parser.add_argument(
		'--output-dir',
		type=Path,
		default=Path(__file__).resolve().parent / 'figures',
	)
	args = parser.parse_args()
	plot_hospital_cadence(args.output_dir)
	print(f'Wrote fig_hospital_cadence.pdf/png → {args.output_dir.resolve()}')
	return 0


if __name__ == '__main__':
	raise SystemExit(main())
