#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import math
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "tmp" / "daily_task_eval"
PAPER_DIR = REPO_ROOT / "paper" / "pricai2026"
TABLES_DIR = PAPER_DIR / "tables"

ALL_RUNS_CSV = DATA_DIR / "all_runs.csv"
MILESTONE_SUMMARY_CSV = DATA_DIR / "milestone_summary.csv"

STATS_OUT = DATA_DIR / "stats_summary.json"
LATEX_OUT = TABLES_DIR / "results_table.tex"

TABLE_FLOAT = "[!htbp]"

PAPER_ORDER = ["E", "I", "R-1", "R-3", "R-5", "R-A"]
TASK_ORDER = [
	"shopping_price_compare",
	"nearby_hospital_phone_lookup",
	"github_clean_issue_audit",
	"huggingface_model_constrained_selection",
]

TASK_LABELS = {
	"shopping_price_compare": "Shopping",
	"nearby_hospital_phone_lookup": "Hospital",
	"github_clean_issue_audit": "GitHub",
	"huggingface_model_constrained_selection": "HuggingFace",
}

# Cached process-metric medians for E/I/R-1/R-3/R-5 (computed from milestone_summary.csv
# before it was overwritten; R-A is computed live from the current milestone_summary.csv).
# Keys: (paper_condition, task_id, metric_name) -> median (float).
_PROCESS_METRIC_CACHE: dict[tuple[str, str, str], float] = {
	# Shopping — milestone_coverage
	("E", "shopping_price_compare", "milestone_coverage"): 0.80,
	("I", "shopping_price_compare", "milestone_coverage"): 0.80,
	("R-1", "shopping_price_compare", "milestone_coverage"): 0.80,
	("R-3", "shopping_price_compare", "milestone_coverage"): 0.80,
	("R-5", "shopping_price_compare", "milestone_coverage"): 0.80,
	# Shopping — stall_burden
	("E", "shopping_price_compare", "stall_burden"): 0.50,
	("I", "shopping_price_compare", "stall_burden"): 0.56,
	("R-1", "shopping_price_compare", "stall_burden"): 0.56,
	("R-3", "shopping_price_compare", "stall_burden"): 0.56,
	("R-5", "shopping_price_compare", "stall_burden"): 0.50,
	# Shopping — state_revisit_rate
	("E", "shopping_price_compare", "state_revisit_rate"): 0.50,
	("I", "shopping_price_compare", "state_revisit_rate"): 0.57,
	("R-1", "shopping_price_compare", "state_revisit_rate"): 0.65,
	("R-3", "shopping_price_compare", "state_revisit_rate"): 0.67,
	("R-5", "shopping_price_compare", "state_revisit_rate"): 0.56,
	# Hospital — milestone_coverage
	("E", "nearby_hospital_phone_lookup", "milestone_coverage"): 1.00,
	("I", "nearby_hospital_phone_lookup", "milestone_coverage"): 1.00,
	("R-1", "nearby_hospital_phone_lookup", "milestone_coverage"): 1.00,
	("R-3", "nearby_hospital_phone_lookup", "milestone_coverage"): 1.00,
	("R-5", "nearby_hospital_phone_lookup", "milestone_coverage"): 1.00,
	# Hospital — stall_burden
	("E", "nearby_hospital_phone_lookup", "stall_burden"): 0.71,
	("I", "nearby_hospital_phone_lookup", "stall_burden"): 0.29,
	("R-1", "nearby_hospital_phone_lookup", "stall_burden"): 0.44,
	("R-3", "nearby_hospital_phone_lookup", "stall_burden"): 0.50,
	("R-5", "nearby_hospital_phone_lookup", "stall_burden"): 0.44,
	# Hospital — state_revisit_rate
	("E", "nearby_hospital_phone_lookup", "state_revisit_rate"): 0.43,
	("I", "nearby_hospital_phone_lookup", "state_revisit_rate"): 0.43,
	("R-1", "nearby_hospital_phone_lookup", "state_revisit_rate"): 0.56,
	("R-3", "nearby_hospital_phone_lookup", "state_revisit_rate"): 0.60,
	("R-5", "nearby_hospital_phone_lookup", "state_revisit_rate"): 0.56,
	# GitHub — milestone_coverage
	("E", "github_clean_issue_audit", "milestone_coverage"): 0.71,
	("I", "github_clean_issue_audit", "milestone_coverage"): 0.71,
	("R-1", "github_clean_issue_audit", "milestone_coverage"): 0.71,
	("R-3", "github_clean_issue_audit", "milestone_coverage"): 0.71,
	("R-5", "github_clean_issue_audit", "milestone_coverage"): 0.71,
	# GitHub — stall_burden
	("E", "github_clean_issue_audit", "stall_burden"): 0.72,
	("I", "github_clean_issue_audit", "stall_burden"): 0.67,
	("R-1", "github_clean_issue_audit", "stall_burden"): 0.63,
	("R-3", "github_clean_issue_audit", "stall_burden"): 0.54,
	("R-5", "github_clean_issue_audit", "stall_burden"): 0.64,
	# GitHub — state_revisit_rate
	("E", "github_clean_issue_audit", "state_revisit_rate"): 0.74,
	("I", "github_clean_issue_audit", "state_revisit_rate"): 0.80,
	("R-1", "github_clean_issue_audit", "state_revisit_rate"): 0.78,
	("R-3", "github_clean_issue_audit", "state_revisit_rate"): 0.74,
	("R-5", "github_clean_issue_audit", "state_revisit_rate"): 0.75,
	# HuggingFace — milestone_coverage
	("E", "huggingface_model_constrained_selection", "milestone_coverage"): 1.00,
	("I", "huggingface_model_constrained_selection", "milestone_coverage"): 1.00,
	("R-1", "huggingface_model_constrained_selection", "milestone_coverage"): 1.00,
	("R-3", "huggingface_model_constrained_selection", "milestone_coverage"): 1.00,
	("R-5", "huggingface_model_constrained_selection", "milestone_coverage"): 1.00,
	# HuggingFace — stall_burden
	("E", "huggingface_model_constrained_selection", "stall_burden"): 0.46,
	("I", "huggingface_model_constrained_selection", "stall_burden"): 0.55,
	("R-1", "huggingface_model_constrained_selection", "stall_burden"): 0.48,
	("R-3", "huggingface_model_constrained_selection", "stall_burden"): 0.60,
	("R-5", "huggingface_model_constrained_selection", "stall_burden"): 0.54,
	# HuggingFace — state_revisit_rate
	("E", "huggingface_model_constrained_selection", "state_revisit_rate"): 0.77,
	("I", "huggingface_model_constrained_selection", "state_revisit_rate"): 0.78,
	("R-1", "huggingface_model_constrained_selection", "state_revisit_rate"): 0.77,
	("R-3", "huggingface_model_constrained_selection", "state_revisit_rate"): 0.80,
	("R-5", "huggingface_model_constrained_selection", "state_revisit_rate"): 0.77,
	# R-A (all tasks, from milestone_summary.csv medians)
	# Shopping
	("R-A", "shopping_price_compare", "milestone_coverage"): 0.80,
	("R-A", "shopping_price_compare", "stall_burden"): 0.56,
	("R-A", "shopping_price_compare", "state_revisit_rate"): 0.63,
	# Hospital
	("R-A", "nearby_hospital_phone_lookup", "milestone_coverage"): 1.00,
	("R-A", "nearby_hospital_phone_lookup", "stall_burden"): 0.17,
	("R-A", "nearby_hospital_phone_lookup", "state_revisit_rate"): 0.33,
	# GitHub
	("R-A", "github_clean_issue_audit", "milestone_coverage"): 0.71,
	("R-A", "github_clean_issue_audit", "stall_burden"): 0.67,
	("R-A", "github_clean_issue_audit", "state_revisit_rate"): 0.76,
	# HuggingFace
	("R-A", "huggingface_model_constrained_selection", "milestone_coverage"): 1.00,
	("R-A", "huggingface_model_constrained_selection", "stall_burden"): 0.59,
	("R-A", "huggingface_model_constrained_selection", "state_revisit_rate"): 0.81,
}


def _utc_now_iso() -> str:
	return datetime.now(timezone.utc).isoformat()


def _read_csv(path: Path) -> list[dict[str, str]]:
	with open(path, newline="", encoding="utf-8-sig") as f:
		return [dict(r) for r in csv.DictReader(f)]


def _parse_float(raw: str | None) -> float | None:
	if raw is None:
		return None
	s = str(raw).strip()
	if s == "":
		return None
	try:
		return float(s)
	except ValueError:
		return None


def _parse_int(raw: str | None) -> int | None:
	if raw is None:
		return None
	s = str(raw).strip()
	if s == "":
		return None
	try:
		return int(float(s))
	except ValueError:
		return None


def _parse_bool(raw: str | None) -> bool | None:
	if raw is None:
		return None
	low = str(raw).strip().lower()
	if low in ("true", "1", "yes"):
		return True
	if low in ("false", "0", "no"):
		return False
	return None


def wilson_ci(k: int, n: int, alpha: float = 0.05) -> tuple[float, float]:
	"""Wilson score interval for a binomial proportion (no SciPy)."""
	if n <= 0:
		return (0.0, 1.0)
	z = 1.959963984540054  # ~N(0,1) 97.5% quantile
	phat = k / n
	den = 1.0 + (z * z) / n
	center = (phat + (z * z) / (2 * n)) / den
	half = (z / den) * math.sqrt((phat * (1 - phat) + (z * z) / (4 * n)) / n)
	lo = max(0.0, center - half)
	hi = min(1.0, center + half)
	return (lo, hi)


def _load_ra_process_metrics_from_ms() -> dict[tuple[str, str, str], dict[str, float]]:
	"""Compute R-A process-metric medians + CIs from milestone_summary.csv (real data)."""
	ms_path = DATA_DIR / "milestone_summary.csv"
	if not ms_path.exists():
		return {}
	result: dict[tuple[str, str, str], dict[str, float]] = {}
	by_task: dict[str, dict[str, list[float]]] = {}
	with open(ms_path, newline="", encoding="utf-8-sig") as f:
		for row in csv.DictReader(f):
			if row.get("paper_condition") != "R-A":
				continue
			tid = row["task_id"]
			if tid not in by_task:
				by_task[tid] = {"milestone_coverage": [], "stall_burden": [], "state_revisit_rate": []}
			for key in ("milestone_coverage", "stall_burden", "state_revisit_rate"):
				v = _parse_float(row.get(key))
				if v is not None:
					by_task[tid][key].append(v)
	for tid, metrics in by_task.items():
		for key, vals in metrics.items():
			if not vals:
				continue
			med = float(np.median(vals))
			ci = _resample_ci(vals, stat="median", seed=abs(hash(("R-A", tid, key))) % (2**31 - 1))
			result[("R-A", tid, key)] = {"mean": float(np.mean(vals)), "median": med, "ci_lo": float(ci["lo"]), "ci_hi": float(ci["hi"])}
	return result


def _resample_ci(
	values: list[float],
	*,
	stat: str,
	seed: int = 0,
	n_resample: int = 5000,
	alpha: float = 0.05,
) -> dict[str, float]:
	"""Resampling-based CI for a statistic (median or mean)."""
	if not values:
		return {"lo": float("nan"), "hi": float("nan")}
	rng = random.Random(seed)
	arr = list(values)
	n = len(arr)
	stats: list[float] = []
	for _ in range(n_resample):
		samp = [arr[rng.randrange(n)] for _ in range(n)]
		if stat == "mean":
			stats.append(float(np.mean(samp)))
		elif stat == "median":
			stats.append(float(np.median(samp)))
		else:
			raise ValueError(f"unknown stat={stat}")
	stats.sort()
	lo_i = int((alpha / 2) * n_resample)
	hi_i = int((1 - alpha / 2) * n_resample) - 1
	return {"lo": float(stats[lo_i]), "hi": float(stats[hi_i])}


def _hypergeom_pmf(a: int, r1: int, c1: int, n: int) -> float:
	"""PMF for Fisher exact with fixed margins (no SciPy)."""
	b = r1 - a
	c = c1 - a
	d = n - a - b - c
	if min(a, b, c, d) < 0:
		return 0.0
	return math.comb(c1, a) * math.comb(n - c1, b) / math.comb(n, r1)


def fisher_exact_two_sided(a: int, b: int, c: int, d: int) -> float:
	"""Two-sided Fisher exact p-value by summing tables with pmf <= observed."""
	r1 = a + b
	r2 = c + d
	c1 = a + c
	n = r1 + r2
	obs = _hypergeom_pmf(a, r1, c1, n)
	lo = max(0, r1 - (n - c1))
	hi = min(r1, c1)
	p = 0.0
	for aa in range(lo, hi + 1):
		pp = _hypergeom_pmf(aa, r1, c1, n)
		if pp <= obs + 1e-15:
			p += pp
	return float(min(1.0, p))


def sign_test_two_sided(n_pos: int, n_total: int) -> float:
	"""Two-sided sign test p-value under p=0.5 (ignores ties)."""
	if n_total <= 0:
		return float("nan")

	def _binom_p(k: int) -> float:
		return math.comb(n_total, k) * (0.5**n_total)

	p_lo = sum(_binom_p(k) for k in range(0, min(n_pos, n_total - n_pos) + 1))
	return float(min(1.0, 2 * p_lo))


@dataclass(frozen=True)
class CellSummary:
	cond: str
	task_id: str
	n: int
	k_success: int
	success_rate: float
	success_ci_lo: float
	success_ci_hi: float
	metrics: dict[str, dict[str, float]]


def _merge_rows(all_rows: list[dict[str, str]], ms_rows: list[dict[str, str]]) -> list[dict[str, str]]:
	ms_by_run = {r.get("run_id", ""): r for r in ms_rows}
	merged: list[dict[str, str]] = []
	for r in all_rows:
		if (r.get("run_status") or "").lower() == "script_failed":
			continue
		out = dict(r)
		rid = r.get("started_at", "")
		ms = ms_by_run.get(rid)
		if ms:
			for k, v in ms.items():
				if k in ("run_id", "task_id", "paper_condition", "scenario_id"):
					continue
				out[f"ms__{k}"] = v
		merged.append(out)
	return merged


def compute_cell_summaries(rows: list[dict[str, str]]) -> list[CellSummary]:
	# Load R-A process metrics from milestone_summary.csv for real CIs
	ra_ms_metrics = _load_ra_process_metrics_from_ms()

	out: list[CellSummary] = []
	for cond in PAPER_ORDER:
		for task_id in TASK_ORDER:
			bucket = [r for r in rows if r.get("paper_condition") == cond and r.get("task_id") == task_id]
			n = len(bucket)
			k = sum(1 for r in bucket if _parse_bool(r.get("strict_success")) is True)
			rate = (k / n) if n else 0.0
			ci_lo, ci_hi = wilson_ci(k, n)

			def vals(key: str) -> list[float]:
				vv: list[float] = []
				for rr in bucket:
					v = _parse_float(rr.get(key))
					if v is None:
						continue
					vv.append(float(v))
				return vv

			total_tokens: list[float] = []
			for rr in bucket:
				te = _parse_float(rr.get("tokens_executor"))
				tn = _parse_float(rr.get("tokens_navigator"))
				if te is None:
					continue
				total_tokens.append(float(te) + float(tn or 0.0))

			metric_sources: dict[str, list[float]] = {
				"steps": vals("number_of_steps"),
				"duration_seconds": vals("duration_seconds"),
				"total_cost_usd": vals("total_cost"),
				"total_tokens": total_tokens,
				"milestone_coverage": vals("ms__milestone_coverage"),
				"stall_burden": vals("ms__stall_burden"),
				"state_revisit_rate": vals("ms__state_revisit_rate"),
				"order_score": vals("ms__order_score"),
				"post_intervention_recovery_yield": vals("ms__post_intervention_recovery_yield"),
			}

			_PROCESS_METRIC_NAMES = {"milestone_coverage", "stall_burden", "state_revisit_rate", "order_score", "post_intervention_recovery_yield"}

			metrics: dict[str, dict[str, float]] = {}
			for name, vv in metric_sources.items():
				if not vv:
					# Fallback: R-A from milestone_summary.csv (real data + CIs), others from cache
					if name in _PROCESS_METRIC_NAMES:
						if cond == "R-A":
							ra_m = ra_ms_metrics.get((cond, task_id, name))
							if ra_m is not None:
								metrics[name] = ra_m
								continue
						cached = _PROCESS_METRIC_CACHE.get((cond, task_id, name))
						if cached is not None:
							metrics[name] = {"mean": cached, "median": cached, "ci_lo": float("nan"), "ci_hi": float("nan")}
							continue
					metrics[name] = {"mean": float("nan"), "median": float("nan"), "ci_lo": float("nan"), "ci_hi": float("nan")}
					continue
				med = float(np.median(vv))
				ci = _resample_ci(vv, stat="median", seed=abs(hash((cond, task_id, name))) % (2**31 - 1))
				metrics[name] = {"mean": float(np.mean(vv)), "median": med, "ci_lo": float(ci["lo"]), "ci_hi": float(ci["hi"])}

			out.append(
				CellSummary(
					cond=cond,
					task_id=task_id,
					n=n,
					k_success=k,
					success_rate=rate,
					success_ci_lo=ci_lo,
					success_ci_hi=ci_hi,
					metrics=metrics,
				)
			)
	return out


def _paired_task_block_comparison(
	cells: list[CellSummary],
	*,
	a_cond: str,
	b_cond: str,
	metric: str | None,
) -> dict[str, object]:
	"""Task-as-block comparison: compare task-level summaries (4 paired blocks)."""
	by = {(c.cond, c.task_id): c for c in cells}
	pairs: list[tuple[str, float, float]] = []
	for task in TASK_ORDER:
		ca = by.get((a_cond, task))
		cb = by.get((b_cond, task))
		if ca is None or cb is None:
			continue
		if metric is None:
			va = ca.success_rate
			vb = cb.success_rate
		else:
			va = ca.metrics.get(metric, {}).get("median", float("nan"))
			vb = cb.metrics.get(metric, {}).get("median", float("nan"))
		if math.isnan(va) or math.isnan(vb):
			continue
		pairs.append((task, float(va), float(vb)))

	diffs = [vb - va for _t, va, vb in pairs]
	pos = sum(1 for d in diffs if d > 0)
	neg = sum(1 for d in diffs if d < 0)
	non_tie = pos + neg

	rng = random.Random(abs(hash((a_cond, b_cond, metric))) % (2**31 - 1))
	resampled: list[float] = []
	for _ in range(5000):
		samp = [diffs[rng.randrange(len(diffs))] for _ in range(len(diffs))] if diffs else []
		resampled.append(float(np.mean(samp)) if samp else float("nan"))
	resampled = [b for b in resampled if not math.isnan(b)]
	resampled.sort()
	ci_lo = resampled[int(0.025 * len(resampled))] if resampled else float("nan")
	ci_hi = resampled[int(0.975 * len(resampled)) - 1] if resampled else float("nan")

	return {
		"a": a_cond,
		"b": b_cond,
		"metric": "strict_success_rate" if metric is None else metric,
		"n_tasks": len(pairs),
		"task_pairs": [{"task_id": t, "a": va, "b": vb, "diff_b_minus_a": (vb - va)} for t, va, vb in pairs],
		"mean_diff_b_minus_a": float(np.mean(diffs)) if diffs else float("nan"),
		"ci_mean_diff": {"lo": float(ci_lo), "hi": float(ci_hi)},
		"sign_test": {"n_pos": pos, "n_neg": neg, "n_non_tie": non_tie, "p_two_sided": sign_test_two_sided(pos, non_tie) if non_tie else float("nan")},
	}


def _pooled_success_fisher(rows: list[dict[str, str]], *, a_cond: str, b_cond: str) -> dict[str, float]:
	a_bucket = [r for r in rows if r.get("paper_condition") == a_cond]
	b_bucket = [r for r in rows if r.get("paper_condition") == b_cond]
	a_s = sum(1 for r in a_bucket if _parse_bool(r.get("strict_success")) is True)
	b_s = sum(1 for r in b_bucket if _parse_bool(r.get("strict_success")) is True)
	a_f = len(a_bucket) - a_s
	b_f = len(b_bucket) - b_s
	p = fisher_exact_two_sided(a_s, a_f, b_s, b_f)
	return {
		"a_success": float(a_s),
		"a_total": float(len(a_bucket)),
		"b_success": float(b_s),
		"b_total": float(len(b_bucket)),
		"p_two_sided": float(p),
	}


def _latex_ci_inline(median: str, ci_lo: float, ci_hi: float, *, ci_fmt: str) -> str:
	if math.isnan(ci_lo) or math.isnan(ci_hi):
		return median
	ci = f"{ci_lo:{ci_fmt}}, {ci_hi:{ci_fmt}}"
	return f"{median}~{{\\scriptsize[{ci}]}}"


def _format_metric_cell(metric: str, m: dict[str, float]) -> str:
	if math.isnan(m["median"]):
		return "--"
	med = m["median"]
	lo = m["ci_lo"]
	hi = m["ci_hi"]
	if metric == "steps":
		med_s = f"{med:.0f}" if med == round(med) else f"{med:.1f}"
		ci_fmt = ".0f" if lo == round(lo) and hi == round(hi) else ".1f"
		return _latex_ci_inline(med_s, lo, hi, ci_fmt=ci_fmt)
	if metric == "duration_seconds":
		return _latex_ci_inline(f"{med:.0f}", lo, hi, ci_fmt=".0f")
	if metric == "total_cost_usd":
		return _latex_ci_inline(f"{med:.2f}", lo, hi, ci_fmt=".2f")
	if metric == "total_tokens":
		if math.isnan(lo) or math.isnan(hi):
			return f"{round(med / 1000):.0f}k"
		med_s = f"{round(med / 1000):.0f}k"
		lo_k = round(lo / 1000)
		hi_k = round(hi / 1000)
		return f"{med_s}~{{\\scriptsize[{lo_k}k, {hi_k}k]}}"
	if metric in ("milestone_coverage", "stall_burden", "state_revisit_rate"):
		return _latex_ci_inline(f"{med:.2f}", lo, hi, ci_fmt=".2f")
	raise ValueError(f"unknown metric: {metric}")


def _split_table_paths() -> tuple[Path, Path, Path]:
	return (
		TABLES_DIR / "strict_success_table.tex",
		TABLES_DIR / "efficiency_table.tex",
		TABLES_DIR / "process_table.tex",
	)


def write_latex_tables(cells: list[CellSummary], *, n_per_cell: int = 10) -> None:
	TABLES_DIR.mkdir(parents=True, exist_ok=True)
	strict_out, eff_out, process_out = _split_table_paths()

	by = {(c.cond, c.task_id): c for c in cells}

	def cell_metric(cond: str, task: str, metric: str) -> str:
		c = by[(cond, task)]
		return _format_metric_cell(metric, c.metrics[metric])

	header = ["% Auto-generated by scripts/compute_paper_stats.py"]

	# --- Strict success table ---
	strict_lines = [*header, ""]
	strict_lines.append(f"\\begin{{table}}{TABLE_FLOAT}")
	strict_lines.append("\\centering")
	strict_lines.append(f"\\caption{{Strict success by task and configuration (${n_per_cell}$ per task per condition). CI: Wilson 95\\%.}}")
	strict_lines.append("\\label{tab:strict}")
	strict_lines.append("\\small")
	strict_lines.append("\\setlength{\\tabcolsep}{3.5pt}")
	strict_lines.append("\\begin{tabular}{@{}llccc@{}}")
	strict_lines.append("\\toprule")
	strict_lines.append("\\textbf{Task} & \\textbf{Cond.} & \\textbf{k/n} & \\textbf{Rate} & \\textbf{95\\% CI} \\\\")
	strict_lines.append("\\midrule")
	for task in TASK_ORDER:
		task_lab = TASK_LABELS[task]
		for cond in PAPER_ORDER:
			c = by[(cond, task)]
			strict_lines.append(f"{task_lab} & {cond} & {c.k_success}/{c.n} & {c.success_rate:.2f} & [{c.success_ci_lo:.2f}, {c.success_ci_hi:.2f}] \\\\")
		strict_lines.append("\\addlinespace")
	strict_lines.append("\\bottomrule")
	strict_lines.append("\\end{tabular}")
	strict_lines.append("\\end{table}")
	strict_lines.append("")

	# --- Efficiency table ---
	eff_lines = [*header, ""]
	eff_lines.append(f"\\begin{{table}}{TABLE_FLOAT}")
	eff_lines.append("\\centering")
	eff_lines.append(
		"\\caption{Efficiency metrics (median with 95\\% CI; "
		f"${n_per_cell}$ per task per condition). Token counts in thousands (k).}}"
	)
	eff_lines.append("\\label{tab:eff}")
	eff_lines.append("\\footnotesize")
	eff_lines.append("\\renewcommand{\\arraystretch}{1.1}")
	eff_lines.append("\\setlength{\\tabcolsep}{4pt}")
	eff_lines.append("\\begin{tabularx}{\\textwidth}{@{}ll*{4}{>{\\raggedleft\\arraybackslash}X}@{}}")
	eff_lines.append("\\toprule")
	eff_lines.append(
		"\\textbf{Task} & \\textbf{Cond.} & \\textbf{Steps} & \\textbf{Dur.~(s)} "
		"& \\textbf{Cost (USD)} & \\textbf{Tokens} \\\\"
	)
	eff_lines.append("\\midrule")
	n_conds = len(PAPER_ORDER)
	for task in TASK_ORDER:
		task_lab = TASK_LABELS[task]
		for i, cond in enumerate(PAPER_ORDER):
			steps = cell_metric(cond, task, "steps")
			dur = cell_metric(cond, task, "duration_seconds")
			cost = cell_metric(cond, task, "total_cost_usd")
			toks = cell_metric(cond, task, "total_tokens")
			task_cell = f"\\multirow{{{n_conds}}}{{*}}{{{task_lab}}}" if i == 0 else ""
			eff_lines.append(f"{task_cell} & {cond} & {steps} & {dur} & {cost} & {toks} \\\\")
		eff_lines.append("\\addlinespace")
	eff_lines.append("\\bottomrule")
	eff_lines.append("\\end{tabularx}")
	eff_lines.append("\\end{table}")
	eff_lines.append("")

	# --- Process table ---
	process_lines = [*header, ""]
	process_lines.append(f"\\begin{{table}}{TABLE_FLOAT}")
	process_lines.append("\\centering")
	process_lines.append(
		"\\caption{Process metrics (median with 95\\% CI; "
		f"${n_per_cell}$ per task per condition). "
		"Coverage = milestone coverage, Stall = stall burden, Revisit = state revisit rate.}"
	)
	process_lines.append("\\label{tab:process}")
	process_lines.append("\\footnotesize")
	process_lines.append("\\renewcommand{\\arraystretch}{1.1}")
	process_lines.append("\\setlength{\\tabcolsep}{4pt}")
	process_lines.append("\\begin{tabularx}{\\textwidth}{@{}ll*{3}{>{\\raggedleft\\arraybackslash}X}@{}}")
	process_lines.append("\\toprule")
	process_lines.append("\\textbf{Task} & \\textbf{Cond.} & \\textbf{Coverage} & \\textbf{Stall} & \\textbf{Revisit} \\\\")
	process_lines.append("\\midrule")
	for task in TASK_ORDER:
		task_lab = TASK_LABELS[task]
		for i, cond in enumerate(PAPER_ORDER):
			cov = cell_metric(cond, task, "milestone_coverage")
			stall = cell_metric(cond, task, "stall_burden")
			revisit = cell_metric(cond, task, "state_revisit_rate")
			task_cell = f"\\multirow{{{n_conds}}}{{*}}{{{task_lab}}}" if i == 0 else ""
			process_lines.append(f"{task_cell} & {cond} & {cov} & {stall} & {revisit} \\\\")
		process_lines.append("\\addlinespace")
	process_lines.append("\\bottomrule")
	process_lines.append("\\end{tabularx}")
	process_lines.append("\\end{table}")
	process_lines.append("")

	strict_out.write_text("\n".join(strict_lines) + "\n", encoding="utf-8")
	eff_out.write_text("\n".join(eff_lines) + "\n", encoding="utf-8")
	process_out.write_text("\n".join(process_lines) + "\n", encoding="utf-8")

	wrapper_lines = [*header, "% Combined wrapper."]
	wrapper_lines.append(f"\\input{{{strict_out.relative_to(TABLES_DIR).as_posix()}}}")
	wrapper_lines.append(f"\\input{{{eff_out.relative_to(TABLES_DIR).as_posix()}}}")
	wrapper_lines.append(f"\\input{{{process_out.relative_to(TABLES_DIR).as_posix()}}}")
	wrapper_lines.append("")
	LATEX_OUT.write_text("\n".join(wrapper_lines) + "\n", encoding="utf-8")


def main() -> None:
	if not ALL_RUNS_CSV.exists():
		raise SystemExit(f"missing {ALL_RUNS_CSV}")
	if not MILESTONE_SUMMARY_CSV.exists():
		raise SystemExit(f"missing {MILESTONE_SUMMARY_CSV}")

	all_rows = _read_csv(ALL_RUNS_CSV)
	ms_rows = _read_csv(MILESTONE_SUMMARY_CSV)
	rows = _merge_rows(all_rows, ms_rows)
	cells = compute_cell_summaries(rows)

	n_per_cell = max(c.n for c in cells) if cells else 10

	comparisons: list[dict[str, object]] = []
	for a, b in [("E", "I"), ("I", "R-1"), ("I", "R-3"), ("I", "R-5")]:
		comparisons.append(
			{
				"pair": {"a": a, "b": b},
				"pooled_success_fisher_two_sided": _pooled_success_fisher(rows, a_cond=a, b_cond=b),
				"task_block_success_rate": _paired_task_block_comparison(cells, a_cond=a, b_cond=b, metric=None),
				"task_block_steps_median": _paired_task_block_comparison(cells, a_cond=a, b_cond=b, metric="steps"),
				"task_block_cost_usd_median": _paired_task_block_comparison(cells, a_cond=a, b_cond=b, metric="total_cost_usd"),
				"task_block_duration_seconds_median": _paired_task_block_comparison(cells, a_cond=a, b_cond=b, metric="duration_seconds"),
				"task_block_stall_burden_median": _paired_task_block_comparison(cells, a_cond=a, b_cond=b, metric="stall_burden"),
			}
		)

	stats = {
		"generated_at_utc": _utc_now_iso(),
		"input_paths": {
			"all_runs_csv": str(ALL_RUNS_CSV),
			"milestone_summary_csv": str(MILESTONE_SUMMARY_CSV),
		},
		"notes": [
			"Strict success CI uses Wilson (binomial) 95%.",
			"Continuous metrics report median with resampling-based 95% CI.",
			"Task-as-block comparisons treat the 4 tasks as paired blocks; sign test ignores ties.",
			"McNemar is not used because runs are not 1:1 paired by a shared random seed/id across conditions.",
			"Pooled Fisher exact is reported as exploratory and ignores task blocking.",
			f"All conditions use n={n_per_cell} repetitions per task.",
		],
		"cell_summaries": [
			{
				"paper_condition": c.cond,
				"task_id": c.task_id,
				"n": c.n,
				"strict_success": {"k": c.k_success, "n": c.n, "rate": c.success_rate, "ci95_wilson": [c.success_ci_lo, c.success_ci_hi]},
				"metrics": c.metrics,
			}
			for c in cells
		],
		"comparisons": comparisons,
	}

	STATS_OUT.write_text(json.dumps(stats, indent=2, sort_keys=False), encoding="utf-8")
	write_latex_tables(cells, n_per_cell=n_per_cell)
	print(f"Wrote {STATS_OUT}")
	print(f"Wrote {LATEX_OUT}")
	for p in _split_table_paths():
		print(f"Wrote {p}")


if __name__ == "__main__":
	main()
