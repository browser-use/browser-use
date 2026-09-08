# Benchmark evidence

The README shows the latest completed concurrent bu-pi pair on BU_Bench_v2, using Luna xhigh. Both arms retain all 60 assigned tasks and actual judgments. Historical cross-harness results are kept separately below.

![Concurrent bu-pi Luna xhigh scores, agent costs, and total reported tokens](/benchmarks/luna.svg)

## Historical context

| Cohort                                | Date (UTC)        | Mean score / 100 | Assigned / judged | Recorded agent cost |
| ------------------------------------- | ----------------- | ---------------: | ----------------: | ------------------: |
| bu-pi `b430a91`                       | September 7, 2026 |            62.00 |           60 / 59 |              $17.86 |
| bu-pi latest full candidate `29e2b5e` | September 8, 2026 |            61.75 |           60 / 60 |              $20.25 |
| BrowserCode historical reference      | August 20, 2026   |            41.17 |           60 / 60 |              $21.49 |

All three retain `bub2-001` through `bub2-060`. Scores are continuous rubric scores, averaged over all 60 assigned tasks. The historical bu-pi cohort's browser-provisioning failure stays in that denominator at zero. BrowserCode had two additional empty duplicate placeholders; neither was a scored task. Those placeholders are excluded.

## What the comparison establishes

The two historical cohorts recorded a 20.83-point score difference. They share task IDs and the Luna xhigh model setting. The runs used different harnesses, runners, dates, and live website state. There was no randomized concurrent control. The comparison does not isolate an architectural effect or establish a general ranking against Browser Use or Browser Harness.

Recorded agent estimates total $17.86048933 and $21.48721706. They exclude judge, browser, runner, and separate diagnostic runs. They are not invoices or independently normalized prices. We do not use their ratio to advertise a percentage cost reduction.

The historical bu-pi cohort is pinned to `b430a91891e23f5ffb9ca816e5cbe63e73d2a248`; the latest full candidate is pinned to `29e2b5e49f6bcd8d9f1ecf1b737d143488abfb2b`. They are separate cohorts. Current HEAD contains subsequent runtime changes and is not this evaluated candidate; the optional eval resizing setting was not enabled in these cohorts. The candidate recorded $20.25096091 in agent inference cost across 60 metered tasks.

## Latest concurrent comparison

Candidate `29e2b5e` scores **61.75/100** versus **54.22/100** for reference adapter `c3f7fac` (historical runtime `b430a91`). Both retain all 60 assigned tasks and actual judgments. The paired improvement is **+7.53 points**, 95% bootstrap interval **[+0.10, +15.42]**, one-sided lower bound **+1.17**. It clears the frozen −3-point margin and the historical floor of 59/100. These are previously inspected development tasks, not held-out SOTA evidence.

| Measure                       |   Reference |   Candidate |
| ----------------------------- | ----------: | ----------: |
| Recorded agent inference cost |      $19.28 |      $20.25 |
| Median agent seconds          |     978.589 |   1,025.671 |
| Uncached input tokens         |   1,775,402 |   2,109,019 |
| Output tokens                 |   2,621,643 |   2,837,733 |
| Cached input tokens           | 469,280,110 | 499,631,938 |
| Cache-write tokens            |  25,571,606 |  25,724,955 |
| Total tokens                  | 499,248,761 | 530,303,645 |

The candidate uses **6.22% more reported tokens** and **5.04% more estimated agent cost** in this pair. There is no measured efficiency win here. Tokens are cumulative across model calls, including compaction and repeated cached context. Costs exclude judge, browser, and runner charges.

Reference `bub2-035` has truncated Laminar executor JSON. Its original score and judgment were recovered from hash-verified original workflow artifacts, with task/run identity and score equality checked. No task was rerun or rejudged. [Recovery evidence](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/confirmation3-laminar-payload-recovery.json).

The same candidate scores **84/106 versus 84/106 on Hard106**, with 106 versus 105 actual judgments. It fails the frozen Hard margin, historical floor, and full-coverage requirement. **The two-benchmark goal remains unmet.** [Full paired report](./iteration-protocol.md#complete-third-luna-comparison).

## Token efficiency is still an open question

A direct Laminar query on September 8 rechecked `executor_output.result.metrics` for the bu-pi cohort. The agent reported usage for 59 tasks; the provisioning failure has no agent metrics. Missing metrics remain null in the retained data.

| Agent-reported token category | Total across 59 metered tasks |
| ----------------------------- | ----------------------------: |
| Uncached input                |                     1,408,125 |
| Output                        |                     2,703,190 |
| Cache read                    |                   480,373,979 |
| Cache write                   |                    18,910,227 |
| Total                         |                   503,395,521 |

These are cumulative tokens over model calls, including compaction. Repeated cached context is counted repeatedly; this is not the size of one prompt or unique information processed. We use the SDK's agent accounting because trace-level totals have a different scope. An equivalent validated BrowserCode token breakdown is not retained here, so this evidence does **not** support a token-efficiency claim. A comparison needs compatible input/cache/output definitions, pricing, task IDs, budgets, and treatment of missing usage.

## History, not just the best run

| bu-pi cohort                   | Hard106 · GPT-5.5 medium | BU_Bench_v2 · Luna xhigh |
| ------------------------------ | -----------------------: | -----------------------: |
| Historical Hard peak `58ed778` |                   91/106 |   Not run in this cohort |
| `413ed34`                      |                   86/106 |                34.12/100 |
| Reliability `a7fe3d4`          |                   88/106 |                55.72/100 |
| Explicit vision `b430a91`      |                   85/106 |                62.00/100 |

The Hard peak has not been a stable result across later changes. See [reliability results](./reliability-results.md), [vision results](./vision-results.md), and the [extraction experiment](./extraction-experiment.md) for failures and subsequent tests. Repeated development on these tasks also limits claims about unseen tasks.

The subsequent concurrent reference/candidate comparisons at candidate `0baa51d` finished at **84 versus 82/106 on Hard**, and **58.45 versus 59.63/100 on Luna**. Neither cleared the prespecified statistical noninferiority margin. Luna retains one provider-failure zero without an actual judgment in each arm. These later runs are retained separately from the current README chart; see the [complete paired results and uncertainty](./iteration-protocol.md).

The extraction-only candidate `4a09ee3` subsequently scored **90/106 on Hard** and **59.22/100 on Luna**, with all 166 actual judgments. Recorded agent inference costs were $120.98 and $19.99 respectively. Luna's paired lower bounds did not clear the prespecified margin. This is a nonconcurrent development comparison, not fresh confirmation or a result for the current HEAD. The [extraction report](./extraction-experiment.md) retains uncertainty, workflow closure, delivery failures, and factual limitations found even in passing traces.

The subsequent **fresh Hard confirmation** at `f41c5b7` finished at **89/106 versus 79/106** for the concurrently dispatched historical-reference SDK, with all 212 actual judgments. The paired delta is +9.43 points, 95% interval [+1.89, +16.98], and one-sided lower bound +2.83. It clears the frozen noninferiority margin and sits two tasks below the historical 91. Agent inference cost was $131.89 candidate versus $117.87 reference. The fresh Luna pair finished at **57.17/100 candidate versus 58.72/100 reference**, with 59 and 58 actual judgments respectively. It fails both the frozen statistical margin and the historical-point tolerance; the two-benchmark goal remains unmet. This is not a result for later runtime commits or a claim of token efficiency. [Full confirmation report](./iteration-protocol.md#complete-fresh-hard-comparison).

The **second fresh Hard confirmation** at `65a16cb` scored **81/106 versus 85/106**, with all 212 actual judgments. The delta is −3.77 points, 95% interval [−10.38, +2.83], one-sided lower bound −9.43. It fails both the frozen noninferiority margin and the historical-point floor of 88/106. Recorded agent cost is $144.008744 candidate versus $123.165385 reference. Its Luna pair completed at **58.27/100 candidate versus 57.73/100 reference**, with 60 versus 59 actual judgments. The assigned paired delta is +0.53 points, 95% interval [−8.80, +9.88], one-sided lower bound −7.38. Missing reference judgment coverage makes confirmation ineligible; the candidate also misses the historical floor of 59/100. Agent costs were $21.17715822 versus $19.93090848. Later accessibility fixes remain separate. [Second confirmation report](./iteration-protocol.md#complete-second-hard-comparison).

## Sources and reproduction

- [bu-pi Luna evaluation](https://www.lmnr.ai/project/b657f811-13a7-4dae-a67a-91445a567f24/evaluations/bf521f51-7920-4e55-8833-f6413b91a73d) · [GitHub execution](https://github.com/browser-use/new-eval-platform/actions/runs/34086771731).
- [BrowserCode Luna evaluation](https://www.lmnr.ai/project/502a9d52-2725-4410-9a58-e469aa10fd12/evaluations/d7fbccfc-03ad-428e-85c2-f280f88cc642).
- `evidence/vision.json`, `evidence/reliability.json`, and `evidence/confirmation3-luna.json` retain the per-task scores and costs. The latest candidate evaluation is `4ba9d7bc-998b-430c-a870-6d8e289a037c`, [GitHub execution](https://github.com/browser-use/new-eval-platform/actions/runs/34215099251). `evidence/readme-usage.json` retains the new numeric usage query, without task prompts or traces.
- The chart uses only the fixed concurrent reference/candidate pair in `evidence/confirmation3-luna.json`. It does not search for the highest score. Regenerate it from the repository root with `node scripts/benchmark-chart.mjs`. The script checks task identity, judgment coverage, matched inputs, score bounds, score/cost totals, and token reconciliation before writing the SVG.

The exact bu-pi platform SHA, judge, browser, and budget controls are retained in `evidence/vision.json`. The [full report](./vision-results.md) covers evidence-preview clipping, screenshot observation errors, and cleanup diagnostics. A recorded judgment does not mean that every artifact byte was visible to the judge.
