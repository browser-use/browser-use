# Browser primitives

The `javascript` tool is a persistent Node REPL. Top-level variables, functions and `await` survive between cells. Code can use Node libraries and workspace files. Pi supplies optional `read`, `write`, `edit` and `bash` tools with `researchTools: true`.

| Primitive                                       | Purpose                                                    |
| ----------------------------------------------- | ---------------------------------------------------------- |
| `page.goto(url)`, `page.info()`                 | Navigate; read URL and title                               |
| `page.snapshot()`                               | AX nodes with backend IDs, roles, names, values and states |
| `page.evaluate(fn, argument)`                   | Run page code; return JSON                                 |
| `page.waitFor(fn, argument, {timeoutMs})`       | Wait for an observed condition                             |
| `page.clickAt(x, y)`                            | Real mouse input in viewport coordinates                   |
| `page.screenshot()`                             | Capture a native image for the model                       |
| `page.cdp(method, params)`                      | Any typed tab CDP command                                  |
| `tabs.open(url)`, `tabs.list()`, `tabs.get(id)` | Open, list and attach tabs                                 |
| `page.close()`                                  | Explicitly close that tab                                  |
| `browser.send(method, params, sessionId?)`      | Root or scoped CDP commands                                |
| `browser.waitFor(event, options)`               | Subscribe before triggering an event                       |

`snapshot()` and `screenshot()` also refer to the current `page`. Assign `page = await tabs.open(url)` to switch it. `evaluate` cannot capture Node variables; pass a JSON argument explicitly.

## AX → coordinates → click

```js
const tree = await page.snapshot();
const button = tree.nodes.find((n) => n.role === 'button' && n.name === 'Continue');
if (!button || button.disabled) throw new Error('Continue is unavailable');
await page.cdp('DOM.scrollIntoViewIfNeeded', { backendNodeId: button.id });
const { model } = await page.cdp('DOM.getBoxModel', { backendNodeId: button.id });
const q = model.content;
await page.clickAt((q[0] + q[2] + q[4] + q[6]) / 4, (q[1] + q[3] + q[5] + q[7]) / 4);
// Inspect the actual outcome. Coordinates can hit an overlay.
```

Prefer AX for discovery and state. Use page evaluation for extraction, screenshots for visual questions, and raw CDP for typing, uploads and frame routing. The [agent prompt](https://github.com/browser-use/browser-use-js/blob/main/src/prompt.ts) teaches these recipes. Reusable helpers belong in the agent’s workspace.

`artifact(name, data)` creates a new file; `checkpoint(name, value)` atomically saves JSON. `reconnect()` resets CDP; reacquire handles and inspect before acting. `finish_from_js({expression})` delivers an existing variable without asking the model to rewrite it.

## Migration

The simplified API removes `find`, `click`, `fill`, `press`, `text`, `select`, `upload`, `frames`, `frame`, and the `Target` type. Replace selector helpers with observed AX IDs, coordinates, page evaluation, and CDP. Existing saved scripts using those methods must change. `run`, `followUp`, workspace, profile and history formats are unchanged.

## Why a worker?

Pi stays in your application. Generated JS runs in one child process with a persistent V8 REPL. A timeout can kill a synchronous infinite loop; `process.exit()` kills only the worker. In-process execution cannot provide those guarantees. A worker is not a security sandbox: code can read files and use the network.

Normal code errors retain JS state. Worker exits, cancellation and cell timeouts lose it. Browser effects and files may survive. Recovery never replays actions automatically. CDP timeout does not prove asynchronous page work stopped.

## Show the interaction target

Set `highlightActions: true` in `BrowserUse.create`. The original Browser Use orange corner brackets animate around clicked or typed-into elements, including raw CDP actions. They stay for one second, then fade over 300 ms. Off by default. The transient element is `aria-hidden`, uses a closed shadow root and passes pointer input through. It adds no labels to the AX tree. Cosmetic failures never fail the action.
