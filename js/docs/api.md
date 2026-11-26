# API

`BrowserUse.create(options)` creates one browser session. `run(task, options)` returns a result; `followUp(task, options)` continues it. Always close the session.

## Typed results

```js
import { BrowserUse, Type } from '@browser_use/core';
const agent = await BrowserUse.create({ model: 'openrouter/openai/gpt-5.6-luna' });
try {
  const result = await agent.run('Read the page title at example.com.', {
    schema: Type.Object({ title: Type.String() }),
    maxSteps: 20,
    timeoutMs: 120_000,
    maxCostUsd: 1,
  });
  if (result.status === 'completed') console.log(result.output.title);
  else console.error(result.status, result.text);
} finally {
  await agent.close();
}
```

## Judge

After each run that took steps, one low-effort request to the run's own model judges it, as Python 1.0.5 `judge.py` does: the task, the trace (images and reasoning left out, 120,000 characters at most), the final result, up to 4 screenshots (the last distinct ones, the final page included) and `judgeContext` first when given. `result.judgement` is `{ success, failureReason, description, promptInjectionDetected, botBlockOrCaptchaDetected, gotchas }` (at most 5 gotchas, secrets redacted). Its tokens and cost are added to `result.usage`. A judge that fails leaves `judgement` unset and adds a warning; it never fails a run. `judge: false` turns it off: set it in matched cost evals, as for Python `judge=False`.

## Default model

Without `model`, the SDK uses `browser-use/bu-4.0` (BU 4.0; also `bu-4.0-mini`, `bu-4.0-pro`) on the Browser Use gateway (`https://api.browser-use.com/api/v4/llm/v1`, OpenAI Responses), as Python 1.0.6 does. The key is `BROWSER_USE_API_KEY`, or the `Browser.cloud({ apiKey })` key: one key runs model and browser. A bare `bu-*` name (`bu-ultrafast`, `bu-smart`) means the gateway too. `create()` first sends a free `GET /models`: a missing gateway, a rejected key (401), no credits (402) or an unlisted model fails there, before a browser starts. On `bu-fast` and `bu-ultrafast`, `mode` defaults to `'ultrafast'`. Without `reasoning`, a `bu-*` model uses its own effort (bu-4.0 high, bu-fast medium, bu-ultrafast low, bu-smart high). `Browser.cloud()` prints its live view link to stderr (`liveView: true` also opens it, `false` hides it), as Python 1.0.6 does. Each gateway response costs what the gateway charged (`browser_use.charge_usd`); a response without a charge counts 0, never a retail estimate.

The default output is a string. Schema validation checks shape; `validateResult(output, signal)` can reject an answer with corrective feedback. It does not make unsupported facts true.

## Options

| Creation                                                 | Purpose                                                        |
| -------------------------------------------------------- | -------------------------------------------------------------- |
| `model`, `reasoning`, `models`, `streamFn`               | Model and provider                                             |
| `browser`, `workspace`, `historyFile`                    | Browser and persistence                                        |
| `instructions`, `tools`, `researchTools`                 | Extra instructions and Pi tools                                |
| `beforeToolCall`, `afterToolCall`, `validateResult`      | Blocking hooks and validation                                  |
| `log`, `redact`, `recording`, `highlightActions`         | Output and recording                                           |
| `mode`, `webSearch`                                      | `'ultrafast'` adds the `bu` helpers; host search               |
| `operationTimeoutMs`, `cellTimeoutMs`                    | CDP / JS deadlines; 20s / 120s                                 |
| `modelTimeoutMs`, `compactionTimeoutMs`, `hookTimeoutMs` | First model event / summary / hook; 300s / 120s / 30s          |
| `modelStreamTimeoutMs`                                   | Whole model stream once events flow; 930s                      |
| `allowedDomains`, `prohibitedDomains`, `sensitiveData`   | Navigation rules and named credentials                         |
| `telemetry`                                              | Anonymous counters; default on                                 |
| `judge`, `judgeContext`                                  | Judge each run that took steps (default on); your own criteria |
| `maxOutputChars`                                         | Printed cell output cap; 12,000                                |

| Per run                                             | Default                             |
| --------------------------------------------------- | ----------------------------------- |
| `schema`                                            | `Type.String()`                     |
| `maxSteps`, `timeoutMs`                             | 100 turns, 1,700,000 ms             |
| `maxCostUsd`                                        | No cost cap; soft boundary when set |
| `compaction`, `maxContextChars`                     | Enabled, 240,000 characters         |
| `signal`, `onEvent`, `observe`, `observerTimeoutMs` | Cancellation and observations       |

[Type definitions](https://github.com/browser-use/browser-use-pi/blob/main/src/types.ts) are the complete contract. Browser launch options live in [browser.ts](https://github.com/browser-use/browser-use-pi/blob/main/src/browser.ts).

## Events and hooks

`log: 'pretty'` prints readable progress; `'json'` prints JSON. `agent.events()` is an async iterator; subscribe before running. It ends when the session closes. Slow consumers can overflow its bounded queue. `onEvent` is awaited and applies backpressure; `observe` is best-effort and may coalesce under load.

```js
const agent = await BrowserUse.create({
  model: 'openrouter/openai/gpt-5.6-luna',
  beforeToolCall: async ({ toolCall }) => {
    if (toolCall.name === 'purchase') return { block: true, reason: 'Needs review' };
  },
});
```

Custom `tools` use upstream Pi’s `AgentTool` interface. Hooks are application controls, not a sandbox: arbitrary JS can call CDP directly. Set `researchTools: true` for Pi’s read/write/edit/bash tools.

## Results and recovery

Every result includes status, text, steps, duration, usage, model and workspace. Successful results additionally contain `output`. Saved history, event and recording paths are returned when available. Inspect `warnings` for auxiliary failures.

### Mapping to Python `AgentHistoryList` (1.0.5)

| Python          | Pi                             | Note                                                                                     |
| --------------- | ------------------------------ | ---------------------------------------------------------------------------------------- |
| `status`        | `status`                       | Pi adds `cancelled`, `cost_limit`, `context_limit`, `incomplete`                         |
| `text`          | `text`                         |                                                                                          |
| `output`        | `output`                       | on `completed` only                                                                      |
| `steps`         | `steps`                        | model requests of the run                                                                |
| `duration_s`    | `durationMs`                   | milliseconds                                                                             |
| `usage`         | `usage`                        | `cacheRead`/`cacheWrite` for `cache_read`/`cache_write`; no `requests` count             |
| `cost_usd`      | `costUsd`                      | `usage.cost.total`, judge and compaction included; a number, never `None`                |
| `partial`       | `partial`                      | `{ path?, value }`                                                                       |
| `error`         | `error`                        |                                                                                          |
| `success`       | `success`                      | the agent's own verdict from `finish({ success })`, when it gave one                     |
| `judgement`     | `judgement`                    | `failureReason`, `promptInjectionDetected`, `botBlockOrCaptchaDetected` in camelCase     |
| `downloads`     | `downloads`                    | absolute paths saved in `workspace/downloads` this run; remote browser files stay remote |
| `messages`      | `agent.history`, `historyPath` | the saved conversation                                                                   |
| `output_schema` | the `schema` passed to `run()` |                                                                                          |

Stop statuses: `max_steps`, `timeout`, `cancelled`, `cost_limit`, `context_limit`, `incomplete`, `error`. Automatic compaction summarizes older context; saved observations remain in the workspace. A failed summary preserves the original context and can stop at the limit. Recovery never replays browser actions. See [browser primitives](./browser.md) for worker reset behavior.

## Keep results when a limit is reached

```js
const result = await agent.run('QA the checkout and report bugs.', {
  maxSteps: 20,
  timeoutMs: 120_000,
  maxCostUsd: 1,
});
console.log(result.status);
console.log(result.status === 'completed' ? result.output : (result.partial?.value ?? result.text));
```

The last allowed turn is reserved for delivery when `maxSteps >= 2`. Near the time limit (90% of it, or 30 s before the end on a short run) or the cost limit, the next turn becomes delivery-only too. No extra model call runs after a limit. Time includes model execution; cleanup can take longer. Cost remains a soft cap checked between turns and can overshoot by one response.

The agent is instructed to publish useful work as it goes:

```js
await checkpoint('findings.json', findings, { partial: true });
```

On an unfinished run, `partial` contains the latest published JSON value and its file path. If cancellation races with an already accepted delivery, its value is retained instead, without a checkpoint path. Publication completes before `checkpoint` returns. The parent retains that snapshot if a later cell hangs or crashes. Partial values are **not** validated against the final schema and are never promoted to `output`. Without a published checkpoint, `text` retains available assistant text or the last tool observation. Workspace files and the transcript remain available.

A new `run` or `followUp` starts a new partial-result scope. It does not silently return an old run’s findings. To carry findings forward, inspect the saved file and explicitly checkpoint the updated value.

## Telemetry

Anonymous run counters go to our EU PostHog project. Payload: random process ID, SDK version, OS, Node major version, browser mode, stop status, steps, duration, input/output token counts and estimated cost. No persistent user ID, model ID, tasks, URLs, page content, paths, credentials or raw errors. No person profiles or GeoIP enrichment; the ingestion service still receives the network request.

Disable with `telemetry: false`, `DO_NOT_TRACK=1`, or `ANONYMIZED_TELEMETRY=false`. Requests are best-effort with a one-second timeout, no retries, and never change task results. Node tests disable telemetry automatically.
