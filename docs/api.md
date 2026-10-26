# API reference

`BrowserUse.create(options)` creates one browser session and JavaScript workspace.
Python also exports `Agent` and `Browser`.
A session can omit its model for deterministic browser execution.
Python `Agent` supplies GPT-6 Luna through the Browser Use gateway when callers omit `model`.
`Browser` and `BrowserUse` keep deterministic execution model-free.

| Option                                | Purpose                                           |
| ------------------------------------- | ------------------------------------------------- |
| `model`, `modelInfo`                  | Exact model and explicit metadata                 |
| `browser`                             | Cloud, Chrome, Chromium, pending, or explicit CDP |
| `workspace`                           | Local artifacts and persistent files              |
| `tools`                               | Application-defined typed tools                   |
| `researchTools`                       | Read, write, edit, bash; defaults enabled         |
| `beforeToolCall`, `afterToolCall`     | Bounded blocking tool callbacks                   |
| `validateResult`                      | Feedback after schema validation                  |
| `allowedDomains`, `prohibitedDomains` | Browser document-navigation rules                 |
| `sensitiveData`, `redact`             | Named secrets and configured text redaction       |
| `recording`                           | Optional sampled browser frames                   |
| `log`                                 | Readable or JSON progress                         |
| `telemetry`                           | Optional aggregate product measurements           |

| Method                     | Behavior                                               |
| -------------------------- | ------------------------------------------------------ |
| `run`                      | Starts a new conversation                              |
| `followUp`                 | Continues the conversation                             |
| `execute`                  | Runs explicit browser JavaScript                       |
| `events`                   | Streams bounded observations                           |
| `pause`, `resume`, `steer` | Controls future execution                              |
| `cancelAndWait`            | Cancels and waits for execution to settle              |
| `history`, `saveHistory`   | Reads or persists a versioned transcript               |
| `files`                    | Lists workspace artifacts                              |
| `close`                    | Closes owned resources and preserves borrowed browsers |

Python exposes equivalent snake-case methods where available.
The TypeScript definitions describe the complete engine contract.

## Run limits

Runs support step, time, and known-cost limits.
Automatic compaction defaults enabled.
Its character budget defaults to four characters per configured model context token.
Summaries can omit details.
Compaction keeps local archives and preserves original context when summary validation fails.

A completed result establishes accepted output delivery.
It does not independently establish website task success.
Keep schema validity, caller validation, and task verification separate.

## Events

Use `log="pretty"` for readable output and `log="json"` for JSON output.
`onEvent` applies backpressure.
`observe` provides best-effort observations.
Slow consumers can lose bounded stream entries.
Manual execution records its own execution events.

Hooks do not sandbox generated code.
See [enterprise controls](enterprise.md) for the actual enforcement boundaries.
