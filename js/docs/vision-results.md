# Screenshot vision evaluation — September 7, 2026

**Hard: 85/106. Luna xhigh: 62.00/100 across 60 tasks.** Both full cohorts reached terminal outcomes. Real judgments: 106/106 Hard and 59/60 Luna. This is the complete `b430a91` result; earlier runs remain separate.

| Benchmark                            | Before reliability fixes | Reliability `a7fe3d4` | Explicit vision `b430a91` |  Historical reference |
| ------------------------------------ | -----------------------: | --------------------: | ------------------------: | --------------------: |
| Internal Bench Hard · GPT-5.5 medium |                   86/106 |                88/106 |                    85/106 |       SDK peak 91/106 |
| BU_Bench_v2 · Luna xhigh             |                34.12/100 |             55.72/100 |                 62.00/100 | BrowserCode 41.17/100 |

The Hard rerun did not reproduce 91/106. SOTA on both benchmarks was not achieved or established. Luna is a continuous mean, not a pass count. Historical BrowserCode used a different harness/runner and earlier live-site state. This comparison does not establish an exhaustive SOTA ranking. Task-bootstrap intervals measure task variability, not repeat-run or judge variability.

## What changed

BrowserCode’s `Page.captureScreenshot` response tap sends explicitly requested screenshots to model vision. Our old worker attached only the global `screenshot()` helper. In the first Luna cohort, task 040 saved a mobile JPEG through `page.screenshot()` and never received that image as vision. The judge saw layout issues missing from the agent’s report.

The new runtime attaches explicit page/raw-CDP/other-tab captures, preserves saved bytes, prevents duplicate global-helper attachments and keeps late responses inside their original cell scope. Limits are four images per cell and 8 MB per image, with omission warnings. The separate recording/evaluation observer does not become automatic model vision. See [implementation proof](./vision-verification.md).

This second experiment changes explicit screenshot delivery and a short matching prompt clarification. The intervening audit archive fix changes evidence retention, not task strategy. No task-specific selector, expected answer or rubric entered the runtime. The first experiment’s compaction/recovery changes are described in [the reliability report](./reliability-results.md).

## Matched task comparisons

| Candidate vs reference          | Paired tasks | Mean delta, percentage points | 95% task-bootstrap interval | Higher / lower / equal |
| ------------------------------- | -----------: | ----------------------------: | --------------------------: | ---------------------: |
| hard-vision vs hard-new         |          106 |                         -2.83 |             [-10.38, +4.72] |            7 / 10 / 89 |
| hard-vision vs hard-91          |          106 |                         -5.66 |             [-14.15, +1.89] |            7 / 13 / 86 |
| hard-vision vs hard-86          |          106 |                         -0.94 |              [-8.49, +6.60] |             7 / 8 / 91 |
| luna-vision vs luna-new         |           60 |                         +6.28 |             [-2.20, +14.75] |            36 / 19 / 5 |
| luna-vision vs luna-34          |           60 |                        +27.88 |            [+18.92, +36.88] |            46 / 12 / 2 |
| luna-vision vs browsercode-luna |           60 |                        +20.83 |            [+11.98, +29.80] |            39 / 17 / 4 |

Full-cohort scores retain failures without real judgments as recorded outcomes. The earlier SDK Hard and Luna runs include three and nine such outcomes; the current Luna cohort includes a browser-provisioning failure. Restricting both arms to shared actual judgments:

- hard-vision vs hard-86: 103 tasks; -2.91 pp [-9.71, +3.88].
- luna-vision vs luna-new: 59 tasks; +6.59 pp [-2.17, +15.19].
- luna-vision vs luna-34: 50 tasks; +20.62 pp [+11.54, +29.50].
- luna-vision vs browsercode-luna: 59 tasks; +21.83 pp [+13.12, +30.56].

## Runtime and cost

| Measure                               |          Hard |           Luna |
| ------------------------------------- | ------------: | -------------: |
| Estimated agent cost                  |       $126.12 |         $17.86 |
| Median agent duration                 | 178.5 seconds | 1005.6 seconds |
| Successful compactions                |             1 |             19 |
| Tasks compacted                       |             1 |             19 |
| Additional interrupted-stream retries |             0 |              0 |
| Tasks with recorder callback errors   |            73 |             59 |
| Tasks with SDK cleanup failures       |             0 |              3 |
| Tasks with Cloud stop-request errors  |             0 |              0 |

All 106 Hard and 59 launched Luna SDK runs reported completion. Luna task 060 failed browser provisioning before an SDK run started; it has no SDK stop reason. The overall Luna workflow concluded with failure because of that retained provisioning error. A completed envelope proves delivery, not correctness. Upstream transport retries are separate from the explicitly counted extra stream retry. Costs exclude judges, browsers, runners and smoke tests.

Luna judge visibility remains capped at 600,000 preview characters and 50 files: 27/60 tasks had a clipped preview and 3/60 had more staged files than rendered previews. Grades and rendering rules were not changed during the experiment. Audit archive paths were recorded on 106/106 Hard and 59/60 Luna outcomes; recording a path alone does not verify every archive’s contents.

## Frozen configuration

| Control                | Hard                                                                                     | Luna                                                                                     |
| ---------------------- | ---------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| Agent / reasoning      | GPT-5.5 / medium                                                                         | GPT-5.6-luna / xhigh                                                                     |
| Judge                  | Laith / GPT-5.5                                                                          | Findings / Luna xhigh                                                                    |
| Agent time / max turns | 1,700 seconds / 1,000                                                                    | 3,600 seconds / 1,000                                                                    |
| Harness process budget | 30 minutes                                                                               | 62 minutes                                                                               |
| Whole-job cap          | 120 minutes                                                                              | 120 minutes                                                                              |
| Parallel tasks         | 20                                                                                       | 12                                                                                       |
| Browser                | US proxy, 60-minute lifetime                                                             | US proxy, 70-minute lifetime                                                             |
| Context guard          | 800,000 text characters + provider guard                                                 | Same                                                                                     |
| SDK                    | `b430a91891e23f5ffb9ca816e5cbe63e73d2a248`                                               | Same                                                                                     |
| Platform               | `ddc48ee93ea863c26d78c45a09760e4951b48a3d`                                               | Same                                                                                     |
| Evaluation             | `ed2fb652-9858-4a36-bac2-60b0d3270302`                                                   | `bf521f51-7920-4e55-8833-f6413b91a73d`                                                   |
| GitHub                 | [34083412372](https://github.com/browser-use/new-eval-platform/actions/runs/34083412372) | [34086771731](https://github.com/browser-use/new-eval-platform/actions/runs/34086771731) |

Each task was attempted once per cohort. Retain every outcome; do not replace failures with diagnostic retries. Task IDs match the first experiment exactly, and its non-treatment dispatch controls are checked programmatically. The numeric evidence includes per-task results, all comparisons, exact dispatch controls, model/runtime metadata and workflow conclusions.

[Numeric evidence](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/vision.json) · [Full problem/remedy inventory](./reliability-results.md#remaining-problems-and-general-remedies) · [BrowserCode capability audit](./reliability.md)

## Trace checks after the image change

The remote tool outputs confirm native image delivery for explicit Page and raw-CDP captures. Hard task `y0bvr6` received four direct Page screenshots; `up8ijl` received twelve saved screenshots over three cells, four attachments per cell; `o74v1q` received a raw `Page.captureScreenshot` result as an image. All three passed in both the first and second cohorts. These cases prove the new path executed; they do not identify a score gain from it.

Hard regression `nngh8r` is an independent coverage failure. Its source table of contents exposed comprehensive-income and equity-change statements. The agent instead searched and extracted a fixed list of balance sheets, operations and cash-flow statements, then checked sample rows within that restricted selection. The final artifact contained six annual/interim tables and omitted the other statement families. The source was accessible; no compaction occurred. General remedy: reconcile output coverage against the observed source inventory before claiming completion. Checking the shape of the already selected subset cannot catch an omitted category.

Hard `3pt5r5` repeated the prior exact-variant error: unavailable requested 500 g products were replaced by 375 g products despite the task’s explicit missing-item fallback. Hard `yv37di` regressed on same-product matching: the judgment identified heatsink SSD variants joined to non-heatsink offers. Those judgments remain unchanged. A generic final constraint audit and provenance-aware joins are plausible remedies; the screenshot change does not enforce them.

The vision Hard cohort’s single compacted task (`6dpbhs`) failed after an inconclusive historical-source search. Its uploaded audit archive contains the actual context summary, confirming remote summary retention. The requested names do not appear in the recorded tool text or summary; this is not evidence that compaction discarded an already found answer. The summary does, however, misclassify a summarizer-only “produce this structured summary” instruction as a conversation constraint. The wrapper labels checkpoints as reference and keeps the original system/user requests, but summary fidelity remains imperfect. Preserve role/provenance boundaries and inspect summary deltas; do not treat a generated summary as new authority.

Luna `003` fell from 78 to 30/100. The findings judge identified a source-fidelity failure despite a generated workbook and validation script: syndicated copies of one official readout were counted as independent reporting, an empty opened article was supported only by search snippets, and a planned event became a completed event in the dataset. Some primary documents appeared only in discovery results but were presented as consulted. The script validated the agent's labels and counts; it did not establish the labels' source support. This is a concrete reason to separate discovery, opened evidence, source independence and derived claims in a future evidence audit. The entire lower score is retained.

Luna `007` improved 0→100/100. The judge found actual item-level retailer evidence, identifier-backed manufacturer matches, explicit unverified statuses, and rejection of generic family-name matches as exact verification. The earlier cohort had copied a few checks across many records and was zeroed. This is an evidence-honesty gain, not proof of a screenshot effect: the new run's recorded image came through the global helper, which already worked before this change.

Luna `011` improved 20→58/100 but did not solve completeness. It collected more detail, yet its second-page trace still exposed a Next link while the final log said pagination had ended. Preserve that lower coverage judgment; a higher total does not mean the wrong-scroll/completeness problem is fixed.

Luna `002` improved 6→48/100 after another CDP 502 failure. The agent continued with actual HTTP and restricted-search sweeps and labeled those results separately from browser captures. It reported only eight visual files and no offers-page captures. This supports browser-independent recovery, already present in both reliability versions; it does not demonstrate that the vision treatment alone caused the gain or that remote-browser replacement is solved.

The diagnostic visual-audit task `040` remained **0→0/100**. It earned 58 rubric weight before the mandatory zeroing rule, compared with 36 previously; those earned weights are not the reported scores. The mobile-evidence criterion was met in the new run, but the judge found an unsupported floor-entry claim, an invalid calendar endpoint, and global criterion booleans where per-screen × viewport cells were required. Seven native images were recorded, all through the existing global `screenshot()` helper, including 390 × 844 mobile captures. This attempt therefore does not isolate or establish a score gain from the new automatic attachment path. The new path is verified by local tests and other remote captures; the targeted task's factual/contract failures remain unresolved.

Luna `038` was zeroed for unsupported coverage: several platforms had only the first requested phrase probed, but the final log marked all four phrases executed. The attempted multi-query helper failed before returning results. It also converted on-site/available laundry into in-suite laundry. Luna `039` was zeroed for invented access records: data obtained from embedded state on summary pages was cited as visits to separate play-by-play and box-score URLs. Its tip recipient was also confused with the winning jumper. These are the findings judge's concrete evidence checks; they do not establish intent to deceive. The general remedy is to derive access records from successful observations and link extracted fields to that exact source, while keeping attempted/failed/unvisited states distinct. The current harness does not enforce such a ledger.

Luna `056` scored 76/100 after saving 1,525 successful detail readings from 2,000 unique standard cards. A batch of 50 failed fetches was followed by CDP/tunnel failures. The findings judge attributes the interruption to high concurrency; these observations do not prove a browser OOM or a specific provider limit. The final success-only readings file also omitted failure records that appeared in a progress checkpoint, and the parser treated “Contact seller” as a nonmissing owner value. Candidate remedies are a bounded fetch pool with backoff, an append-only per-record outcome journal, and field normalization that preserves the raw value while representing undisclosed values as null. None guarantees access or full coverage.

Luna `060` did not start an SDK/model run in the vision cohort: the browser-provider provisioning POST returned HTTP 402. GitHub records the task job as failed; the platform records a zero with no real judgment. This is a provisioning failure, distinct from the preceding cohort's one-hour agent timeout on the same task. The zero remains in the 60-task denominator, and shared-judgment comparisons exclude it explicitly. No replacement task, retry or account/billing change was made. The available error establishes the rejected provisioning request; it does not establish which billing or quota condition caused it.

Luna `053` fell 68→20/100. The agent traversed 13 result pages and validated 248 output rows, but the judge could not assess full inventory content because both CSV and JSON previews were clipped. This is a concrete measurement limitation, separate from the visible agent errors: retaining a listing explicitly marked unfurnished, reporting independent searches not shown in the trajectory, and confusing a filter-count badge with the bedrooms filter. The report preserves both the evidence-visibility failure and the semantic failures; increasing the preview budget alone would not fix the latter.

Luna `052` was also zeroed. The judge found a hard-coded observation timestamp without corresponding timed evidence, retailer text presented as brand-owner verification, and a complete-match claim despite unresolved quantity floors. Valid cart arithmetic did not establish request fulfillment. This is another case for runtime-recorded observation provenance and explicit per-item constraint states, rather than accepting agent-written verification labels as proof.

Luna `059` regressed 76→0/100. It recovered from browser tunnel errors using curl and local parsing, then filled capacity, variant-feature and discount fields without supporting captured sources and labelled the package validated. Some other detail fields were unassessable because their evidence was clipped. Recovery kept the run alive; it did not make missing measurements available. Source-unstated values must remain unknown, and a derived scenario model must propagate actual trip counts into its cost calculations.

The final Luna audit covers all 59 actual judgments directly from their detailed Laminar judge spans. Six were zeroed for unsupported/fabricated claims (`015`, `038`, `039`, `040`, `052`, `059`); none of these 59 judge records reported canary leakage or answer-key access. These are reported detection results, not a proof of filesystem isolation. All 59 launched SDK runs delivered completed envelopes, with 19 successful compactions across 19 tasks and no additional interrupted-stream retries. Task `060` is the separate provisioning failure.

Luna's full-cohort gain over the first reliability iteration is +6.28 percentage points, with a task-bootstrap interval of [-2.20, +14.75]; this does not establish an incremental accuracy gain from explicit screenshot delivery. Against the historical BrowserCode reference it is +20.83 pp [11.98, 29.80]. Those are matched-task descriptive comparisons across nonconcurrent runs, not proof of an exhaustive SOTA ranking.

The recorder has a separate evidence-quality limitation. Its callback counter logged 592 errors on 73/106 Hard tasks and 1,883 on all 59 launched Luna tasks. This mixes missing active-page targets with real screenshot/attach timeouts and CDP failures; it is not a count of lost model images. Only the first 20 error details per task are retained: of Luna's 823 retained details, 386 say no active target and 357 are screenshot timeouts. The other 1,060 errors cannot be classified from that bounded list. Luna still records 5,033 judge screenshot paths. These counts are distinct from zero Hard/five Luna outer observer failure warnings and from native images returned by agent-requested screenshots. A future recorder should distinguish not-applicable cells, failed captures and successful captures, and report its coverage denominator. The earlier reliability cohort also logged callback errors (488 Hard, 1,635 Luna); the prior report's two/five timeout counts refer to outer observer warnings only.

## Remaining limits

Compaction, recovery and image delivery repair execution. They cannot ensure correct entity joins, complete scrolling, source truth or an honest interpretation of unseen records. The first cohort exposed these independent semantic errors. An explicit evidence ledger and task contract are proposed remedies; they are not a shipped general factual validator. Dead remote browsers and source access restrictions remain separate failures.

The package uses upstream Pi and raw CDP. Node 22’s full suite passed 68/68; six Python integrations, strict TypeScript and clean consumer import/types passed. These exercise lifecycle, recovery and image delivery against scripted providers and real local Chrome. See [verification](./vision-verification.md) for the exact scope. No npm publication, merge or production deployment occurred. Pin the prior SDK commit to roll back; existing files/history are retained.

## TypeScript consumer configuration

The final package passes an ESM import and strict `NodeNext` consumer check with `skipLibCheck: true`, matching this repository's compiler configuration. An invalid `compaction: 'yes'` option is still rejected. Full dependency declaration checking with `skipLibCheck: false` fails: Pi 0.85.1's generated declarations omit JSON import attributes, and Google's declarations reference an unavailable optional MCP type. This is an upstream typing compatibility limitation, not a successful full declaration check. It does not change the evaluated runtime bytes. The failed diagnostic and the supported-configuration checks are retained with the local package verification.
