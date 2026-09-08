# Testing generated data transformations

This experiment follows runtime `2737754`. The completed confirmation remains pinned to `f41c5b7`; no result is replaced.

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

## Frozen diagnostic

One task, `bub2-009`, at SDK `65a16cb6e43a31e67d59a7ed841858e70f05a5ba`, Luna/Findings Luna xhigh, 1,000 steps, 3,600 seconds, 800,000 characters and one parallel job. The full per-task controls are preserved; timing and concurrency differ from the cohorts. Inspect actual transformation checks and the generated fields. Do not substitute the outcome into confirmation or treat the previous 44/100 as a concurrent control. [Exact plan](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/semantic-validation-plan.json).

The earlier candidate had 59 of 60 outcomes at diagnostic selection. Even a perfect last task would cap its assigned mean at 58.83/100, below the frozen 59.00 floor. This monotone upper bound explains why another experiment is necessary; it is not a replacement score. Both remaining confirmation tasks continue, and all outcomes will be retained before the next full-cohort selection.

## Completed diagnostic

The September 8 diagnostic finished at **60/100**, with a real Findings judgment and a successful [workflow 34193959471](https://github.com/browser-use/new-eval-platform/actions/runs/34193959471). SDK `65a16cb`, Luna xhigh, 128 tool executions, 1,899.345 agent seconds, **$0.28926299 recorded agent inference**, 21 delivered files, zero compactions and zero SDK inference retries. All 101 judge PNGs have valid signatures. Three screenshot warnings followed the initial tab-list cell and two syntax-error cells. No cleanup error was recorded; a read-only Cloud check confirmed the owned browser stopped. All 335 owned browsers from the completed confirmation and its three diagnostics are now confirmed stopped.

All **93 exclusion reasons are nonempty strings** in the canonical data and exported exclusion sheet. The prior boolean-reason corruption did not recur. The agent repaired undefined page ranks, adjusted exclusion/cap counts, inspected a workbook coverage row and README values, and regenerated files after changes. Those are useful checks. Reviewing all 128 tool calls did not find transformation tests on missing/error/contradictory records, or a comparison of screening status/reason fields between canonical data and workbook.

A direct XLSX audit found **171/171 blank status cells and 171/171 blank reason cells** in Search Inventory. The canonical `screenedProjects` has both fields for all 171 rows. The generator populated that sheet from the raw `searchInventory` instead. The separate exclusion sheet correctly retains 93 reasons, so this is a specific worksheet delivery defect, not loss of the entire screening log. Row-count checks passed despite the wrong source selection.

Two source contradictions were independently checked: Bastrio was excluded for a missing license although its captured README names GNU GPL v3.0; Stagehand Python was retained and ranked highly despite a captured archived/read-only notice. Ten of 53 installation-evidence fields explicitly say the excerpt did not capture installation instructions. The judge also rejected the Silkworm registry claim; its row does disclose that package JSON was not queried. Do not describe that gap as wholly undisclosed.

The judge awarded search execution, screening depth/log, classification, artifact shape and completion-honesty items. It rejected verification, coverage, source fidelity and qualification items. Its official 60 stays unchanged. An initial local suspicion about escaped newline splitting was disproved by decoded source and actual output; it is excluded from the defect list.

**Integration and lifecycle passed; semantic-test adoption remains unproven.** This is one previously inspected task, with different timing/concurrency from the earlier 44/100 candidate and 82/100 reference. It cannot establish a score improvement or justify replacing either outcome. A full paired cohort must evaluate the complete runtime bundle, including image limits, provider recovery, journal discovery and cleanup verification, with the original model, judge, tasks, budgets and margin.

[Pinned manifest, source hashes, numerical audit and limitations](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/semantic-validation-smoke.json).
