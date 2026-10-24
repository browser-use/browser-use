# Migrate to the Pi engine

This major-version draft keeps the package name, Python import, and `browser-use` command.
It replaces the old planner with Pi.

## Public API

| Previous pattern                | New pattern                                                                |
| ------------------------------- | -------------------------------------------------------------------------- |
| `Agent(task=task, llm=llm)`     | `await Agent.create(model="provider/model")`, then `await agent.run(task)` |
| Python provider wrapper classes | Exact model string and optional provider metadata                          |
| `BrowserSession` and Watchdogs  | Pi browser session and CDP helpers                                         |
| `@tools.action`                 | Typed Python `Tool` callback                                               |
| Old step callback               | Event stream or before/after tool callback                                 |
| Old history replay              | Transcript, workspace, checkpoints, and explicit follow-up                 |
| Rust `[core]` extra             | Pi engine                                                                  |

Existing lockfiles retain their selected release until users update them.
The new package does not preserve every old internal import.

## Browser ownership

Omitting the browser creates an owned Cloud browser.
Explicit Cloud and Chromium choices create owned browsers.
Explicit Chrome and CDP choices borrow browsers.
Closing a borrowed connection preserves unrelated tabs and the caller's browser.

The agent and generated code run with the application.
A remote browser does not move bash or JavaScript onto the browser host.

## Models and cost

Known provider transports accept exact new model IDs without catalog registration.
Unknown prices remain unknown.
A cost limit requires known prices or provider-reported cost.
Time, turn, and token limits remain available when pricing is unknown.
The library never silently substitutes another model.

## Controls

Bash and file tools default on in the proposed major version.
Use trusted application hooks for approval and setup.
Use browser-side enforcement for browser restrictions.
Use deployment isolation when tasks require host restrictions.
The SDK provides no sandbox claim for unrestricted Node code.

## Provider integrations

OpenAI and Anthropic adapters retain their provider contracts.
Their browser backend uses Pi without another model loop.
Install only the extra that your application uses.
Keep exact SDK versions in the application lockfile.

## CLI and records

The CLI preserves existing stdin programs through Browser Harness.
The explicit `run` command uses Pi.
Cloud becomes the Browser Use default while explicit local sessions keep their selection.
The independent Browser Harness command keeps its own defaults.
Direct stdin Chrome and Chromium modes attach through Harness discovery.
The Pi task command launches an isolated browser for `--browser chromium`.

Transcript restoration does not restore JavaScript variables or browser login.
Recording uses sampled frames and can miss visual changes.
Text redaction does not sanitize image pixels.

## Scope

The migration removes the old event bus, Watchdogs, DOM serializer, model wrappers, and Rust beta.
It keeps one Pi planning engine.
Subagent orchestration remains outside the initial base API.
Product telemetry reports subagent counts only when an application supplies measured child activity.

## Release gates

Keep this migration unpublished until these checks finish:

- Execute installed wheels on every supported native platform.
- Compare the frozen migration against Pi on BU Bench V2.1.
- Review the pinned Pi dependencies and update vulnerable nested packages through a tested upstream release.
- Validate each required remote file workflow against its actual browser provider.

The current dependency audit identifies vulnerable Undici and brace-expansion versions inside Pi's pinned dependency tree.
Source review establishes no normal-use exploit path.
That review does not remove the dependency release gate.
A small evaluation sample does not establish full benchmark parity.
