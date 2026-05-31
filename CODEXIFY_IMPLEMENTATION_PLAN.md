# Browser Use Codexification Plan

Plan for making Browser Use simpler, more capable, and more Codex-like without throwing away the browser automation heuristics that already work.

The important idea: **Browser Use should keep its excellent browser state/action layer, but the agent runtime around it should become more like Codex: typed context, native tools, streaming events, explicit services, compaction, and escape hatches.**

This document is intentionally not a full implementation spec. Each implementation agent should inspect the relevant code paths before editing. The plan gives the direction, phase boundaries, constraints, and acceptance criteria.

## Principles

- [x] Preserve Browser Use's current browser automation strengths.
- [x] Keep `backendNodeId` as the model-visible element index unless a better replacement is proven.
- [x] Keep runtime access to full `targetId`, `sessionId`, `frameId`, and `backendNodeId`.
- [x] Give the model more freedom through screenshot, coordinate click, JS eval, raw CDP, HTML/markdown reads, accessibility tree, network inspection, and HTTP fetch.
- [x] Replace heavy indirection with explicit runtime pieces.
- [x] Keep old behavior working while the new runtime is introduced.
- [ ] Use focused tests and evals to prove each simplification works.
- [x] Avoid huge rewrites that remove hard-won browser heuristics.

## What To Keep

- [x] State -> action browser automation loop.
- [x] DOM processing and cleaned interactive representation.
- [x] Selector map keyed by `backendNodeId`.
- [x] Robust click, type, scroll, tabs, downloads, dialogs, upload, and PDF behavior.
- [x] `ActionResult` style structured feedback.
- [x] `ChatBrowserUse` as the recommended default model for browser automation.
- [x] `Browser(use_cloud=True)` as the production performance path for hosted browser execution.

## What To Simplify

- [ ] Message manager.
- [ ] Fake structured-output action protocol.
- [x] Bubus/event bus in the hot action path.
- [ ] Watchdog architecture.
- [ ] Giant agent/browser/tool files.
- [ ] Dynamic tool/action model generation.
- [x] Prompt variant sprawl.
- [x] Cloud, telemetry, GIF, and callback logic inside the core agent loop.

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
- [x] Build and store the typed context snapshot inside the message manager each step.
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
- [x] `AgentStateItem`
- [x] `PageActionsItem`
- [x] `StepInfoItem`
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

- [x] Define browser tools with explicit Pydantic v2 input/output models.
- [x] Ensure default built-in tools use explicit Pydantic models instead of signature-generated models.
- [x] Route tools through one `ToolContext`, not magic function parameter injection.
- [x] Keep compatibility with the old `AgentOutput(action=[...])` path during migration.
- [x] Treat `done` and structured final output as proper native outputs, not fake actions.
- [x] Execute native `browser.done` directly instead of routing completion through the registered action adapter.
- [x] Keep `ActionResult`/tool result content structured and model-readable.
- [x] Add provider-facing tool result messages and OpenAI native tool-call response parsing.
- [x] Add an opt-in agent path that adapts provider-native tool calls to existing registered actions.
- [x] Add native-tool-call prompt guidance when the opt-in path is enabled.

Core tools:

- [x] `browser.navigate`
- [x] `browser.click`
- [x] `browser.click_coordinates`
- [x] `browser.type`
- [x] `browser.scroll`
- [x] `browser.send_keys`
- [x] `browser.extract`
- [x] `browser.screenshot`
- [x] `browser.evaluate`
- [x] `browser.cdp`
- [x] `browser.get_state`
- [x] `browser.find_elements`
- [x] `browser.search_page`
- [x] `browser.switch_tab`
- [x] `browser.close_tab`
- [x] `browser.upload_file`
- [x] `browser.wait`
- [x] `browser.done`

Exit criteria:

- [x] Native tool-call mode can complete simple browser tasks.
- [x] Old action-list mode still works.
- [x] Tool results are added back into typed context.

## Phase 4: Direct Browser Services

Goal: move browser action execution out of bubus/watchdog routing.

Implement:

- [x] Create explicit services for state capture, actions, downloads, dialogs, tabs, network, lifecycle, and storage.
- [x] Route public click/type tools through direct services instead of event dispatch.
- [x] Route public navigation, back, tab, and keyboard tools through direct services where parity is clear.
- [x] Route public page and element scroll through direct services, including scroll-container heuristics.
- [x] Route public upload through direct services while preserving file safety checks.
- [x] Route public scroll-to-text through direct services.
- [x] Route public dropdown tools through a direct service wrapper.
- [x] Remove event-bus fallbacks from direct click/type/dropdown service wrappers.
- [x] Route print-button PDF tracking through the direct download handler.
- [x] Route coordinate clicks through the direct click handler so they share click/download heuristics.
- [x] Expose explicit click handler methods and keep event handlers as compatibility adapters.
- [x] Expose explicit text-entry handler methods and keep event handlers as compatibility adapters.
- [x] Expose explicit dropdown handler methods and keep event handlers as compatibility adapters.
- [x] Move click safety, print, and download heuristics into `ClickService`.
- [x] Move low-level click helpers into `ClickService` so direct clicks no longer call watchdog internals.
- [x] Move text-entry fallback and sensitive logging policy into `TypeService`.
- [x] Move low-level text-entry helpers into `TypeService` so direct typing no longer calls watchdog internals.
- [x] Make legacy scroll and scroll-to-text handlers delegate to `ScrollService`.
- [x] Make legacy upload handler delegate to `UploadService`.
- [x] Make legacy navigation and keyboard handlers delegate to direct services.
- [x] Move dropdown option and selection policy into `DropdownService`.
- [x] Move remaining scroll/session helper implementations into direct services.
- [x] Preserve useful watchdog heuristics by moving them into direct service methods.
- [x] Keep event streaming for observability, not internal control flow.
- [x] Keep compatibility path until direct services have parity.

Suggested services:

- [x] `BrowserStateService`
- [x] `ActionService`
- [x] `ClickService`
- [x] `TypeService`
- [x] `NavigationService`
- [x] `TabService`
- [x] `DownloadService`
- [x] `DialogService`
- [x] `NetworkService`
- [x] `StorageStateService`
- [x] `LifecycleService`

Target shape:

```text
tool -> service method -> CDP
```

Not:

```text
tool -> event -> bubus -> watchdog -> CDP
```

Exit criteria:

- [x] Core actions can execute without bubus in the hot path.
- [x] Downloads and dialogs still work.
- [x] Click/type behavior remains at least as robust as before.

## Phase 5: Streaming Events

Goal: make runs observable without coupling internal control flow to an event bus.

Implement:

- [x] Add a clean runtime event stream.
- [x] Emit events for turns, context, model output, tool calls, browser state, downloads, artifacts, compaction, completion, and failures.
- [x] Move cloud sync, telemetry, GIF generation, and user callbacks to subscribers.
- [x] Make runs understandable without reading internal debug logs.

Example events:

- [x] `turn.started`
- [x] `context.built`
- [x] `model.delta`
- [x] `tool.started`
- [x] `tool.completed`
- [x] `browser.state_refreshed`
- [x] `download.started`
- [x] `download.completed`
- [x] `artifact.created`
- [x] `context.compacted`
- [x] `turn.completed`
- [x] `run.completed`

Exit criteria:

- [x] Cloud/telemetry/GIF/callback behavior can be implemented as subscribers.
- [x] A failed run can be debugged from events and typed history.

## Phase 6: Browser-Harness Escape Hatches

Goal: give the model more freedom while keeping Browser Use's cleaned DOM state as the default.

Implement:

- [x] Add first-class tools for screenshot, coordinate click, JS eval, raw CDP, HTML, markdown, accessibility tree, element inspection, network requests, and HTTP fetch.
- [x] Let the model choose between DOM index actions, coordinate actions, JS/CDP, extraction, or HTTP depending on the situation.
- [x] Add guidance for when each tool style is appropriate.

Important:

- [x] Do not remove the current DOM pipeline.
- [x] Do not hide runtime handles needed for CDP.
- [x] Do not force the model to use a single representation of the page.

Exit criteria:

- [x] The model can solve tasks using DOM, screenshot, coordinates, JS, CDP, and HTTP as appropriate.
- [x] Simple tasks do not get slower or noisier.

## Phase 7: File And Shell Workspace

Goal: bring in the useful Codex-style file/shell interaction for browser tasks that produce artifacts or need data processing.

Implement:

- [x] Add optional permission-gated file tools.
- [x] Add optional permission-gated shell tools.
- [x] Connect downloads and generated artifacts to the workspace.
- [x] Keep outputs truncated and artifact-backed when large.

Use cases:

- [x] Inspect downloaded files.
- [x] Transform CSV/JSON/HTML/PDF data.
- [x] Run small helper scripts.
- [x] Validate extracted results.
- [x] Persist artifacts across turns.

Exit criteria:

- [x] Browser tasks can work with downloaded/generated files.
- [x] Shell/file tools are disabled or permission-gated where unsafe.

## Phase 8: Skills And Playbooks

Goal: borrow the browser-harness idea of relevant domain/interaction skills without bloating every prompt.

Implement:

- [x] Add optional domain and interaction skills.
- [x] Load skills only when relevant by URL, task, explicit mention, or repeated failure.
- [x] Keep skills out of the base prompt unless needed.
- [x] Start with interaction skills for downloads, dialogs, iframes, shadow DOM, dropdowns, and uploads.

Exit criteria:

- [x] Skills improve hard tasks without increasing prompt size for simple tasks.
- [x] Skills are discoverable and inspectable.

## Phase 9: Compaction

Goal: implement compaction over typed context items instead of one giant conversation string.

Implement:

- [x] Preserve current task, active browser state, recent failures, active files/downloads, output constraints, and runtime handles.
- [x] Summarize old turns, old browser states, old tool results, and large extraction outputs.
- [x] Keep current page execution safe after compaction.
- [x] Trigger compaction from token/context pressure.

Exit criteria:

- [x] Long tasks keep working after compaction.
- [x] Compaction does not break element targeting or current page actions.

## Phase 10: Cleanup

Goal: simplify public API and internals after the new runtime has proven parity.

Implement:

- [ ] Simplify the public config shape.
- [x] Move model-name heuristics into model capability detection.
- [x] Remove per-call dynamic `ActionModel` creation from direct `Tools` action calls.
- [x] Cache legacy action-list model generation for stable available action sets.
- [x] Introduce one system-prompt renderer boundary around profile/template selection.
- [x] Extract the shared browser service base into its own module.
- [x] Extract browser interaction services out of the browser service facade.
- [x] Split browser interaction services into service-specific modules.
- [x] Collapse prompt variants into one renderer with capability/mode blocks.
- [x] Extract typed context construction out of the legacy message manager.
- [x] Extract message compaction out of the legacy message manager.
- [x] Extract message history rendering and mutation out of the legacy message manager.
- [x] Fix shared default `MessageManagerState` construction.
- [ ] Split giant files into smaller modules once the new runtime owns the behavior.
- [ ] Remove old message manager, bubus hot path, and watchdog control flow after compatibility is proven.

Exit criteria:

- [x] Public API remains usable.
- [ ] New API is simpler.
- [ ] Internal modules have clearer ownership.

## Phase 11: Prove It Works

Goal: prove the new runtime is actually better, not just cleaner.

Implement:

- [x] Run unit tests.
- [x] Run browser tests.
- [ ] Run task evals with `ChatBrowserUse`.
- [ ] Run task evals with at least one generic model.
- [ ] Compare against baseline success rate, speed, steps, token usage, and failure categories.
- [ ] Validate local browser, remote CDP, and `Browser(use_cloud=True)`.
- [x] Run pre-commit.
- [ ] Update docs and migration notes.

Exit criteria:

- [ ] Success rate is equal or better.
- [ ] Speed is equal or better on common tasks.
- [ ] Token usage is equal or better on common tasks.
- [x] Failures are easier to debug.
- [ ] Migration path is documented.

## Suggested PR Sequence

- [ ] PR 1: Baseline tests and runtime skeleton.
- [ ] PR 2: Typed context behind feature flag.
- [ ] PR 3: Native tool abstraction and old-path adapter.
- [x] PR 4: Direct services for core browser actions.
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
- [x] Add runtime skeleton.
- [x] Add typed context item models.
- [x] Add a context renderer behind a feature flag.
- [x] Do not change default runtime behavior.
