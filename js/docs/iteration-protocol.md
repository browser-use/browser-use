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

Candidate minus reference: **−1.89 percentage points**, with 7 gains, 90 ties, and 9 losses. The paired task-bootstrap 95% interval is **[−9.43, +5.66] points**; its one-sided 95% lower bound is **−7.55**. This does **not** clear the −3-point noninferiority margin. The candidate also did not reach the historical 91/106 target within that margin. Neither benchmark has a fresh confirmation claim.

The historical 91/106 SDK itself scored 84/106 here. Consequently, the historical decline cannot all be assigned to newer SDK changes. Dates, live sites, and sampling remain possible contributors; this is not a measurement of pure judge noise.

The candidate's 24 zeros have judge-assigned classes: 14 site-blocked, 3 missing-required-fields, 2 wrong-record, 2 empty-result, and one each listing-vs-detail, synthetic-or-unsupported, and source-limited. Those are classifications, not independently proven root causes. For example, one access-loss trace reconstructed a form POST with invented verification state, while the reference used the page's form handler and obtained records. The extractor-validation and workspace-delivery experiments address separate observed mechanisms.

Two candidate SDK cleanup errors were recorded. No claim of complete browser-lifecycle verification follows from the passing workflow. Cost estimates exclude judge, browser, runner, and diagnostic runs.

[Per-task numerical evidence](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/iteration1-hard.json) · [Extraction experiment](./extraction-experiment.md) · [Workspace delivery experiment](./workspace-experiment.md)

## Complete Luna result

Both 60-task Luna cohorts finished on September 8 UTC. All 120 assigned outcomes are retained. Each arm has one provider-failure runner zero without an actual judgment; both workflows consequently concluded `failure`. The two missing judgments concern different tasks, leaving 58 shared actual judgments.

| Measure | Reference `b430a91` | Candidate `0baa51d` |
| --- | ---: | ---: |
| Mean score / 100, all 60 assigned tasks | 58.45 | 59.63 |
| Actual judgments | 59 | 59 |
| Recorded agent inference cost, all assigned tasks | $19.56921285 | $19.30596715 |
| Recorded agent inference cost, 58 shared judgments | $18.98211235 | $19.04315836 |
| Compactions / tasks that compacted | 22 / 21 | 19 / 19 |
| SDK-recorded inference retries | 0 | 1 |
| Tasks with SDK cleanup errors | 2 | 2 |

Candidate minus reference over all 60 assigned tasks is **+1.18 points**. Raw task differences are positive on 28, zero on 7, and negative on 25; these signs use no calibrated tie margin. The paired task-bootstrap 95% interval is **[−8.08, +10.22]**, with a one-sided 95% lower bound of **−6.55**. This does **not** clear the −3-point noninferiority margin. Over the 58 shared actual judgments, the delta is **+0.36**, interval **[−8.72, +9.05]**, and lower bound **−7.24**. Missing actual judgments also make confirmation preliminary.

The candidate point estimate is 2.37 points below the historical 62.00 score, within the chosen 3-point product tolerance. That point comparison does not establish statistical parity. The historical reference itself scored 58.45 in this cohort. Preserve both historical and current numbers rather than replacing the target with the weaker rerun.

The reference's provider failure was `bub2-051`; the candidate's was `bub2-046`. Later SDK commits extend the existing one-inference retry to those explicit temporary error messages, without changing these recorded outcomes. The candidate's one observed retry was on `bub2-055`: the 300-second response cap fired, the partial response's tool call never executed, and 76 later tool executions produced artifacts. That task still scored zero for unsupported verification claims. The trace proves recovery behavior, not that the interrupted response was stalled or that the retry improved its score. Its missing failed-response usage can undercount cost.

Large audited losses include misplaced deliverables (`bub2-021`), source observations lost from a summary before entering a durable dataset (`bub2-041`, `bub2-045`), and unsupported source/verification claims without any compaction (`bub2-052`). The judge globally zeroed seven reference tasks and four candidate tasks for suspected fabrication or related integrity failures. Those are retained judge classifications, not proof of malicious intent; no alternative scores replace them. Neither the workspace fix nor the [context archive experiment](./context-archive-experiment.md) can be credited with resolving every such failure.

Numeric evidence: [all task scores, controls, costs and comparisons](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/iteration1-luna.json). Recorded costs exclude judge, browser, runner and separate diagnostic runs. The task bootstrap does not independently measure judge sampling variance. Cleanup errors and incomplete judgment coverage remain explicit limitations. The separate extraction-only Hard cohort finished at 90/106 with all actual judgments; its Luna cohort remains ongoing. See the [extraction report](./extraction-experiment.md). Candidate selection and fresh confirmation remain outstanding.

## Compatibility and recovery

The latest recovery SDK `f41c5b7116ede9393696b67a166e38f91893163f` includes the workspace warning, narrow additional provider-error retry coverage, retrievable context archive, and corrected timeout guidance. Individual CDP/page-condition timeouts do not themselves reset the worker; whole-cell timeouts and cancellation do. A real-Chrome fault test verifies that an individual command can time out after its action happened once, while the Node binding and tab remain available without replay. All 82 Node tests, typecheck and docs build passed. The first full test invocation selected the Mac's broken Xcode Python stub; the full rerun with the project's Python runtime passed.

A bounded integration smoke on `bub2-060` completed at that exact SDK: [GitHub 34183301120](https://github.com/browser-use/new-eval-platform/actions/runs/34183301120), evaluation `3ed7037e-31b5-4153-9376-b16a226d3022`. It used 12 turns and 240 seconds with Luna xhigh and Findings Luna xhigh. Actual inference/browser execution produced eight verified PNG evidence images and a real **20/100** judgment. The final response explicitly described unfinished work; no task deliverable files were created. Recorded agent execution was 53.454 seconds, 11 steps and $0.01861405. Two screenshot warnings reported an unavailable active target: one after the initial clock/tab-list cell, the other after a failed attempt to open a workbook URL in a new tab. No SDK cleanup errors were recorded, and a separate Cloud API read confirmed that this smoke's browser was stopped. No compaction or inference retry occurred, so neither mechanism gains remote validation from this smoke. [Exact inputs and numeric evidence](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/recovery-sdk-smoke.json).

This smoke checks the current package and evaluation integration, not benchmark quality. It substitutes no outcomes into either full cohort.

## Selected candidate and fresh confirmation

On September 8 UTC, freeze SDK `f41c5b7116ede9393696b67a166e38f91893163f` for both fresh comparisons. Its generalized fixes have local fault-test coverage and the completed integration smoke above. Do not change the candidate during these cohorts. References remain `58ed778` for Hard and `b430a91` for Luna; historical targets and the prespecified −3-point margin remain unchanged.

Selection occurred while three tasks in the earlier extraction-only Luna cohort were still pending: `bub2-054`, `bub2-056`, and `bub2-060`. Giving all three hypothetical scores of 100 produces a best possible exploratory one-sided 95% lower bound of −5.82 points versus the recorded strongest-reference rerun, or −6.45 versus the prior candidate. Neither can clear the −3-point margin. These are monotone upper bounds from the unfinished cohort, not final scores, substituted outcomes, a causal claim, or fresh confirmation. The old run continues and its complete results will be retained.

The fresh plan contains all four arms, exact task IDs and hashes, full platform/SDK refs, model/reasoning, judge, budgets, and 12-job concurrency per arm. The final old tasks may overlap fresh dispatch; retain run times and this overlap. No task retries enter a cohort. Report all assigned outcomes, missing judgments, shared-judgment comparisons, costs, flips, and the same bootstrap uncertainty before claiming parity. [Frozen plan](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/confirmation1-plan.json).

## Compatibility and rollback

No Pi fork, browser engine change, history format migration, login/profile change, or legacy Python Browser Use modification. The Python bridge accepts the two new timeout options. Existing sessions and profiles remain compatible. Slow valid model responses can hit the new five-minute cap; callers may raise it, but the whole-run deadline still wins. A provider that ignores abort can continue spending remotely even though the SDK stops waiting; reported usage may undercount that work.

Rollback is the prior SDK SHA. Do not revert the already-fixed screenshot hook regression. No npm publication, merge, or account/billing changes are part of this experiment.
