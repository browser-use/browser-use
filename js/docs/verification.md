# Verification

**43 tests pass on Node 22.19.0 and Node 24.5.0.** The suite uses the package’s explicit raw-CDP transport. Evidence is recorded in `evidence/verification.json`. Tests use real local Chromium browsers and synthetic data.

## What green proves

| Area               | Evidence                                                                                                           |
| ------------------ | ------------------------------------------------------------------------------------------------------------------ |
| Agent loop         | Pi executes browser code and delivers a schema-valid result                                                        |
| Provider transport | Real OpenAI Responses serializer/parser exercised against a loopback SSE server                                    |
| Validation         | Invalid structured output is rejected and can be repaired                                                          |
| Completion         | A finish blocks later actions in the same model batch                                                              |
| Browser            | Forms, extraction, accessibility snapshots, native images, frames, shadow DOM, selects, files, downloads, and tabs |
| Persistence        | Real lexical variables, functions, and top-level await across cells                                                |
| Recovery           | Infinite loops, cancellation, worker exits, and crashes between cells                                              |
| Ownership          | Existing tabs and cookies survive attachment and cleanup, including after worker timeout                           |
| Limits             | Step, time, estimated-cost, and context stops remain distinct from success                                         |
| Privacy boundary   | Provider environment is not inherited by the worker                                                                |
| SDK boundary       | Concurrent operations and invalid settings fail explicitly                                                         |

The deterministic integration demo completed three model turns: read a catalog, save a selection once and capture artifacts, then deliver typed output. The model responses in this demo are scripted. The browser operations and result checks are real.

Direct-delivery regressions check all 455 records survive a 100-character observation limit; invalid JSON/schema values stay repairable; completion blocks a later action in the same batch. Missing-finish tests cover a single repair turn, retained data, original step/cost/context/deadline/cancellation budgets, and preservation of partial text.

Page-attachment failure tests inject failures in both domain-initialization commands, observe a real Chrome detach event, and verify the caller's existing session remains usable. The recorder contract captures screenshots through a direct CDP session and accounts for capture time and detach failures.

## Hosted-model evaluation

The SDK has run real GPT-5.5 inference on Internal Bench Hard, with raw-CDP cloud browsers, recorded Pi model/tool spans, artifact evidence, and the independent Laith outcome judge. The updated two-task smoke passed **2/2**. See [the benchmark report](/benchmark) for the full run, exact commits, costs, failure analysis, and comparison limits.

Local tests prove specific browser and lifecycle contracts. They do not prove broad web accuracy, factual correctness, complete replay coverage, or production reliability. No production qualification has been performed. The earlier 89/106 Browser Harness and 88/106 Playwright scores belong to different implementations.

## Run the checks

```sh
npm ci
# Install Google Chrome, or attach an existing CDP endpoint.
npm run check
npm run format:check
npm test
npm run demo
npm run docs:build
npm audit
npm pack
```

`npm test` makes no paid model requests and never opens a production site. Dynamic `import()` uses Node's experimental VM loader hook; its warning is expected. Conventional `require()` is available without that hook.

## Run a local task with real inference

The `examples/verify-agent.mjs` example runs one fixed local task using actual provider inference. It checks the final browser independently: correct product, price, filter, shipping choice, and exactly one save. It records the fixture hash, model, budgets, usage, events, screenshot, and result.

After configuring provider credentials and authorizing the provider charges:

```sh
MODEL=openai/gpt-5.5 node examples/verify-agent.mjs
```

This is a functional smoke, not a benchmark. Broader accuracy claims require a frozen task set, repeat runs, matched browser conditions, explicit retries, and a consistent judge.

## Docs and package checks

The docs were inspected at desktop and 390 px mobile widths. Model selection updates the copyable example. The mobile layout has no horizontal overflow. Source formatting, strict TypeScript checks, the docs production build, and the package dependency audit are part of the verification commands above.

The surrounding eval platform's 74 Python tests and 31 UI tests pass. Its UI typecheck/build pass. Two existing Ruff violations in `harnesses/browser-use-harness-sdk/run.py` remain outside this package's scope.
