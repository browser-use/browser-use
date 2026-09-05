# Internal Bench Hard

**The delivery candidate passed 91/106 tasks (85.8%).** The fresh frozen SDK baseline passed 76/106 (71.7%). The paired change is **+15 tasks / +14.2 percentage points**, with 19 gains and 4 regressions. Both full runs used GPT-5.5, medium reasoning, the same 106 tasks, and the same Laith judge configuration. No task was rerun or substituted.

This measures one contemporaneous pair against our previous SDK. It does not establish SOTA against current competing agents. The earlier Python + Browser Harness score was 89/106 on another date; the [original 79/106 SDK report](/benchmark-baseline) preserves that history.

## Results

| Measure                                    | Frozen SDK baseline |                      Delivery candidate |
| ------------------------------------------ | ------------------: | --------------------------------------: |
| Recorded passes / all attempted tasks      |              76/106 |                                  91/106 |
| Recorded failures                          |                  30 |                                      14 |
| Recorded error status                      |                   0 | 1; delivered script failed syntax check |
| Agent inference cost, estimated            |             $114.95 |                                 $123.63 |
| Trace-recorded model cost, including judge |             $169.13 |                                 $182.66 |
| SDK schema-valid completions               |              91/106 |                                 106/106 |
| Empty SDK answers after inference          |               4/105 |                                   0/106 |
| Missing-finish repair turns                |                   0 |                                      19 |
| Saved screenshots                          |                2993 |                                    3181 |
| Screenshot capture errors                  |                 457 |                     601 across 74 tasks |
| SDK cleanup errors                         |              1 task |                                 2 tasks |

Agent cost excludes judge inference, cloud browsers, runners, and separate smoke runs. It uses the pinned Pi model catalog, including cache accounting; it is an estimate, not a bill. Candidate inference cost increased 7.5%, while estimated agent cost per recorded pass changed from $1.51 to $1.36.

The paired 95% task-bootstrap interval for the rate change is **[5.7, 22.6] percentage points** (20,000 resamples; seed 20260905). Exact two-sided McNemar p = 0.0026. These describe task sampling within one pair, not repeated-run model, live-site, or judge variability.

## Why the old version lost tasks

### Correct extraction could be damaged at delivery

The old finish tool asked the model to regenerate data already held in JavaScript. Large tables consumed another generation and could be shortened, duplicated, or malformed. A truncated observation did not mean the underlying runtime value was missing.

`finish_from_js({expression: 'JSON.stringify(records)'})` now delivers the existing value over worker IPC and validates it with the same schema as `finish`. Structured schemas accept the array/object directly. The model chooses what to deliver; it does not rewrite every record. The channel has its own 16 MB JSON ceiling and does not inherit the observation text limit.

Independent final-output parsing and counts confirmed these cases in the matched pair:

| Collected data         | Fresh baseline delivery                     | Candidate delivery                        |
| ---------------------- | ------------------------------------------- | ----------------------------------------- |
| 125 job records        | 50 final JSON records                       | 125 final JSON records                    |
| 455 map records        | 581 final table rows                        | 455 final table rows                      |
| 50 qualifying products | Malformed final JSON                        | Valid JSON with 50 records                |
| 200 reviews            | Passing summary linked to a saved JSON file | Valid JSON with 200 records, also passing |

All four candidate tasks passed. The review task is **not** a gain over this fresh baseline: the judge verified its saved file. The original run's 200-to-280 corruption remains a separate historical observation. Another candidate task delivered 18,928 CSV records through an existing text variable; its fresh baseline delivered only the first 25 rows.

### A provider stop did not guarantee a final answer

The baseline had normal provider stops without a valid finish. It also had two timeout tasks with empty final answers; their saved excerpts did not satisfy the requested deliverables. We now allow **one** delivery-only repair turn using the same transcript and remaining step, time, context, and estimated-cost budgets. Provider errors, cancellation, and exhausted limits do not trigger this repair. Browser actions are never automatically replayed.

The candidate used repair on 19/106 tasks: 15 passed and four failed. Compared with the fresh baseline, these were 14 pass/pass pairs, four fail/fail pairs, and only one fail/pass gain. Repair improved the completion contract; it does not explain most of the score increase. It produced zero empty final answers and 106 schema-valid completions. Those are delivery measurements. A completed SDK result can still be factually wrong or incomplete; 15 candidate outcomes did not pass the task judge. There is no isolated ablation here, so the aggregate gain cannot be assigned entirely to repair or entirely to direct delivery.

### Source selection and coverage still fail

Four tasks regressed from baseline pass to candidate failure:

- **Permit history:** selected an official but two-year-limited dataset; returned five records instead of completing the full permit/detail workflow.
- **Menu coverage:** omitted the actual catering sections despite returning menu tables.
- **Trending videos:** substituted ordinary search results for the requested Trending source.
- **Review pagination:** delivered 1,049 records against a displayed 1,717 total after access failures, without disclosing the coverage gap. The baseline accessed a different exposed subset, so its source denominator also differed.

None of these four used the repair turn. A stronger extraction channel preserves what was collected; it cannot prove that the collection satisfies the request.

## Separate capability from measurement noise

The full manifest comparison found only the expected SDK SHA/config-hash and run-identity differences. Task sets, dataset hash, model, reasoning, judge, budgets, platform SHA, observed Node version, and dependency lock matched wherever recorded. The baseline browser-initialization failure has no recorded Node/lock metadata; the other 105 baseline tasks and all 106 candidate tasks do. Both runs executed concurrently, each capped at 12 workers. Live websites, model sampling, browser access, and judge sampling remain variable.

Three audited cases matter when interpreting the gain:

- One baseline browser failed CDP discovery with HTTP 503 before inference. The platform recorded a failed task at zero agent cost. The headline retains this **end-to-end outcome**; it is not evidence of inferior agent reasoning. Excluding that infrastructure-affected pair leaves 76/105 baseline passes versus 90/105 candidate passes (13.3 percentage points).
- A sign-in-blocked task passed in the candidate and failed in the baseline despite the same substantive blocker. That flip demonstrates judge interpretation variability, not a demonstrated capability gain.
- One candidate reached listing cards where the baseline encountered access denial. Access variability contributes to the observed outcome; direct delivery is not an established explanation for that flip.

The candidate's one raw `error` status is also audited: the judge completed, checked a delivered regeneration script with `node -c`, and found invalid JavaScript alongside incomplete coverage. The adapter maps `failure_class: runtime-failure` to `status: error`, retaining a zero score. It is a delivered-artifact failure, not missing judge inference. We retain its raw status and zero score and count it as a nonpass. The candidate GitHub workflow remains **failed** because of this task; its other 105 task jobs completed successfully. The baseline workflow finished **failed** because of the pre-inference CDP discovery error.

These are Laith's recorded judgments, not independent human verification. No manual score correction, best-of selection, agent retry, or judge retry was substituted into this comparison.

## Recorder and lifecycle follow-up

The full score belongs to **`58ed778`**. It includes active-tab/error telemetry, but screenshot capture remained unreliable: 601 errors across 74/106 tasks. Two SDK cleanups timed out enumerating targets; neither reported a separate cloud-browser stop error. Capture failures are replay gaps and can consume wall time; they must not be conflated with browser-action failures.

A later runtime commit, **`a5f2157`**, detaches CDP sessions when page initialization fails and captures eval screenshots through a direct target session, avoiding repeated target enumeration and domain initialization. It adds capture-time and detach-error metrics.

That follow-up passed a separate **2/2** hosted smoke at **$1.497672 agent cost**. Both tasks reported no cleanup or screenshot-detach errors. Seven 15-second screenshot timeouts and two unavailable-active-target observations remained. Capture work took 111.053 seconds in a 287.369-second task, and 9.510 seconds in a 266.345-second task. This is evidence that telemetry can be expensive, not proof that the new recorder is faster. The final runtime has **not** received its own full 106-task comparison.

[Cleanup smoke execution](https://github.com/browser-use/new-eval-platform/actions/runs/33998180917) · [Cleanup smoke evaluation](https://www.lmnr.ai/project/b657f811-13a7-4dae-a67a-91445a567f24/evaluations/1605ab28-f4bc-449a-98a4-4cac5e4cc332)

The earlier direct-delivery smoke passed 2/2 at $1.238372 agent cost. It remains separate from the full denominator and the later cleanup smoke.

## What to improve next

Keep Pi, persistent JavaScript, and raw CDP. The next experiments should target observed failures with small, separately measured changes:

1. **Coverage before completion.** Track required sources, filters, observed totals, extracted counts, and missing sections in an explicit JavaScript value. Verify those facts before finishing; preserve partial output honestly when coverage is blocked. A generic check must not invent a total or train on benchmark-specific tasks.
2. **Affordable recording.** Bound capture overhead independently of action execution and measure replay coverage versus task latency. The current cloud smoke still spent 111 seconds on capture work; a success-rate comparison must freeze recording policy across arms.
3. **Matched competitors and repeated runs.** Run the current best external harness under the same task/model/judge/budget/browser conditions, repeat the pair, and inspect flips. Then validate on an untouched task set. This benchmark has already informed development, so it cannot alone establish generalization.

These are proposed experiments, not implemented capability claims. Adding a planner framework, another agent, or more browser abstractions is not justified by this evidence.

## Frozen configuration

| Field          | Value                                                                                                         |
| -------------- | ------------------------------------------------------------------------------------------------------------- |
| Candidate SDK  | [`58ed778`](https://github.com/browser-use/bu-pi/commit/58ed778b575f8a1c13479a0552ddadc38eea03bc)             |
| Baseline SDK   | [`7ad464c`](https://github.com/browser-use/bu-pi/commit/7ad464c9db872e3d0618662e6f08d40772b91b13)             |
| Platform       | [`ddc48ee`](https://github.com/browser-use/new-eval-platform/commit/ddc48ee93ea863c26d78c45a09760e4951b48a3d) |
| Dataset        | All 106 Internal Bench Hard tasks, one attempt each                                                           |
| Agent          | GPT-5.5, medium reasoning; Pi 0.85.1                                                                          |
| Observed Node  | 22.23.2 on all 211 tasks with runtime metadata; one pre-inference failure lacks it                            |
| Judge          | Vendored Laith, GPT-5.5; default judge options                                                                |
| Agent limits   | 1,000 model turns; 800,000 text characters; 1,700 seconds                                                     |
| Platform limit | 30 minutes per task                                                                                           |
| Browser        | Browser Use Cloud; US proxy; 1,440 × 900; 60-minute lifetime                                                  |
| Runner         | GitHub-hosted Ubuntu 24.04; max 12 workers per arm                                                            |
| Retries        | One task attempt; no automatic browser-action replay; pinned Pi transport retries remain enabled              |

<details>
<summary>Full fingerprints</summary>

```text
dataset.sha256 = 62ca711571e3337234efb54e7708d5768dec8c849bb8a2a54e010c4e31e988c4
package-lock.sha256 = c6694c15c7ab43eba1ae55da26553f3a00c13156896269e63aa631363e41d007
judge.sha256 = 22428ce6e404454808ea596d9c8a016e33b955ab7072ac04e81964f1b34bd3cd
candidate.config_hash = de94f9b98c54cc03c68a740353098df760a6951ec062856ae187f98476dcd821
baseline.config_hash = d2111da8975d653216a15d1f07c1896d111e3ba6de0d7e5f8672557aa788a441
```

</details>

[Candidate execution](https://github.com/browser-use/new-eval-platform/actions/runs/33995420997) · [Candidate Laminar results](https://www.lmnr.ai/project/b657f811-13a7-4dae-a67a-91445a567f24/evaluations/5ab99c00-c360-4ab9-b0f8-ca58bf80e5e0)

[Baseline execution](https://github.com/browser-use/new-eval-platform/actions/runs/33995448219) · [Baseline Laminar results](https://www.lmnr.ai/project/b657f811-13a7-4dae-a67a-91445a567f24/evaluations/d11df546-072c-40e1-b90d-a9c2cd39354a)

The benchmark dataset and traces require organization access. This package publishes aggregate evidence and configuration; private task prompts and raw browser artifacts remain outside the package.

## Reproduce

Use the frozen platform and candidate SHA below. Change only `target_ref` to the baseline SHA for the other arm. Dispatching this command incurs provider, browser, and runner charges.

```sh
gh workflow run eval.yml \
  --repo browser-use/new-eval-platform \
  --ref codex/bu-pi-evals-k7m2 \
  -f platform_ref=ddc48ee93ea863c26d78c45a09760e4951b48a3d \
  -f target_repo=browser-use/bu-pi \
  -f target_ref=58ed778b575f8a1c13479a0552ddadc38eea03bc \
  -f message='Reproduce the raw-CDP delivery candidate' \
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

Hosted runner images, Node patch selection, model service behavior, and live sites can change. Record those differences before interpreting a reproduction. The SDK's default text guard remains 240,000 characters; the evaluation explicitly uses 800,000. Model turns are not browser-action counts: one JavaScript cell may perform many actions.
