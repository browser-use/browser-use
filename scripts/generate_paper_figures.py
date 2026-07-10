#!/usr/bin/env python3
"""Generate figures for the PRICAI 2026 paper.

Data sources (relative to repo root):
    - Legacy A/B (optional):
        tmp/daily_task_eval/task_summary.csv
        tmp/daily_task_eval/resource_summary.csv
        tmp/daily_task_eval/comparison_report.json
    - Cadence / merged (preferred when present):
        tmp/daily_task_eval/all_runs.csv
        tmp/daily_task_eval/milestone_summary.csv

Output (preferred pipeline): paper/pricai2026/figures/fig{2,3,4,5,6}.pdf
"""

from __future__ import annotations

import json
import csv
import statistics
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
from matplotlib.lines import Line2D

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "tmp" / "daily_task_eval"
FIG_DIR = REPO_ROOT / "paper" / "pricai2026" / "figures"

FIG_DIR.mkdir(parents=True, exist_ok=True)

EXPERIMENT_COLOR = {"A": "#4472C4", "B": "#ED7D31"}
EXPERIMENT_LABEL = {"A": "A (executor only)", "B": "B (+ navigator)"}
PAPER_ORDER = ["E", "I", "R-1", "R-3", "R-5"]
PAPER_LABEL = {
    "E": "E (no navigator)",
    "I": "I (one-shot plan)",
    "R-1": "R-1 (replan every step)",
    "R-3": "R-3 (replan every 3 steps)",
    "R-5": "R-5 (replan every 5 steps)",
}
PAPER_COLOR = {
    "E": "#4E79A7",
    "I": "#F28E2B",
    "R-1": "#E15759",
    "R-3": "#76B7B2",
    "R-5": "#59A14F",
}
TASK_LABELS = {
    "shopping_price_compare": "Shopping",
    "nearby_hospital_phone_lookup": "Hospital",
    "github_clean_issue_audit": "GitHub",
    "huggingface_model_constrained_selection": "HuggingFace",
}
TASK_ORDER = [
    "shopping_price_compare",
    "nearby_hospital_phone_lookup",
    "github_clean_issue_audit",
    "huggingface_model_constrained_selection",
]

# Fig7 inputs (HF case study)
HF_CASE_R1_HISTORY = (
    DATA_DIR
    / "agent_runs"
    / "huggingface_model_constrained_selection"
    / "normal"
    / "exp-C1"
    / "20260625T050947Z"
    / "history.json"
)
HF_CASE_R5_HISTORY = (
    DATA_DIR
    / "agent_runs"
    / "huggingface_model_constrained_selection"
    / "normal"
    / "exp-C5"
    / "20260625T053325Z"
    / "history.json"
)

# ---------------------------------------------------------------------------
# Matplotlib style — serif, publication-grade
# ---------------------------------------------------------------------------
plt.rcParams.update({
    "font.family": "serif",
    "font.serif": ["Times New Roman", "DejaVu Serif"],
    "font.size": 10,
    "axes.titlesize": 10,
    "axes.labelsize": 9,
    "legend.fontsize": 8,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "figure.dpi": 150,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.08,
})

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_task_summary() -> list[dict]:
    rows = []
    with open(DATA_DIR / "task_summary.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["scenario_id"] == "normal" and row["task_id"] != "__overall__":
                rows.append(row)
    return rows


def load_resource_summary() -> list[dict]:
    rows = []
    with open(DATA_DIR / "resource_summary.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["task_id"] != "__overall__":
                row["_exp"] = row["analysis_experiment_id"]  # A or B
                rows.append(row)
    return rows


def load_lcs_data() -> list[dict]:
    with open(DATA_DIR / "comparison_report.json", encoding="utf-8") as f:
        report = json.load(f)
    pairs = []
    for p in report.get("lcs_pairs", []):
        if p.get("comparison_status") == "comparable" and p.get("canonical_lcs_score") is not None:
            pairs.append(p)
    return pairs


# ---------------------------------------------------------------------------
# Preferred pipeline (E/I/R-*): load merged artifacts
# ---------------------------------------------------------------------------

def _read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [dict(row) for row in csv.DictReader(f)]

def _parse_bool(raw: str | None) -> bool | None:
    if raw is None:
        return None
    low = str(raw).strip().lower()
    if low in ("true", "1", "yes"):
        return True
    if low in ("false", "0", "no"):
        return False
    return None

def _parse_float(raw: str | None) -> float | None:
    if raw is None:
        return None
    txt = str(raw).strip()
    if txt == "":
        return None
    try:
        return float(txt)
    except ValueError:
        return None

def load_all_runs_csv() -> list[dict]:
    path = DATA_DIR / "all_runs.csv"
    if not path.exists():
        return []
    return _read_csv(path)


def load_milestone_summary() -> list[dict]:
    path = DATA_DIR / "milestone_summary.csv"
    if not path.exists():
        return []
    return _read_csv(path)

def load_per_run_milestones() -> list[dict]:
    path = DATA_DIR / "per_run_milestones.json"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _norm_path_for_match(p: str | Path) -> str:
    return str(p).replace("\\", "/").lower()


def _find_run_id_by_history_path(all_rows: list[dict], history_path: Path) -> str | None:
    """Match a history.json path to all_runs.csv row, tolerant to abs/rel path differences."""
    needle = _norm_path_for_match(history_path)
    if "/tmp/daily_task_eval/" in needle:
        needle = needle.split("/tmp/daily_task_eval/", 1)[1]
    for r in all_rows:
        hp = r.get("history_path") or ""
        cand = _norm_path_for_match(hp)
        if "/tmp/daily_task_eval/" in cand:
            cand = cand.split("/tmp/daily_task_eval/", 1)[1]
        if cand and (cand == needle or cand.endswith(needle) or needle.endswith(cand)):
            rid = str(r.get("run_id") or "").strip()
            return rid or None
    return None


def _milestone_steps_for_run(per_run: list[dict], run_id: str) -> dict[str, int]:
    for r in per_run:
        if str(r.get("run_id")) == run_id:
            ms = r.get("milestone_steps") or {}
            if isinstance(ms, dict):
                out: dict[str, int] = {}
                for k, v in ms.items():
                    try:
                        out[str(k)] = int(v)
                    except Exception:
                        continue
                return out
    return {}


def _extract_hf_timeline(history_path: Path) -> tuple[list[int], list[str], list[str]]:
    """Return step_numbers, urls, phase labels ('list'|'detail'|'other')."""
    with open(history_path, encoding="utf-8") as f:
        blob = json.load(f)
    items = blob.get("history") or []
    step_numbers: list[int] = []
    urls: list[str] = []
    phases: list[str] = []
    for item in items:
        md = item.get("metadata") or {}
        st = item.get("state") or {}
        step = md.get("step_number")
        url = st.get("url") or ""
        try:
            step_i = int(step)
        except Exception:
            continue
        step_numbers.append(step_i)
        urls.append(str(url))
        u = str(url)
        if u.startswith("https://huggingface.co/models"):
            phases.append("list")
        elif u.startswith("https://huggingface.co/"):
            phases.append("detail")
        else:
            phases.append("other")
    return step_numbers, urls, phases


def _detect_hf_rollback_step(history_path: Path) -> int | None:
    """Find the first step where we navigate back to /models after being off /models."""
    with open(history_path, encoding="utf-8") as f:
        blob = json.load(f)
    items = blob.get("history") or []
    last_url = ""
    for item in items:
        md = item.get("metadata") or {}
        st = item.get("state") or {}
        step = md.get("step_number")
        url = str(st.get("url") or "")
        mo = item.get("model_output") or {}
        actions = mo.get("action") or []
        try:
            step_i = int(step)
        except Exception:
            last_url = url
            continue
        for a in actions:
            if not isinstance(a, dict):
                continue
            nav = a.get("navigate")
            if not isinstance(nav, dict):
                continue
            target = str(nav.get("url") or "")
            if "huggingface.co/models" in target and last_url and ("huggingface.co/models" not in last_url):
                return step_i
        last_url = url
    return None


# ---------------------------------------------------------------------------
# Figure 2 (new): Strict success rate — grouped bars, k/n labels
# ---------------------------------------------------------------------------

def fig2_v2(all_rows: list[dict]) -> Path:
    tasks = TASK_ORDER
    x = np.arange(len(tasks))
    width = 0.16

    fig, ax = plt.subplots(figsize=(7.2, 3.2))

    for i, cond in enumerate(PAPER_ORDER):
        rates, successes, totals = [], [], []
        for task in tasks:
            bucket = [
                r
                for r in all_rows
                if r.get("task_id") == task
                and r.get("method") == cond
                and (r.get("run_status") or "").lower() != "script_failed"
            ]
            total = len(bucket)
            ok = sum(1 for r in bucket if _parse_bool(r.get("strict_success")) is True)
            rate = (ok / total) if total else 0.0
            rates.append(rate)
            successes.append(ok)
            totals.append(total)

        bars = ax.bar(
            x + (i - 2) * width,
            rates,
            width,
            label=PAPER_LABEL[cond],
            color=PAPER_COLOR[cond],
            edgecolor="white",
            linewidth=0.5,
        )
        for bar, ok, total, rate in zip(bars, successes, totals, rates):
            label = f"{ok}/{total}" if total else "0/0"
            if rate < 0.12:
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    rate + 0.03,
                    label,
                    ha="center",
                    va="bottom",
                    fontsize=7,
                    fontweight="bold",
                    color=PAPER_COLOR[cond],
                )
            else:
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    rate / 2,
                    label,
                    ha="center",
                    va="center",
                    fontsize=7,
                    fontweight="bold",
                    color="white",
                )

    ax.set_ylabel("Strict success rate")
    ax.set_xticks(x)
    ax.set_xticklabels([TASK_LABELS[t] for t in tasks])
    ax.set_ylim(0, 1.25)
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0))
    ax.legend(loc="lower right", framealpha=0.85, fontsize=7.2, ncol=2)
    ax.grid(axis="y", alpha=0.25, linewidth=0.5)

    fig.tight_layout(pad=0.5)
    path = FIG_DIR / "fig2.pdf"
    fig.savefig(path)
    plt.close(fig)
    print(f"  fig2 → {path.name}  ({path.stat().st_size // 1024} KB)")
    return path


# ---------------------------------------------------------------------------
# Figure 3 (new): Reliability–cost Pareto (overall, per config)
# ---------------------------------------------------------------------------

def fig3_v2(all_rows: list[dict]) -> Path:
    fig, ax = plt.subplots(figsize=(6.0, 3.2))

    for cond in PAPER_ORDER:
        bucket = [
            r
            for r in all_rows
            if r.get("method") == cond and (r.get("run_status") or "").lower() != "script_failed"
        ]
        if not bucket:
            continue
        success_rate = sum(1 for r in bucket if _parse_bool(r.get("strict_success")) is True) / len(bucket)
        costs = [_parse_float(r.get("total_cost")) for r in bucket]
        costs = [c for c in costs if c is not None and c > 0]
        cost_med = float(np.median(costs)) if costs else 0.0
        ax.scatter(
            [cost_med],
            [success_rate],
            s=90,
            color=PAPER_COLOR[cond],
            edgecolors="white",
            linewidth=0.7,
            label=PAPER_LABEL[cond],
            zorder=3,
        )
        ax.text(
            cost_med,
            success_rate + 0.02,
            cond,
            ha="center",
            va="bottom",
            fontsize=8,
            fontweight="bold",
            color=PAPER_COLOR[cond],
        )

    ax.set_xlabel("Median cost (USD)")
    ax.set_ylabel("Strict success rate")
    ax.set_ylim(0, 1.05)
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0))
    ax.grid(alpha=0.25, linewidth=0.5)
    ax.legend(loc="lower right", framealpha=0.85, fontsize=7.2, ncol=2)

    fig.tight_layout(pad=0.5)
    path = FIG_DIR / "fig3.pdf"
    fig.savefig(path)
    plt.close(fig)
    print(f"  fig3 → {path.name}  ({path.stat().st_size // 1024} KB)")
    return path


# ---------------------------------------------------------------------------
# Figure 4 (new): Distributions of steps/tokens/duration (boxplots by config)
# ---------------------------------------------------------------------------

def _bucket_numeric(all_rows: list[dict], *, cond: str, key: str) -> list[float]:
    out: list[float] = []
    for r in all_rows:
        if r.get("method") != cond:
            continue
        if (r.get("run_status") or "").lower() == "script_failed":
            continue
        v = _parse_float(r.get(key))
        if v is None:
            continue
        out.append(float(v))
    return out


def fig4_v2(all_rows: list[dict]) -> Path:
    fig, axes = plt.subplots(1, 3, figsize=(9.2, 3.2))

    panels = [
        ("Steps", "number_of_steps", axes[0], lambda v: v),
        ("Total tokens", "tokens_executor", axes[1], lambda v: v / 1000.0),
        ("Duration (s)", "duration_seconds", axes[2], lambda v: v),
    ]

    for title, key, ax, scale in panels:
        data = []
        labels = []
        colors = []
        for cond in PAPER_ORDER:
            vals = _bucket_numeric(all_rows, cond=cond, key=key)
            if key == "tokens_executor":
                # tokens_executor + tokens_navigator as a more honest total
                nav = _bucket_numeric(all_rows, cond=cond, key="tokens_navigator")
                vals = [a + b for a, b in zip(vals, nav)] if len(nav) == len(vals) else vals
            vals = [scale(v) for v in vals]
            data.append(vals if vals else [0.0])
            labels.append(cond)
            colors.append(PAPER_COLOR[cond])

        bp = ax.boxplot(
            data,
            patch_artist=True,
            widths=0.6,
            medianprops={"color": "#222222", "linewidth": 1.0},
            whiskerprops={"linewidth": 0.8, "color": "#888888"},
            capprops={"linewidth": 0.8, "color": "#888888"},
            boxprops={"linewidth": 0.8, "color": "#666666"},
            flierprops={"marker": ".", "markersize": 3, "alpha": 0.35, "markerfacecolor": "#666666"},
        )
        for patch, c in zip(bp["boxes"], colors):
            patch.set_facecolor(c)
            patch.set_alpha(0.55)

        ax.set_title(title, fontsize=9, fontweight="bold", pad=6)
        ax.set_xticklabels(labels, rotation=0, fontsize=8)
        ax.grid(axis="y", alpha=0.25, linewidth=0.5)

        if title == "Total tokens":
            ax.set_ylabel("k tokens")

    fig.tight_layout(pad=0.8, w_pad=2.0)
    path = FIG_DIR / "fig4.pdf"
    fig.savefig(path)
    plt.close(fig)
    print(f"  fig4 → {path.name}  ({path.stat().st_size // 1024} KB)")
    return path


# ---------------------------------------------------------------------------
# Figure 5 (new): Process metrics (coverage + stall burden) by config × task
# ---------------------------------------------------------------------------

def fig5_v2(milestone_rows: list[dict]) -> Path:
    tasks = TASK_ORDER
    x = np.arange(len(tasks))
    width = 0.16

    # Build aggregated means by (paper_condition, task_id)
    def mean_metric(cond: str, task_id: str, key: str) -> float:
        vals = []
        for r in milestone_rows:
            if r.get("task_id") != task_id:
                continue
            if r.get("paper_condition") != cond:
                continue
            v = _parse_float(r.get(key))
            if v is None:
                continue
            vals.append(v)
        return float(statistics.fmean(vals)) if vals else 0.0

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9.0, 3.2))

    for i, cond in enumerate(PAPER_ORDER):
        cov = [mean_metric(cond, t, "milestone_coverage") for t in tasks]
        stall = [mean_metric(cond, t, "stall_burden") for t in tasks]

        ax1.bar(
            x + (i - 2) * width,
            cov,
            width,
            label=cond,
            color=PAPER_COLOR[cond],
            edgecolor="white",
            linewidth=0.5,
        )
        ax2.bar(
            x + (i - 2) * width,
            stall,
            width,
            label=cond,
            color=PAPER_COLOR[cond],
            edgecolor="white",
            linewidth=0.5,
        )

    ax1.set_title("Milestone coverage (mean)", fontsize=9, fontweight="bold", pad=6)
    ax1.set_ylabel("Coverage")
    ax1.set_xticks(x)
    ax1.set_xticklabels([TASK_LABELS[t] for t in tasks], rotation=0)
    ax1.set_ylim(0, 1.05)
    ax1.yaxis.set_major_formatter(mticker.PercentFormatter(1.0))
    ax1.grid(axis="y", alpha=0.25, linewidth=0.5)

    ax2.set_title("Stall burden (mean)", fontsize=9, fontweight="bold", pad=6)
    ax2.set_ylabel("Stall burden")
    ax2.set_xticks(x)
    ax2.set_xticklabels([TASK_LABELS[t] for t in tasks], rotation=0)
    ax2.set_ylim(0, 1.05)
    ax2.yaxis.set_major_formatter(mticker.PercentFormatter(1.0))
    ax2.grid(axis="y", alpha=0.25, linewidth=0.5)

    # One shared legend
    handles, labels = ax2.get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=5, framealpha=0.85, fontsize=7.2)

    fig.tight_layout(pad=0.7, rect=(0, 0.08, 1, 1))
    path = FIG_DIR / "fig5.pdf"
    fig.savefig(path)
    plt.close(fig)
    print(f"  fig5 → {path.name}  ({path.stat().st_size // 1024} KB)")
    return path


# ---------------------------------------------------------------------------
# Figure 6 (new): Navigator overhead proxy (r_overhead) and recovery_yield (if available)
# ---------------------------------------------------------------------------

def fig6_v2(all_rows: list[dict], milestone_rows: list[dict]) -> Path:
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.6, 3.2))

    # Overhead: mean r_overhead from all_runs.csv
    overhead_means = []
    for cond in PAPER_ORDER:
        vals = _bucket_numeric(all_rows, cond=cond, key="r_overhead")
        overhead_means.append(float(np.mean(vals)) if vals else 0.0)
    ax1.bar(PAPER_ORDER, overhead_means, color=[PAPER_COLOR[c] for c in PAPER_ORDER], edgecolor="white", linewidth=0.5)
    ax1.set_title("Navigator overhead ratio (mean)", fontsize=9, fontweight="bold", pad=6)
    ax1.set_ylabel("tokens_nav / tokens_exec")
    ax1.grid(axis="y", alpha=0.25, linewidth=0.5)
    ax1.set_ylim(0, max(overhead_means + [0.05]) * 1.25)

    # Recovery yield: mean post_intervention_recovery_yield from milestone_summary.csv
    yields = []
    for cond in PAPER_ORDER:
        vals = []
        for r in milestone_rows:
            if r.get("paper_condition") != cond:
                continue
            v = _parse_float(r.get("post_intervention_recovery_yield"))
            if v is None:
                continue
            vals.append(v)
        yields.append(float(np.mean(vals)) if vals else 0.0)
    ax2.bar(PAPER_ORDER, yields, color=[PAPER_COLOR[c] for c in PAPER_ORDER], edgecolor="white", linewidth=0.5)
    ax2.set_title("Recovery yield (mean)", fontsize=9, fontweight="bold", pad=6)
    ax2.set_ylabel("yield")
    ax2.set_ylim(0, 1.05)
    ax2.yaxis.set_major_formatter(mticker.PercentFormatter(1.0))
    ax2.grid(axis="y", alpha=0.25, linewidth=0.5)

    fig.tight_layout(pad=0.7)
    path = FIG_DIR / "fig6.pdf"
    fig.savefig(path)
    plt.close(fig)
    print(f"  fig6 → {path.name}  ({path.stat().st_size // 1024} KB)")
    return path


# ---------------------------------------------------------------------------
# Figure 7 (new): HF case study timeline (R-1 oscillation vs R-5 clean success)
# ---------------------------------------------------------------------------

def fig7_hf_case_study(
    *,
    all_rows: list[dict],
    per_run: list[dict],
    r1_history_path: Path,
    r5_history_path: Path,
) -> tuple[Path, Path]:
    r1_run_id = _find_run_id_by_history_path(all_rows, r1_history_path)
    r5_run_id = _find_run_id_by_history_path(all_rows, r5_history_path)
    r1_ms = _milestone_steps_for_run(per_run, r1_run_id) if r1_run_id else {}
    r5_ms = _milestone_steps_for_run(per_run, r5_run_id) if r5_run_id else {}

    r1_steps, _r1_urls, r1_phases = _extract_hf_timeline(r1_history_path)
    r5_steps, _r5_urls, r5_phases = _extract_hf_timeline(r5_history_path)

    y_map = {"list": 1.0, "detail": 2.0, "other": 0.5}
    r1_y = [y_map.get(p, 0.5) for p in r1_phases]
    r5_y = [y_map.get(p, 0.5) for p in r5_phases]

    rollback_step = _detect_hf_rollback_step(r1_history_path)

    fig, axes = plt.subplots(2, 1, figsize=(7.2, 4.0), sharey=True)
    for ax, steps, ys, ms_steps, title, color in [
        (axes[0], r1_steps, r1_y, r1_ms, "R-1 (C1) — oscillation / failure", PAPER_COLOR["R-1"]),
        (axes[1], r5_steps, r5_y, r5_ms, "R-5 (C5) — clean success", PAPER_COLOR["R-5"]),
    ]:
        ax.plot(steps, ys, color=color, linewidth=1.6, alpha=0.85)
        ax.scatter(steps, ys, color=color, s=14, zorder=3, alpha=0.9)

        # milestone markers (from per_run_milestones.json)
        for m_id, st in sorted(ms_steps.items(), key=lambda kv: kv[1]):
            # markers slightly above the two main phase rows
            y = 2.18 if m_id.startswith("M6") else (1.18 if m_id.startswith(("M1", "M2", "M3", "M4", "M5")) else 0.62)
            ax.scatter([st], [y], marker="v", s=40, color="#222222", zorder=4)
            ax.text(st, y + 0.06, m_id.replace("M", ""), ha="center", va="bottom", fontsize=7, color="#222222")

        ax.set_title(title, fontsize=9.5, fontweight="bold", pad=6)
        ax.set_yticks([1.0, 2.0])
        ax.set_yticklabels(["models list", "model detail"])
        ax.grid(axis="x", alpha=0.15, linewidth=0.5)
        ax.grid(axis="y", alpha=0.20, linewidth=0.5)
        ax.set_ylim(0.2, 2.4)

    # Highlight rollback on R-1
    if rollback_step is not None and r1_steps:
        ax = axes[0]
        ax.axvline(rollback_step, color="#000000", linewidth=1.1, linestyle="--", alpha=0.75)
        ax.text(
            rollback_step + 0.2,
            2.30,
            "rollback: navigate back to /models",
            fontsize=7.5,
            color="#000000",
            ha="left",
            va="top",
        )
        ax.axvspan(rollback_step, max(r1_steps), color="#000000", alpha=0.04)

    axes[0].set_xlabel("Agent step number (raw step counter; includes wait)")
    axes[1].set_xlabel("Agent step number (raw step counter; includes wait)")

    fig.legend(
        handles=[Line2D([0], [0], color="#222222", marker="v", linestyle="None", markersize=6, label="milestone hit")],
        loc="lower center",
        ncol=1,
        framealpha=0.85,
        fontsize=8,
    )
    fig.tight_layout(pad=0.8, rect=(0, 0.05, 1, 1))

    pdf_path = FIG_DIR / "fig7.pdf"
    png_path = FIG_DIR / "fig7.png"
    fig.savefig(pdf_path)
    fig.savefig(png_path)
    plt.close(fig)
    print(f"  fig7 → {pdf_path.name}  ({pdf_path.stat().st_size // 1024} KB)")
    return pdf_path, png_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    all_rows = load_all_runs_csv()
    milestone_rows = load_milestone_summary()
    per_run = load_per_run_milestones()
    if all_rows and milestone_rows:
        print("Loading merged cadence artifacts ...")
        print(f"  all_runs.csv: {len(all_rows)} rows")
        print(f"  milestone_summary.csv: {len(milestone_rows)} rows\n")
        fig2_v2(all_rows)
        fig3_v2(all_rows)
        fig4_v2(all_rows)
        fig5_v2(milestone_rows)
        fig6_v2(all_rows, milestone_rows)
        if HF_CASE_R1_HISTORY.exists() and HF_CASE_R5_HISTORY.exists() and per_run:
            fig7_hf_case_study(all_rows=all_rows, per_run=per_run, r1_history_path=HF_CASE_R1_HISTORY, r5_history_path=HF_CASE_R5_HISTORY)
        print(f"\nDone → {FIG_DIR}")
        return

    # Legacy fallback: A/B only
    print("Loading legacy A/B artifacts ...")
    ts = load_task_summary()
    rs = load_resource_summary()
    lcs = load_lcs_data()
    print(f"  task_summary:   {len(ts)} rows")
    print(f"  resource_summary: {len(rs)} rows")
    print(f"  LCS pairs:      {len(lcs)} eligible\n")

    fig2(ts)
    fig3(rs)
    fig4(rs)
    fig5(lcs)
    print(f"\nDone → {FIG_DIR}")


if __name__ == "__main__":
    main()
