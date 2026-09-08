# Regression recovery protocol

Frozen before dispatch on September 7, 2026. This is an experiment plan, not a performance claim.

## References and acceptance

Hard106: GPT-5.5 medium, Laith GPT-5.5, historical reference `58ed778b575f8a1c13479a0552ddadc38eea03bc` (91/106).
BU_Bench_v2: GPT-5.6-luna xhigh, Findings Luna xhigh, reference `b430a91891e23f5ffb9ca816e5cbe63e73d2a248` (62.00/100 over 60 assigned tasks).

The September 7 direct Laminar inventory of this project's same-model runs since August 15 found no stronger result on these task sets. The historical BrowserCode Luna reference is 41.17/100. This is a scoped reference inventory, not an exhaustive public SOTA ranking.

The practical noninferiority margin is **3 percentage points** on each benchmark's original metric. It is a chosen product tolerance, not measured judge noise. Pair by task ID; compute candidate minus reference. A confirmation passes only if the one-sided 95% task-bootstrap lower bound is greater than -3 points on **both** benchmarks. Use 20,000 resamples and seed 20260907. Overlapping marginal intervals and a nonsignificant difference do not establish noninferiority. If the interval is too wide, report inconclusive.

Historical scores remain descriptive. Rerun the frozen references with the candidate's controls. Retain all assigned tasks and every attempt; never splice retries into a cohort. Report provisioning/provider/runner/judge failures separately, including their effect on the assigned-task denominator. Missing real judgments make confirmation preliminary; do not silently call an infrastructure zero a real judgment.

Development iterations are exploratory. Inspect flips and failure traces before the next change. Freeze the selected candidate before a fresh confirmation pair; use that pair, not the highest development score, for the acceptance claim. These are previously inspected development benchmarks, not held-out generalization evidence.

## Fixed controls

- Platform `ddc48ee93ea863c26d78c45a09760e4951b48a3d`; SDK target pinned by full SHA.
- Hard: all 106 frozen IDs; 1700 seconds, 1000 turns, 800000 text characters; US proxy, 60-minute browser, 30-minute harness; Laith unchanged.
- Luna: all 60 frozen IDs; 3600 seconds, 1000 turns, 800000 characters; US proxy, 70-minute browser, 62-minute harness; Findings evidence and judge unchanged, including clipping.
- Both arms use 12 parallel task jobs per run. The previous 85/88/86 Hard runs used 20, so those historical comparisons remain unmatched on concurrency.
- No task retries or replacement tasks. Ordinary SDK inference recovery remains part of the treatment and is recorded.
- A one-task diagnostic smoke gates full cohorts. It must prove browser provisioning, actual inference/tool execution, evidence/judgment and cleanup. A smoke is never ranking evidence.
- Costs report agent inference separately from judge, browser and runner costs. Preserve errors and unknown accounting.

## First candidate

Bound model response setup/streaming at 300 seconds and summaries at 120 seconds, with public overrides and the original whole-run deadline. Failed partial tool calls never run. One inference retry shares the preexisting retry budget. Abort and late-output fault tests verify containment. Original context survives summary failure.

Clarify summary provenance: the summarization request is outside the original conversation and must not become a task constraint; original requests remain pinned and authoritative over generated checkpoint text. This is a mitigation, not a proof against every summarizer mistake.

Keep the task prompt, browser helpers, output schema, judge and evidence renderer unchanged in this candidate. Test answer-completeness changes separately.

Candidate runtime: `0baa51da98e93accf0c3471eff9a74f5d76e6819`. The two diagnostic smokes completed provisioning, inference, tool use, evidence, real judgments and cleanup. Their reduced 12-turn budgets forced early delivery; the failed Hard judgment and 12/100 Luna judgment remain diagnostic outcomes, not ranking evidence.

The full exploratory pairs were dispatched:

| Benchmark | Frozen reference                                                                         | Candidate                                                                                |
| --------- | ---------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| Hard106   | [34173484591](https://github.com/browser-use/new-eval-platform/actions/runs/34173484591) | [34173486020](https://github.com/browser-use/new-eval-platform/actions/runs/34173486020) |
| Luna60    | [34173710531](https://github.com/browser-use/new-eval-platform/actions/runs/34173710531) | [34173712013](https://github.com/browser-use/new-eval-platform/actions/runs/34173712013) |

Exact task hashes, IDs, dispatch inputs, evaluation IDs and local verification are retained in `evidence/iteration1-dispatch.json`. A real local SSE fault test additionally verifies that both stalled HTTP connections close after one additional inference retry.

## Complete Hard result

Both 106-task Hard cohorts finished on September 8 UTC. All 212 actual judgments are retained, including the reference's judge-labelled runtime failures. Those verdicts caused two failed workflow jobs; they are not missing judgments.

| Measure                        |           Reference `58ed778` | Candidate `0baa51d` |
| ------------------------------ | ----------------------------: | ------------------: |
| Passes / assigned tasks        |                        84/106 |              82/106 |
| Actual judgments               |                           106 |                 106 |
| Estimated agent inference cost |                       $123.71 |             $137.21 |
| SDK-recorded inference retries |              Not instrumented |                   0 |
| Successful compactions         | Not available in this runtime |                   3 |

Candidate minus reference: **−1.89 percentage points**, with 7 gains, 90 ties, and 9 losses. The paired task-bootstrap 95% interval is **[−9.43, +5.66] points**; its one-sided 95% lower bound is **−7.55**. This does **not** clear the −3-point noninferiority margin. The candidate also did not reach the historical 91/106 target within that margin. Luna is still running; neither benchmark has a fresh confirmation claim.

The historical 91/106 SDK itself scored 84/106 here. Consequently, the historical decline cannot all be assigned to newer SDK changes. Dates, live sites, and sampling remain possible contributors; this is not a measurement of pure judge noise.

The candidate's 24 zeros have judge-assigned classes: 14 site-blocked, 3 missing-required-fields, 2 wrong-record, 2 empty-result, and one each listing-vs-detail, synthetic-or-unsupported, and source-limited. Those are classifications, not independently proven root causes. For example, one access-loss trace reconstructed a form POST with invented verification state, while the reference used the page's form handler and obtained records. The extractor-validation and workspace-delivery experiments address separate observed mechanisms.

Two candidate SDK cleanup errors were recorded. No claim of complete browser-lifecycle verification follows from the passing workflow. Cost estimates exclude judge, browser, runner, and diagnostic runs.

[Per-task numerical evidence](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/iteration1-hard.json) · [Extraction experiment](./extraction-experiment.md) · [Workspace delivery experiment](./workspace-experiment.md)

## Compatibility and recovery

No Pi fork, browser engine change, history format migration, login/profile change, or legacy Python Browser Use modification. The Python bridge accepts the two new timeout options. Existing sessions and profiles remain compatible. Slow valid model responses can hit the new five-minute cap; callers may raise it, but the whole-run deadline still wins. A provider that ignores abort can continue spending remotely even though the SDK stops waiting; reported usage may undercount that work.

Rollback is the prior SDK SHA. Do not revert the already-fixed screenshot hook regression. No npm publication, merge, or account/billing changes are part of this experiment.
