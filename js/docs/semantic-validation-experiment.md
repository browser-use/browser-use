# Testing generated data transformations

This is a prepared experiment after runtime `2737754`. The running confirmation remains pinned to `f41c5b7`; no result is replaced.

## Why this change

The [paired trace audit](./confirmation-trace-audit.md#generated-transformations-can-corrupt-correct-observations) found correct or explicitly unknown source records corrupted during report construction. A boolean expression discarded 92 exclusion reasons; truthy error payloads became verified records; unknown timezone text became an explicit timezone; a negated account statement became an account gate. The agents checked parsing, counts and nonblank cells without testing these transformations. The higher-scoring reference on one task visibly checked error cases and canonical/export agreement, though it still made other errors.

The separate [journal diagnostic](./journal-discovery-experiment.md#completed-real-model-diagnostic) also showed a report becoming stale after a later observation. Its live journal was available but never read. A discoverable archive alone does not establish evidence fidelity.

## Treatment

Replace overlapping research and final-delivery prose with a short request to test transformations on observed successes, missing values, errors and contradictions. Check field types and meaning, compare generated files with canonical records, and update reports after later observations. Preserve exact excerpts separately from interpretation and check eligibility before counting rows.

The entire prompt grows by **65 characters**. There are no site names, task IDs, expected answers, grader rules, registry-specific parsers or field-specific validators in the treatment. Browser commands, agent loop, tool schemas, retry policy, model, reasoning, compaction thresholds, deadlines and budgets are unchanged. The prompt still requires raw data, source coverage, honest unknown states and the user's missing-item fallback.

This is guidance, not enforcement. A model can omit a check or write an incorrect one. Adding another sentence cannot be called a proven repair. A separate model reviewer would add inference, context transfer and another failure mode; it is not part of this experiment.

## Verification and next decision

Typecheck and the existing compaction, journal and structured-result tests pass at their original limits. These scripted-model tests validate compatibility and the tight context boundary, not real-model adoption. The first full suite exposed a separate cleanup acknowledgement gap. After its independently tested fix, **94/94 Node tests** and **7/7 Python bundle tests** pass, as does the docs build. [Cleanup change](./cleanup-verification.md). Any new full cohort includes this additional runtime change and must say so. Verification is recorded in [verification evidence](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/semantic-validation.json).

The candidate was prepared while five confirmation outcomes remained pending. Select any next full cohort only after retaining the complete current outcomes. A real-model diagnostic must inspect actual checking behavior and source-to-report agreement; a higher single score alone cannot validate the mechanism. Keep its outcome, controls, costs and cleanup separate. The model may spend additional existing steps on validation, reducing time for collection; neither speed nor improved quality is guaranteed.

No public option, persisted-data format, Python API, login profile, or legacy Browser Use behavior changes. The Python bundle must be rebuilt to carry the same prompt. Rollback is runtime `2737754`; histories and existing artifacts remain readable. No package publication or merge is included.
