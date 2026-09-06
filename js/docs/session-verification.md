# Session SDK verification

**September 6, 2026 · 56 JavaScript tests passed on Node 22.19.0. Six Python integration tests passed.** Tests use real local Chrome, synthetic data and a local SSE model endpoint. No paid model request or remote benchmark was dispatched for this change.

## What was added

- Explicit conversation follow-ups, with per-run and cumulative usage.
- Persistent Chrome profiles, exclusive ownership and normal-close lock cleanup.
- Ordinary persistent workspaces, file inventory and versioned history save/restore.
- Bounded event streams, structured/pretty logs, safe-boundary pause, steering and cancellation.
- Bounded before/after-tool hooks and schema-valid result rejection with application feedback.
- Captured-frame MP4/GIF export with pointer animation, captions, redaction and exclusive output creation.
- A Python wheel containing the same JS engine, typed Pydantic results and bidirectional Python custom tools.

## What green proves

| Area          | Evidence                                                                                                                                                                         |
| ------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Compatibility | The existing 43 integration tests remain green.                                                                                                                                  |
| Continuation  | Follow-up sees the prior task and exact JS values; fresh run does not receive the old transcript.                                                                                |
| Cost/context  | Usage is not double-counted across calls; oversized input stops before a provider call and does not return the previous answer as new partial work.                              |
| Profiles      | Cookies, local storage and IndexedDB survive closing and reopening Chrome; a concurrent owner is rejected.                                                                       |
| Files/history | Workspace IO uses ordinary files; inventory excludes symlinks/internal state; malformed history is rejected; configured secrets are redacted from saved text.                    |
| Hooks/control | Rejected results are corrected; failed tools reach hooks; hung hooks time out; pause is acknowledged before the queued mutation; cancelling a paused run prevents that mutation. |
| Streaming     | Events are visible before completion; a slow consumer fails explicitly instead of accumulating unlimited events.                                                                 |
| Recovery      | History-save failure retains completed output with a warning; non-JSON tool metadata cannot break event persistence.                                                             |
| Video         | Actual CDP click metadata and screenshots produce H.264 MP4 and GIF files; both exports leave the source page's click counter at exactly one.                                    |
| Python        | Real Python → bundled Node → Pi → local SSE → Python tool round trips, including tool failure, cancellation and nested Pydantic output.                                          |
| Packaging     | npm tarball installed into a separate application; Python wheel installed into a fresh virtual environment outside the source checkout.                                          |
| Documentation | VitePress production build and real-Chrome checks of sessions/events/recording/Python pages; no horizontal overflow at 1440px.                                                   |

The session demo creates a CSV, transcript and recordings. Model responses are scripted; Chrome actions, file writes and rendering are real. Its video is demonstration evidence, not an accuracy result.

## Reproduce

Install Chrome, Node 22.19+, ffmpeg and uv. From the source checkout:

```sh
npm ci
npm run check
npm test
npm run format:check
npm run docs:build
npm run demo:session

uv venv .venv
uv pip install --python .venv/bin/python -e ./python
npm run test:python
uvx ruff check python
uvx ruff format --check python

npm pack --pack-destination artifacts
npm run build:python
uv build python --wheel --out-dir artifacts/python
```

`npm test` requires ffmpeg; it does not silently skip the recording integration. `npm run test:python` builds the bundled runtime before running the Python tests. The tested Python host was CPython 3.14 on macOS; Python 3.11 is the declared minimum but was not separately exercised. Windows and Linux packaging/browser paths were not exercised in this session.

## Compatibility and remaining limits

`run()` retains fresh-conversation semantics. Relative Node filesystem paths now resolve from the workspace. Workspace-installed packages resolve through `require()`; dynamic imports retain normal worker-module resolution. The context guard now also runs before the first provider call. These intentional changes must be frozen as part of future evaluation configurations.

History restore does not restore the JS heap or replay actions. Profiles are single-owner and require explicit stale-lock recovery after a crash. Events/recording have bounded queues/frame counts; recordings are sampled rather than lossless video. Arbitrary custom application callbacks and synchronous Python tool threads must cooperate with cancellation. Text redaction does not cover screenshot pixels. The execution process is not an OS sandbox.

Neither package has been published. The existing `browser_use.beta` implementation and eval-platform worktree are untouched. This change supplies an opt-in Python client, not a silent 62-parameter compatibility swap. No CI run, PR or deployment is claimed here. The historical 91/106 score is not a measurement of this new session API.
