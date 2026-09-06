# API reference

## `BrowserUse.create(options)`

Creates an owned local browser or attaches to a caller-owned CDP browser. The JavaScript worker starts on the first cell.

| Option               | Default                 | Purpose                                            |
| -------------------- | ----------------------- | -------------------------------------------------- |
| `model`              | required                | Explicit `provider/model-id`                       |
| `browser`            | `{ headless: true }`    | Local configuration or `{ cdpUrl }`                |
| `workspace`          | new temporary directory | Artifact directory, retained after close           |
| `models`             | Pi built-in collection  | Native Pi provider collection                      |
| `reasoning`          | `medium`                | Pi reasoning level                                 |
| `tools`              | `[]`                    | Additional Pi tools                                |
| `instructions`       | empty                   | Application instructions appended to system prompt |
| `operationTimeoutMs` | `15000`                 | CDP command and element lookup timeout             |
| `cellTimeoutMs`      | `30000`                 | Worker execution timeout                           |
| `maxOutputChars`     | `12000`                 | Model-facing text prefix limit                     |
| `beforeToolCall`     | absent                  | Async application preflight hook                   |
| `streamFn`           | Pi `streamSimple`       | Advanced transport override                        |

Local browser options: `profileDir`, `headless`, `channel: 'chrome' | 'msedge'`, `executablePath`. They cannot be combined with `cdpUrl`. An attached browser may specify `targetId` to select a caller-owned tab.

## `agent.run(task, options?)`

Returns `Promise<RunResult<string>>`, or `Promise<RunResult<Static<S>>>` when passed `schema: S`.

| Option            | Default         | Purpose                       |
| ----------------- | --------------- | ----------------------------- |
| `schema`          | `Type.String()` | Finish-tool result schema     |
| `maxSteps`        | `40`            | Model-turn ceiling            |
| `timeoutMs`       | `300000`        | Abort the run after this time |
| `maxCostUsd`      | unset           | Soft estimated-cost threshold |
| `maxContextChars` | `240000`        | Projected-context guard       |
| `signal`          | absent          | Caller cancellation           |
| `onEvent`         | absent          | Awaited Pi event listener     |

Every result contains `status`, `text`, `steps`, `finishRepairs`, `durationMs`, `usage`, `workspace`, and `model`. Completed results include `output`. Failed results may include `error`. `usage.cost` is catalog-estimated cost, not billed cost.

## `agent.execute(code, options?)`

Execute browser JavaScript directly. Options: `timeoutMs` and `signal`. Returns `{ text, images, outputFile?, targetId? }`. `targetId` identifies the current tab after the cell for observers. Code and browser errors reject the promise.

## `agent.close()`

Idempotent asynchronous cleanup. Cancels active work and closes the owned browser. Attached external browsers stay running. Artifacts are retained. Also available as `Symbol.asyncDispose`.

## Exports

`BrowserUse`, `CDP`, `Page`, `Tabs`, `Type`, `builtinModels`, plus types: `Target`, `AXNode`, `BrowserUseOptions`, `BrowserOptions`, `RunOptions`, `RunResult`, `RunMetrics`, `StopReason`, `CellResult`, `Image`, `AgentTool`, `AgentEvent`, `StreamFn`, `Static`, and `TSchema`.

The tool names `javascript`, `finish`, and `finish_from_js` are reserved. `finish_from_js` evaluates an expression once and validates its JSON value against the run schema. See [typed results](./results).

## Sessions & control

| API / option              | Contract                                                                 |
| ------------------------- | ------------------------------------------------------------------------ |
| `followUp(task, options)` | Same schemas/budgets as run; retains the conversation.                   |
| `events()`                | Bounded async iterator of `SessionEvent`; finishes at close.             |
| `history`, `usage`        | Independent snapshots of conversation/session accounting.                |
| `files()`                 | Bounded inventory of ordinary workspace files.                           |
| `saveHistory(path?)`      | Atomic versioned snapshot; default `.browser-use/session.json`.          |
| `pause()`                 | Await a safe tool boundary or run completion; then check `isPaused`.     |
| `resume()`                | Await manual code completion, then release the pause.                    |
| `steer(text)`             | Queue feedback in the active Pi run.                                     |
| `cancel()`                | Abort the run; await its result before starting more work.               |
| `historyFile`             | Create option restoring same-model version 1 history.                    |
| `log`                     | `false` (default), `pretty`, or `json`; writes stderr.                   |
| `redact`                  | Exact text values removed from saved history/session events; not pixels. |
| `hookTimeoutMs`           | Callback deadline; default 30,000 ms.                                    |
| `afterToolCall`           | Pi result hook for non-finalization tools.                               |
| `validateResult`          | Reject schema-valid final output by returning feedback.                  |
| `recording`               | `false` (default), `true`, or `{ intervalMs, maxFrames }`.               |

Auxiliary persistence failures appear in `warnings` and omit the unavailable path; they do not discard delivered output. Run results additionally carry `runId`, `historyPath`, `eventsPath` and optional `recordingPath`. `exportRecording(path, options)` exports MP4/GIF; see [recording](./recording). `SessionHistory`, `WorkspaceFile`, `SessionEvent`, `RecordingOptions`, `VideoOptions` and `formatEvent` are exported.
