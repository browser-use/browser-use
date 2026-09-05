# Browser & JavaScript

`execute()` exposes the same persistent browser environment the agent uses. Combine deterministic code and natural-language tasks in one session.

## Local or remote Chrome

```js
const agent = await BrowserUse.create({
  model: 'openai/gpt-5.5',
  browser: { headless: false }, // Installed Chrome. Isolated temporary profile.
});
```

Set `browser.executablePath` for another Chromium binary. To attach, use `browser: { cdpUrl: process.env.BROWSER_CDP_URL }`. HTTP(S) discovery endpoints and browser WebSocket endpoints are accepted. Local options cannot be combined with `cdpUrl`.

An attached browser belongs to you. The SDK creates a dedicated tab in its default context, where existing cookies remain available. Cleanup closes SDK-created tabs and discovered popups, including after a worker timeout. Caller-owned tabs survive. Tabs created through raw `Target.createTarget` are outside the ownership helper; manage them yourself.

Cloud provisioning and proxies belong to the provider. The SDK accepts an endpoint and has no implicit cloud billing.

## Accessibility first, raw CDP underneath

```js
await agent.execute(`
  await page.goto('https://example.com');
  await snapshot();
`);
```

| Global                 | Purpose                                                      |
| ---------------------- | ------------------------------------------------------------ |
| `page`                 | Current tab: navigation, AX, real input, evaluation, frames  |
| `tabs`                 | `list()`, `open(url)`, `get(targetId)`                       |
| `browser`              | Root CDP: `send(method, params)`, `waitFor(event, options)`  |
| `snapshot()`           | URL, title, nodes with backend DOM ids, roles, names, values |
| `screenshot()`         | Native viewport JPEG attached to the tool result             |
| `artifact(name, data)` | Exclusive file creation in the workspace                     |
| `workspace`            | Absolute output directory                                    |

```js
await page.click({ role: 'button', name: 'Search' });
await page.fill({ role: 'textbox', name: 'Email' }, 'person@example.com');
await page.select({ role: 'combobox', name: 'Shipping' }, 'Express');
await page.upload({ css: 'input[type=file]' }, [workspace + '/notes.txt']);
```

Targets accept `{role, name?}`, `{css}`, or an observed numeric backend DOM node id. Accessibility names normalize whitespace. Matches are exact. Multiple matches fail, and missing elements wait up to `operationTimeoutMs`. IDs expire after navigation. CSS queries stay within the current document; accessibility discovery reaches open shadow roots.

Clicks scroll into view, check enabled state and overlay coverage, then send real CDP mouse input to the box center. There is no hidden retry after a mutation. Custom widgets can use `page.clickAt(x, y)` and raw input commands.

```js
const rows = await page.evaluate(() =>
  Array.from(document.querySelectorAll('article'), (el) => ({
    title: el.querySelector('h2')?.textContent,
    price: el.getAttribute('data-price'),
  })),
);
await artifact('products.json', JSON.stringify(rows, null, 2));
await page.waitFor(() => document.querySelector('#status')?.textContent.includes('Saved'));
```

Functions and a JSON argument are serialized into the browser. They cannot capture Node variables. Use `evaluate(fn, argument)` instead of escaping nested source strings. Wait for an observable outcome after actions; no network-idle assumption is made.

## Frames and tabs

```js
const frames = await page.frames();
const frame = await page.frame(frames.find((f) => f.url.endsWith('/frame')).id);
await frame.fill({ role: 'textbox', name: 'Reference' }, 'A42');

page = await tabs.open('https://example.com');
await page.close();
```

Frame handles use explicit execution contexts or an out-of-process iframe target. Reacquire the handle after frame navigation. Use `tabs.list()` after a popup and select its exact target id.

## Commands, events, and files

```js
await page.cdp('Page.handleJavaScriptDialog', { accept: true });
await browser.send('Browser.setDownloadBehavior', {
  behavior: 'allow',
  downloadPath: workspace,
  eventsEnabled: true,
});
const completed = browser.waitFor('Browser.downloadProgress', {
  predicate: (event) => event.state === 'completed',
  timeoutMs: 20000,
});
await page.click({ role: 'link', name: 'Export catalog' });
await completed;
```

Register events before triggering actions. `page.cdp()` scopes commands to its session; root commands use `browser.send()`. Event waits support `sessionId`, `timeoutMs`, `predicate`, and `signal`. Events and commands are separate APIs. Every timeout is a positive integer in milliseconds. Socket closure rejects pending work.

`downloadPath` and file-input paths belong to the machine running Chrome. With remote Chrome, transfer files through the provider's file API or fetch an observed download URL into a local artifact. A remote path alone is not a delivered file.

Use `await screenshot()` for vision or `await artifact('page.jpg', await page.screenshot({quality:80}))` for a saved image. Each cell returns `{text, images, outputFile?}`. Four images per cell, two recent image-bearing messages carried into model context.

## Persistent code and recovery

Top-level `let`, `const`, functions, and `await` use V8's real REPL semantics. Node built-ins are available through `require()` and dynamic `import()`; the latter uses Node's experimental VM loader hook.

One session accepts one active operation. A deadline terminates the worker and loses JavaScript bindings; Chrome survives where possible. Inspect page state before retrying an action. The worker is a fault boundary, **not an OS sandbox**. See [recovery](/recovery).
