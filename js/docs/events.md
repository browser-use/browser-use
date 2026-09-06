# Streaming & hooks

Show what the agent is doing. Intervene when you need to.

## Terminal logs

```js
const agent = await BrowserUse.create({
  model: 'openai/gpt-5.5',
  log: 'pretty', // or 'json'
});
```

Logs go to stderr. Each run also saves a JSONL event log at `result.eventsPath`.

## Live events

Subscribe before starting a run:

```js
const events = agent.events();
const display = (async () => {
  for await (const event of events) {
    console.log(event);
  }
})();

try {
  await agent.run('Find the top story on Hacker News.');
} finally {
  await agent.close();
  await display;
}
```

Events include run start/end, model output, tool calls, pause/resume and warnings.

## Hooks

Set hooks when creating the agent:

```js
const agent = await BrowserUse.create({
  model: 'openai/gpt-5.5',
  beforeToolCall: async ({ toolCall }) => {
    console.log('Starting', toolCall.name);
  },
  afterToolCall: async ({ toolCall, isError }) => {
    console.log(toolCall.name, isError ? 'failed' : 'finished');
  },
  validateResult: async (output) => {
    if (!output) return 'Return a nonempty result.';
  },
});
```

Return `{ block: true, reason: '...' }` from `beforeToolCall` to block a tool. Return a feedback string from `validateResult` to ask the model to correct its answer.

## Pause or cancel

```js
const running = agent.run('Compare these products.');

// From your UI, while the run is active:
await agent.pause();
if (agent.isPaused) {
  agent.steer('Prioritize battery life over price.');
  await agent.resume();
}

const result = await running;
```

Pause waits for the next tool boundary. Use `agent.execute()` while paused to inspect or change the browser. Use `agent.cancel()` to stop, then await the run before starting another.

::: details Streaming limits & callbacks
Events carry a sequence number, timestamp and run ID. The session stream includes run start/end, native Pi events, pause/resume and warnings. It does not block the agent: a consumer that exceeds 256 queued events or 8 MB receives an explicit overflow error. It can read the run log and resubscribe. Call the iterator’s `return()` when an application disconnects.

`log: 'pretty'` prints a compact timeline to stderr; `log: 'json'` prints structured events. Nothing is logged to stdout by the SDK. On-disk JSONL stores finalized events rather than duplicating the entire assistant message for each streamed token. Large events are marked truncated; image bytes are omitted from the event log. The transcript is the full saved conversational record.

The original `run(..., { onEvent })` callback remains available. It is awaited and therefore applies backpressure. Do not await the active run, `close()` or `pause()` inside that callback: you would be waiting on the callback’s own execution. Use the independent event iterator for application control.
:::

::: details Hook deadlines & scope
and before acceptance. Returning a nonempty string rejects the result and gives the model feedback within the existing budgets. Finalization tools do not run `afterToolCall`; use the result validator for them. Hooks and awaited event callbacks have a bounded deadline (30 seconds by default). Callbacks must honor cancellation; timing out a callback cannot reverse its external effects.

A tool preflight governs the whole tool invocation. It cannot approve every individual CDP command inside arbitrary JavaScript. Use explicit custom tools for business operations requiring application authorization.
:::

::: details Pause and cancellation behavior
is reached, or when the run ends. Check `isPaused` before intervening. It does not interrupt a click, a provider request, or an in-flight custom tool. The original run deadline keeps ticking while paused. `resume()` waits for an in-progress manual cell before releasing the agent. `steer()` uses Pi’s steering queue, so feedback enters at the next supported loop boundary.

`cancel()` aborts the current run and releases a pause. Await the run’s result before starting another task. Browser mutations may already have happened; cancellation never automatically retries them. `close()` cancels the run, settles it and cleans up owned resources.
:::
