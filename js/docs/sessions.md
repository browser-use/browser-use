# Sessions & login

Keep the conversation, your login and your files between tasks.

## Follow up

Use the same agent for related work:

```js
await agent.run('Find three products under $100.');
await agent.followUp('Save their names and prices as CSV.');
```

`followUp()` remembers the conversation. `run()` starts a new conversation. Both keep the live browser and JavaScript variables.

## Save your login

Choose a dedicated Chrome profile. Open it visibly to sign in, then reuse the same path on later runs.

```js
const agent = await BrowserUse.create({
  model: 'openai/gpt-5.5',
  browser: {
    profileDir: './profiles/work',
    headless: false,
  },
});
```

Close the agent when finished. Chrome keeps cookies and site storage. Only one agent can use a profile at a time; websites can still expire your login.

## Keep your files

```js
const agent = await BrowserUse.create({
  model: 'openai/gpt-5.5',
  workspace: './work/research',
});

await agent.run('Read brief.txt and save your findings as a CSV.');
console.table(await agent.files());
```

Put input files in the workspace. The agent reads and writes ordinary files there. Files survive `close()`.

## Continue after a restart

```js
await agent.saveHistory(); // after a run finishes
await agent.close();

const resumed = await BrowserUse.create({
  model: 'openai/gpt-5.5',
  workspace: './work/research',
  historyFile: './work/research/.browser-use/session.json',
});
try {
  await resumed.followUp('Continue from the saved findings.');
} finally {
  await resumed.close();
}
```

History restores the conversation and usage. JavaScript variables are reset. To restore login too, pass the same `browser.profileDir`.

::: details Profile ownership & crash recovery
One SDK owner can use a profile at a time. A `.bu-pi.lock` file protects concurrent launches. Normal close releases the lock and retains the profile. After an SDK crash, verify both Chrome and the old SDK process have exited before removing a stale lock. The SDK deliberately does not steal a lock based on a timeout. Authentication can expire; reuse is not a guarantee that a website will keep you logged in.
:::

::: details Connect to an existing browser

```ts
const agent = await BrowserUse.create({
  model: 'openai/gpt-5.5',
  browser: { cdpUrl, targetId }, // targetId optional; otherwise create an owned tab
});
```

Attached browsers and explicitly attached caller tabs remain caller-owned. Local profile options cannot be combined with a CDP endpoint. Paid cloud provisioning remains the application’s responsibility; any provider exposing CDP can be attached.
:::

::: details Workspace behavior
The worker’s current directory is the workspace. `require()` resolves workspace-installed packages. The agent can use Node’s filesystem and process APIs to process inputs; the SDK adds no document preprocessing layer. Dynamic `import()` follows the worker module’s normal Node resolution; use workspace-relative `require()` for locally installed packages.

`files()` returns relative/absolute paths, byte sizes and modification times. It excludes internal `.browser-use`, `node_modules`, `.git`, and symlinks; inventory is bounded to 10,000 files and 16 directory levels. This inventory is a convenience, not filesystem isolation. Remote-browser download paths still refer to the remote machine unless the bytes are explicitly transferred.
:::

::: details History, usage & privacy
Each call has its own budgets and `result.usage`. `agent.usage` includes all runs and restored usage. A session executes one operation at a time.

Each run writes a versioned transcript and event log under `.browser-use/runs/`. Results include `historyPath` and `eventsPath`. `saveHistory()` writes `.browser-use/session.json` by default, using an atomic replacement and private file permissions.

Restore accepts version 1 histories for the same model. It restores conversation and usage, **not JavaScript bindings, open connections or a browser checkpoint**. The agent receives an explicit reset notice. No actions are automatically replayed. Custom tools and instructions must be supplied again.

`history` returns an independent in-memory snapshot. `redact: ['value-to-hide']` removes configured values from persisted text and session event streams. Redaction does not change live model context or hide pixels in images. Raw browser profiles, files and screenshots can contain sensitive data; the application controls access and retention.
:::
