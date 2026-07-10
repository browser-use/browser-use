# Step 3: Milestone-Based Process Metrics

This directory contains the implementation of milestone-based process metrics for the daily task evaluation framework.

## Overview

**Purpose**: Quantify process-level behavior to explain **why** runs succeed or fail, beyond just terminal `strict_success`. Specifically designed to analyze cases like "C1 HF step 14 regression" where agents get stuck in loops.

**Problem Solved**: `strict_success` only captures terminal outcomes. This system adds process indicators to detect:
- **Stall/Loop behavior**: Agent repeating actions without progress
- **Order violations**: Milestones achieved out of sequence
- **State revisits**: Navigating to previously-seen URLs
- **Post-intervention recovery**: Whether navigator injection breaks loops (R-* conditions)

## Components

### 1. Milestone Definitions (`task_registry.py`)

Defines critical progress checkpoints for each task:

- **Shopping** (M1–M5): Navigate site → Search → Results → Product detail → Extract
- **Hospital** (M1–M6): Navigate map → Search → Results → Select POI → Phone visible → Extract
- **GitHub** (M1–M7): Navigate issues → Bug filter → Confirm filter → Sort → Click issue → Detail loaded → Extract
- **HuggingFace** (M1–M7): Navigate models → Text Gen filter → PyTorch filter → Chinese filter → Sort downloads → Open model → Extract

Each milestone has a `check(step, url, action_name) -> bool` function that inspects history steps.

### 2. Process Metrics (`trajectory_metrics.py`)

**`parse_history_for_milestones(history, task_id, run_id, experiment_id)`**

Parses a run's `history.json` and returns `MilestoneProcessMetrics`:

- **milestone_coverage**: Fraction of expected milestones achieved (0.0–1.0)
- **order_score**: Kendall τ correlation between achieved order and expected order (-1.0 to 1.0)
- **stall_burden**: Fraction of steps that didn't achieve a new milestone (0.0–1.0)
- **state_revisit_rate**: Fraction of steps revisiting a previously-seen URL (0.0–1.0)
- **post_intervention_recovery_yield**: For R-* runs only, did navigator injection break the loop within 2 steps? (0.0 or 1.0)

### 3. Computation Script (`scripts/compute_milestone_metrics.py`)

Processes all completed runs in `tmp/daily_task_eval/agent_runs.json` and outputs:

```bash
uv run python scripts/compute_milestone_metrics.py
```

**Outputs**:
- `tmp/daily_task_eval/per_run_milestones.json`: Detailed milestone events per run
- `tmp/daily_task_eval/milestone_summary.csv`: Aggregated metrics for analysis

### 4. CI Tests (`tests/ci/test_milestone_metrics.py`)

Tests milestone parsing on:
- HF C1 20260625T050947Z (the step-14 regression case)
- GitHub C runs
- Edge cases (empty history, malformed steps)
- Coverage and stall burden calculations

```bash
uv run pytest -xvs tests/ci/test_milestone_metrics.py
```

## Usage

### Computing Metrics

```python
from browser_use.experiments.daily_task_eval.trajectory_metrics import parse_history_for_milestones

with open('history.json', encoding='utf-8') as f:
    history = json.load(f)['history']

metrics = parse_history_for_milestones(
    history,
    task_id='huggingface_model_constrained_selection',
    run_id='20260625T050947Z',
    experiment_id='C1'
)

print(f"Coverage: {metrics.milestone_coverage:.2f}")
print(f"Stall burden: {metrics.stall_burden:.2f}")
print(f"Milestones: {metrics.milestones_achieved}")
```

### Adding New Milestones

To add milestones for a new task:

1. Define milestone check functions in `task_registry.py`:
```python
def _newtask_m1_check(step: dict, url: str | None, action_name: str | None) -> bool:
    """M1: First critical checkpoint."""
    if not url:
        return False
    return 'example.com' in url.lower()
```

2. Create milestone list:
```python
NEWTASK_MILESTONES = [
    MilestoneDefinition('M1_checkpoint', 'First checkpoint', _newtask_m1_check),
    MilestoneDefinition('M2_checkpoint', 'Second checkpoint', _newtask_m2_check),
    # ...
]
```

3. Register in `TASK_MILESTONE_REGISTRY`:
```python
TASK_MILESTONE_REGISTRY: dict[str, list[MilestoneDefinition]] = {
    'new_task_id': NEWTASK_MILESTONES,
    # ...
}
```

4. Add tests in `tests/ci/test_milestone_metrics.py`

## Interpretation Guide

### Coverage
- **1.0**: All milestones achieved (ideal)
- **0.7–0.9**: Most milestones hit, minor gaps
- **< 0.5**: Significant progress failures

### Order Score (Kendall τ)
- **1.0**: Perfect sequence adherence
- **0.5–0.8**: Mostly ordered with some swaps
- **< 0.0**: Significant out-of-order execution

### Stall Burden
- **< 0.3**: Efficient, direct path
- **0.5–0.7**: Moderate redundancy (typical)
- **> 0.8**: High loop/stall behavior (red flag)

### State Revisit Rate
- **< 0.3**: Linear navigation
- **0.5–0.7**: Some backtracking (normal)
- **> 0.8**: Circular navigation patterns

### Post-Intervention Recovery (R-* only)
- **1.0**: Navigator broke the loop within 2 steps
- **0.0**: Loop persisted after injection

## Example: Diagnosing C1 HF Step-14 Regression

```bash
# Compute metrics
uv run python scripts/compute_milestone_metrics.py

# Check HF C1 runs in CSV
grep "huggingface.*C1" tmp/daily_task_eval/milestone_summary.csv
```

**Expected findings**:
- High stall_burden (> 0.8): Agent stuck re-clicking same filter
- High state_revisit_rate: URL not changing between steps
- Low coverage early: M4 (Chinese filter) not activating
- Order violations: M2/M3/M4 firing out of sequence

## Integration with Paper Figures

Milestone metrics feed into:
- **Figure 3**: Coverage/stall by experiment condition
- **Table 2**: Process metrics vs strict_success correlation
- **Appendix**: Per-task milestone achievement rates

## File Locations

- Milestone definitions: `browser_use/experiments/daily_task_eval/task_registry.py`
- Metric computation: `browser_use/experiments/daily_task_eval/trajectory_metrics.py`
- Script: `scripts/compute_milestone_metrics.py`
- Tests: `tests/ci/test_milestone_metrics.py`
- Outputs:
  - `tmp/daily_task_eval/per_run_milestones.json`
  - `tmp/daily_task_eval/milestone_summary.csv`

## Relation to Other Steps

- **Step 2 (Human Reference)**: Provides ground-truth trajectories; milestones can be compared agent vs human
- **Step 1 (Adjudication)**: Milestones add process depth to binary success/failure
- **Step 4+ (Paper Figures)**: Milestone metrics are core data for process analysis charts
