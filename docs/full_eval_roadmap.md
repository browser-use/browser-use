# Full Human–Agent evaluation roadmap

Phased plan for `paper-full-eval`. Each phase should land with tests and docs before downstream phases depend on it.

## Phase 1: validate human reference records

- Audit existing `human_runs.json` entries for completeness (outcome, steps, URLs, stuck/recovery notes).
- Define minimum fields for a reference run to enter comparison.
- Document validation failures and fix or exclude bad baselines.

## Phase 2: add multi-human reference-set support

- Schema for multiple independent human runs per task/scenario.
- Selection / aggregation policy (e.g. best LCS, union of milestones).
- CLI and compare report updates—without breaking single-reference mode on `paper-cd-only`.

## Phase 3: add route comparability and milestone annotations

- Milestone labels on human and agent trajectories.
- Route comparability checks and cross-site fallback labels when paths diverge legitimately.
- Navigation-level vs canonical LCS reporting aligned to milestones.

## Phase 4: implement Human Navigation Skeleton guidance

- Extract skeleton from validated human references.
- Inject skeleton guidance into agent runs (human-guidance condition).
- Keep no-guidance and navigator-only baselines reproducible.

## Phase 5: run E/N/H/HN controlled experiments

- Register experiment presets for ablations (executor-only, navigator, human-guidance, combined).
- Run controlled batches; store structured summaries and CSV exports per method.
- No pre-filled paper numbers until runs complete.

## Phase 6: generate paper tables and figures

- Aggregate metrics across tasks and methods.
- Figures for LCS, cost, success rate, navigator overhead.
- Separate artifact bundle from the C/D-only paper line.
