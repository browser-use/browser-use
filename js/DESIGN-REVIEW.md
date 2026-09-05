# Design and review notes

The package is independent of the eval platform. It adds no platform orchestration, remote dispatch, customer-state migration, or UI mutations.

## Decisions

| Decision                   | Why                                                                     | Tradeoff                                                                 |
| -------------------------- | ----------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| Pi agent core              | Reuse model protocols, tool validation, and lifecycle events            | Follow Pi's versioned model/provider contract                            |
| Raw CDP                    | Explicit protocol commands/events and small inspectable browser helpers | We own helper correctness; no locator framework or auto-retry            |
| V8 REPL in a child process | Real bindings and await; terminate stuck code                           | Reset loses JavaScript objects; Node dynamic import hook is experimental |
| Parent-owned Chrome        | Worker failure need not kill the browser                                | An external endpoint still needs its own lifecycle owner                 |
| Typed finish tool          | Validate delivery and stop without another model round trip             | Schema validity is not factual correctness                               |
| Artifacts and bounded text | Keep large observations out of recurring context                        | Applications own output retention                                        |
| One operation per session  | Prevent accidental page races                                           | Parallel work needs separate sessions                                    |
| Fresh transcript per run   | Small, explicit lifecycle without a persistence framework               | No durable sessions or automatic compaction                              |

## Review changes

| Before                                                                | After                                                                   |
| --------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| Terminal REPL could print exceptions without settling a callback      | V8 evaluation returns an explicit result or exception                   |
| A Node 22 inspector/GC crash could abort the SDK host                 | REPL moved from a worker thread into a terminable child process         |
| Worker inherited host execution flags                                 | Child starts with only a heap-limit flag and an empty environment       |
| Timed-out worker could leave the attached primary tab behind on close | Parent tracks owned targets and closes them without reviving the worker |
| Crash between cells could silently discard bindings                   | The next call reports lost state before executing new code              |
| Screenshot base64 counted against text context                        | Images are excluded from the text-size calculation                      |
| Completion tracked with independent boolean and value                 | One completion object contains validated output and text                |
| Node minimum assumed from the SDK stack                               | Minimum set to Pi's actual 22.19 requirement and tested                 |
| Stable docs dependency pulled a vulnerable Vite version               | Vite pinned to patched 6.4.3; package audit reports zero advisories     |

## Documentation interface

New interface; no existing customer UI was replaced.

| Before                                 | After                                                                                                                                             |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| Empty package directory                | Custom SDK homepage with a usable code example, local setup instructions, and explicit prototype status                                           |
| No navigation                          | Searchable guides, API reference, design decisions, migration scope, and verification                                                             |
| No interactive example                 | Provider selection updates the code; copy control copies the selected example or selects it for manual copying if clipboard access is unavailable |
| No visual system                       | Orange accent, dark/light themes, strong type hierarchy, consistent code surfaces and spacing                                                     |
| No mobile layout                       | Stacked 390 px layout, accessible menu, code scrolling within its panel                                                                           |
| No interaction/accessibility treatment | Focus indicators, labeled select, keyboard navigation, reduced-motion support, and usable control targets                                         |

## Compatibility, rollout, rollback

Existing Python imports, eval commands, customer sessions, persisted files, and production APIs are unchanged. Try the tarball in a separate application first. Route only new test workloads to it. Rollback is switching new work to the old implementation; never translate an in-flight session between runtimes.

The worker is not a sandbox. Untrusted tasks require an OS isolation boundary and restricted browser accounts. Custom tools and callbacks must cooperate with cancellation. The cost threshold is checked between turns and can overshoot by one response. Hosted benchmark results and their limits are recorded in `docs/benchmark.md`. No production qualification has been completed.
