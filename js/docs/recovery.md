# Limits & recovery

Reliability means distinguishing “the request failed” from “the action did not happen.” A timed-out click may already have submitted a form.

## Separate deadlines

```js
const agent = await BrowserUse.create({
  model: 'openai/gpt-5.5',
  operationTimeoutMs: 15_000,
  cellTimeoutMs: 30_000,
  modelTimeoutMs: 300_000,
  compactionTimeoutMs: 120_000,
  maxOutputChars: 12_000,
});

const result = await agent.run('Find the requested information.', {
  maxSteps: 40,
  timeoutMs: 300_000,
  maxCostUsd: 2,
  maxContextChars: 240_000,
});
```

- **Operation:** CDP command and element lookup deadline.
- **Cell:** execution deadline. A stuck cell causes worker termination.
- **Model:** connection setup plus the entire streamed response. A timeout gets at most one extra inference attempt per run, sharing the existing transient-stream retry budget. Partial tool calls never execute.
- **Compaction:** summary response deadline. Failure keeps the original context, disables further compaction for that run and emits a warning. The context guard still applies.
- **Run:** aborts the model loop and active browser cell.

`maxSteps` counts model turns, not browser actions. A single code cell may contain multiple actions. Cost is estimated from Pi's catalog and checked between turns; it can overshoot by one response. It is not a hard billing cap. `maxContextChars` is a text-character guard. Automatic upstream Pi compaction also uses token estimates and provider usage before the context becomes full; set `compaction: false` to opt out. Summary inference counts toward usage and cost.

## Temporary provider failures

The one-retry policy also recognizes `Unable to verify model access right now. Please retry.` It preserves the transcript, JavaScript state, and original run limits. Failed-response tools never execute. Invalid API keys and permanent model-access denials fail immediately.

## Missing final delivery

A normal provider stop without a validated result triggers at most one additional model turn. Only `finish` and `finish_from_js` are exposed in that turn. It shares the original deadline, step ceiling, cost estimate, and context guard. `finishRepairs` records 0 or 1; the turn and its usage are included in totals. Provider errors, cancellation, and exhausted budgets do not trigger this repair.

The SDK does not replay browser actions. A JavaScript delivery expression remains executable code, so this is not a read-only sandbox. If the repair fails, useful earlier assistant text is retained and the run stays incomplete (or reports its budget/error status).

## What survives a failure?

| Event                       | JavaScript bindings                  | Browser/tab                                  | Result                     |
| --------------------------- | ------------------------------------ | -------------------------------------------- | -------------------------- |
| Normal cell                 | Preserved                            | Preserved                                    | Value/images               |
| Caught syntax/runtime error | Preserved, including partial changes | Preserved                                    | Error returned to model    |
| Cell timeout / cancellation | Reset                                | Reattached when target exists                | Explicit reset error       |
| Worker crash                | Reset                                | Reattached when target exists                | Explicit worker-exit error |
| Chrome exits                | Preserved while worker remains alive | Lost                                         | Reconnect fails explicitly |
| `close()`                   | Discarded                            | Owned browser closes; external browser stays | Artifacts retained         |

If page attachment fails after Chrome creates a protocol session, the SDK attempts to detach that session before returning the original error. It does not close the tab or caller-owned connection.

A new worker reconnects to the primary tab by Chrome target ID. It never automatically replays the failed cell. The agent is instructed to inspect the current page before retrying a mutation. If the tab no longer exists, a fresh tab is created; do not assume the previous page survived.

## Keep progress through a reset

```js
await checkpoint('records.json', records);
// After a worker reset:
const recovered = JSON.parse(require('node:fs').readFileSync('records.json', 'utf8'));
```

`checkpoint` atomically replaces JSON in the workspace. Save after each successful item or small batch. Work held only in memory is lost when the worker is terminated. Failed cells retain bounded captured output and report whether their JavaScript state was reset.

Pure JavaScript and file work remain available when Chrome is unhealthy. Use `await reconnect()` for an explicit CDP reconnect, then reacquire cached page/frame handles and inspect state. Reconnect preserves Node bindings and files; it does not revive a dead remote Chrome or establish whether a timed-out action happened.

Compaction preserves recent complete tool groups and exact original user messages. The run journal retains the original trajectory; context checkpoints are saved under `.browser-use/context`. Summary omissions remain possible, so canonical datasets should live in ordinary files. See [reliability](./reliability) for the full contract.

## Cancel a task

```js
const controller = new AbortController();
const running = agent.run('Research this topic.', {
  signal: controller.signal,
});
controller.abort();
const result = await running; // status: 'cancelled'
```

The browser worker is terminable even during an infinite JavaScript loop. The SDK stops waiting on provider responses even when a transport ignores abort; late output cannot change the result or execute tools. The transport must still honor abort to release its own network resources and stop billable work. Usage includes reported partial tokens, not an estimate of unreported provider work. Custom tools and application callbacks must cooperate with abort. This is not a universal deadline guarantee over arbitrary third-party code.

## Execution boundaries

The model executes general-purpose Node.js code. The worker receives an empty environment and does not inherit provider API keys, inspector flags, or preload hooks. Nevertheless, Node code can access the host filesystem, spawn processes, and reach the network. **A worker or V8 context is not a security sandbox.**

Run untrusted users' tasks in separate containers or VMs with restricted mounts, network controls, and narrowly scoped browser accounts. Keep provider credentials outside any filesystem mounted into that environment. Do not use a shared personal browser for mutually untrusted tasks.

The model necessarily sees the browser content it inspects. Saved datasets, downloads, screenshots, and event consumers can contain sensitive data. The SDK retains artifacts after closing; your application owns retention. It creates no hosted telemetry account and uploads no SDK trace by default. The configured model provider still receives prompts and tool results.
