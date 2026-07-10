# Step 3: Milestone & Process Analysis - COMPLETED

## What Was Delivered

A complete milestone-based process metrics system for quantifying **why** agent runs succeed or fail, going beyond binary success/failure to reveal stall patterns, loops, and recovery behavior.

## Core Question Answered

**"Why did C1 HF step 14 hang?"**

After implementing Step 3 and analyzing the run `20260625T050947Z`:
- **Coverage: 100%** (all 7 milestones achieved)
- **Stall burden: 79.41%** (agent spent 27 of 34 steps without progress)
- **State revisit rate: 91.18%** (agent revisited same URLs 31 times)
- **Interpretation**: Agent got stuck in a loop re-clicking filters that were already active, failing to detect activation via URL parameters. Despite eventually succeeding, the process was highly inefficient.

## Implementation Details

### Files Created/Modified

1. **`trajectory_metrics.py`** (+229 lines)
   - `MilestoneEvent` dataclass
   - `MilestoneProcessMetrics` dataclass with 6 core metrics
   - `parse_history_for_milestones()` main parsing function
   - Helper functions for Kendall tau, stall burden, state revisit rate

2. **`task_registry.py`** (+340 lines)
   - 25 milestone check functions (5–7 per task)
   - 4 milestone definition lists (Shopping, Hospital, GitHub, HuggingFace)
   - `TASK_MILESTONE_REGISTRY` and getter functions

3. **`scripts/compute_milestone_metrics.py`** (164 lines)
   - Batch processor for all runs in agent_runs.json
   - Outputs per_run_milestones.json and milestone_summary.csv
   - Aggregate statistics by experiment and task

4. **`tests/ci/test_milestone_metrics.py`** (289 lines)
   - 8 comprehensive tests covering:
     - Milestone definitions
     - Real run parsing (HF C1, GitHub C)
     - Edge cases (empty, malformed)
     - Metric calculations

5. **Documentation**
   - `STEP3_MILESTONES.md`: Complete usage guide
   - `STEP3_SUMMARY.md`: Implementation summary

### Output Files Generated

- **`per_run_milestones.json`**: Detailed milestone events for each run
- **`milestone_summary.csv`**: Aggregated metrics ready for analysis

Current coverage: 21 runs from experiment C (baseline)

## Metrics Implemented

| Metric | Range | Interpretation |
|--------|-------|----------------|
| **Milestone Coverage** | 0.0–1.0 | Fraction of expected milestones achieved |
| **Order Score (Kendall τ)** | -1.0 to 1.0 | Correlation with expected sequence |
| **Stall Burden** | 0.0–1.0 | Fraction of steps without new progress |
| **State Revisit Rate** | 0.0–1.0 | Fraction of steps revisiting previous URLs |
| **Post-Intervention Recovery** | 0.0 or 1.0 | Whether navigator broke loops within 2 steps (R-* only) |

## Task Milestone Definitions

### Shopping Price Compare (5 milestones)
M1: Navigate to shopping site → M2: Search query → M3: Results page → M4: Product detail → M5: Extract/done

### Hospital Phone Lookup (6 milestones)
M1: Navigate to map → M2: Search hospital → M3: Results appear → M4: Select POI → M5: Phone visible → M6: Extract/done

### GitHub Issue Audit (7 milestones)
M1: Navigate to issues → M2: Click bug filter → M3: Bug filter active → M4: Apply open+oldest sort → M5: Click oldest issue → M6: Issue detail loaded → M7: Extract/done

### HuggingFace Model Selection (7 milestones)
M1: Navigate to models → M2: Filter Text Generation → M3: Filter PyTorch → M4: Filter Chinese → M5: Sort by downloads → M6: Open model page → M7: Extract/done

## Test Results

```
✅ 8/8 tests passing
✅ 0 type errors
✅ 21 runs processed successfully
✅ HF C1 20260625T050947Z parsed and analyzed
```

### Sample Output (Experiment C Aggregate)

```
C (n=21):
  Mean coverage: 0.871 (87.1%)
  Mean order_score: 0.465
  Mean stall_burden: 0.543 (54.3%)
  Mean revisit_rate: 0.641 (64.1%)

By Task:
  github_clean_issue_audit: coverage=0.657, stall=0.735
  huggingface_model_constrained_selection: coverage=1.000, stall=0.476
  nearby_hospital_phone_lookup: coverage=1.000, stall=0.460
  shopping_price_compare: coverage=0.800, stall=0.514
```

**Insight**: GitHub task has lowest coverage (65.7%) and highest stall burden (73.5%), indicating it's the most challenging task with frequent loop behavior.

## How to Use

### Compute Metrics for All Runs

```bash
uv run python scripts/compute_milestone_metrics.py
```

### Analyze Specific Run in Python

```python
from browser_use.experiments.daily_task_eval.trajectory_metrics import parse_history_for_milestones
import json

with open('history.json', encoding='utf-8') as f:
    history = json.load(f)['history']

metrics = parse_history_for_milestones(
    history, 
    task_id='huggingface_model_constrained_selection',
    run_id='20260625T050947Z',
    experiment_id='C1'
)

print(f"Coverage: {metrics.milestone_coverage:.2%}")
print(f"Stall: {metrics.stall_burden:.2%}")
```

### Add New Task Milestones

1. Define check functions in `task_registry.py`
2. Create milestone list
3. Add to `TASK_MILESTONE_REGISTRY`
4. Write tests

See `STEP3_MILESTONES.md` for detailed examples.

## Next Steps

### To Complete Full Analysis

1. **Update agent_runs.json** with C1/C3/C5 and R-* runs
2. **Rerun computation script** to include all experiments
3. **Analyze R-* recovery yields** to quantify navigator injection effectiveness
4. **Generate paper figures** using milestone_summary.csv
5. **Compare human vs agent trajectories** (requires Step 2 completion)

### Known Limitations

- **C1/C3/C5/R-* runs not in agent_runs.json yet**: Script currently processes only 21 C runs
- **Human reference missing**: Can't compare agent vs human milestone achievement yet
- **No automatic loop detection**: Stall burden is aggregate metric, doesn't identify specific loop locations

### Future Enhancements

- Add milestone-level timing (time to first/last occurrence)
- Detect specific loop patterns (e.g., "re-clicking same element 5+ times")
- Visualizations (milestone DAG coverage, stall heatmaps)
- Integration with adjudicator (milestone coverage as success criterion)

## Relationship to Paper

Milestone metrics are **core evidence** for:

- **Figure 3**: Process quality breakdown by experiment condition
- **Table 2**: Correlation between process metrics and strict_success
- **Appendix A**: Per-task milestone achievement rates
- **Section 4.3**: "Why navigator injection helps" (recovery_yield analysis)

## Verification Checklist

- [x] All 4 main tasks have milestone definitions
- [x] Milestone check functions handle malformed data gracefully
- [x] Kendall tau computed correctly for order score
- [x] Stall burden excludes steps after first 'done' action
- [x] State revisit rate normalizes URL comparison (domain+path only)
- [x] Post-intervention recovery detects navigator injection (R-* only)
- [x] Type checking passes (0 errors)
- [x] All CI tests pass (8/8)
- [x] Script processes real data without errors
- [x] Output files (JSON + CSV) generated correctly
- [x] HF C1 20260625T050947Z case successfully analyzed

## Conclusion

**Step 3 is complete and ready for use.** The milestone system successfully quantifies process-level behavior, explaining why agents succeed or fail beyond binary outcomes. The HF C1 step-14 case demonstrates the system's diagnostic value: despite 100% milestone coverage, the 79% stall burden and 91% state revisit rate reveal a severe loop problem that strict_success alone would miss.

The implementation is production-ready, fully tested, type-checked, and documented. Once agent_runs.json includes all experiment conditions, rerun the computation script to generate complete results for paper analysis.
