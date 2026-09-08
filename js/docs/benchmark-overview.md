# Benchmark evidence

The README compares two historical Luna xhigh cohorts on BU_Bench_v2. This page keeps the comparison's scope and accounting next to its chart.

![Historical Luna xhigh scores and recorded agent costs](/benchmarks/luna.svg)

| Cohort                           | Date (UTC)        | Mean score / 100 | Assigned / judged | Recorded agent cost |
| -------------------------------- | ----------------- | ---------------: | ----------------: | ------------------: |
| bu-pi `b430a91`                  | September 7, 2026 |            62.00 |           60 / 59 |              $17.86 |
| BrowserCode historical reference | August 20, 2026   |            41.17 |           60 / 60 |              $21.49 |

Both retain `bub2-001` through `bub2-060`. Scores are continuous rubric scores, averaged over all 60 assigned tasks. bu-pi's browser-provisioning failure stays in that denominator at zero. BrowserCode had two additional empty duplicate placeholders; neither was a scored task. Those placeholders are excluded.

## What the comparison establishes

These particular cohorts recorded a 20.83-point score difference. They share task IDs and the Luna xhigh model setting. The runs used different harnesses, runners, dates, and live website state. There was no randomized concurrent control. The comparison does not isolate an architectural effect or establish a general ranking against Browser Use or Browser Harness.

Recorded agent estimates total $17.86048933 and $21.48721706. They exclude judge, browser, runner, and separate diagnostic runs. They are not invoices or independently normalized prices. We do not use their ratio to advertise a percentage cost reduction.

The chart is pinned to evaluated SDK commit `b430a91891e23f5ffb9ca816e5cbe63e73d2a248`. Later timeout and extraction-guidance experiments are separate cohorts. This is not a score for the current branch HEAD.

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

The subsequent concurrent reference/candidate comparisons at candidate `0baa51d` finished at **84 versus 82/106 on Hard**, and **58.45 versus 59.63/100 on Luna**. Neither cleared the prespecified statistical noninferiority margin. Luna retains one provider-failure zero without an actual judgment in each arm. These later runs are retained separately from the historical README chart; see the [complete paired results and uncertainty](./iteration-protocol.md).

The extraction-only candidate `4a09ee3` subsequently scored **90/106 on Hard** and **59.22/100 on Luna**, with all 166 actual judgments. Recorded agent inference costs were $120.98 and $19.99 respectively. Luna's paired lower bounds did not clear the prespecified margin. This is a nonconcurrent development comparison, not fresh confirmation or a result for the current HEAD. The [extraction report](./extraction-experiment.md) retains uncertainty, workflow closure, delivery failures, and factual limitations found even in passing traces.

The subsequent **fresh Hard confirmation** at `f41c5b7` finished at **89/106 versus 79/106** for the concurrently dispatched historical-reference SDK, with all 212 actual judgments. The paired delta is +9.43 points, 95% interval [+1.89, +16.98], and one-sided lower bound +2.83. It clears the frozen noninferiority margin and sits two tasks below the historical 91. Agent inference cost was $131.89 candidate versus $117.87 reference. Luna confirmation is still ongoing; this is not a result for later runtime commits or a claim of token efficiency. [Full confirmation report](./iteration-protocol.md#complete-fresh-hard-comparison).

## Sources and reproduction

- [bu-pi Luna evaluation](https://www.lmnr.ai/project/b657f811-13a7-4dae-a67a-91445a567f24/evaluations/bf521f51-7920-4e55-8833-f6413b91a73d) · [GitHub execution](https://github.com/browser-use/new-eval-platform/actions/runs/34086771731).
- [BrowserCode Luna evaluation](https://www.lmnr.ai/project/502a9d52-2725-4410-9a58-e469aa10fd12/evaluations/d7fbccfc-03ad-428e-85c2-f280f88cc642).
- `evidence/vision.json` and `evidence/reliability.json` retain the numeric per-task scores and costs. `evidence/readme-usage.json` retains the new numeric usage query, without task prompts or traces.
- The chart uses those fixed cohorts. It does not search for the highest score. Regenerate it from the repository root with `node scripts/benchmark-chart.mjs`. The script checks task identity, score bounds, score/cost totals, and usage reconciliation before writing the SVG.

The exact bu-pi platform SHA, judge, browser, and budget controls are retained in `evidence/vision.json`. The [full report](./vision-results.md) covers evidence-preview clipping, screenshot observation errors, and cleanup diagnostics. A recorded judgment does not mean that every artifact byte was visible to the judge.
