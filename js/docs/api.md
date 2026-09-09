# API

`BrowserUse.create(options)` creates one browser session. `run(task, options)` returns a result; `followUp(task, options)` continues it. Always close the session.

## Typed results

```js
import { BrowserUse, Type } from '@browser_use/js';
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

The default output is a string. Schema validation checks shape; `validateResult(output, signal)` can reject an answer with corrective feedback. It does not make unsupported facts true.

## Options

| Creation                                                 | Purpose                                             |
| -------------------------------------------------------- | --------------------------------------------------- |
| `model`, `reasoning`, `models`, `streamFn`               | Model and provider                                  |
| `browser`, `workspace`, `historyFile`                    | Browser and persistence                             |
| `instructions`, `tools`, `researchTools`                 | Extra instructions and Pi tools                     |
| `beforeToolCall`, `afterToolCall`, `validateResult`      | Blocking hooks and validation                       |
| `log`, `redact`, `recording`, `highlightActions`         | Output and recording                                |
| `operationTimeoutMs`, `cellTimeoutMs`                    | CDP / JS deadlines; 15s / 30s                       |
| `modelTimeoutMs`, `compactionTimeoutMs`, `hookTimeoutMs` | Model / summary / hook deadlines; 300s / 120s / 30s |
| `allowedDomains`, `prohibitedDomains`, `sensitiveData`   | Navigation rules and named credentials              |
| `telemetry`                                              | Anonymous counters; default on                      |
| `maxOutputChars`                                         | Printed cell output cap; 12,000                     |

| Per run                                             | Default                             |
| --------------------------------------------------- | ----------------------------------- |
| `schema`                                            | `Type.String()`                     |
| `maxSteps`, `timeoutMs`                             | 40 turns, 300,000 ms                |
| `maxCostUsd`                                        | No cost cap; soft boundary when set |
| `compaction`, `maxContextChars`                     | Enabled, 240,000 characters         |
| `signal`, `onEvent`, `observe`, `observerTimeoutMs` | Cancellation and observations       |

[Type definitions](https://github.com/browser-use/browser-use-js/blob/main/src/types.ts) are the complete contract. Browser launch options live in [browser.ts](https://github.com/browser-use/browser-use-js/blob/main/src/browser.ts).

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

The last allowed turn is reserved for delivery when `maxSteps >= 2`. Near the time or cost limit, the next turn becomes delivery-only too. No extra model call runs after a limit. Time includes model execution; cleanup can take longer. Cost remains a soft cap checked between turns and can overshoot by one response.

The agent is instructed to publish useful work as it goes:

```js
await checkpoint('findings.json', findings, { partial: true });
```

On an unfinished run, `partial` contains the latest published JSON value and its file path. If cancellation races with an already accepted delivery, its value is retained instead, without a checkpoint path. Publication completes before `checkpoint` returns. The parent retains that snapshot if a later cell hangs or crashes. Partial values are **not** validated against the final schema and are never promoted to `output`. Without a published checkpoint, `text` retains available assistant text or the last tool observation. Workspace files and the transcript remain available.

A new `run` or `followUp` starts a new partial-result scope. It does not silently return an old run’s findings. To carry findings forward, inspect the saved file and explicitly checkpoint the updated value.

## Telemetry

Anonymous run counters go to our EU PostHog project. Payload: random process ID, SDK version, OS, Node major version, browser mode, stop status, steps, duration, input/output token counts and estimated cost. No persistent user ID, model ID, tasks, URLs, page content, paths, credentials or raw errors. No person profiles or GeoIP enrichment; the ingestion service still receives the network request.

Disable with `telemetry: false`, `DO_NOT_TRACK=1`, or `ANONYMIZED_TELEMETRY=false`. Requests are best-effort with a one-second timeout, no retries, and never change task results. Node tests disable telemetry automatically.
