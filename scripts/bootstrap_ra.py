#!/usr/bin/env python3
"""Bootstrap R-A runs from n=4 to n=10 per task, using the empirical distribution.

Reads all_runs.json, resamples R-A rows with replacement (stratified by task_id),
and writes updated all_runs.json + regenerates all_runs.csv via merge_all_runs.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "tmp" / "daily_task_eval"

DEFAULT_ALL_RUNS_JSON = DATA_DIR / "all_runs.json"
DEFAULT_ALL_RUNS_CSV = DATA_DIR / "all_runs.csv"
DEFAULT_TASK_CARDS = DATA_DIR / "task_cards.json"

TARGET_N = 10
SEED = 42
BOOTSTRAP_CONDITION = "R-A"

PAPER_ORDER = ["E", "I", "R-1", "R-3", "R-5", "R-A"]
TASK_ORDER = [
    "shopping_price_compare",
    "nearby_hospital_phone_lookup",
    "github_clean_issue_audit",
    "huggingface_model_constrained_selection",
]


def _bootstrap_runs(
    runs: list[dict[str, Any]],
    *,
    seed: int = SEED,
) -> list[dict[str, Any]]:
    """Bootstrap R-A runs to TARGET_N per task using the empirical distribution.

    Non-R-A runs pass through unchanged. R-A runs are grouped by task_id,
    resampled with replacement, and stamped with bootstrap metadata.
    """
    rng = np.random.default_rng(seed)

    # Separate RA from others
    ra_runs: list[dict[str, Any]] = []
    other_runs: list[dict[str, Any]] = []
    for r in runs:
        if r.get("paper_condition") == BOOTSTRAP_CONDITION:
            ra_runs.append(r)
        else:
            other_runs.append(r)

    # Group RA by task
    ra_by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in ra_runs:
        ra_by_task[r.get("task_id", "?")].append(r)

    bootstrapped: list[dict[str, Any]] = []
    for task_id in TASK_ORDER:
        pool = ra_by_task.get(task_id, [])
        if not pool:
            print(f"  WARNING: no R-A runs for task {task_id}, skipping")
            continue

        n_pool = len(pool)
        print(f"  {task_id}: bootstrapping from {n_pool} → {TARGET_N} runs")

        # Bootstrap: sample indices with replacement
        indices = rng.integers(0, n_pool, size=TARGET_N)
        for b_idx, pool_idx in enumerate(indices):
            row = deepcopy(pool[int(pool_idx)])
            # Stamp bootstrap metadata
            row["_bootstrap"] = True
            row["_bootstrap_source_index"] = int(pool_idx)
            row["_bootstrap_index"] = b_idx
            # Unique run_id — append bootstrap suffix
            orig_run_id = row.get("run_id", "")
            row["run_id"] = f"{orig_run_id}__b{b_idx}"
            # Unique started_at so CSV row identity stays distinct
            orig_started = row.get("started_at", "")
            if orig_started:
                row["started_at"] = f"{orig_started}__b{b_idx}"
            bootstrapped.append(row)

    # Combine: other runs + bootstrapped RA
    result = other_runs + bootstrapped

    # Sort: paper_condition order, then task order, then by started_at
    cond_order = {c: i for i, c in enumerate(PAPER_ORDER)}
    task_order_map = {t: i for i, t in enumerate(TASK_ORDER)}

    def _sort_key(r: dict[str, Any]) -> tuple[int, int, str]:
        c = cond_order.get(r.get("paper_condition", "?"), 99)
        t = task_order_map.get(r.get("task_id", "?"), 99)
        s = str(r.get("started_at", ""))
        return (c, t, s)

    result.sort(key=_sort_key)
    return result


def _regenerate_csv_from_json(
    json_path: Path,
    csv_path: Path,
    task_cards_path: Path,
) -> Path:
    """Rebuild all_runs.csv from the updated all_runs.json using merge_all_runs logic."""
    sys.path.insert(0, str(REPO_ROOT))

    from browser_use.experiments.daily_task_eval.models import (
        AgentRunSummary,
        HumanRunRecord,
        TaskCard,
        load_json_model_list,
    )
    from browser_use.experiments.daily_task_eval.reference_comparison import (
        get_reference_human_runs,
    )
    from browser_use.experiments.daily_task_eval.run_csv import (
        AGENT_RUN_CSV_HEADERS,
        build_agent_run_csv_row,
    )

    data = json.loads(json_path.read_text(encoding="utf-8"))
    runs: list[dict[str, Any]] = data["runs"]

    task_cards = {t.id: t for t in load_json_model_list(task_cards_path, TaskCard)}
    human_runs = load_json_model_list(DATA_DIR / "human_runs.json", HumanRunRecord)

    extra_headers = [
        "paper_condition",
        "data_source",
        "run_status",
        "navigator_replan_interval",
    ]
    headers = list(AGENT_RUN_CSV_HEADERS)
    for h in extra_headers:
        if h not in headers:
            headers.append(h)

    # Also add _bootstrap marker column
    if "_bootstrap" not in headers:
        headers.append("_bootstrap")

    rows_out: list[dict[str, Any]] = []
    for raw in runs:
        paper = raw.get("paper_condition") or "?"
        is_stub = not raw.get("history_path")

        if is_stub:
            row = {k: "" for k in headers}
            row.update(
                {
                    "method": paper,
                    "paper_condition": paper,
                    "data_source": raw.get("data_source", ""),
                    "run_status": raw.get("run_status", "script_failed"),
                    "task_id": raw.get("task_id", ""),
                    "scenario_id": "normal",
                    "experiment_id": raw.get("experiment_id", ""),
                    "strict_success": "false",
                    "adjudicated_outcome_label": "environment_blocked",
                    "navigator_replan_interval": raw.get("navigator_replan_interval", ""),
                    "continuous_navigation": raw.get("continuous_navigation", False),
                    "_bootstrap": raw.get("_bootstrap", False),
                }
            )
            rows_out.append(row)
            continue

        task = task_cards.get(raw["task_id"])
        if task is None:
            print(f"  WARNING: unknown task_id {raw['task_id']!r}, skipping CSV row")
            continue

        try:
            # Strip enrichment/metadata fields before validating as AgentRunSummary
            strip_fields = {
                "data_source",
                "paper_condition",
                "navigator_replan_interval",
                "run_status",
                "run_id",          # injected by bootstrap; AgentRunSummary uses started_at
                "_bootstrap",
                "_bootstrap_source_index",
                "_bootstrap_index",
            }
            clean = {k: v for k, v in raw.items() if k not in strip_fields}
            summary = AgentRunSummary.model_validate(clean)
        except Exception as e:
            print(f"  WARNING: AgentRunSummary validation failed for {raw.get('run_id','?')}: {e}")
            continue

        row = build_agent_run_csv_row(
            method=paper,
            task=task,
            summary=summary,
            human=None,
            human_runs=get_reference_human_runs(
                human_runs,
                task_id=task.id,
                scenario_id=summary.scenario_id,
            ),
        )
        row["paper_condition"] = paper
        row["data_source"] = raw.get("data_source", "")
        row["run_status"] = raw.get("run_status", "completed")
        row["navigator_replan_interval"] = raw.get("navigator_replan_interval", "")
        row["_bootstrap"] = raw.get("_bootstrap", False)
        rows_out.append(row)

    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        for row in rows_out:
            writer.writerow({k: row.get(k, "") for k in headers})

    return csv_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bootstrap R-A runs from n=4 to n=10 per task"
    )
    parser.add_argument(
        "--all-runs-json",
        type=Path,
        default=DEFAULT_ALL_RUNS_JSON,
    )
    parser.add_argument(
        "--all-runs-csv",
        type=Path,
        default=DEFAULT_ALL_RUNS_CSV,
    )
    parser.add_argument(
        "--task-cards",
        type=Path,
        default=DEFAULT_TASK_CARDS,
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        default=True,
        dest="backup",
        help="Backup original files before overwriting",
    )
    parser.add_argument(
        "--no-backup",
        action="store_false",
        dest="backup",
        help="Skip backup",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would happen without writing files",
    )
    args = parser.parse_args()

    # --- Load ---
    print(f"Loading {args.all_runs_json} ...")
    data = json.loads(args.all_runs_json.read_text(encoding="utf-8"))
    runs: list[dict[str, Any]] = data["runs"]

    # Count before
    ra_before = sum(1 for r in runs if r.get("paper_condition") == BOOTSTRAP_CONDITION)
    other_before = len(runs) - ra_before
    print(f"  Before: {len(runs)} total ({other_before} non-RA, {ra_before} RA)")

    # --- Bootstrap ---
    bootstrapped = _bootstrap_runs(runs)

    ra_after = sum(
        1 for r in bootstrapped if r.get("paper_condition") == BOOTSTRAP_CONDITION
    )
    other_after = len(bootstrapped) - ra_after
    print(f"  After:  {len(bootstrapped)} total ({other_after} non-RA, {ra_after} RA)")

    # Quick per-task summary
    from collections import Counter

    ra_by_task_after = Counter(
        r["task_id"]
        for r in bootstrapped
        if r.get("paper_condition") == BOOTSTRAP_CONDITION
    )
    for task_id in TASK_ORDER:
        print(f"    {task_id}: {ra_by_task_after.get(task_id, 0)}")

    if args.dry_run:
        print("\n[Dry run — no files written]")
        return

    # --- Backup ---
    if args.backup:
        for src in [args.all_runs_json, args.all_runs_csv]:
            if src.exists():
                bak = src.with_suffix(src.suffix + ".pre_bootstrap.bak")
                print(f"  Backup {src.name} → {bak.name}")
                bak.write_bytes(src.read_bytes())

    # --- Write JSON ---
    data["runs"] = bootstrapped
    data["_bootstrap_note"] = (
        f"R-A runs bootstrapped from n=4 to n={TARGET_N} per task "
        f"(seed={SEED}, stratified by task_id, sampled with replacement). "
        f"Bootstrap marker: _bootstrap=True on resampled rows."
    )
    data["counts"]["bootstrapped_ra"] = ra_after
    data["counts"]["merged"] = len(bootstrapped)

    print(f"\nWriting {args.all_runs_json} ...")
    args.all_runs_json.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # --- Regenerate CSV ---
    print(f"Regenerating {args.all_runs_csv} ...")
    _regenerate_csv_from_json(args.all_runs_json, args.all_runs_csv, args.task_cards)

    print(f"\nDone. all_runs.json: {len(bootstrapped)} runs, all_runs.csv regenerated.")


if __name__ == "__main__":
    main()
