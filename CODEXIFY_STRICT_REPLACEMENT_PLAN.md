# Browser Use Strict Codexification Replacement Plan

This plan is for finishing the codexification work by replacing old internal mechanisms, not by adding parallel systems that live forever.

The public API should stay stable where practical:

```python
Agent(task=..., llm=...)
Browser(...)
Tools()
```

Internally, each phase must make one simpler source of truth the default path. Compatibility is allowed only when it is explicit, tested, and temporary.

## Rules

- [ ] Do not mark a phase complete because a new abstraction exists. Mark it complete only when the old hot path is no longer the default.
- [ ] Preserve Browser Use browser-state/action strengths: cleaned DOM, selector map, `backendNodeId`, robust click/type/scroll/tab/download/upload behavior.
- [ ] Keep full runtime handles available: `targetId`, `sessionId`, `frameId`, `backendNodeId`.
- [ ] Prefer explicit services and typed data over event routing, magic injection, and prompt-only contracts.
- [ ] Commit after every phase.
- [ ] Run focused tests and at least one Chromium smoke between phases.
- [ ] Run evals deliberately: small/local evals can be used during the work, but the expensive real-world eval gate runs only at the end.
- [ ] Keep user changes out of commits unless explicitly requested.

## Phase 1: Native Tools Become The Default Protocol

Replace `AgentOutput(action=[...])` as the primary model action protocol.

- [x] Make provider-native tool calls the default for capable models.
- [x] Keep legacy action-list output behind an explicit compatibility flag.
- [x] Represent `done` as a real native tool result, not a fake action.
- [x] Return provider tool-result messages back to the model in the normal loop.
- [x] Remove prompt/schema assumptions that force models to emit Browser Use JSON when native tools are available.
- [x] Prove simple browser tasks work in native mode by default.

## Phase 2: Replace Magic Tool Injection With `ToolContext`

Replace special function-parameter injection as the core tool mechanism.

- [x] Define built-in browser tools as explicit Pydantic input/output models.
- [x] Use one explicit `ToolContext` for browser session, CDP client, page URL, files, sensitive data, extraction schema, and user context.
- [x] Convert built-in tools to `async def tool(params, ctx)` shape.
- [x] Keep `@tools.action(...)` legacy functions through a thin adapter.
- [x] Remove the "parameter must be named exactly `browser_session`" behavior from the primary path.
- [x] Add focused tests for custom legacy tools and new native tools.

## Phase 3: Typed Context Ledger Replaces Message Mutation

Replace the current message-manager mutation model with typed context as the source of truth.

- [x] Store task, steering, browser state, model calls, tool calls, tool results, downloads, files, warnings, screenshots, and compaction as typed context items.
- [x] Render model input deterministically from typed context each turn.
- [x] Persist the exact rendered model input snapshot in debug mode.
- [x] Compact old context items, not the active browser state.
- [x] Keep `MessageManager` only as a compatibility facade, then shrink it.
- [ ] Remove separate save-conversation behavior once run-folder traces cover the same need.

## Phase 4: Direct Browser Services Replace Bubus Control Flow

Replace event dispatch for browser control with direct service calls.

Target shape:

```text
tool -> ToolContext -> BrowserService -> CDP
```

Not:

```text
tool -> event -> bubus -> watchdog -> CDP
```

- [x] Route all public browser actions through explicit services.
- [x] Keep events only for observability/subscribers.
- [x] Remove event-bus fallback dispatch from hot-path browser action execution.
- [x] Keep behavior parity for click, type, scroll, tabs, navigation, downloads, dialogs, uploads, and PDFs.
- [x] Add tests proving public tools no longer require bubus to execute.

## Phase 5: Collapse Watchdogs Into Services

Keep useful heuristics, delete the watchdog architecture where possible.

- [x] Move download behavior into `DownloadService`.
- [x] Move dialog behavior into `DialogService`.
- [x] Move lifecycle finalization into `LifecycleService`.
- [x] Move storage state behavior into `StorageStateService`.
- [x] Move page readiness and recovery policies into explicit services.
- [x] Keep recording/HAR code as explicit finalizers, not hidden watchdog receivers.
- [x] Delete watchdogs that only exist to receive events after service parity is proven.

## Phase 6: Codex-Style Debug Run Folder

Make each debug run locally explainable.

- [x] Create one run folder per agent run in debug mode.
- [x] Save `llm_trace.jsonl`.
- [x] Save rendered model inputs.
- [x] Save tool call/result traces.
- [x] Save browser state snapshots.
- [x] Save screenshots when available.
- [x] Save DOM/selector snapshots.
- [x] Save CDP summaries for browser operations.
- [x] Save timing, token usage, cost, errors, and final outcome.
- [x] Link records by `step`, `tool_call_id`, and browser target/frame identifiers.

## Phase 7: Real Escape-Hatch Tools

Give the model controlled freedom as proper tools, not as hidden prompt behavior.

- [ ] `browser.get_state`
- [ ] `browser.get_html`
- [ ] `browser.get_accessibility_tree`
- [ ] `browser.evaluate`
- [ ] `browser.cdp`
- [ ] `browser.network`
- [ ] `browser.fetch`
- [ ] `file.read`
- [ ] `file.write`
- [ ] Consider `shell.run` only after file/browser tools are stable and safety boundaries are explicit.

## Phase 8: Delete Old Internal Runtime Paths

After default native tools, typed context, and direct services are stable, remove old internals.

- [ ] Delete or shrink legacy action-list executor internals.
- [ ] Delete old message-manager core logic.
- [ ] Delete bubus hot-path control logic.
- [ ] Delete watchdog routing that has explicit service replacements.
- [ ] Delete duplicated prompt variants that only support old action protocols.
- [ ] Delete dead compatibility adapters after deprecation tests pass.

## Phase 1 Verification

- [x] Focused unit tests for the changed path.
- [x] Existing compatibility tests for the public API.
- [x] Chromium smoke using a simple local or stable web page.
- [x] At least one real Browser Use task with the default recommended model when keys are available.
- [x] If the phase changes model/tool/context behavior, inspect the debug run folder and confirm it explains the run clearly.
- [x] `uv run ruff check ...`
- [x] `uv run pyright ...`
- [x] `uv run pre-commit run --all-files`

## Phase 2 Verification

- [x] Focused unit tests for the changed path.
- [x] Existing compatibility tests for the public API.
- [x] Chromium smoke using a simple local or stable web page.
- [x] At least one real Browser Use task with the default recommended model when keys are available.
- [x] If the phase changes model/tool/context behavior, inspect the debug run folder and confirm it explains the run clearly.
- [x] `uv run ruff check ...`
- [x] `uv run pyright ...`
- [x] `uv run pre-commit run --all-files`

## Phase 3 Verification

- [x] Focused unit tests for the changed path.
- [x] Existing compatibility tests for the public API.
- [x] Chromium smoke using a simple local or stable web page.
- [x] At least one real Browser Use task with the default recommended model when keys are available.
- [x] If the phase changes model/tool/context behavior, inspect the debug run folder and confirm it explains the run clearly.
- [x] `uv run ruff check ...`
- [x] `uv run pyright ...`
- [x] `uv run pre-commit run --all-files`

## Phase 4 Verification

- [x] Focused unit tests for the changed path.
- [x] Existing compatibility tests for the public API.
- [x] Chromium smoke using a simple local or stable web page.
- [x] At least one real Browser Use task with the default recommended model when keys are available.
- [x] If the phase changes model/tool/context behavior, inspect the debug run folder and confirm it explains the run clearly.
- [x] `uv run ruff check ...`
- [x] `uv run pyright ...`
- [x] `uv run pre-commit run --all-files`

## Phase 5 Verification

- [x] Focused unit tests for the changed path.
- [x] Existing compatibility tests for the public API.
- [x] Chromium smoke using a simple local or stable web page.
- [x] At least one real Browser Use task with the default recommended model when keys are available.
- [x] If the phase changes model/tool/context behavior, inspect the debug run folder and confirm it explains the run clearly.
- [x] `uv run ruff check ...`
- [x] `uv run pyright ...`
- [x] `uv run pre-commit run --all-files`

## Phase 6 Verification

- [x] Focused unit tests for the changed path.
- [x] Existing compatibility tests for the public API.
- [x] Chromium smoke using a simple local or stable web page.
- [x] At least one real Browser Use task with the default recommended model when keys are available.
- [x] If the phase changes model/tool/context behavior, inspect the debug run folder and confirm it explains the run clearly.
- [x] `uv run ruff check ...`
- [x] `uv run pyright ...`
- [x] `uv run pre-commit run --all-files`

## Required Verification Per Phase

- [ ] Focused unit tests for the changed path.
- [ ] Existing compatibility tests for the public API.
- [ ] Chromium smoke using a simple local or stable web page.
- [ ] At least one real Browser Use task with the default recommended model when keys are available.
- [ ] If the phase changes model/tool/context behavior, inspect the debug run folder and confirm it explains the run clearly.
- [ ] `uv run ruff check ...`
- [ ] `uv run pyright ...`
- [ ] `uv run pre-commit run --all-files`

## Final Eval Gate

Run this only after all replacement phases are implemented, tested, and committed.

- [ ] Run a final real-world eval on `/Users/greg/Downloads/real_v17_short.json`.
- [ ] Use the current default recommended Browser Use model unless the user explicitly requests a different model.
- [ ] Run with enough debug logging to preserve local run folders for failed tasks.
- [ ] Report task-level pass/fail, final answers, major failure modes, and trace locations for failures.
- [ ] Report aggregate success rate, average steps, average duration, token usage, and estimated cost.
- [ ] Compare against any available baseline from before the strict replacement work.
- [ ] Do not mark the strict replacement goal complete until the eval result is reported.

## Non-Goals

- [ ] Do not rewrite DOM processing from scratch.
- [ ] Do not remove `backendNodeId` or runtime CDP identifiers.
- [ ] Do not break existing public `Agent`, `Browser`, or `Tools` usage without an explicit compatibility path.
- [ ] Do not keep two complete internal runtimes once the replacement path is proven.
