# Preserve evidence across errors and named tabs

The completed delivery-review diagnostic exposed two concrete SDK defects. This candidate fixes evidence transport and observation routing. It does not change the task prompt, delivery-review default, judge, budgets, browser viewport, or retry policy.

## Observed failure and reproduction

A JavaScript cell can capture an image or mutate the browser and then fail. The worker returns `CellError.result` with the captured image, output path and page target. The SDK previously converted it to an ordinary thrown error. Pi consequently emitted text with empty details, discarding the image before the next model turn and leaving the evaluator no target to capture. A real-Chrome scripted-model test reproduces this by saving once, taking a screenshot and throwing: the next model turn must see one native image and `isError: true`, and the subsequent browser read must still say saved exactly once. The test failed before this patch.

Separately, the worker reported the global `page.targetId` even when code used `const other = await tabs.open(...)` or sent raw commands to another session. The diagnostic has 183 nonempty result target IDs, all for the primary page, despite successful named-tab work. The new two-tab test reproduces the mismatch. These defects explain specific evidence loss, not the entire aggregate benchmark regression.

## Change

- Restore a failed cell's native images and structured metadata through Pi's existing `afterToolCall` integration, preserving the error flag. Application hooks receive that evidence and retain their normal override authority. No Pi fork or action replay.
- Keep primary-page recovery and observation targets separate. An additive `observationTargetId` tracks the last protocol target, including named tabs and raw session commands. The evaluator uses it for the existing screenshot operation.
- Map out-of-process iframe observations to the owning top-level page using CDP's reported target/frame relationships. Chrome cannot screenshot an iframe target directly. Recording routes to that page and omits cursor coordinates when they belong to a child frame.
- Preserve the primary target returned with a failed initial cell, so a later worker reset can reconnect to the existing page. The browser action is never replayed.

Tracking is passive: no extra browser calls, automatic navigation, retries, selector rules, task-specific logic or rubric knowledge. A tab list alone does not select a page. An unknown or closed target remains unavailable; the observer does not guess a replacement. Work using separately constructed CDP connections outside the SDK's shared connection remains outside this tracking.

## Compatibility and test scope

No model, dependencies, user prompt, profile, transcript version, public options or legacy Python library change. `targetId` retains its primary-page meaning. Python bundles the same updated engine. Error events now carry images that were previously lost, so next-turn token/image use can increase. Existing caller hooks can replace the content before the model sees it. Whole-cell termination cannot recover images still only in the killed worker; durable files remain available.

Local regressions cover failed-cell image delivery through real Pi and hooks, no later-cell image leakage, exactly-once browser mutation, named tabs, raw session commands, cross-origin frames, reconnect, closed targets, primary recovery after an initial failure, and evaluator PNG dimensions from the named tab after an error. The existing suite also covers cancellation, policy hooks, session persistence and actual MP4/GIF export. The full suite passes **107/107 on Node 22.23.2** (also 107/107 on Node 23.11.0), and **7/7 Python integration tests** pass. Typecheck and the docs build pass. [Source and verification hashes](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/observation-evidence-verification.json). Remote quality remains unproven until the new frozen evaluations finish.

## Evaluation plan

Run one original-budget diagnostic on Hard task `hukwqv` and one on Luna task `bub2-020`, one attempt each. Freeze the candidate commit and inputs before dispatch. Retain every outcome, actual judgment, screenshot error, runtime error, artifact and usage record. Verify browser cleanup. A low score does not itself fail the integration gate, but missing/broken evidence or an uncontained runtime failure does.

Only after those diagnostics are terminal and audited, select the next full matched arms. Use the corrected screenshot-ownership reference pins `769ea148382cb9094662188a593b0410f6e9f0d5` (Hard) and `c3f7fac2d8a46a3801e06d89a3c3c9b1343db79e` (Luna), whose agent runtime trees remain byte-identical to their historical originals. Candidate evidence completeness is part of the treatment; the judge and evidence renderer remain unchanged. Do not interpret a score gain as pure improvement in agent reasoning.

The original 106/60 task sets, model/reasoning, judges, budgets, one attempt, 12-job full-arm concurrency, historical targets, 3-point margin and frozen 20,000-resample uncertainty procedure remain in force. All previous results remain. These are development benchmarks, not held-out SOTA evidence. Rollback is the prior SDK SHA; never replay uncertain browser actions during rollback.
