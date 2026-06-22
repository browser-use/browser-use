# Study scope — full Human–Agent evaluation (`paper-full-eval`)

This branch is the home for the **complete** human–agent evaluation protocol. It shares harness code with `daily-task-eval-core` but does **not** claim that future capabilities are already implemented.

## Planned protocol (not all present yet)

The full line will include:

- multiple independent human reference runs;
- human outcome validation;
- reference eligibility rules;
- milestone-based evaluation;
- route comparability and cross-site fallback labels;
- Human Navigation Skeleton guidance;
- no-guidance / navigator / human-guidance / combined-guidance ablations;
- canonical trajectory LCS and navigation-level LCS.

## Relationship to `paper-cd-only`

- **C/D results and presets** stay on `paper-cd-only`; this branch must not overwrite or reinterpret existing C/D artifact files as if full-eval features were used.
- New experiment ids (E, N, H, HN, …) and protocol fields are developed here first, then shared infrastructure merges back through `daily-task-eval-core` when stable.

## Current status

At branch creation, only **scope documents and roadmap** are added. Implementation follows `docs/full_eval_roadmap.md`.

See `docs/branching_strategy.md` for merge and cherry-pick rules.
