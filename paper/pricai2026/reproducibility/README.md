# PRICAI 2026 — Navigator Cadence Study Reproducibility Package

This repository supports reproduction of:

> **How Often Should a Navigator Replan? An Evidence-Audited Cadence Study for a CDP Browser Agent**

It contains frozen task definitions, run artifacts, analysis scripts, and figure-generation code for the 240-run cadence sweep (4 tasks × 6 conditions × 10 repetitions).

## Repository layout

```
.
├── data/
│   ├── task_cards.json          # Frozen task cards (hard criteria, prompts)
│   ├── all_runs.csv             # Per-run outcomes (strict_success, steps, duration, tokens, cost)
│   ├── milestone_summary.csv    # Per-run process metrics (stall, revisit, milestones)
│   ├── run_audit.csv            # Criterion-level strict-success audit labels
│   ├── agent_runs.json          # Consolidated run metadata
│   └── stats_summary.json       # Per-cell medians and 95% CIs (generated)
├── code/
│   ├── daily_task_eval/         # Experiment runner, navigator, executor, metrics
│   ├── compute_paper_stats.py   # Regenerate LaTeX tables and stats_summary.json
│   ├── compute_milestone_metrics.py
│   └── make_figures.py          # Regenerate paper figures
├── paper/
│   ├── main.tex                 # Manuscript source
│   ├── tables/                  # Auto-generated LaTeX tables
│   └── figures/                 # Generated figure assets
└── README.md
```

In the upstream `browser-use` monorepo, the corresponding paths are:

| This repo path | Monorepo path |
|---|---|
| `code/daily_task_eval/` | `browser_use/experiments/daily_task_eval/` |
| `data/task_cards.json` | `examples/evaluation/fixtures/task_cards.json` |
| `code/compute_paper_stats.py` | `scripts/compute_paper_stats.py` |
| `code/compute_milestone_metrics.py` | `scripts/compute_milestone_metrics.py` |
| `code/make_figures.py` | `paper/pricai2026/make_figures.py` |
| `data/*.csv`, `data/*.json` | `tmp/daily_task_eval/` (after batch runs) |

## Quick start

```bash
# Python >= 3.11
uv venv --python 3.11
source .venv/bin/activate   # Windows: .venv\Scripts\activate
uv sync

# Regenerate milestone metrics from saved history.json traces
uv run python code/compute_milestone_metrics.py --data-dir data

# Regenerate paper statistics and LaTeX tables
uv run python code/compute_paper_stats.py --data-dir data --output-dir paper/tables

# Regenerate figures
uv run python code/make_figures.py --data-dir data --output-dir paper/figures
```

## Re-running experiments (optional)

Experiments require API keys for the Doubao executor and DeepSeek navigator configured in `.env`.

**Full 240-run matrix (randomized condition order within each task, matching the paper):**

```bash
uv run python scripts/run_full_eval_batch.py --reps 10 --seed 42
```

Use `--dry-run` to inspect the shuffled schedule without launching browsers. Each run records
`condition_order_mode=randomized_within_task` and `schedule_seed` in its manifest.

To replay a single condition manually:
```bash
uv run python -m browser_use.experiments.daily_task_eval.runner \
  --preset CA --task hospital_lookup --repeat 0
```

See `code/daily_task_eval/` for presets **E / I / R-1 / R-3 / R-5 / R-A** (paper labels).

## Citation

If you use this artifact, please cite the PRICAI 2026 paper (bib entry in `paper/references.bib`).

## License

Code follows the MIT license of the parent Browser-Use project. Run logs and task cards are released for research reproducibility.
