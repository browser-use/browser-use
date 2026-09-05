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

Local browser options: `headless`, `channel: 'chrome' | 'msedge'`, `executablePath`. They cannot be combined with `cdpUrl` in TypeScript.

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

Every result contains `status`, `text`, `steps`, `durationMs`, `usage`, `workspace`, and `model`. Completed results include `output`. Failed results may include `error`. `usage.cost` is catalog-estimated cost, not billed cost.

## `agent.execute(code, options?)`

Execute browser JavaScript directly. Options: `timeoutMs` and `signal`. Returns `{ text, images, outputFile? }`. Code and browser errors reject the promise.

## `agent.close()`

Idempotent asynchronous cleanup. Cancels active work and closes the owned browser. Attached external browsers stay running. Artifacts are retained. Also available as `Symbol.asyncDispose`.

## Exports

`BrowserUse`, `CDP`, `Page`, `Tabs`, `Type`, `builtinModels`, plus types: `Target`, `AXNode`, `BrowserUseOptions`, `BrowserOptions`, `RunOptions`, `RunResult`, `RunMetrics`, `StopReason`, `CellResult`, `Image`, `AgentTool`, `AgentEvent`, `StreamFn`, `Static`, and `TSchema`.
