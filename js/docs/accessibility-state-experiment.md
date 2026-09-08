# Accessibility state preservation

Prepared separately from the running second confirmation. No benchmark result is attributed to this change.

## Observed gap

At runtime `65a16cb`, `Page.snapshot()` receives Chrome's complete accessibility nodes but maps each one to only its ID, role, name and optional value. It discards reported control properties. A checked radio and an unchecked radio therefore lack their checked state in the returned snapshot. Raw CDP and DOM inspection can recover it, but the advertised discovery helper loses it.

Two local tests against that unchanged build failed because checked state was `undefined`, including controls inside shadow DOM. These are real isolated Chrome sessions with synthetic fixtures, not live benchmark sites or mocked CDP responses.

## Change

Preserve five optional properties directly from Chrome: `checked`, `pressed`, `selected`, `expanded`, and `disabled`. Checked and pressed support `true`, `false`, and `'mixed'`; the other fields are booleans. Absent state remains absent rather than becoming false. Do not infer selection from names, add domain selectors, or automatically act on any state.

The same mapping applies to page and explicit-frame snapshots. Each call reads fresh Chrome data; earlier returned observations remain unchanged. The model-facing API description documents the fields and absent-state semantics. There are no additional CDP requests, new tools, retries, or changes to task/model/judge budgets.

## Verification and limits

The targeted real-Chrome tests pass after the mapping change. They exercise native radios, an indeterminate checkbox, ARIA selected/expanded/pressed state, disabled input rejection, actual clicks and subsequent snapshots, navigation, shadow DOM and an explicit iframe. The ordinary button has no invented state properties. These checks prove exposure of the observed fixture state. They do not prove that a model will use it correctly or that any live score will increase.

The first broader suite passed 95 of 96 tests. Its Findings fixture failed because the default `python3` resolved to macOS's Xcode shim; the existing `BU_EVAL_PYTHON` override selected the installed CPython interpreter. The full rerun passed **96/96 Node tests**, including the unchanged 35,000-character compaction and journal boundaries. The rebuilt Python engine passed **7/7 integration tests**. Typecheck passed. The local environment was Node 23.11.0 and CPython 3.12.11 on macOS; this does not establish new cross-platform coverage or a tested wheel release.

This is an additive change to the public `AXNode` type and snapshot output. Existing IDs, role/name matching and click behavior remain unchanged. There is no profile, transcript or persisted-data migration, no Pi fork, and no modification to the Python Browser Use library. Snapshots can contain more text, so the existing context/compaction boundary tests remain required. Rollback is the previous SDK SHA. All four running confirmation2 arms remain pinned to their original commits.

The [trace audit](./confirmation2-trace-audit.md) includes control-state interpretation errors, but those traces do not isolate missing AX properties as their cause. A fresh frozen diagnostic and complete matched evaluation are required before making a quality claim.

[Verification evidence](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/accessibility-state.json).

## Frozen diagnostic

Freeze runtime `7d1c107` on the single previously inspected Hard task `hukwqv`, GPT-5.5 medium and unchanged Laith GPT-5.5. Retain the full per-task Hard budgets, US proxy and browser lifetime; concurrency is one. Inspect whether actual tools read the new state properties, verify selection after changing configuration, and preserve requested variants. Provisioning, inference, screenshots, delivered artifacts, actual judgment and cleanup must also complete. The same four confirmation2 cohorts remain untouched. This diagnostic is separate, can overlap them, and cannot establish a ranking or replace an outcome. The exact plan is saved before dispatch.

[Frozen inputs and selection limits](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/accessibility-state-plan.json).

The plan was pushed at `775129f` before the single diagnostic was dispatched. Its prepare job succeeded and its original task job is running: [GitHub 34201460363](https://github.com/browser-use/new-eval-platform/actions/runs/34201460363), Laminar `676dfc4f-1a92-425f-9b33-d837a96e6edd`. No outcome exists yet. [Dispatch record](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/accessibility-state-dispatch.json).
