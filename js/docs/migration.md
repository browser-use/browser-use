# Migration & scope

This prototype recreates the common _documented_ Browser Use workflows. We did not measure per-feature customer usage, so this is not a ranking of “most used” features.

| Browser Use workflow     | This package                                      |
| ------------------------ | ------------------------------------------------- |
| Natural-language task    | `agent.run(task)`                                 |
| Choose an LLM            | `model: 'provider/model'`                         |
| Structured extraction    | Typed final output; agent-written extraction code |
| Custom actions           | Pi `AgentTool` definitions                        |
| Browser configuration    | Local Chrome/Chromium or external CDP             |
| Logged-in sessions       | Persistent profile or existing CDP context        |
| Screenshots / vision     | Native tool image returns                         |
| Uploads / downloads      | Raw CDP file input and download events            |
| Multi-tab tasks          | `tabs.open()`, `tabs.list()`, `tabs.get(id)`      |
| Step callbacks / history | Live events, saved history and run metrics        |
| Stop a task              | `AbortSignal`, deadlines, `close()`               |
| Output files             | Persistent workspace and artifact paths           |

## Deliberate gaps

This is not a drop-in Python replacement. It does not currently provide cloud provisioning, a hosted agent service, automatic CAPTCHA solving, stealth guarantees, automatic compaction, a scheduler, a drop-in Python beta compatibility layer, or sandboxing for untrusted users.

Runs reuse browser and JavaScript state in the same live instance, but each `run()` starts a fresh Pi transcript. Explicit `followUp()` retains the transcript. Saved version 1 histories can restore conversation after a restart, but live bindings are lost. Files survive according to the output directory's lifetime.

## Adopt without migrating customer state

1. Install the tarball in a separate application or experimental code path.
2. Give it isolated browsers and test accounts.
3. Compare matched tasks against your current implementation.
4. Add application-specific checks for correctness and external actions.
5. Choose a default only after repeated quality, cost, and recovery measurements.

Existing Browser Use sessions keep their existing runtime. Roll back by routing **new** work to the existing library. This package changes no database schema, API endpoint, or existing customer setting.

## New session API and Python client

The session API now supports explicit follow-ups, saved profiles and transcripts, live event streams, hooks and recording. `run()` still starts a fresh transcript. These additions do not reproduce Python Browser Use's planner/action loop.

An opt-in Python package, `browser_use_next`, wraps this engine and supports Pydantic results and Python tools. It does not replace the installed `browser_use.beta` import or pretend to accept its full constructor. See [Python](./python) and [sessions](./sessions).
