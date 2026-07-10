#!/usr/bin/env python3
"""Planning-cadence ablation batch: 4 tasks × 3 replan intervals × 2 reps = 24 runs.

Compares navigator_replan_interval ∈ {1, 3, 5} under continuous_navigation=true.
All runs share the identical executor (Doubao) and navigator (DeepSeek) config.

Combined with the prior 48-run no-nav / one-shot batch (Experiment A/B per paper),
this provides a 3-condition planning-cadence picture.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from dotenv import load_dotenv

from browser_use.experiments.daily_task_eval.executor import ExecutorConfig
from browser_use.experiments.daily_task_eval.models import (
    TaskCard,
    load_json_model_list,
    write_json,
)
from browser_use.experiments.daily_task_eval.navigator import NavigatorConfig, build_navigator
from browser_use.experiments.daily_task_eval.runner import run_agent_task

# ── Config ──────────────────────────────────────────────────────────
OUTPUT_DIR = REPO_ROOT / "tmp" / "daily_task_eval"
TASK_CARDS_PATH = OUTPUT_DIR / "task_cards.json"
CSV_DIR = OUTPUT_DIR / "csv_out"

MAIN_TASKS = [
    "shopping_price_compare",
    "nearby_hospital_phone_lookup",
    "github_clean_issue_audit",
    "huggingface_model_constrained_selection",
]

REPLAN_INTERVALS = [1, 3, 5]
N_REPS = 2

# ── Frozen executor (identical for all runs) ───────────────────────
EXECUTOR_CONFIG = ExecutorConfig(
    backend="openai_compatible",
    model="doubao-seed-2-0-pro-260215",
    api_key_env="ARK_API_KEY",
    base_url="https://ark.cn-beijing.volces.com/api/v3",
    temperature=0.0,
    use_vision=False,
)

# ── Frozen navigator base (interval varies) ────────────────────────
NAVIGATOR_BASE = NavigatorConfig(
    enabled=True,
    backend="deepseek",
    model="deepseek-chat",
    api_key_env="DEEPSEEK_API_KEY",
    base_url="https://api.deepseek.com/v1",
    temperature=0.0,
)

# ── Common run parameters ──────────────────────────────────────────
COMMON_KWARGS = dict(
    max_steps=35,
    max_failures=3,
    headless=False,
    llm_timeout=120,
    step_timeout=150,
    heartbeat_seconds=30,
    max_actions_per_step=1,
)


def make_batch_id() -> str:
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"cadence-{ts}"


async def run_one(
    task: TaskCard,
    interval: int,
    rep: int,
    batch_id: str,
) -> dict:
    """Run a single Agent task and return its summary dict."""
    condition_id = f"C_interval_{interval}"
    experiment_id = f"C{interval}"

    navigator = build_navigator(NAVIGATOR_BASE)

    summary = await run_agent_task(
        task=task,
        output_dir=OUTPUT_DIR,
        scenario_id="normal",
        executor_config=EXECUTOR_CONFIG,
        navigator=navigator,
        navigator_config=NAVIGATOR_BASE,
        continuous_navigation=True,
        navigator_replan_interval=interval,
        experiment_id=experiment_id,
        batch_id=batch_id,
        csv_dir=CSV_DIR,
        run_manifest_extra={
            "condition_id": condition_id,
            "repeat_id": rep,
            "planning_cadence_interval": interval,
        },
        **COMMON_KWARGS,
    )

    return summary.model_dump(mode="json")


async def main() -> None:
    load_dotenv()

    # Check API keys
    for env_var in ["ARK_API_KEY", "DEEPSEEK_API_KEY"]:
        if not os.getenv(env_var):
            print(f"❌ {env_var} is not set. Aborting.")
            return

    # Load task cards
    all_cards = load_json_model_list(TASK_CARDS_PATH, TaskCard)
    task_cards = {t.id: t for t in all_cards if t.id in MAIN_TASKS}
    missing = set(MAIN_TASKS) - set(task_cards.keys())
    if missing:
        print(f"❌ Missing task cards: {missing}")
        return
    print(f"✅ Loaded {len(task_cards)} task cards")

    batch_id = make_batch_id()
    total = len(MAIN_TASKS) * len(REPLAN_INTERVALS) * N_REPS
    print(f"\n🔬 Planning-cadence batch: {batch_id}")
    print(f"   Tasks: {len(MAIN_TASKS)}")
    print(f"   Intervals: {REPLAN_INTERVALS}")
    print(f"   Reps per cell: {N_REPS}")
    print(f"   Total runs: {total}\n")

    all_summaries: list[dict] = []
    run_idx = 0

    for task_id in MAIN_TASKS:
        task = task_cards[task_id]
        print(f"── {task_id} ──")
        for rep in range(1, N_REPS + 1):
            for interval in REPLAN_INTERVALS:
                run_idx += 1
                label = f"{task_id} I={interval} rep={rep} [{run_idx}/{total}]"
                print(f"  {label} ...", end=" ", flush=True)
                try:
                    summary = await run_one(task, interval, rep, batch_id)
                    status = "✅" if summary.get("strict_success") else "⚠️"
                    outcome = summary.get("adjudicated_outcome_label", "?")
                    steps = summary.get("number_of_steps", "?")
                    dur = summary.get("duration_seconds", 0)
                    print(f"{status} {outcome} steps={steps} dur={dur:.0f}s")
                    all_summaries.append(summary)
                except Exception as exc:
                    print(f"❌ ERROR: {exc}")
                    all_summaries.append({
                        "task_id": task_id,
                        "experiment_id": f"C{interval}",
                        "condition_id": f"C_interval_{interval}",
                        "repeat_id": rep,
                        "error": str(exc),
                    })

    # ── Save ───────────────────────────────────────────────────────
    out_path = OUTPUT_DIR / "agent_runs_planning_cadence.json"
    write_json(out_path, all_summaries)
    print(f"\n📦 Saved {len(all_summaries)} summaries → {out_path}")
    print("✅ Batch complete.")


if __name__ == "__main__":
    asyncio.run(main())
