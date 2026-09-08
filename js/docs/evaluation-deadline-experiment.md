# Stop timed-out synchronous evaluations in Chrome

The latest full runtime `29e2b5e` passes the Luna criterion and misses the Hard criterion. Keep it as the explicit diagnostic control. This experiment changes only the execution deadline on `page.evaluate()`; it adds no prompt rule, source-specific logic, model, judge, or action retry.

## Mechanism and reproduction

The client removes a timed-out CDP request from its pending map. Chrome can still be running the requested JavaScript. Reconnecting the WebSocket does not stop that execution.

A finite local fixture increments a counter, loops synchronously for 1.2 seconds, then increments a second counter. With a 200 ms CDP deadline, the old runtime rejects the first request and the next page read also times out. The new runtime sends Chrome's native `Runtime.evaluate.timeout` using the same connection deadline. The first request still fails, but a fresh read succeeds before the original loop could finish. The first counter is 1; the second stays 0 even after the loop's original end time. No action is replayed or rolled back.

A separate test deliberately waits on a timer past the deadline. Its callback still runs later. The fix bounds synchronous evaluation, not arbitrary asynchronous page work. It cannot recover every stalled renderer, native dialog, browser/provider fault, or unrelated page script. The chess trace's original stall remains unisolated; this local reproduction does not prove its cause.

## Compatibility and recovery

No new public option, dependency, history format, profile migration, prompt, Python API, or evaluator default. The existing connection operation timeout is also sent to Chrome. Raw CDP callers retain explicit parameter control. Synchronous scripts that previously continued after the caller saw a timeout are now terminated by Chrome. Earlier side effects remain; downstream code must inspect state rather than retry blindly. Promise callbacks and network activity may continue.

Chrome marks this protocol parameter experimental. The local actual-browser test and remote diagnostics must validate support. Unsupported protocol implementations should report the error; do not silently retry the same potentially mutating evaluation without the deadline. Rollback is the prior SDK commit, with no replay or persisted-data change.

Local validation: **112/112 Node tests**, **7/7 Python integration tests**, TypeScript checking and docs build pass. This verifies the local execution boundary and existing SDK behavior; it does not establish remote score parity. [Retained reproduction and source hashes](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/evaluation-deadline-verification.json).

## Diagnostic gate

Run `mlgses` on Hard106 with GPT-5.5 medium and `bub2-023` on BU_Bench_v2 with Luna xhigh, each once per control/candidate arm. These are inspected development tasks with earlier control stalls. Keep the original per-task model, reasoning, judge, time/turn/context/browser controls; one task job per diagnostic arm. No original result is replaced.

Inspect actual tool execution, protocol errors, before/after-timeout behavior, model recovery, original judgments, delivered evidence and browser cleanup. A passing score alone does not isolate the mechanism. A failure without a synchronous-evaluation stall does not falsify the local reproduction. Do not weaken or relabel the original score.

Only after all four diagnostics complete and their integration evidence is checked, select the next frozen full comparison. Both original task sets, historical floors (88/106 Hard, 59/100 Luna), full actual-judgment coverage, 3-point margin, and 20,000 paired bootstrap resamples with seed 20260907 remain unchanged. No SOTA or full-benchmark gain is claimed here.
