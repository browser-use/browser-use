# Streaming, logs and control

Use `events()` for a live UI or service response. Use hooks when your application needs to change execution.

```ts
const events = agent.events(); // subscribe before the run
const display = (async () => {
  for await (const event of events) {
    if (event.type === 'agent_event') updateUI(event.event);
    if (event.type === 'run_end') showResult(event.result);
  }
})();
try {
  await agent.run(task);
} finally {
  await agent.close(); // finishes event iterators
  await display;
}
```

Events carry a sequence number, timestamp and run ID. The session stream includes run start/end, native Pi events, pause/resume and warnings. It does not block the agent: a consumer that exceeds 256 queued events or 8 MB receives an explicit overflow error. It can read the run log and resubscribe. Call the iterator’s `return()` when an application disconnects.

`log: 'pretty'` prints a compact timeline to stderr; `log: 'json'` prints structured events. Nothing is logged to stdout by the SDK. On-disk JSONL stores finalized events rather than duplicating the entire assistant message for each streamed token. Large events are marked truncated; image bytes are omitted from the event log. The transcript is the full saved conversational record.

The original `run(..., { onEvent })` callback remains available. It is awaited and therefore applies backpressure. Do not await the active run, `close()` or `pause()` inside that callback: you would be waiting on the callback’s own execution. Use the independent event iterator for application control.

## Three hooks

```ts
const agent = await BrowserUse.create({
  model: 'openai/gpt-5.5',
  hookTimeoutMs: 10_000,
  beforeToolCall: async ({ toolCall, args }, signal) => {
    if (toolCall.name === 'send_invoice' && !approved(args)) {
      return { block: true, reason: 'Invoice needs application approval.' };
    }
  },
  afterToolCall: async ({ toolCall, result, isError }, signal) => {
    // Optionally replace content/details or append useful application feedback.
    // Browser effects have already happened; this is not a transaction rollback.
  },
  validateResult: async (output, signal) => {
    if (!satisfiesBusinessRules(output)) return 'Include the missing invoice ID.';
  },
});
```

`validateResult` runs after schema validation and before acceptance. Returning a nonempty string rejects the result and gives the model feedback within the existing budgets. Finalization tools do not run `afterToolCall`; use the result validator for them. Hooks and awaited event callbacks have a bounded deadline (30 seconds by default). Callbacks must honor cancellation; timing out a callback cannot reverse its external effects.

A tool preflight governs the whole tool invocation. It cannot approve every individual CDP command inside arbitrary JavaScript. Use explicit custom tools for business operations requiring application authorization.

## Pause, intervene, continue

```ts
const running = agent.run(task);
// In response to a user action, outside awaited Pi callbacks:
await agent.pause();
if (agent.isPaused) {
  await agent.execute('console.log(await page.info())');
  agent.steer('Keep the current selection and export it.');
  await agent.resume();
}
const result = await running;
```

Pause resolves when the next tool boundary is reached, or when the run ends. Check `isPaused` before intervening. It does not interrupt a click, a provider request, or an in-flight custom tool. The original run deadline keeps ticking while paused. `resume()` waits for an in-progress manual cell before releasing the agent. `steer()` uses Pi’s steering queue, so feedback enters at the next supported loop boundary.

`cancel()` aborts the current run and releases a pause. Await the run’s result before starting another task. Browser mutations may already have happened; cancellation never automatically retries them. `close()` cancels the run, settles it and cleans up owned resources.
