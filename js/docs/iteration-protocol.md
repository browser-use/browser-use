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

| Measure                                            | Reference `b430a91` | Candidate `0baa51d` |
| -------------------------------------------------- | ------------------: | ------------------: |
| Mean score / 100, all 60 assigned tasks            |               58.45 |               59.63 |
| Actual judgments                                   |                  59 |                  59 |
| Recorded agent inference cost, all assigned tasks  |        $19.56921285 |        $19.30596715 |
| Recorded agent inference cost, 58 shared judgments |        $18.98211235 |        $19.04315836 |
| Compactions / tasks that compacted                 |             22 / 21 |             19 / 19 |
| SDK-recorded inference retries                     |                   0 |                   1 |
| Tasks with SDK cleanup errors                      |                   2 |                   2 |

Candidate minus reference over all 60 assigned tasks is **+1.18 points**. Raw task differences are positive on 28, zero on 7, and negative on 25; these signs use no calibrated tie margin. The paired task-bootstrap 95% interval is **[−8.08, +10.22]**, with a one-sided 95% lower bound of **−6.55**. This does **not** clear the −3-point noninferiority margin. Over the 58 shared actual judgments, the delta is **+0.36**, interval **[−8.72, +9.05]**, and lower bound **−7.24**. Missing actual judgments also make confirmation preliminary.

The candidate point estimate is 2.37 points below the historical 62.00 score, within the chosen 3-point product tolerance. That point comparison does not establish statistical parity. The historical reference itself scored 58.45 in this cohort. Preserve both historical and current numbers rather than replacing the target with the weaker rerun.

The reference's provider failure was `bub2-051`; the candidate's was `bub2-046`. Later SDK commits extend the existing one-inference retry to those explicit temporary error messages, without changing these recorded outcomes. The candidate's one observed retry was on `bub2-055`: the 300-second response cap fired, the partial response's tool call never executed, and 76 later tool executions produced artifacts. That task still scored zero for unsupported verification claims. The trace proves recovery behavior, not that the interrupted response was stalled or that the retry improved its score. Its missing failed-response usage can undercount cost.

Large audited losses include misplaced deliverables (`bub2-021`), source observations lost from a summary before entering a durable dataset (`bub2-041`, `bub2-045`), and unsupported source/verification claims without any compaction (`bub2-052`). The judge globally zeroed seven reference tasks and four candidate tasks for suspected fabrication or related integrity failures. Those are retained judge classifications, not proof of malicious intent; no alternative scores replace them. Neither the workspace fix nor the [context archive experiment](./context-archive-experiment.md) can be credited with resolving every such failure.

Numeric evidence: [all task scores, controls, costs and comparisons](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/iteration1-luna.json). Recorded costs exclude judge, browser, runner and separate diagnostic runs. The task bootstrap does not independently measure judge sampling variance. Cleanup errors and incomplete judgment coverage remain explicit limitations. The separate extraction-only cohorts finished at 90/106 Hard and 59.22/100 Luna, with all 166 actual judgments. See the [extraction report](./extraction-experiment.md). The selected candidate and fresh confirmation are recorded below.

## Compatibility and recovery

The latest recovery SDK `f41c5b7116ede9393696b67a166e38f91893163f` includes the workspace warning, narrow additional provider-error retry coverage, retrievable context archive, and corrected timeout guidance. Individual CDP/page-condition timeouts do not themselves reset the worker; whole-cell timeouts and cancellation do. A real-Chrome fault test verifies that an individual command can time out after its action happened once, while the Node binding and tab remain available without replay. All 82 Node tests, typecheck and docs build passed. The first full test invocation selected the Mac's broken Xcode Python stub; the full rerun with the project's Python runtime passed.

A bounded integration smoke on `bub2-060` completed at that exact SDK: [GitHub 34183301120](https://github.com/browser-use/new-eval-platform/actions/runs/34183301120), evaluation `3ed7037e-31b5-4153-9376-b16a226d3022`. It used 12 turns and 240 seconds with Luna xhigh and Findings Luna xhigh. Actual inference/browser execution produced eight verified PNG evidence images and a real **20/100** judgment. The final response explicitly described unfinished work; no task deliverable files were created. Recorded agent execution was 53.454 seconds, 11 steps and $0.01861405. Two screenshot warnings reported an unavailable active target: one after the initial clock/tab-list cell, the other after a failed attempt to open a workbook URL in a new tab. No SDK cleanup errors were recorded, and a separate Cloud API read confirmed that this smoke's browser was stopped. No compaction or inference retry occurred, so neither mechanism gains remote validation from this smoke. [Exact inputs and numeric evidence](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/recovery-sdk-smoke.json).

This smoke checks the current package and evaluation integration, not benchmark quality. It substitutes no outcomes into either full cohort.

## Selected candidate and fresh confirmation

On September 8 UTC, freeze SDK `f41c5b7116ede9393696b67a166e38f91893163f` for both fresh comparisons. Its generalized fixes have local fault-test coverage and the completed integration smoke above. Do not change the candidate during these cohorts. References remain `58ed778` for Hard and `b430a91` for Luna; historical targets and the prespecified −3-point margin remain unchanged.

Selection occurred while three tasks in the earlier extraction-only Luna cohort were still pending: `bub2-054`, `bub2-056`, and `bub2-060`. Giving all three hypothetical scores of 100 produces a best possible exploratory one-sided 95% lower bound of −5.82 points versus the recorded strongest-reference rerun, or −6.45 versus the prior candidate. Neither can clear the −3-point margin. These are monotone upper bounds from the unfinished cohort, not final scores, substituted outcomes, a causal claim, or fresh confirmation. The old run continues and its complete results will be retained.

The fresh plan contains all four arms, exact task IDs and hashes, full platform/SDK refs, model/reasoning, judge, budgets, and 12-job concurrency per arm. The final old tasks may overlap fresh dispatch; retain run times and this overlap. No task retries enter a cohort. Report all assigned outcomes, missing judgments, shared-judgment comparisons, costs, flips, and the same bootstrap uncertainty before claiming parity. [Frozen plan](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/confirmation1-plan.json).

All four arms were dispatched once at 04:02 UTC on September 8, after the plan was pushed and the exact workflow SHA and latest smoke were rechecked. The earlier extraction-only Luna workflow subsequently completed successfully; its outcomes were not substituted into confirmation.

| Benchmark | Reference execution                                                                      | Candidate execution                                                                      |
| --------- | ---------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| Hard106   | [34185574950](https://github.com/browser-use/new-eval-platform/actions/runs/34185574950) | [34185576664](https://github.com/browser-use/new-eval-platform/actions/runs/34185576664) |
| Luna60    | [34185578184](https://github.com/browser-use/new-eval-platform/actions/runs/34185578184) | [34185579665](https://github.com/browser-use/new-eval-platform/actions/runs/34185579665) |

Both pairs are complete. Hard passes the frozen criterion; Luna fails it and has three missing actual judgments. The selected runtime remained unchanged throughout execution.

An [interim trace audit](./confirmation-trace-audit.md) separates observed evidence-fidelity failures from delivery, compaction, and judge interpretation. It also records a subsequently fixed generic provider-error recovery gap. That later patch does not change the candidate or replace any outcomes in these four confirmation runs.

### Complete fresh Hard comparison

Both Hard workflows finished on September 8 UTC with all 212 actual judgments. The reference workflow concluded `failure` because one real judge verdict was classified `runtime-failure`; its rubric and checked evidence are present. The candidate workflow succeeded.

| Measure                        | Reference `58ed778` | Candidate `f41c5b7` |
| ------------------------------ | ------------------: | ------------------: |
| Passes / assigned tasks        |              79/106 |              89/106 |
| Actual judgments               |                 106 |                 106 |
| Recorded agent inference cost  |         $117.866279 |         $131.890341 |
| Median steps                   |                  30 |                  29 |
| Median agent duration, seconds |            231.3265 |            219.4085 |
| Tasks with SDK cleanup errors  |                   1 |                   0 |

Candidate minus reference is **+9.43 percentage points**, with 14 gains, 88 ties, and 4 losses. The paired 20,000-resample 95% interval is **[+1.89, +16.98]**, with a one-sided 95% lower bound of **+2.83**. This fresh Hard comparison clears the prespecified −3-point noninferiority margin. The candidate is two tasks below the historical 91/106 target, also within the 3-point tolerance. It does not set a new historical peak or establish public SOTA. Luna must still satisfy its separate conditions before claiming the two-benchmark goal.

The candidate incurred more recorded agent inference cost in this pair. The duration medians are descriptive; this is not an isolated speed or token-efficiency experiment. Costs exclude judge, browser, runner, and unreported usage. There were no successful candidate compactions or recorded SDK inference retries in this Hard cohort, so this result does not demonstrate gains from either mechanism.

An initial local reporting rule incorrectly treated every `runner-no-result` label as a missing judgment. Candidate `6dpbhs` has that label, but its downloaded artifact contains a real 17.77-second Laith judgment, populated rubric, checked task evidence, and a final response explaining the unresolved historical puzzle. The classifier now distinguishes synthetic runner zeros by their absent rubric rather than the failure label alone. Its official zero never changed. All 106 paired Hard judgments are included. The three provider-failure Luna zeros currently lack actual rubrics and remain missing judgments.

[Complete per-task evidence, controls, costs and uncertainty](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/confirmation1-hard.json). Both SDKs were frozen before dispatch. The difference bundles runtime, prompt, and dependency changes; it does not isolate their individual causal effects. The historical reference itself has now scored 91, 84, and 79 in distinct live cohorts, so historical movement cannot be attributed solely to new SDK code.

### Complete fresh Luna comparison

Both Luna workflows finished on September 8 UTC. **All 120 assigned outcomes are retained**, including three provider-failure zeros without actual judgments. Both workflow conclusions are `failure`; those execution failures are distinct from the many completed tasks with low judge scores.

| Measure                                         | Reference `b430a91` | Candidate `f41c5b7` |
| ----------------------------------------------- | ------------------: | ------------------: |
| Continuous mean / 100, all 60 assigned          |             58.7167 |             57.1667 |
| Actual judgments                                |                  58 |                  59 |
| Recorded agent inference cost, all assigned     |        $18.88851468 |        $21.07582767 |
| Recorded agent cost, 57 shared actual judgments |        $18.51239706 |        $20.42569297 |
| Compactions / tasks that compacted              |             19 / 17 |             26 / 24 |
| SDK-recorded inference retries                  |                   0 |                   0 |
| SDK cleanup errors                              |                   1 |                   2 |
| Median steps                                    |                 124 |                 119 |
| Median agent duration, seconds                  |           1024.7935 |             974.356 |

Candidate minus reference is **−1.55 points** across all 60 assigned tasks. The paired 95% interval is **[−10.60, +7.53]**; its one-sided 95% lower bound is **−9.13**, below the frozen −3-point margin. Raw task differences are positive on 27, equal on 7 and negative on 26; no calibrated tie margin is implied. Over the **57 shared actual judgments**, the delta is **−1.74**, interval **[−10.70, +7.12]**, and lower bound **−9.25**. Neither view establishes noninferiority.

The candidate is **4.83 points below** the historical 62.00 target, outside the frozen 3-point product tolerance. Missing real judgments also make confirmation ineligible. **The two-benchmark goal is not achieved.** The historical target, judge, margin, assigned denominator and recorded scores stay unchanged. The bootstrap uses the task as its unit and does not independently measure provider or judge sampling variation.

Missing judgments: reference `bub2-002` exceeded the provider's image-patch limit; reference `bub2-041` and candidate `bub2-038` ended on the generic provider error. Later image/recovery patches are separate and replace none of these zeros. Candidate `bub2-040` has an infrastructure flag but a real 42/100 rubric judgment with checked evidence; candidate `bub2-002` has both integrity and infrastructure flags with a real rubric. Flags alone do not turn recorded judgments into missing data.

The judge applied its global integrity penalty to **11 candidate tasks versus four reference tasks**. Those are judge classifications, not proof of intent. Audited failures include loss of reason strings through boolean expressions, unknown/negative states converted into positive claims, altered excerpts and timestamps, incorrect eligibility, and scope choices made before compaction. The [trace audit](./confirmation-trace-audit.md) distinguishes independently observed defects from clipped evidence and judge interpretation. Both arms have imperfect artifacts; file delivery and schema validity did not establish factual correctness.

A read-only Cloud API audit confirmed **334/334 owned browsers from completed confirmation tasks plus the image and journal diagnostics stopped**. This is separate from the recorded SDK cleanup errors. Costs exclude judge, browser, runner, separate diagnostics and unreported usage. The candidate cost more in this pair; duration medians do not establish a causal speed advantage.

[Complete Luna evidence](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/confirmation1-luna.json) · [Combined frozen confirmation](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/confirmation1.json). The next prepared runtime and its one-task diagnostic are documented in the [semantic validation experiment](./semantic-validation-experiment.md); no new full-cohort score is attributed to them.

## Second frozen confirmation

After retaining all 332 confirmation1 outcomes and the completed semantic diagnostic, freeze runtime **`65a16cb6e43a31e67d59a7ed841858e70f05a5ba`** for a second full matched confirmation. References remain `58ed778` for Hard and `b430a91` for Luna. Historical targets, the 3-point margin, the bootstrap, all 106/60 task IDs, model/reasoning, judge, renderer, budgets and 12-job concurrency per arm remain unchanged. All prior bu-pi iteration workflows are terminal at selection.

The candidate bundles the later image-preview guard, exact generic-provider recovery, journal discovery, owned-tab cleanup verification and semantic-test guidance. The [completed diagnostic](./semantic-validation-experiment.md#completed-diagnostic) establishes integration and cleanup, but does not establish semantic-test adoption or improved quality. Its workbook still lost screening fields despite preserving them in canonical data. Keep that failure and its 60/100 score separate from both full cohorts.

Four arms are frozen before dispatch; no newer SDK commit may enter them. Every assigned outcome is retained, including failures and missing judgments. Completion requires actual-judgment coverage and the original acceptance on both benchmarks. These remain development benchmarks, not held-out SOTA evidence. No new full result exists at selection. [Exact plan](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/confirmation2-plan.json).

The plan was pushed at `3b3536a` before all four arms were dispatched once. The workflow ref still resolved to `3fbf236`; the execution platform remains `ddc48ee`. All four prepare jobs succeeded, created all 332 datapoints and started 12 task jobs per arm. All four workflows are now terminal; both full comparisons are retained below.

| Benchmark | Reference execution                                                                      | Candidate execution                                                                      |
| --------- | ---------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| Hard106   | [34197086884](https://github.com/browser-use/new-eval-platform/actions/runs/34197086884) | [34197089074](https://github.com/browser-use/new-eval-platform/actions/runs/34197089074) |
| Luna60    | [34197091644](https://github.com/browser-use/new-eval-platform/actions/runs/34197091644) | [34197094678](https://github.com/browser-use/new-eval-platform/actions/runs/34197094678) |

[Recorded dispatch inputs and Laminar evaluation IDs](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/confirmation2-dispatch.json).

The [ongoing trace audit](./confirmation2-trace-audit.md) separates early access losses from source-state and arithmetic errors in delivered artifacts. It is a selected diagnostic view, not an estimate of aggregate quality.

### Complete second Hard comparison

Both original Hard workflows completed on September 8 UTC with **all 212 actual judgments**. Candidate `65a16cb` scored **81/106** against reference `58ed778` at **85/106**. The candidate workflow succeeded; the reference concluded `failure` with a real runtime-failure judge verdict. Execution conclusion is separate from actual-judgment coverage.

| Measure                        | Reference `58ed778` | Candidate `65a16cb` |
| ------------------------------ | ------------------: | ------------------: |
| Passes / assigned              |              85/106 |              81/106 |
| Actual judgments               |                 106 |                 106 |
| Recorded agent inference cost  |         $123.165385 |         $144.008744 |
| Median steps                   |                  33 |                  32 |
| Median agent duration, seconds |            281.9255 |             249.115 |
| Tasks with SDK cleanup errors  |                   2 |                   0 |

The paired candidate-minus-reference difference is **−3.77 percentage points**: five gains, 92 ties and nine losses. The frozen 20,000-resample bootstrap gives a 95% interval of **[−10.38, +2.83]**, with one-sided 95% lower bound **−9.43**. This fails the original −3-point noninferiority criterion. The candidate also falls seven tasks below the required historical-tolerance floor of 88/106. The interval includes zero, so this single cohort does not establish a statistically isolated harmful code effect either. **Parity is not established; the two-benchmark goal remains unmet.**

The candidate has 14 `site-blocked` judge labels versus seven in the reference; six of the nine candidate losses carry that label. These are classifications, not a verified common cause. The [trace audit](./confirmation2-trace-audit.md) separately establishes selected access-state differences, stale product identity and variant acquisition errors. Requested Cloud settings and tab lifecycle were checked earlier, but actual IP/reputation/browser versions and live-site state were not matched. The change bundle and external variation prevent attributing the full drop to any single prompt or runtime patch.

All task IDs, manifests, model/reasoning, judges, budgets, assigned zeros and attempt numbers are retained. Each dependency lock matches its pinned SDK. Agent costs exclude judge, browser, runner and unreported usage. Median durations are descriptive. Later accessibility-state and label-click fixes are separate and replace no outcomes. The completed Luna pair retains a missing actual judgment from the [reference screenshot-ownership failure](./evidence-ownership.md). The agent deleted the evaluator screenshot directory while cleaning deliverables; its official zero remains.

[Complete per-task Hard evidence and frozen uncertainty calculation](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/confirmation2-hard.json).

### Complete second Luna comparison

Both original Luna workflows completed on September 8 UTC. Candidate `65a16cb` scored **58.27/100** versus reference `b430a91` at **57.73/100**. Each retains all 60 assigned outcomes. The candidate has 60 actual judgments; the reference has 59. Its screenshot-ownership failure remains an official zero, without restoration or rejudgment. GitHub reports candidate success and reference failure.

| Measure                       | Reference `b430a91` | Candidate `65a16cb` |
| ----------------------------- | ------------------: | ------------------: |
| Continuous mean / 100         |               57.73 |               58.27 |
| Assigned / actual judgments   |             60 / 59 |             60 / 60 |
| Recorded agent inference cost |        $19.93090848 |        $21.17715822 |

The assigned candidate-minus-reference delta is **+0.53 points**, with frozen 20,000-resample 95% interval **[−8.80, +9.88]** and one-sided lower bound **−7.38**. It fails the −3-point noninferiority margin. Across the 59 shared actual judgments, the paired delta is **−0.03 points**, interval **[−9.39, +9.49]**, and lower bound **−7.86**. This diagnostic subset does not replace the assigned denominator.

Missing judgment coverage independently makes confirmation ineligible. The candidate also misses the historical-tolerance floor of **59/100**. **Neither benchmark establishes parity in this confirmation.** All task IDs, manifests, model/reasoning, judges, budgets, attempt numbers, and pinned dependency locks were validated against the frozen plan. Costs are reported agent inference estimates, excluding judge, browser, runner and unreported usage. These results do not establish a token-efficiency advantage or isolate any individual runtime change.

[Complete per-task Luna evidence and uncertainty](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/confirmation2-luna.json).

## Third frozen comparison

After both original [observation diagnostics](./observation-evidence-experiment.md) completed and their artifacts were audited, freeze candidate **`29e2b5e49f6bcd8d9f1ecf1b737d143488abfb2b`** for the next full comparison. The diagnostic scores, Hard 0/1 and Luna 73/100 on one task, establish no ranking. Their manifests, actual judgments, evidence paths and Cloud cleanup were checked before selection.

The reference adapter refs are **`769ea148382cb9094662188a593b0410f6e9f0d5`** for Hard and **`c3f7fac2d8a46a3801e06d89a3c3c9b1343db79e`** for Luna. Their complete runtime source trees, manifests and dependency locks remain byte-identical to historical `58ed778` and `b430a91`. Only the previously tested [evaluator screenshot ownership correction](./evidence-ownership.md) enters those adapters. Candidate evidence preservation is part of the treatment; a score change cannot be assigned solely to model reasoning.

Four arms retain the original 106/60 task IDs, models, reasoning, judges, budgets, one attempt and 12 concurrent task jobs per arm. The historical floors remain **88/106 Hard** and **59/100 Luna**. Each paired one-sided 95% bootstrap lower bound must exceed **−3 points**, using 20,000 resamples and seed 20260907, with all actual judgments present on both benchmarks. No prior outcome is replaced. These are development benchmarks.

The plan is frozen before dispatch. [Exact four-arm inputs, task hashes, audit hashes and acceptance](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/confirmation3-plan.json).

All four arms were dispatched once at 10:22 UTC on September 8, after plan commit `63bd10e` was pushed and both original diagnostic workflows were rechecked as terminal. All four prepare jobs succeeded. Results remain pending; delayed Laminar rows are not replacement-task authorization.

| Benchmark | Reference execution                                                                      | Candidate execution                                                                      |
| --------- | ---------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| Hard106   | [34215091305](https://github.com/browser-use/new-eval-platform/actions/runs/34215091305) | [34215093599](https://github.com/browser-use/new-eval-platform/actions/runs/34215093599) |
| Luna60    | [34215096477](https://github.com/browser-use/new-eval-platform/actions/runs/34215096477) | [34215099251](https://github.com/browser-use/new-eval-platform/actions/runs/34215099251) |

[Original dispatch inputs and Laminar evaluation IDs](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/confirmation3-dispatch.json).

The local report was fault-tested against the historical browser-provisioning failure shape: such a failure has no SDK model/lock metadata or usage. It now retains the assigned zero and unknown metrics instead of crashing, while rejecting a completed row with missing SDK metadata or a reported wrong model. Four offline cases pass; task scores, runtime, judges, bootstrap and acceptance are unchanged. Unreported capture counts remain unknown rather than zero. [Accounting regression evidence](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/confirmation3-report-verification.json).

The [ongoing trace audit](./confirmation3-trace-audit.md) separates model-written extraction errors from SDK transport faults in selected completed pairs. These findings do not change the running candidate or replace outcomes.

### Historical Hard floor is already unreachable

At the retained September 8 snapshot, the candidate has **76 passes from 95 actual judgments**, with **11 of 106 tasks still pending**. Even if every pending task passes, its maximum is **87/106**, below the frozen historical floor of **88/106**. The two-benchmark goal therefore cannot be achieved by this candidate in this comparison. This is an arithmetic bound, not a final score or evidence of a statistically isolated harmful code effect.

All four original arms continue unchanged. Complete the cohorts before calculating the frozen paired intervals or selecting the next intervention. [Snapshot, all assigned task IDs and upper-bound calculation](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/confirmation3-hard-floor-bound.json).

### Reference execution and evidence failures

The Hard reference has an additional, independent confirmation gap. Task `swebnv` ends after six steps with the provider response “Sorry, something went wrong.” The runner records a zero with an empty rubric, no judge model and zero judge duration. It is a synthetic assigned outcome, not an actual judgment. The original zero stays; the frozen full-coverage requirement is therefore unmet even if every remaining task receives a judgment.

Reference task `aoim45` is different: its agent result and actual judgment exist in Laminar, but the GitHub **Upload task evidence** step fails with “Upload progress stalled.” The original run's complete artifact inventory has no `aoim45-1` artifact at inspection. Keep its actual score and judgment; report the missing downloadable evidence separately. Neither failure authorizes a replacement task or a changed judge.

[Original provider-error artifact hashes, judgment coverage and upload-failure classification](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/confirmation3-reference-failures.json).

### Candidate Hard cohort complete

The original candidate workflow completed successfully with **84/106 passes and 106 actual judgments**, at runtime `29e2b5e`. Recorded agent inference cost is **$128.653298**, excluding judge, browser, runner and unreported usage. Its final task, `6dpbhs`, receives a real failure judgment; no outcome was replaced. The historical floor of 88/106 is missed by four tasks.

At this snapshot the reference still has one task pending. Do not infer a paired final score or interval yet. Its missing actual judgment on `swebnv` remains an independent eligibility failure. Both Luna arms continue. [Complete candidate task-level results and validated pins](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/confirmation3-hard-candidate-terminal.json).

## Compatibility and rollback

No Pi fork, browser engine change, history format migration, login/profile change, or legacy Python Browser Use modification. The Python bridge accepts the two new timeout options. Existing sessions and profiles remain compatible. Slow valid model responses can hit the new five-minute cap; callers may raise it, but the whole-run deadline still wins. A provider that ignores abort can continue spending remotely even though the SDK stops waiting; reported usage may undercount that work.

Rollback is the prior SDK SHA. Do not revert the already-fixed screenshot hook regression. No npm publication, merge, or account/billing changes are part of this experiment.
