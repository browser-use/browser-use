# Browser Use Codexification Plan

Plan for making Browser Use simpler, more capable, and more Codex-like without throwing away the browser automation heuristics that already work.

The important idea: **Browser Use should keep its excellent browser state/action layer, but the agent runtime around it should become more like Codex: typed context, native tools, streaming events, explicit services, compaction, and escape hatches.**

This document is intentionally not a full implementation spec. Each implementation agent should inspect the relevant code paths before editing. The plan gives the direction, phase boundaries, constraints, and acceptance criteria.

## Principles

- [ ] Preserve Browser Use's current browser automation strengths.
- [ ] Keep `backendNodeId` as the model-visible element index unless a better replacement is proven.
- [ ] Keep runtime access to full `targetId`, `sessionId`, `frameId`, and `backendNodeId`.
- [ ] Give the model more freedom through screenshot, coordinate click, JS eval, raw CDP, HTML/markdown reads, accessibility tree, network inspection, and HTTP fetch.
- [ ] Replace heavy indirection with explicit runtime pieces.
- [ ] Keep old behavior working while the new runtime is introduced.
- [ ] Use focused tests and evals to prove each simplification works.
- [ ] Avoid huge rewrites that remove hard-won browser heuristics.

## What To Keep

- [ ] State -> action browser automation loop.
- [ ] DOM processing and cleaned interactive representation.
- [ ] Selector map keyed by `backendNodeId`.
- [ ] Robust click, type, scroll, tabs, downloads, dialogs, upload, and PDF behavior.
- [ ] `ActionResult` style structured feedback.
- [ ] `ChatBrowserUse` as the recommended default model for browser automation.
- [ ] `Browser(use_cloud=True)` as the production performance path for hosted browser execution.

## What To Simplify

- [ ] Message manager.
- [ ] Fake structured-output action protocol.
- [ ] Bubus/event bus in the hot action path.
- [ ] Watchdog architecture.
- [ ] Giant agent/browser/tool files.
- [ ] Dynamic tool/action model generation.
- [ ] Prompt variant sprawl.
- [ ] Cloud, telemetry, GIF, and callback logic inside the core agent loop.

## Phase 0: Baseline

Goal: make sure we know what must not break before changing architecture.

Implement:

- [x] Identify current behavior that must not regress.
- [x] Add or collect tests for DOM ids, click/type, downloads, dialogs, tabs, uploads, extraction, screenshots, and `multi_act`.
- [x] Capture baseline smoke/eval numbers for success rate, steps, speed, token usage, and common failure modes.
- [x] Run targeted current suites and document known failures.

Relevant context to inspect:

- [x] Agent step loop.
- [x] DOM serializer and selector map.
- [x] Click/type action code.
- [x] Downloads/dialogs/tabs behavior.
- [x] Existing browser CI tests and task evals.

Exit criteria:

- [x] Current behavior is covered well enough that later simplification is safe.
- [x] There is a baseline for accuracy, speed, token usage, and flakiness.

## Phase 1: Runtime Shape

Goal: introduce the Codex-like runtime skeleton without changing default behavior.

Implement:

- [x] Add a session/turn runtime layer beside the existing `Agent`.
- [x] Add high-level concepts: session, turn context, runtime config, model capabilities, event stream, artifact store.
- [x] Keep `Agent` as the public facade.
- [x] Keep the old runtime as the default path while the new pieces mature.

Suggested shape:

- [x] `BrowserAgentSession`
- [x] `BrowserTurnContext`
- [x] `BrowserRunConfig`
- [x] `ModelCapabilities`
- [x] `ToolContext`
- [x] `BrowserRuntimeEvent`
- [x] `BrowserEventStream`
- [x] `ArtifactStore`

Exit criteria:

- [x] New runtime objects can represent a run and a turn.
- [x] No public API break.
- [x] Existing tests still pass.

## Phase 2: Typed Context

Goal: replace message-manager string mutation with typed context items and deterministic rendering.

Implement:

- [x] Represent task, user steering, browser state, tool calls, tool results, downloads, files, artifacts, warnings, and compaction as explicit context items.
- [x] Render model input from typed context deterministically.
- [x] Keep current browser state fresh every turn.
- [x] Compact or summarize old context, not the active page.
- [x] Preserve current runtime handles even if the model-visible context is compact.

Suggested context items:

- [x] `TaskItem`
- [x] `UserSteerItem`
- [x] `BrowserStateItem`
- [x] `ToolCallItem`
- [x] `ToolResultItem`
- [x] `DownloadItem`
- [x] `FileArtifactItem`
- [x] `ExtractionArtifactItem`
- [x] `WarningItem`
- [x] `CompactionItem`

Relevant context to inspect:

- [x] Current message manager.
- [x] Current prompt rendering.
- [x] `ActionResult` memory/read-state handling.
- [x] Browser state prompt.
- [x] Agent history models.

Exit criteria:

- [x] New context renderer can reproduce the important content of the old message manager.
- [x] Context rendering is testable with snapshots or focused assertions.
- [x] Old message manager can remain behind compatibility path.

## Phase 3: Native Tool Calls

Goal: make native tool calls the primary action protocol.

Implement:

- [ ] Define browser tools with explicit Pydantic v2 input/output models.
- [ ] Route tools through one `ToolContext`, not magic function parameter injection.
- [ ] Keep compatibility with the old `AgentOutput(action=[...])` path during migration.
- [ ] Treat `done` and structured final output as proper native outputs, not fake actions.
- [ ] Keep `ActionResult`/tool result content structured and model-readable.

Core tools:

- [ ] `browser.navigate`
- [ ] `browser.click`
- [ ] `browser.click_coordinates`
- [ ] `browser.type`
- [ ] `browser.scroll`
- [ ] `browser.send_keys`
- [ ] `browser.extract`
- [ ] `browser.screenshot`
- [ ] `browser.evaluate`
- [ ] `browser.cdp`
- [ ] `browser.get_state`
- [ ] `browser.find_elements`
- [ ] `browser.search_page`
- [ ] `browser.switch_tab`
- [ ] `browser.close_tab`
- [ ] `browser.upload_file`
- [ ] `browser.wait`
- [ ] `browser.done`

Exit criteria:

- [ ] Native tool-call mode can complete simple browser tasks.
- [ ] Old action-list mode still works.
- [ ] Tool results are added back into typed context.

## Phase 4: Direct Browser Services

Goal: move browser action execution out of bubus/watchdog routing.

Implement:

- [ ] Create explicit services for state capture, actions, downloads, dialogs, tabs, network, lifecycle, and storage.
- [ ] Preserve useful watchdog heuristics by moving them into direct service methods.
- [ ] Keep event streaming for observability, not internal control flow.
- [ ] Keep compatibility path until direct services have parity.

Suggested services:

- [ ] `BrowserStateService`
- [ ] `ActionService`
- [ ] `ClickService`
- [ ] `TypeService`
- [ ] `NavigationService`
- [ ] `TabService`
- [ ] `DownloadService`
- [ ] `DialogService`
- [ ] `NetworkService`
- [ ] `StorageStateService`
- [ ] `LifecycleService`

Target shape:

```text
tool -> service method -> CDP
```

Not:

```text
tool -> event -> bubus -> watchdog -> CDP
```

Exit criteria:

- [ ] Core actions can execute without bubus in the hot path.
- [ ] Downloads and dialogs still work.
- [ ] Click/type behavior remains at least as robust as before.

## Phase 5: Streaming Events

Goal: make runs observable without coupling internal control flow to an event bus.

Implement:

- [ ] Add a clean runtime event stream.
- [ ] Emit events for turns, context, model output, tool calls, browser state, downloads, artifacts, compaction, completion, and failures.
- [ ] Move cloud sync, telemetry, GIF generation, and user callbacks to subscribers.
- [ ] Make runs understandable without reading internal debug logs.

Example events:

- [ ] `turn.started`
- [ ] `context.built`
- [ ] `model.delta`
- [ ] `tool.started`
- [ ] `tool.completed`
- [ ] `browser.state_refreshed`
- [ ] `download.started`
- [ ] `download.completed`
- [ ] `artifact.created`
- [ ] `context.compacted`
- [ ] `turn.completed`
- [ ] `run.completed`

Exit criteria:

- [ ] Cloud/telemetry/GIF/callback behavior can be implemented as subscribers.
- [ ] A failed run can be debugged from events and typed history.

## Phase 6: Browser-Harness Escape Hatches

Goal: give the model more freedom while keeping Browser Use's cleaned DOM state as the default.

Implement:

- [ ] Add first-class tools for screenshot, coordinate click, JS eval, raw CDP, HTML, markdown, accessibility tree, element inspection, network requests, and HTTP fetch.
- [ ] Let the model choose between DOM index actions, coordinate actions, JS/CDP, extraction, or HTTP depending on the situation.
- [ ] Add guidance for when each tool style is appropriate.

Important:

- [ ] Do not remove the current DOM pipeline.
- [ ] Do not hide runtime handles needed for CDP.
- [ ] Do not force the model to use a single representation of the page.

Exit criteria:

- [ ] The model can solve tasks using DOM, screenshot, coordinates, JS, CDP, and HTTP as appropriate.
- [ ] Simple tasks do not get slower or noisier.

## Phase 7: File And Shell Workspace

Goal: bring in the useful Codex-style file/shell interaction for browser tasks that produce artifacts or need data processing.

Implement:

- [ ] Add optional permission-gated file tools.
- [ ] Add optional permission-gated shell tools.
- [ ] Connect downloads and generated artifacts to the workspace.
- [ ] Keep outputs truncated and artifact-backed when large.

Use cases:

- [ ] Inspect downloaded files.
- [ ] Transform CSV/JSON/HTML/PDF data.
- [ ] Run small helper scripts.
- [ ] Validate extracted results.
- [ ] Persist artifacts across turns.

Exit criteria:

- [ ] Browser tasks can work with downloaded/generated files.
- [ ] Shell/file tools are disabled or permission-gated where unsafe.

## Phase 8: Skills And Playbooks

Goal: borrow the browser-harness idea of relevant domain/interaction skills without bloating every prompt.

Implement:

- [ ] Add optional domain and interaction skills.
- [ ] Load skills only when relevant by URL, task, explicit mention, or repeated failure.
- [ ] Keep skills out of the base prompt unless needed.
- [ ] Start with interaction skills for downloads, dialogs, iframes, shadow DOM, dropdowns, and uploads.

Exit criteria:

- [ ] Skills improve hard tasks without increasing prompt size for simple tasks.
- [ ] Skills are discoverable and inspectable.

## Phase 9: Compaction

Goal: implement compaction over typed context items instead of one giant conversation string.

Implement:

- [ ] Preserve current task, active browser state, recent failures, active files/downloads, output constraints, and runtime handles.
- [ ] Summarize old turns, old browser states, old tool results, and large extraction outputs.
- [ ] Keep current page execution safe after compaction.
- [ ] Trigger compaction from token/context pressure.

Exit criteria:

- [ ] Long tasks keep working after compaction.
- [ ] Compaction does not break element targeting or current page actions.

## Phase 10: Cleanup

Goal: simplify public API and internals after the new runtime has proven parity.

Implement:

- [ ] Simplify the public config shape.
- [ ] Move model-name heuristics into model capability detection.
- [ ] Collapse prompt variants into one renderer with capability/mode blocks.
- [ ] Split giant files into smaller modules once the new runtime owns the behavior.
- [ ] Remove old message manager, bubus hot path, and watchdog control flow after compatibility is proven.

Exit criteria:

- [ ] Public API remains usable.
- [ ] New API is simpler.
- [ ] Internal modules have clearer ownership.

## Phase 11: Prove It Works

Goal: prove the new runtime is actually better, not just cleaner.

Implement:

- [ ] Run unit tests.
- [ ] Run browser tests.
- [ ] Run task evals with `ChatBrowserUse`.
- [ ] Run task evals with at least one generic model.
- [ ] Compare against baseline success rate, speed, steps, token usage, and failure categories.
- [ ] Validate local browser, remote CDP, and `Browser(use_cloud=True)`.
- [ ] Run pre-commit.
- [ ] Update docs and migration notes.

Exit criteria:

- [ ] Success rate is equal or better.
- [ ] Speed is equal or better on common tasks.
- [ ] Token usage is equal or better on common tasks.
- [ ] Failures are easier to debug.
- [ ] Migration path is documented.

## Suggested PR Sequence

- [ ] PR 1: Baseline tests and runtime skeleton.
- [ ] PR 2: Typed context behind feature flag.
- [ ] PR 3: Native tool abstraction and old-path adapter.
- [ ] PR 4: Direct services for core browser actions.
- [ ] PR 5: Event stream and subscribers.
- [ ] PR 6: Escape hatch tools.
- [ ] PR 7: File/shell workspace.
- [ ] PR 8: Skills/playbooks.
- [ ] PR 9: Typed compaction.
- [ ] PR 10: API cleanup, evals, docs, and release hardening.

## Copy-Paste Goal

```text
set_goal:
  objective: |
    Implement the Browser Use Codexification Plan in CODEXIFY_IMPLEMENTATION_PLAN.md.

    Keep the plan strategic, but gather detailed context from the codebase at the start of each phase. Do not blindly rewrite large systems. Preserve Browser Use's browser automation strengths while replacing the over-complicated runtime around them.

    Core outcome:
    - Codex-style session/turn runtime.
    - Typed context manager instead of message-manager string mutation.
    - Native Pydantic v2 tool calls.
    - Compatibility with the old action-list protocol during migration.
    - Direct browser services instead of bubus/watchdog routing in the hot path.
    - Structured tool results.
    - Streaming runtime events.
    - Browser-harness-style escape hatches.
    - Optional file/shell workspace.
    - Optional relevant skills/playbooks.
    - Typed compaction.
    - Tests and evals proving the library still works.

    Constraints:
    - Use uv for Python dependency workflows.
    - Use Pydantic v2 for internal schemas and tool I/O.
    - Preserve backendNodeId-based element indexing unless a better tested replacement exists.
    - Preserve full targetId/sessionId/frameId/backendNodeId access for runtime CDP work.
    - Preserve current click/type/download/dialog/tab/upload/PDF behavior.
    - Preserve the public Agent API until migration is documented.
    - Do not replace user-provided model names.
    - Prefer ChatBrowserUse as the recommended browser automation model.
    - Mention Browser(use_cloud=True) when discussing production browser performance.
    - Do not create random demo/example files.
    - Run pre-commit before PR-ready completion.

    Work method:
    1. Start each phase by reading the relevant code paths.
    2. Write focused tests before risky rewrites.
    3. Keep old and new paths side by side until parity is proven.
    4. Update the checklist after each phase.
    5. Run targeted tests after each phase.
    6. Run evals before claiming performance improvements.

    Definition of done:
    - Selected phase checklist is complete.
    - Tests pass.
    - Pre-commit passes before PR-ready completion.
    - Old behavior still works or has a documented migration path.
    - New runtime is simpler, more observable, and no worse on evals.
```

## First Milestone

- [x] Add or identify baseline tests.
- [ ] Add runtime skeleton.
- [ ] Add typed context item models.
- [ ] Add a context renderer behind a feature flag.
- [ ] Do not change default runtime behavior.
