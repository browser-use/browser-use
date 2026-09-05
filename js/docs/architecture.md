# Design decisions

The goal is a capable web agent with few moving parts. This package owns session lifetime and the browser tool. Pi owns inference and the agent loop. An explicit CDP connection owns browser commands and events.

```text
Application
  └─ BrowserUse
      ├─ Pi Agent → your model provider
      ├─ JavaScript tool → child process → V8 REPL
      │                                    └─ CDP → Chrome
      └─ Typed finish tool → validated result
```

## Keep CDP explicit

The earlier Pi experiments recorded 89/106 for Python + Browser Harness and 88/106 for Python + raw Playwright. That single-task difference did not establish a stable advantage. The custom JavaScript facade had crashes, broken filesystem conventions, incomplete persistence, and silent waits.

This package uses Node's WebSocket and a typed CDP transport. `send(method, params)` is separate from `waitFor(event, options)`; a property typo cannot become a made-up protocol call. Every pending command has a deadline, and socket closure rejects pending commands and event waits.

A small page API provides AX discovery, strict matching, scroll-to-element, hit testing, real mouse/keyboard input, and function-based evaluation. It does not reproduce a locator framework. There are no automatic action retries. Explicit raw commands remain available for network, dialogs, scrolling, downloads, and browser-specific features.

That design reduces protocol indirection and leaves the model free to compose several actions in one turn. It also means we own the correctness of these helpers. Frame navigation, custom widgets, and provider-specific behavior need real eval coverage; lower dependency count alone does not prove higher success. Historical scores belong to their exact older implementations.

## Use V8's REPL semantics

Wrapping each cell in an async function loses ordinary lexical bindings. Rewriting source code creates another language implementation to debug. Node's terminal REPL also has exception paths designed to print and reprompt, rather than settle an evaluation callback.

The worker uses Node's inspector protocol with V8's native `replMode` and `awaitPromise`. It gets an explicit exception or result while retaining top-level bindings. No inspector network port is opened. The REPL runs in a child process. The parent can terminate an infinite loop without killing the agent. A Node 22 inspector/GC fatal error reproduced during testing; a worker thread allowed it to abort the SDK host. Process isolation contains native crashes as well as JavaScript errors, at the cost of process startup and memory.

## Let Chrome outlive a worker

The parent owns a temporary persistent browser profile. The worker attaches over CDP. Killing the worker loses JavaScript state but does not inherently kill Chrome. Reconnection uses the primary tab's target ID.

An external browser has different ownership: the SDK disconnects, but never shuts down that browser. There is no automatic replay of failed actions.

## Keep the model context small

The worker captures at most 1 MB of tool text. The model sees a bounded prefix, with full captured output saved to a file when truncated. Screenshots are images, not base64 text. Only recent tool images are carried forward. A context guard ends the run explicitly rather than silently deleting arbitrary evidence.

This is deliberately not durable memory or automatic compaction. Those require their own semantics and evals.

## Use a finish tool

Structured results are schema-validated before acceptance. A valid finish ends the run without requiring another model call. Subsequent actions in the same batch are blocked. Exhausting a limit does not manufacture success.

Schema validity is not factual correctness. Research results still need sources and outcome evaluation.

## Keep the integration surface native

Custom tools and streamed events use Pi's types. Models use Pi's provider collections. Browser code uses explicit page helpers and raw CDP. The application learns one small lifecycle API, not three new frameworks.

The [hard benchmark](/benchmark) documents observed failures and comparison limits. Raw CDP removes an automation dependency; it does not by itself guarantee better task completion.

## What this changes for existing users

Nothing in the existing Python library or eval platform is replaced. This is an independently installable package with a new import path. No persisted customer sessions or settings are migrated. Adoption should begin in an isolated workload; rollback is selecting the old implementation for new runs. Never translate an active session halfway through a task.
