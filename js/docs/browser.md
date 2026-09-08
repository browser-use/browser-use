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

## Responsive layouts

Resize a page with raw CDP, then inspect the resulting layout and screenshot:

```js
await page.cdp('Emulation.setDeviceMetricsOverride', {
  width: 390,
  height: 844,
  deviceScaleFactor: 1,
  mobile: false,
});
console.log((await page.cdp('Page.getLayoutMetrics')).cssVisualViewport);
await screenshot();
```

This tests a narrow desktop viewport. `mobile: true` additionally enables Chrome's mobile layout behavior; pages without a responsive viewport meta tag can have a wider layout viewport. Neither setting makes Chrome a physical mobile device.

For Browser Use Cloud, provision the browser with **`allowResizing: true`** before attaching the SDK. Default cloud sessions can acknowledge resize commands while retaining their original dimensions. The option can affect stealth and initial geometry; verify the actual viewport after connecting. Reported device-pixel ratio may still differ from the requested scale. The SDK cannot change the provisioning policy of an already attached browser. [Measured behavior and limits](./confirmation3-trace-audit.md#cloud-resizing-is-an-explicit-provisioning-capability).

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

Snapshot nodes retain Chrome's reported `checked`, `pressed`, `selected`, `expanded`, and `disabled` states. Values are booleans; `checked` and `pressed` may also be `'mixed'`. An absent property means Chrome did not report it, not `false`. Read a fresh snapshot after input to observe changes. A control's name describes its label; its state describes the current selection.

```js
const radios = (await page.snapshot()).nodes.filter((node) => node.role === 'radio');
const selected = radios.filter((node) => node.checked === true);
```

Clicks scroll into view, check enabled state and overlay coverage, then send real CDP mouse input to the box center. There is no hidden retry after a mutation. Custom widgets can use `page.clickAt(x, y)` and raw input commands.

For a clipped native radio or checkbox whose own center cannot receive input, `click()` can use its single visible associated HTML label. The label must pass the same hit test; an embedded link or unrelated interactive control is rejected. Disabled controls, covered ordinary inputs and ambiguous labels still fail. This resolves the click surface before sending input; it does not invoke DOM `.click()`, set checked state, or replay an action. Controls without a layout box still require explicit targeting of their visible UI. Inspect a fresh snapshot to verify the resulting selection.

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

`page.evaluate()` also passes the connection's operation timeout to Chrome's execution watchdog. This stops synchronous evaluation that exceeds the deadline, so a rejected client promise does not leave that script consuming the renderer. It does not undo prior effects or cancel asynchronous callbacks, fetches, or other page work. Inspect state after every timeout; never assume cancellation or replay an action. Raw `page.cdp()` parameters remain caller-controlled.

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

Inside `agent.execute()` and the agent's JavaScript tool, explicit screenshots on the worker's browser connection supply native model previews. This includes `screenshot()`, `page.screenshot()`, other tabs, and raw `Page.captureScreenshot` calls. Saving the original bytes still works:

```js
await artifact('mobile.jpg', await mobilePage.screenshot({ quality: 80 }));
// The file is saved and the model receives the image on its next turn.
```

The global helper captures once; it does not duplicate the underlying CDP command. Each cell returns `{text, images, outputFile?}`. Up to four captures of at most 8 MB each enter preview processing. Ordinary viewport images under 2000 pixels on each axis and 4.5 MiB of base64 data pass through unchanged. Larger previews use upstream Pi resizing to fit those limits. Original CDP responses and saved files remain unchanged. A text note states the original and preview dimensions; long-page thumbnails can lose legibility, so capture a viewport or bounded `Page.captureScreenshot` clip for readable detail. Preview coordinates are not automatically viewport coordinates.

Excess captures, unsupported dimensions, images above 50 megapixels, and failed resizing produce explicit model-vision omission warnings. They do not replay the capture or discard its original bytes. Processing remains inside the existing cell deadline; deadline/cancellation can still reset the worker as documented. Two recent image-bearing messages are retained in model context. Late responses from an ended cell are not attached to a later cell. These limits bound screenshot previews, not every possible provider restriction or images returned by application-defined tools.

This does not automatically take screenshots after actions. Recording/eval observers use separate connections and do not feed their images to the agent. Saving an existing image file does not display it; use Pi's image-capable `read` tool when enabled. Model vision still depends on the chosen provider/model. Standalone `Page` calls outside the worker continue returning bytes to your application.

## Persistent code and recovery

Top-level `let`, `const`, functions, and `await` use V8's real REPL semantics. Node built-ins are available through `require()` and dynamic `import()`; the latter uses Node's experimental VM loader hook.

One session accepts one active operation. A deadline terminates the worker and loses JavaScript bindings; Chrome survives where possible. Inspect page state before retrying an action. The worker is a fault boundary, **not an OS sandbox**. See [recovery](/recovery).
