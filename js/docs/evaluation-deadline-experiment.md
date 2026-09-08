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

The frozen candidate is `45cedf407debcc6615462a3ca9eecf8d3b4e98c0`. The diagnostic control `62e9caf5e241cc27c36ef863476544df1fe044ec` retains the complete evaluated `29e2b5e` runtime; its eval adapter and dependency lock match the candidate. [Exact inputs and gate](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/evaluation-deadline-plan.json).

## Original executions

All four prepare jobs created their original Laminar evaluations. Both Hard arms and the Luna control are complete and audited; the original Luna candidate is still running.

| Arm            | GitHub workflow                                                                          | Laminar evaluation                     |
| -------------- | ---------------------------------------------------------------------------------------- | -------------------------------------- |
| hard-control   | [34230002630](https://github.com/browser-use/new-eval-platform/actions/runs/34230002630) | `4a175f9b-c914-445e-b4f5-beb0e5d7bfc1` |
| hard-candidate | [34230005987](https://github.com/browser-use/new-eval-platform/actions/runs/34230005987) | `a83eaaac-a035-49ac-91bb-ed7924132d46` |
| luna-control   | [34230009051](https://github.com/browser-use/new-eval-platform/actions/runs/34230009051) | `fe55ecee-b13e-49c0-9843-5fed5734cf05` |
| luna-candidate | [34230012210](https://github.com/browser-use/new-eval-platform/actions/runs/34230012210) | `1037a431-3d9a-4979-930c-d9c258af7b10` |

[Original dispatch inputs and IDs](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/evaluation-deadline-dispatch.json). Preserve each original handle until terminal; an observation timeout is not a reason to restart.

## Candidate Hard diagnostic: complete

The original candidate `mlgses` workflow completed successfully with an actual Laith **1/1** judgment. All frozen manifest, task, model/reasoning, budget and dependency-lock checks pass. The agent used **15 steps**, **111.927 seconds** and **$0.346486** recorded agent inference. Fourteen JavaScript calls succeeded; all fourteen evaluator screenshots are retained, with zero capture errors. The owned Cloud browser is independently confirmed stopped.

The model dismissed onboarding dialogs, entered the rated puzzle UI, checked a guessed trending route that returned 404, returned to the rated workflow and played board moves through CDP mouse input. Original screenshot `014.jpg` and event 55 both show **Solved / Very good!**. The pass is retained, but neither establishes that this puzzle was first in a trending ranking. Its solution was read from the site's own stored puzzle state, so this is not evidence of independent chess reasoning.

There was **no recorded tool timeout**. Consequently this run supports compatibility and delivered browser evidence, not a causal performance gain from the new synchronous execution deadline. The paired control audit follows. No full evaluation is selected yet.

[Original judgment, manifest, errors, metrics, cleanup and hashes](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/evaluation-deadline-smoke-hard-candidate.json).

## Original Hard pair: both pass, mechanism not isolated

| Measure                                   | Control `62e9caf` | Candidate `45cedf4` |
| ----------------------------------------- | ----------------: | ------------------: |
| Actual Laith judgment                     |               1/1 |                 1/1 |
| Agent steps                               |                84 |                  15 |
| Agent seconds                             |         1,028.433 |             111.927 |
| Estimated agent inference cost            |         $3.532799 |           $0.346486 |
| JavaScript completions / flagged failures |           83 / 13 |              14 / 0 |
| Retained screenshots / capture errors     |           16 / 67 |              14 / 0 |

The control's original screenshot `016.jpg` shows **Solved / Bingo! You got it.** Its trace includes accessibility and CDP timeouts, nineteen cells calling reconnect, and a worker exit after an unawaited screenshot call. The retained evidence does not establish why the worker exited or why the renderer stalled. Even a later explicit `Runtime.terminateExecution` call timed out.

The successful final recovery cell reconnects, closes tabs, opens a rated page, sets local welcome flags, waits for the puzzle state, calls `window.stop()`, and makes mouse moves. These interventions are bundled; no individual intervention is established as the cause of recovery. The first-trending-puzzle identity remains unproven in both arms, and both official judgments remain unchanged.

Both original workflows are terminal, manifests and dependency locks match their frozen arms, and both owned browsers are confirmed stopped. Neither arm compacted or retried a provider request. The candidate has no recorded watchdog activation. The large observed time/cost difference is therefore **not an isolated speedup from the timeout fix**.

[Original control audit](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/evaluation-deadline-smoke-hard-control.json).

## Original Luna control: 90/100

The original `bub2-023` control completed with an actual Findings judgment of **90/100**, 114 steps, 869.833 agent seconds, and $0.248409 in estimated agent inference cost. Its 110 JavaScript completions include five flagged failures: a cookie-overlay obstruction, an undefined string read, two HTTP/2 navigation failures, and a generated-code syntax error. It retained 103 screenshots with seven capture errors, compacted once, and recorded no provider retry. The owned browser is confirmed stopped.

All ten weighted findings are present. The sole unmet item is the ten-point Oura inventory item: the deliverables claim limited functionality without a subscription, but the cited extraction exposes an FAQ question and membership pricing rather than evidence of that functionality. This is a source-to-claim failure, not a demonstrated execution-timeout failure. The official 90/100 remains intact; it does not certify every catalogue field.

The control delivered eight catalogue rows, a report, a JSON catalogue, a cost-model CSV, and a progress file. Its final response labels the whole catalogue verified despite the unsupported subscription field. Later full experiments must not add this task's product facts or hidden finding IDs to the agent prompt.

[Original control judgment, errors, screenshot registration, cleanup, and hashes](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/evaluation-deadline-smoke-luna-control.json). The original Luna candidate is still pending; no replacement or rejudge has been dispatched.
