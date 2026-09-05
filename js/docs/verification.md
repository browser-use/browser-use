# Verification

**35 tests pass on Node 22.19.0 and Node 24.5.0.** The suite uses the package’s explicit raw-CDP transport. Evidence is recorded in `evidence/verification.json`. Tests use real local Chromium browsers and synthetic data.

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

## What green does not prove

No hosted-model benchmark or production run has been performed for this package. The two-task remote smoke is prepared for `r2dhyl,n1u349`; it requires the new code at an immutable remote commit. The adapter lifecycle is tested with real Chrome and stubbed cloud/model/telemetry services, including screenshot evidence and cleanup. The local Ollama attempt stopped at the model loader before browser work: `Missing required key: general.description`. That is unavailable inference, not a measured task failure or a browser-quality score.

The earlier 89/106 Browser Harness and 88/106 Playwright scores belong to different implementations. They motivated the design; they are not results for this SDK.

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

## Prepare the autonomous proof

The `examples/verify-agent.mjs` example runs one fixed local task using actual provider inference. It checks the final browser independently: correct product, price, filter, shipping choice, and exactly one save. It records the fixture hash, model, budgets, usage, events, screenshot, and result.

After configuring provider credentials and authorizing the provider charges:

```sh
MODEL=openai/gpt-5.5 node examples/verify-agent.mjs
```

This is a functional smoke, not a benchmark. Broader accuracy claims require a frozen task set, repeat runs, matched browser conditions, explicit retries, and a consistent judge.

## Docs and package checks

The docs were inspected at desktop and 390 px mobile widths. Model selection updates the copyable example. The mobile layout has no horizontal overflow. Source formatting, strict TypeScript checks, the docs production build, and the package dependency audit are part of the verification commands above.

The surrounding eval platform's 74 Python tests and 31 UI tests pass. Its UI typecheck/build pass. Two existing Ruff violations in `harnesses/browser-use-harness-sdk/run.py` remain outside this package's scope.

## Hosted smoke findings

The first two-task Internal Bench Hard smoke ran against commit `789c3f3` on September 5, 2026. The FAA task reached the SDK's default 240,000-character guard after 24 model turns, before producing its CSV. The eval adapter now exposes `max_context_chars`, set to 800,000 for GPT-5.5. This changes the evaluation configuration; it does not retroactively change that failed outcome. The SDK's general-purpose default remains 240,000.

The historical Python/Pi run did not enforce the platform's advertised 35-step limit: 43 of 106 tasks used more than 35 model turns, with a maximum of 89. The full candidate uses a 1,000-turn safety ceiling and a 1,700-second agent deadline within a 30-minute platform budget. The old agent had a 1,770-second deadline. The dataset hash, model, reasoning, judge, and browser proxy settings match; runtime versions, context behavior, runner provider, and execution date differ. This is a historical benchmark comparison, not a controlled contemporaneous A/B test.
