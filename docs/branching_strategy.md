# Daily Task Eval — branching strategy

This fork splits Daily Task Eval work into three local branches so the current C/D paper line and the future full Human–Agent evaluation protocol do not contaminate each other.

## Branches

| Branch | Purpose |
|--------|---------|
| `daily-task-eval-core` | Shared, verified infrastructure: models, runner, CSV export, dual LCS, CI tests, CLI entrypoints, and cross-cutting bug fixes. |
| `paper-cd-only` | C vs D study only (Doubao executor ± DeepSeek navigator). Human trajectories are a single reference baseline for LCS—not a multi-reference gold protocol. |
| `paper-full-eval` | Future complete Human–Agent evaluation: multi-human reference sets, milestones, Human Navigation Skeleton, E/N/H/HN ablations, and paper tables. |

## Lineage

```text
ZYH_version
└── daily-task-eval-core
    ├── paper-cd-only
    └── paper-full-eval
```

`ZYH_version` is frozen as the pre-split integration branch. Do not rewrite its history.

## Workflow

1. **Shared fixes and harness improvements** land on `daily-task-eval-core` first (with CI green on `tests/ci/test_daily_task_comparison.py`).
2. **Cherry-pick or merge** from `daily-task-eval-core` into `paper-cd-only` and/or `paper-full-eval` as needed.
3. **C/D-only changes** (presets, C/D docs, C/D result interpretation) go only on `paper-cd-only`.
4. **Full-eval protocol changes** (multi-human references, skeleton guidance, new experiment ids) go only on `paper-full-eval`.
5. **Do not merge unverified full-eval features into `paper-cd-only`.** Keep the C/D paper line stable and reproducible.

## Push (manual)

After review, push each branch independently:

```bash
git push -u origin daily-task-eval-core
git push -u origin paper-cd-only
git push -u origin paper-full-eval
```
