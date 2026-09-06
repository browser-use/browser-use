# Sessions that keep working

A browser profile, a workspace, and a conversation solve different problems. Choose each explicitly.

```ts
const agent = await BrowserUse.create({
  model: 'openai/gpt-5.5',
  workspace: './work/customer-research',
  browser: { profileDir: './profiles/research', headless: false },
  log: 'pretty',
});
try {
  await agent.run('Find the three products that match the brief.');
  await agent.followUp('Save those products as a CSV in the workspace.');
  console.table(await agent.files());
  await agent.saveHistory();
} finally {
  await agent.close();
}
```

## Follow-up or fresh start

`run()` keeps its original behavior: a fresh conversation, using the existing browser and JavaScript namespace. `followUp()` carries forward the conversation too. Each call has its own result schema and budgets. `result.usage` counts that call; `agent.usage` counts the session, including restored historical usage.

Call `execute()` between runs for deterministic work. It shares the agent’s browser and variables. A single session executes one operation at a time. Use separate sessions for parallel tasks.

## Login once

Set `browser.profileDir` to a dedicated directory and open headed Chrome to sign in normally. Later runs can open that directory headlessly. Cookies, local storage and IndexedDB remain with Chrome. The SDK never asks the model to copy credentials from your personal browser.

One SDK owner can use a profile at a time. A `.bu-pi.lock` file protects concurrent launches. Normal close releases the lock and retains the profile. After an SDK crash, verify both Chrome and the old SDK process have exited before removing a stale lock. The SDK deliberately does not steal a lock based on a timeout. Authentication can expire; reuse is not a guarantee that a website will keep you logged in.

To use an existing browser:

```ts
const agent = await BrowserUse.create({
  model: 'openai/gpt-5.5',
  browser: { cdpUrl, targetId }, // targetId optional; otherwise create an owned tab
});
```

Attached browsers and explicitly attached caller tabs remain caller-owned. Local profile options cannot be combined with a CDP endpoint. Paid cloud provisioning remains the application’s responsibility; any provider exposing CDP can be attached.

## Files are ordinary files

The worker’s current directory is the workspace. `require()` resolves workspace-installed packages. The agent can use Node’s filesystem and process APIs to process inputs; the SDK adds no document preprocessing layer. Dynamic `import()` follows the worker module’s normal Node resolution; use workspace-relative `require()` for locally installed packages.

`files()` returns relative/absolute paths, byte sizes and modification times. It excludes internal `.browser-use`, `node_modules`, `.git`, and symlinks; inventory is bounded to 10,000 files and 16 directory levels. This inventory is a convenience, not filesystem isolation. Remote-browser download paths still refer to the remote machine unless the bytes are explicitly transferred.

## Save and restore

Each run writes a versioned transcript and event log under `.browser-use/runs/`. Results include `historyPath` and `eventsPath`. `saveHistory()` writes `.browser-use/session.json` by default, using an atomic replacement and private file permissions.

```ts
const resumed = await BrowserUse.create({
  model: 'openai/gpt-5.5',
  workspace: './work/customer-research',
  browser: { profileDir: './profiles/research' },
  historyFile: './work/customer-research/.browser-use/session.json',
});
await resumed.followUp('Continue from the saved notes.');
```

Restore accepts version 1 histories for the same model. It restores conversation and usage, **not JavaScript bindings, open connections or a browser checkpoint**. The agent receives an explicit reset notice. No actions are automatically replayed. Custom tools and instructions must be supplied again.

`history` returns an independent in-memory snapshot. `redact: ['value-to-hide']` removes configured values from persisted text and session event streams. Redaction does not change live model context or hide pixels in images. Raw browser profiles, files and screenshots can contain sensitive data; the application controls access and retention.
