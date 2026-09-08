# Delivery review experiment

This is an optional evaluation policy using the SDK's existing `validateResult` hook. It is not enabled by default and does not add an SDK parameter, a second model, a new tool or a new agent loop. No live quality result exists at preparation.

## Hypothesis

Selected traces show intact observations followed by incorrect artifact reconstruction or interpretation. In the [currency audit](./confirmation2-trace-audit.md#correct-source-strings-changed-during-reconstruction), Unicode source strings reached the model intact, but manually constructed final records changed them. Synthetic parser examples were then labeled as exact observations. Earlier general verification guidance did not prevent those errors.

A single explicit checkpoint at the first schema-valid finish may prompt a useful comparison between the proposed delivery, the original task and retained sources. This is a hypothesis about model behavior, not a proven bug fix. A late check cannot undo a forbidden action already taken, recover nonexistent evidence, or guarantee truthful output.

## Implementation and limits

The evaluation option `delivery_review: true` installs a validation callback that returns review feedback on the first schema-valid submission only. A later schema-valid finish is accepted under the existing SDK rules. Both `finish` and `finish_from_js` use that same validation path. The feedback asks the agent to compare consequential claims and exact fields with retained source observations, correct unsupported statements, preserve conflicts and failures, respect task boundaries, and state unresolved gaps.

The original transcript, model, tools, context, time, step and cost limits remain in force. Review can use the remaining budget and can exhaust it; no extra turn allowance is created. `delivery_review_submissions` counts calls to the enabled callback, not completed factual audits. A model may simply submit again without checking anything. The diagnostic must inspect actual tool use and changed artifacts to distinguish a useful review from an extra finish call.

Omitting the option preserves existing behavior and option manifests. Explicit false also disables it; non-boolean values fail. The SDK's default prompt and public API remain unchanged. The evaluation adapter already owns the one task-local session, so the counter cannot leak across runs. No profiles, histories, dependencies, Python engine or legacy customers change. Rollback is disabling the option or using the preceding adapter SHA.

## Local verification

Real isolated Chrome with scripted provider responses checks ordinary default/Findings flows, evaluator screenshot retention after agent cleanup, one rejected finish followed by accepted delivery, and exhaustion at the original two-turn budget without a third model request. The seven adapter tests and full **103/103 Node tests** pass, as does typecheck. These tests prove feedback delivery, accounting, cleanup and budget enforcement. They do not prove semantic review: the scripted model simply submits a second time.

## Diagnostic selection

Prepare a two-arm diagnostic on the previously inspected `bub2-020` task: the same SDK commit with `delivery_review: false` and `true`. Use Luna xhigh and the original Findings Luna xhigh judge, task, 3600-second agent budget, 1000-step limit, 800,000-character context allowance, US proxy, 70-minute browser lifetime, 62-minute runner budget and one concurrent job per arm. Both arms use the same evaluator screenshot-ownership correction. Freeze exact inputs before dispatch; dispatch each once.

The purpose is to observe whether the checkpoint is reached, whether retained sources are consulted, whether source/artifact discrepancies are actually repaired, and whether the extra phase stays within budget with complete evidence and cleanup. Preserve the full task outcomes, missing judgments, boundary violations and costs. This selected one-task comparison cannot rank harnesses or satisfy either full-benchmark criterion. It may overlap the original Luna confirmation; all original SDK pins and outcomes remain untouched. No full-cohort candidate is selected from an unfinished confirmation.

The exact SDK and dispatch inputs will be pinned in a separate plan after local verification. Any later full confirmation must retain the original historical targets, paired uncertainty procedure and three-point margin.

[Local verification and source hashes](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/delivery-review-verification.json).
