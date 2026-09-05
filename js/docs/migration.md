# Migration & scope

This prototype recreates the common _documented_ Browser Use workflows. We did not measure per-feature customer usage, so this is not a ranking of “most used” features.

| Browser Use workflow     | This package                                 |
| ------------------------ | -------------------------------------------- |
| Natural-language task    | `agent.run(task)`                            |
| Choose an LLM            | `model: 'provider/model'`                    |
| Structured extraction    | TypeBox `schema` with inferred output        |
| Custom actions           | Pi `AgentTool` definitions                   |
| Browser configuration    | Local Chrome/Chromium or external CDP        |
| Logged-in sessions       | Attach to an existing browser's context      |
| Screenshots / vision     | Native tool image returns                    |
| Uploads / downloads      | Raw CDP file input and download events       |
| Multi-tab tasks          | `tabs.open()`, `tabs.list()`, `tabs.get(id)` |
| Step callbacks / history | Pi lifecycle events and run metrics          |
| Stop a task              | `AbortSignal`, deadlines, `close()`          |
| Output files             | Persistent workspace and artifact paths      |

## Deliberate gaps

This is not a drop-in Python replacement. It does not currently provide cloud provisioning, a hosted agent service, automatic CAPTCHA solving, stealth guarantees, durable conversation restore, automatic compaction, a scheduler, a Python compatibility layer, or sandboxing for untrusted users.

Runs reuse browser and JavaScript state in the same live instance, but each `run()` starts a fresh Pi transcript. Closing the process loses the transcript and live bindings. Files survive according to the output directory's lifetime.

## Adopt without migrating customer state

1. Install the tarball in a separate application or experimental code path.
2. Give it isolated browsers and test accounts.
3. Compare matched tasks against your current implementation.
4. Add application-specific checks for correctness and external actions.
5. Choose a default only after repeated quality, cost, and recovery measurements.

Existing Browser Use sessions keep their existing runtime. Roll back by routing **new** work to the existing library. This package changes no database schema, API endpoint, or existing customer setting.
