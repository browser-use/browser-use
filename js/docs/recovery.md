# Limits & recovery

Reliability means distinguishing “the request failed” from “the action did not happen.” A timed-out click may already have submitted a form.

## Three separate budgets

```js
const agent = await BrowserUse.create({
  model: 'openai/gpt-5.5',
  operationTimeoutMs: 15_000,
  cellTimeoutMs: 30_000,
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
- **Run:** aborts the model loop and active browser cell.

`maxSteps` counts model turns, not browser actions. A single code cell may contain multiple actions. Cost is estimated from Pi's catalog and checked between turns; it can overshoot by one response. It is not a hard billing cap. Context size is a character guard, not a tokenizer or automatic compactor.

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
| Chrome exits                | Cannot preserve browser state        | Lost                                         | Reconnect fails explicitly |
| `close()`                   | Discarded                            | Owned browser closes; external browser stays | Artifacts retained         |

A new worker reconnects to the primary tab by Chrome target ID. It never automatically replays the failed cell. The agent is instructed to inspect the current page before retrying a mutation. If the tab no longer exists, a fresh tab is created; do not assume the previous page survived.

## Cancel a task

```js
const controller = new AbortController();
const running = agent.run('Research this topic.', {
  signal: controller.signal,
});
controller.abort();
const result = await running; // status: 'cancelled'
```

The browser worker is terminable even during an infinite JavaScript loop. Provider transports, custom tools, and application callbacks must cooperate with abort. This is not a universal deadline guarantee over arbitrary third-party code.

## Execution boundaries

The model executes general-purpose Node.js code. The worker receives an empty environment and does not inherit provider API keys, inspector flags, or preload hooks. Nevertheless, Node code can access the host filesystem, spawn processes, and reach the network. **A worker or V8 context is not a security sandbox.**

Run untrusted users' tasks in separate containers or VMs with restricted mounts, network controls, and narrowly scoped browser accounts. Keep provider credentials outside any filesystem mounted into that environment. Do not use a shared personal browser for mutually untrusted tasks.

The model necessarily sees the browser content it inspects. Saved datasets, downloads, screenshots, and event consumers can contain sensitive data. The SDK retains artifacts after closing; your application owns retention. It creates no hosted telemetry account and uploads no SDK trace by default. The configured model provider still receives prompts and tool results.
