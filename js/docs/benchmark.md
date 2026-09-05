# Internal Bench Hard

This is a real hosted-model evaluation of this SDK, using GPT-5.5 through Pi and raw CDP against isolated Browser Use Cloud browsers. Local contract tests and scripted demos are separate evidence.

## Result

**79/106 passed (74.5%); 27/106 failed. All 106 tasks were judged.** The historical Python + Browser Harness run passed 89/106. No smoke result or task retry replaces a full-run outcome.

| Measure                                    | Raw-CDP JavaScript SDK | Historical Python + Browser Harness |
| ------------------------------------------ | ---------------------: | ----------------------------------: |
| Laith passes                               |                 79/106 |                              89/106 |
| Agent model cost, estimated                |                $111.01 |                             $136.81 |
| Trace-recorded model cost, including judge |                $166.02 |                             $190.65 |
| Date                                       |      September 5, 2026 |                      August 7, 2026 |

Pairing by the exact 106 task IDs gives **8 new passes and 18 regressions**, a net change of **-10 tasks** (-9.4 percentage points). The other 80 task judgments agree. These are historical outcome flips, not causal estimates of the harness change.

Agent costs use Pi's pinned model catalog and cached-token accounting; they are estimates, not provider invoices. The $55.01 trace-cost remainder is judge inference. Browser sessions and CI runner charges are excluded. The two-task smokes are also excluded from the full-run costs above. Lower total cost does not establish better efficiency when success rates and execution conditions differ.

## Execution and evidence coverage

The SDK reported 90 typed finishes and 16 incomplete stops. It reported no terminal model/runtime error, timeout, turn-limit stop or context-limit stop in this run. This does not mean every browser tool call succeeded: inspected traces include recoverable target ambiguity and CDP timeout errors.

The median task used 31.5 model turns and 212.4 SDK run seconds. The maximum was 101 turns and 1524.3 seconds. Duration measures the SDK run, including its callbacks; it excludes browser provisioning and judge inference. The historical harness's timing boundary differs.

All task executions produced result envelopes. One task reported an SDK cleanup timeout while enumerating browser targets; its separate cloud-stop call reported no error. Saved screenshot evidence exists for **105/106 tasks** (3,098 screenshots). **40/106 tasks reported 417 screenshot-capture errors**; one task had no saved screenshots. All tasks were nevertheless judged using available code, outputs, artifacts and screenshots. The adapter counts capture failures but does not preserve their exception details, so these gaps cannot be fully attributed. Screenshots sample the first nonblank page target, which can differ from the agent's active tab.

| SDK stop     | Laith pass | Laith fail |
| ------------ | ---------: | ---------: |
| `completed`  |         71 |         19 |
| `incomplete` |          8 |          8 |

One task completed inference and received a passing judgment, then failed to publish its datapoint because Laminar returned a database-permission error. We recovered the original result, judgment and manifest from its GitHub evidence artifact and republished them through the existing platform publisher to the same datapoint and trace. No agent or judge inference was rerun and no score was edited. The GitHub workflow remains red for that original publication failure; Laminar contains the recovered outcome.

## Recorded failure classes

These are the judge's labels, retained verbatim. They describe outcomes; they do not independently identify a technical root cause.

| Judge label                | Tasks |
| -------------------------- | ----: |
| `site-blocked`             |     8 |
| `empty-result`             |     7 |
| `result-final-mismatch`    |     4 |
| `missing-required-fields`  |     2 |
| `synthetic-or-unsupported` |     2 |
| `runner-no-result`         |     1 |
| `source-limited`           |     1 |
| `source-scope-drift`       |     1 |
| `wrong-record`             |     1 |

## What the traces explain

**Data delivery is a concrete weakness.** Three failed tasks had useful data in the JavaScript runtime before their final output changed it: 125 jobs became 126; 455 map records became 837; a 200-review extraction became 280 objects despite a 200-record maximum. We inspected the JavaScript tool outputs and subsequent `finish` arguments. The browser had already done substantial work. Regenerating a large value through model tokens introduced another failure opportunity. A fourth task built 50 qualifying products, then explicitly selected only the first 16 for its final answer. Its tool output had been truncated; the full 50-record value still existed in the runtime.

The generic benchmark used the SDK's default string result. It did not encode task-specific array lengths or required fields in a schema. A caller-provided schema can reject a 280-item result with `maxItems: 200`; it cannot prove that the remaining 200 records are correct. For large deliverables, [save the extracted value directly and return its artifact path](/results#deliver-large-tables-without-regenerating-them). That recipe is available today, but has not been measured as a separate benchmark arm.

**A normal provider stop is not reliable delivery.** Four inspected empty-answer traces ended with Pi reporting `rawStopReason: completed`, empty final text, and no `finish` call. The SDK correctly returned `incomplete`; it did not request a repair turn. Raw provider event streams were not retained, so model behavior versus provider/parser behavior remains unresolved. The judge's `runner-no-result` label on one such task describes a missing answer; the GitHub runner itself completed and delivered evidence.

**Access and source constraints remain real.** Observed blockers included HTTP 403, sign-in gates, and a search CAPTCHA. Other failures omitted required source sections or substituted another source for a specifically requested workflow. Those outcomes remain failures; a useful partial artifact is not complete coverage. Access also improved on some historical-failure tasks, so the two dates do not isolate a stealth or browser-provider advantage.

**The judge moves too.** On one selector-discovery task, both final outputs used detail-page selectors for listing fields. The historical judgment rejected that adaptation; the current judgment accepted it. We kept the recorded scores. This is direct evidence that some score flips reflect interpretation, not a proven capability improvement.

## Small changes worth evaluating next

1. Let a JavaScript cell deliver an existing value or saved artifact through the same schema validator, without asking the model to regenerate it. Preserve explicit completion and the rule blocking later actions.
2. Test one budgeted repair turn when the provider stops without a valid finish. Keep empty output, plain-text completion, provider errors and timeouts distinct. Record the extra inference cost.
3. Track the agent's active target in the eval recorder and retain capture error details. Replay gaps should be diagnosable independently of browser-action failures.

These are proposed experiments, not claimed fixes or results. This commit's score remains attached to its original code and configuration. The evidence does not establish that JavaScript or raw CDP is intrinsically better or worse than Python plus Browser Harness.

## Frozen configuration

| Field                 | Candidate                                                                                                     |
| --------------------- | ------------------------------------------------------------------------------------------------------------- |
| SDK commit            | [`7ad464c`](https://github.com/browser-use/bu-pi/commit/7ad464c9db872e3d0618662e6f08d40772b91b13)             |
| Platform commit       | [`ddc48ee`](https://github.com/browser-use/new-eval-platform/commit/ddc48ee93ea863c26d78c45a09760e4951b48a3d) |
| Tasks                 | All 106 Internal Bench Hard tasks, one attempt each                                                           |
| Dataset identity      | Exact SHA-256 below                                                                                           |
| Agent                 | GPT-5.5, medium reasoning; Pi 0.85.1                                                                          |
| Observed Node runtime | 22.23.2 on every task                                                                                         |
| Judge                 | Vendored Laith, GPT-5.5; no manual score overrides                                                            |
| Budgets               | 1,000 model turns; 800,000 text characters; 1,700 agent seconds                                               |
| Platform budget       | 30 minutes per task                                                                                           |
| Browser               | Browser Use Cloud; US proxy; 1,440 × 900; 60-minute lifetime                                                  |
| Runner                | GitHub-hosted Ubuntu 24.04; up to 12 concurrent tasks                                                         |
| Retries               | No task reruns or automatic browser-action replay; Pi provider transport retries remain enabled               |

<details>
<summary>Full dataset and dependency fingerprints</summary>

```text
dataset.sha256 = 62ca711571e3337234efb54e7708d5768dec8c849bb8a2a54e010c4e31e988c4
package-lock.sha256 = c6694c15c7ab43eba1ae55da26553f3a00c13156896269e63aa631363e41d007
judge.sha256 = 22428ce6e404454808ea596d9c8a016e33b955ab7072ac04e81964f1b34bd3cd
```

</details>

[GitHub execution](https://github.com/browser-use/new-eval-platform/actions/runs/33989195407) · [Laminar results and traces](https://www.lmnr.ai/project/b657f811-13a7-4dae-a67a-91445a567f24/evaluations/0ee87e4e-cffb-487b-b160-51ffb5709de4)

The benchmark dataset, workflow and traces require organization access. This repository publishes configuration and aggregate findings, not private tasks or raw browser artifacts. Clone the evaluated commit for reproduction; later documentation commits do not change its measured code.

## Historical comparison limits

The earlier Python/Pi + Browser Harness run passed **89/106** on August 7, 2026. Its agent cost was **$136.81**; the trace-recorded total including judge inference was **$190.65**. Those are different accounting scopes. Browser infrastructure and GitHub runner charges are outside these model-cost figures.

[Historical evaluation](https://www.lmnr.ai/project/b657f811-13a7-4dae-a67a-91445a567f24/evaluations/96a1ab87-f2ae-4e80-a361-2d6d2035a585) · [Historical execution](https://github.com/browser-use/new-eval-platform/actions/runs/31207346007)

The dataset hash, model, reasoning level, judge source, judge model and proxy country match. This is **a historical comparison, not a controlled contemporaneous A/B**. The old run used Blacksmith runners, different model/runtime versions, different context behavior and browser dimensions, and a 1,770-second agent deadline. Live sites changed between dates.

The old manifest advertised 35 steps, but its harness did not read that limit. Its recorded `metadata.turns` exceeded 35 on **43/106 tasks**, with a maximum of **89**. The candidate uses a high safety ceiling so time and context, rather than an accidentally tighter turn cap, govern long tasks. Model-turn counts are not browser-action counts; one JavaScript cell can perform many actions.

Laith is an imperfect LLM judge. Scores describe that frozen judging process, not a human-verified guarantee. SDK `completed` means schema-valid delivery. It does not mean the website task succeeded. Conversely, `incomplete` can contain useful plain-text output that a task judge accepts.

## Smoke history

Two exact regression tasks were run before the full benchmark:

| Configuration                                  | Outcome | What happened                                                      |
| ---------------------------------------------- | ------- | ------------------------------------------------------------------ |
| SDK `789c3f3`, 35 turns, 240,000 text chars    | 0/2     | Context guard stopped one task at 24 turns; the other hit 35 turns |
| SDK `7ad464c`, 1,000 turns, 800,000 text chars | 2/2     | Tasks finished in 55 and 75 model turns; $4.366644 agent cost      |

The first smoke remains a failed attempt. The second is a budget/configuration change, not proof that larger budgets always improve results. Neither smoke is added to the 106-task denominator or substituted for a full-run result.

Before those inference runs, one dispatch was cancelled while waiting for unavailable runners and one failed checkout because an abbreviated SHA was treated as a branch. Both consumed no model inference. Reproduction uses full commit SHAs.

The SDK default remains 240,000 text characters. The eval adapter defaults to 800,000. This is an approximate text guard, not a model token counter or durable context compaction.

## Reproduce the full run

From an account with access to the evaluation platform and its configured model/browser secrets:

```sh
gh workflow run eval.yml \
  --repo browser-use/new-eval-platform \
  --ref codex/bu-pi-evals-k7m2 \
  -f platform_ref=ddc48ee93ea863c26d78c45a09760e4951b48a3d \
  -f target_repo=browser-use/bu-pi \
  -f target_ref=7ad464c9db872e3d0618662e6f08d40772b91b13 \
  -f message='Reproduce the raw-CDP SDK hard benchmark' \
  -f harness=pi-browser-use-next \
  -f dataset=datasets/internal-bench-hard.json \
  -f task_limit=0 \
  -f model=gpt-5.5 \
  -f judge=laith \
  -f judge_model=gpt-5.5 \
  -f max_steps=1000 \
  -f max_parallel=12 \
  -f timeout_minutes=30 \
  -f options_json='{"reasoning_effort":"medium","task_timeout_seconds":1700,"proxy_country_code":"us","browser_timeout_minutes":60,"max_context_chars":800000}'
```

The command pins code and task configuration. Hosted runner images, the Node 22 patch selected by the workflow, model service behavior and live websites can change on a later date. Record those differences before interpreting another score. For plumbing checks, use the two exact smoke IDs in the platform README instead of running all 106 tasks.
