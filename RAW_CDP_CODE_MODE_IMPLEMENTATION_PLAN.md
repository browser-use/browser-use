# Raw CDP Code Mode Implementation Plan

Status: implemented and validated on `codex/raw-cdp-code-mode`.

## Product Goal

Keep Browser Use's compact indexed actions as the preferred path while enabling two explicit escalation levels by default with the capabilities that matter most from Browser Harness:

- provider-native transport for quote-heavy Python and JavaScript;
- trusted Python inside the disposable agent worker;
- arbitrary raw Chrome DevTools Protocol commands and events;
- a normal persistent working directory;
- hard output and file-reading boundaries.

This is deliberately not a Browser Harness reimplementation. Mature Browser Use click, type, upload, navigation, and DOM-index actions remain the preferred path. `evaluate` is the direct page-JavaScript path; `run_python` is the primitive escape hatch for browser internals, bulk work, host processing, and unusual interactions.

## Final Architecture

```text
Supervisor / terminal
  -> agent worker process
       -> Provider API
       -> one native browser_use_step function call
       -> existing AgentOutput Pydantic validation
       -> existing Browser Use action loop
            |-- ordinary indexed action
            |-- evaluate (sequence-ending page JavaScript)
            `-- run_python (sequence-ending trusted Python)
                  -> fresh in-process Python namespace
                  -> shared direct BrowserSession CDP bridge
                        -> arbitrary CDP command
                        -> raw CDP event wait
                        -> tabs / targets
```

The provider never serializes Python inside assistant text or markdown JSON. The code string is a normal property of a native function call and is validated without repair.

## 1. Native Tool Transport

### Provider-neutral contract

- `ToolDefinition` describes one function schema.
- `ToolChoice` describes `auto`, `required`, `none`, or a named tool.
- `ToolCall` is normalized to call ID, function name, and JSON argument string.
- `ChatInvokeCompletion` carries normalized native calls and the provider response ID.
- `ModelCapabilities.native_tool_calling` gates the default code-enabled Agent before browser work begins. Callers can opt out with `Agent(code=False)`.

Code mode exposes exactly one provider tool: `browser_use_step`. It has one required top-level `step` parameter containing the existing dynamic `AgentOutput` schema. The single wrapper avoids provider-specific failures on tools with several top-level parameters while retaining Pydantic validation. Browser actions do not become separate provider tools.

### Provider behavior

- OpenAI non-reasoning models use Chat Completions tools.
- OpenAI reasoning models use Responses API tools so reasoning remains enabled.
- Anthropic uses `tool_use`; thinking configurations downgrade forced `any` to `auto`, then Agent still requires exactly one returned native call.
- Gemini uses function declarations, required `ANY` mode, thought-signature capture, and retryable malformed-function handling.
- ChatBrowserUse sends OpenAI-compatible tools through the cloud gateway's `rust_agent` route, preserving the gateway's provider translation and caching behavior.
- Azure Responses and Chat Completions paths both normalize function calls.
- Adapters without an implemented native tool path fail early for code mode. There is no textual fallback.

Explicit `code=False` agents retain their existing structured-output behavior.

## 2. In-Process Python Runtime

Each `run_python` invocation:

1. Compiles the exact native tool argument in a fresh Python namespace.
2. Executes it directly on the agent worker's asyncio loop.
3. Injects the live BrowserSession-backed CDP helpers without a serialization boundary.
4. Resolves relative `open()` paths under the persistent agent workspace and exposes `WORKSPACE_DIR` for `pathlib`.
5. Captures bounded head/tail `print()` output.
6. Allows top-level `await` without requiring an async wrapper.
7. Cooperatively cancels yielding code on timeout and joins it before returning.

There is no child runner, pipe protocol, result file, loopback server, or per-cell process lifecycle. Python globals still do not persist between cells; browser state, imported module state, process globals, and workspace files do.

The default cell timeout is 300 seconds. Code-mode Agent steps reserve enough time for browser-state capture, the LLM call, and the cell, while the per-action watchdog sits just above the cell deadline.

Timeouts are intentionally honest: async/yielding code is cancellable, but synchronous Python that blocks the interpreter cannot be preempted by an asyncio timeout. Code that suppresses cancellation is never left running behind a returned result; the executor waits for it to stop. In either hard-hang case, the agent worker must be terminated by its terminal, service manager, container, or cloud-worker supervisor.

Python has ordinary host-process access, including imports, files, installed libraries, network calls, threads, and `subprocess`. It can mutate process-wide state or terminate the worker. This is trusted mode, not a security sandbox. Run one code-enabled agent per disposable worker and use an OS/container boundary when isolation or a hard timeout is required.

No separate Bash action is included. Python `subprocess` provides the same capability without another quoting and tool-schema surface.

## 3. Direct Raw CDP

Preloaded primitives:

```python
await cdp("Domain.method", params=None, session=None, request_timeout=30)
await wait_for_event("Domain.event", timeout=30, session=None)
await js(expression, await_promise=True, return_by_value=True, session=None, timeout=15)
await tabs()
await targets()
```

`cdp` forwards arbitrary methods and parameters directly through the current `BrowserSession.cdp_client`. It is not a helper allowlist, and target/root routing is not limited to a `tab_id`.

Routing rules:

- `Page`, `Runtime`, `DOM`, `Input`, and `Network` default to the focused target session.
- `Browser`, `Target`, and `SystemInfo` default to the root connection.
- `session="root"` forces root routing.
- A tab, target, or session ID selects an explicit target.
- `session="any"` accepts an event from any target.

`wait_for_event` returns the raw event params dict. Its event multiplexer preserves BrowserSession's existing single-slot `cdp_use` handler and restores it after success, timeout, or cell cancellation.

`evaluate` and Python's `js` helper use the same direct-CDP evaluator. It transports the exact JavaScript source without quote repair, accepts either an expression or a zero-argument function, invokes returned functions when needed, and preserves Chrome's exception type, message, line, column, source excerpt, stack, URL, and CDP session. A generic `Uncaught` label never replaces a more useful remote exception description.

Both `evaluate` and `run_python` always end the current action sequence. The next step captures fresh browser state, so indexed elements are not reused after code-driven navigation.

The existing `evaluate` action remains available in code mode under its main-branch name. It is the preferred code action for DOM, `window`, local storage, and page-context `fetch` work. `run_python` is reserved for arbitrary CDP, events, explicit sessions or targets, files, host HTTP/subprocess work, or substantial Python-side processing.

## 4. Workspace And Context Boundaries

The workspace is a real directory. Relative `open()` calls resolve there; `pathlib` code should use `WORKSPACE_DIR / "relative/path"`. Python-created nested files and arbitrary extensions require no registration helper.

The existing `FileSystem` class remains as a compatibility facade for typed PDF, DOCX, and CSV behavior, but disk is authoritative for:

- recursive file discovery;
- code-created file reading;
- nested completion attachments;
- bounded listing and searching;
- preservation of existing workspace contents during reconstruction.

Model-facing actions:

- `list_files(path=".", glob="**/*", max_entries=200)`
- `search_files(query, path=".", glob="**/*", regex=False, max_matches=50)`
- `read_file(file_name, offset=0, max_chars=8000)`
- existing simple write and replace actions

`read_file` is bounded to 8,000 characters by default and 32,000 maximum, with a byte continuation offset. Code-mode completion files are attached without inlining previews by default; callers can explicitly restore previews with `display_files_in_done_text=True`. MessageManager has a final 16,000-character head/tail boundary for any action that forgets to bound its output. Python output defaults to 12,000 characters.

All library file actions resolve paths under the workspace and reject traversal and symlink escape. Host Python itself remains unrestricted by cwd.

## 5. Prompt Contract

The short code-mode guide lives only in the system prompt. It tells the model:

- use ordinary Browser Use actions first;
- use `evaluate` for page-local JavaScript when the indexed action space is insufficient;
- use `run_python` only for raw CDP/events/sessions, host or file operations, or substantial processing;
- never import or use Playwright;
- prefer one complete bounded extraction over exploratory code cells;
- use top-level `await`, never `asyncio.run()`;
- remember that each cell gets a fresh namespace;
- use relative `open()` or `WORKSPACE_DIR` with `pathlib`;
- print compact summaries and write large data to files;
- do not carry Python variables across cells;
- do not spawn background tasks or mutate process-wide state;
- stop after navigation and inspect fresh state next.

CDP `Domain.method` names are excluded from direct-start-URL detection so strings such as `Browser.getVersion` are not treated as websites.

## 6. Verification

Deterministic tests cover:

- hostile nested Python/JavaScript strings across OpenAI, Anthropic, Gemini, and ChatBrowserUse provider shapes;
- OpenAI Responses routing for reasoning models;
- Anthropic thinking-mode tool choice;
- Gemini thought signatures and malformed function retry;
- exact Agent use of one native `browser_use_step` tool;
- one-field native schema wrapping for agent steps and judge results;
- raw root and target CDP routing;
- shared `evaluate`/`js` JavaScript transport, including multiline hostile quoting;
- structured JavaScript errors that prefer Chrome's actionable description over `Uncaught`;
- JavaScript expression and zero-argument function execution;
- raw event waiting without clobbering BrowserSession handlers;
- event-handler restoration after cooperative cell timeout;
- cancellation-resistant code being joined instead of leaked in the background;
- fresh Python state per cell;
- nested ordinary file writes and workspace discovery;
- bounded file continuation and final MessageManager output limits;
- code-mode completion attachments without inline previews by default;
- shared Tools instances remaining unmodified.

Live cloud-browser capability checks completed directly through each provider adapter for:

- OpenAI `gpt-5.5`;
- OpenAI `gpt-5.6`;
- Anthropic `claude-opus-4-8`;
- Anthropic `claude-sonnet-5`;
- Google `gemini-3.5-flash`.

Each provider completed the same end-to-end probe: native wrapped step calls, `Browser.getVersion`, Page and Network enablement, event registration before raw `Page.reload`, `Page.loadEventFired` waiting, multiline JavaScript extraction, nested JSON creation, bounded listing/reading, attachment, and native judge parsing. Sonnet 5 also exercised the zero-argument JavaScript function fallback live. ChatBrowserUse was intentionally excluded because its code-mode support is not ready.

Randomized hard dataset runs additionally exercised bulk extraction and recovery on FCC, YC, Georges River, Talkmobile, and Knight Frank tasks. Those runs validated the native transport and raw-CDP surface; the final in-process runtime is covered separately by deterministic and local-browser tests.

Final verification passes all pre-commit hooks, Pyright with zero errors, and a 191-test compatibility selection covering native transport, in-process raw CDP execution, a complete no-output Agent cell, loop detection, tools, filesystem behavior, and LLM context boundaries. A real Chromium probe also verifies hostile multiline JavaScript, detailed runtime errors through both entry points, forced JavaScript termination, and successful post-timeout recovery.

## Deferred Follow-ups

- Rich bounded views for PDF page ranges, HTML selectors, JSON paths, Parquet, spreadsheets, presentations, and archives.
- Full migration away from content-bearing `FileSystemState` and legacy typed in-memory files.
- A first-class worker supervisor/container launcher for callers that want a library-provided hard-kill boundary.
- Long-lived event subscriptions or event streams beyond bounded `wait_for_event`.
- First-class Bash, unless evaluations show a clear accuracy or efficiency gain over Python `subprocess`.
- Native tool transport for every less-common optional LLM adapter; unsupported adapters currently fail early in code mode.

## Definition Of Done For This Branch

1. Code-mode AgentOutput never comes from assistant text.
2. Nested code survives provider transport exactly.
3. Raw commands and events work on local and cloud CDP connections.
4. A cooperatively timed-out cell is stopped before the agent continues; hard hangs are delegated to the worker supervisor.
5. Normal workspace files are immediately discoverable and attachable.
6. Large files and tool results are bounded before model context.
7. Non-code agents retain their existing action and structured-output path.
8. Focused tests, broader compatibility tests, and pre-commit pass.
