# Reliability evaluation — September 7, 2026

> Historical verification. [Latest full evaluations](./vision-results.md) · [Current runtime tests](./vision-verification.md). Scores below belong to their stated commits.

The candidate adds upstream Pi compaction, durable checkpoints, browser-independent code/files, optional Pi coding tools, explicit reconnect, partial-output recovery, a delivery reserve, and nonblocking screenshot observation. Pi supplies summary generation and token estimation; bu-pi schedules compaction and preserves the working context. No Pi fork or Playwright.

## Full results

**Hard: 88/106 (83.02%). Luna: 55.72/100 across all 60 tasks.** All 166 tasks received real judgments. The Hard peak of 91 was not reproduced. These runs do not establish SOTA on both benchmarks.

| Cohort                               |   Current | Previous SDK |  Historical reference | Current agent cost |
| ------------------------------------ | --------: | -----------: | --------------------: | -----------------: |
| Internal Bench Hard · GPT-5.5 medium |    88/106 |       86/106 |       91/106 SDK peak |            $118.47 |
| BU_Bench_v2 · Luna xhigh             | 55.72/100 |    34.12/100 | 41.17/100 BrowserCode |             $17.22 |

Luna is a continuous mean, not a pass count. The historical BrowserCode run is not a concurrent control. Five previously examined Luna reference runs ranged from 33.12 to 42.37/100; that is a limited inventory, not a verified leaderboard of every harness/model/configuration.

| Paired change                | Tasks | Mean delta, percentage points | Task-bootstrap 95% interval | Higher / lower / equal |
| ---------------------------- | ----: | ----------------------------: | --------------------------: | ---------------------: |
| hard-new vs hard-91          |   106 |                         -2.83 |             [-11.32, +4.72] |            8 / 11 / 87 |
| hard-new vs hard-86          |   106 |                         +1.89 |             [-6.60, +10.38] |            11 / 9 / 86 |
| luna-new vs luna-34          |    60 |                        +21.60 |            [+12.50, +30.78] |            39 / 17 / 4 |
| luna-new vs browsercode-luna |    60 |                        +14.55 |             [+5.87, +23.42] |            33 / 18 / 9 |

The prior SDK contains missing real judgments. Keeping only shared actual judgments in **both** arms gives:

- hard-new vs hard-86: 103 tasks; -0.97 pp [-8.74, +6.80].
- luna-new vs luna-34: 51 tasks; +15.22 pp [+6.12, +24.35].

Hard reported {'completed': 106} and no compactions. Luna reported {'timeout': 1, 'completed': 59}, with 20 compactions across 19 tasks. The explicit extra provider-stream retry executed 0 times on Hard and 0 times on Luna; upstream provider transport retries remain a separate mechanism. Agent median durations were 196.0 seconds (Hard) and 992.2 seconds (Luna).

The three previous fatal screenshot-hook tasks now pass. Two Hard observer timeouts were contained. Three Hard SDK tab-cleanup attempts warned; separate Cloud stop requests reported no errors across all 106 tasks. A completed agent envelope means deliverable completion, not factual correctness.

[Numeric evidence and per-task paired scores](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/reliability.json) contains every retained outcome, exact evaluation IDs and bootstrap settings. No task retry or smoke result replaces an outcome.

## Where the Luna change appears

| Previous SDK stop | Same tasks | Previous mean / 100 | Current mean / 100 | Current tasks compacted |
| ----------------- | ---------: | ------------------: | -----------------: | ----------------------: |
| completed         |         28 |               58.11 |              55.39 |                       2 |
| context_limit     |         23 |               18.26 |              55.30 |                      15 |
| error             |          9 |                0.00 |              57.78 |                       2 |

This is a descriptive split by the prior run’s outcome, not a randomized ablation. It checks whether the gain is concentrated where context/recovery failures previously occurred. It cannot identify compaction’s individual causal effect.

Judge artifact visibility: **25/60 tasks had at least one clipped file preview; 3/60 had more staged files than rendered previews.** The adapter retains BrowserCode’s 600,000-character/50-file preview budget and marks clipping. Raw staged files are distinct from judge-visible previews. A real judgment does not imply complete visibility into every large artifact. Improving that measurement boundary requires a separate frozen judge/evidence experiment; these grades were not changed.

## Frozen experiment

| Control                | Internal Bench Hard                                                                      | BU_Bench_v2                                                                              |
| ---------------------- | ---------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| Task count             | 106                                                                                      | 60                                                                                       |
| Agent                  | GPT-5.5, medium                                                                          | GPT-5.6-luna, xhigh                                                                      |
| Judge                  | Laith / GPT-5.5                                                                          | Findings / Luna xhigh                                                                    |
| Agent budget           | 1,700 seconds, 1,000 turns                                                               | 3,600 seconds, 1,000 turns                                                               |
| Harness process budget | 30 minutes                                                                               | 62 minutes                                                                               |
| Whole-job cap          | 120 minutes                                                                              | 120 minutes                                                                              |
| Parallel tasks         | 20                                                                                       | 12                                                                                       |
| Browser                | US proxy; 60-minute lifetime                                                             | US proxy; 70-minute lifetime                                                             |
| Context guard          | 800,000 text characters + provider-context guard                                         | Same                                                                                     |
| Platform SHA           | `ddc48ee93ea863c26d78c45a09760e4951b48a3d`                                               | Same                                                                                     |
| SDK SHA                | `a7fe3d46625ec0d3b5ac1d2022d08a5a9b03163d`                                               | Same                                                                                     |
| Evaluation             | `e3e1c31c-2341-4de8-bdfe-fa12422fd892`                                                   | `63143674-db53-41dc-b3c1-b91d12b2e4ff`                                                   |
| GitHub run             | [34077343902](https://github.com/browser-use/new-eval-platform/actions/runs/34077343902) | [34077345331](https://github.com/browser-use/new-eval-platform/actions/runs/34077345331) |

Dataset SHA-256: Hard `62ca711571e3337234efb54e7708d5768dec8c849bb8a2a54e010c4e31e988c4`; BU_Bench_v2 `fedc07de8d02a73e81fe1aa50775d753d00b7714203b87bbdd42e75a7257ffd0`. Runtime Node 22.23.2; dependency lock SHA-256 `7ab8ce4c0dd453995b211d1fff5fc61b43242742a02a064a88c9dfde15e86508`.

One agent attempt per task. The new harness permits one specific transient provider-stream retry within the original budget; it does not replay browser actions. Preserve every task outcome. The 2/2 integration smoke and 1/1 archive smoke are separate development runs and are never substituted into either cohort.

These are deliberate treatment changes: compaction/accounting, response output cap, observer execution, recovery/delivery instructions, and research tools/search permission on findings tasks. Their joint result cannot identify each change's causal contribution. The model response cap is 32,768 tokens here; compaction uses the same model at low reasoning with its own smaller summary allowance, and its usage is included.

## Comparison rules

The recent prior SDK runs are 86/106 Hard (`49046b14-4bec-48b4-96be-41408d185724`) and 34.12/100 Luna (`3e98b41b-2411-4531-b994-bad88026c6a3`). The older Hard peak is 91/106 (`5ab99c00-c360-4ab9-b0f8-ca58bf80e5e0`). The BrowserCode Luna reference is 41.17/100 (`d7fbccfc-03ad-428e-85c2-f280f88cc642`), from August 20. It used another runner/harness and earlier live website state; it is not a simultaneous control.

Scores are paired by task ID. Report end-to-end scores and actual judgment coverage separately: prior SDK Hard has 103 actual judgments plus three runner failures; prior Luna has 51 judgments plus nine runner failures. The 91-run has 106 actual judgments, including one judge-labelled runtime-error outcome. A judge's `error` verdict is not automatically a failed judge invocation. Historical BrowserCode has 60 scored tasks plus two empty duplicate placeholders, which are excluded without discarding any scored task.

Task-bootstrap intervals use 20,000 resamples and seed 20260907. These measure task sampling variability, not uncertainty from repeated live-site or judge runs. Continuous score differences remain continuous; no arbitrary win threshold is introduced. Costs are reported as estimated agent cost, excluding judge, browser and runner charges.

## What the traces prove

- Compaction executed on long research tasks; task 004 model spans show input dropping from 154,632 tokens to 9,981 and work continuing. Home Depot task 004 improved 10→92/100; news task 003 improved 0→78. Both report one successful compaction. They do not isolate compaction from the other changes.
- Hard task `0oxfq8` survived three worker resets, explicitly reloaded checkpoints and produced a 44-row artifact. The first timeout had printed 15 completed items, but a checkpoint every eight retained only eight. Recovery is real; uncheckpointed work still gets lost.
- Luna 001 improved 0→73: 134 cards delivered, with unvisited detail pages correctly labelled `not_attempted_after_global_captcha`. The prior run had been zeroed for unsupported per-record claims.
- Hard score flips include access and judge effects. Copilot showed a sign-in wall in all three compared runs; the 91-run accepted impossibility and the two later judgments failed it. Apartments.com previously yielded 37 listings; both newer runs received 403. Preserve original scores rather than rejudging for a preferred result.

## Remaining problems and general remedies

| Problem                                            | Candidate evidence                                                                                                                  | General remedy                                                                                                                                                                                                                        |
| -------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Wrong scroll surface, false completeness           | Luna 011 screened 18 cards against a 72-result heading; document did not scroll but the results pane did                            | Discover scroll containers; target the correct pane; reconcile displayed counts and pagination before claiming all/none                                                                                                               |
| Visual evidence saved but not inspected            | Luna 040 saved a mobile JPEG without attaching it to model context; the judge saw severe reflow that the report missed              | Fixed after this cohort in `b430a91`: attach every explicit screenshot on the worker connection; separate new full-cohort evaluation required. Observer captures remain evaluator evidence                                            |
| Unknown becomes false                              | Luna 001 defaulted sponsorship to false across 134 records from a global negative observation                                       | Nullable/unknown field states and field-level evidence scopes                                                                                                                                                                         |
| Global checks copied into per-record verification  | Luna 007 repeated a few retailer checks across 241 records and was zeroed                                                           | Track observed, failed, unattempted and verified per record; require a real item-level attempt before assigning its outcome                                                                                                           |
| Numeric/task-contract limits ignored               | Luna 025 retained 53 rows despite a 40-row maximum; 039 added an extra schema field and selected the wrong observation date         | Extract an explicit task contract, validate caps/schema/date windows against it, and inspect failures before finish                                                                                                                   |
| Entity/source origin confused                      | Luna 025 used a similarly named company’s board; 009 mapped a repository to the wrong registry package                              | Follow official outbound links; verify organization identity and package/requisition IDs before joining sources                                                                                                                       |
| Numbers parsed incorrectly                         | Luna 029 turned a comma-formatted original price into a small integer                                                               | Keep raw currency text beside normalized values; test locale/grouping parsing and plausible comparisons                                                                                                                               |
| Wrong variant or scope                             | Hard `3pt5r5` substituted 375 g for requested 500 g; `m5zja8` included non-IT tenders                                               | Final constraint audit against exact identifiers, variant dimensions, filters and explicit fallback rules                                                                                                                             |
| Partial batches still lost                         | `0oxfq8` checkpointed every eight records                                                                                           | Save each successful record or bounded batch immediately; use reusable scripts and stable IDs                                                                                                                                         |
| Wrong or unobserved request semantics              | Luna 017 received Explore metadata but twelve widget-data requests returned 400                                                     | Inspect actual network request parameters; compare native UI and export responses; change strategy after repeated identical errors. A 400 alone is not proof of a site blocker                                                        |
| Source meaning altered during extraction           | Luna 012 treated delivery wording as a Prime badge; 021 corrected ASR text while claiming an exact quote                            | Keep raw excerpts separate from interpretation; preserve quote bytes and attach a source location to each derived field                                                                                                               |
| Search/filter state assumed                        | Luna 016 initially used an unvalidated location query; 022 logged friendly URLs not actually visited                                | Record observed URL, applied filters and observation time together; verify the applied state before collection                                                                                                                        |
| Contradictory aggregation                          | Luna 015 counted “not explicitly permanent” as permanent                                                                            | Aggregate from explicit enums/nulls rather than substring matching; reconcile counts against canonical rows                                                                                                                           |
| Synthetic examples presented as observations       | Luna 020 parser examples were not labelled synthetic                                                                                | Distinguish observed evidence from generated fixtures in file metadata and prose                                                                                                                                                      |
| User evidence-retention constraints missed         | Luna 021 saved full source bodies despite a short-excerpt constraint                                                                | Apply the user’s retention policy before writes and exports; keep only permitted excerpts                                                                                                                                             |
| Dead remote Chrome                                 | Luna 002 lost the remote CDP connection and could not finish captures                                                               | Reconnect first; a replacement browser requires provider integration, restoration and uncertain-action checks. That replacement policy is not implemented                                                                             |
| SDK tab cleanup can fail                           | Three Hard cleanup warnings; cloud stop accepted for all 106                                                                        | Preserve cleanup diagnostics and stop the owned cloud session separately; reconnect cannot guarantee a dead target will respond                                                                                                       |
| Draft output conflicts with corrected final output | Luna 042 fixed two source statuses in its final ledger but an older progress file retained the wrong claims; the judge counted them | Distinguish final deliverables from dated scratch/checkpoint evidence using an explicit manifest; keep audit history instead of silently deleting counterevidence                                                                     |
| Judge cannot see every output byte                 | Findings previews are capped at 600,000 characters and 50 files, preserving BrowserCode’s rendering rules                           | Explicit primary-deliverable manifests, bounded evidence retrieval and retained omission metadata; evaluate changes separately because they alter the judging surface                                                                 |
| A model turn consumes the delivery reserve         | Luna 060’s final model-turn span remained open from 04:38:22 to 05:23:04 UTC; the run timed out with no final answer                | Bound individual model and compaction requests inside the whole-task deadline; preserve incomplete output and explicit failure reasons. The current reserve only runs between turns, and the stalled internal phase is not identified |
| Slow result publication / missing audit files      | Task 016 scored before trace/upload completed; hidden summaries omitted by GitHub                                                   | Audit archive is fixed and smoke-tested. Bounded platform publication timeout remains a proposed improvement; the observed delay’s cause was not proven                                                                               |
| Genuine source blockers                            | CAPTCHA, sign-in and 403 outcomes                                                                                                   | Preserve honest blocker evidence; use permitted alternative sources where the task allows them. Runtime code cannot guarantee source access                                                                                           |
| Inconsistent blocked-task judgments                | Copilot/LoopNet/CarMax flips                                                                                                        | Calibrate a consistent impossibility policy; repeat or human-audit judgments separately, without rewriting this cohort's grades                                                                                                       |

Rows above describe remaining problems and proposed remedies, except the explicitly identified archive and later screenshot-delivery fixes. They are not claims that semantic validation, browser replacement or a platform timeout patch has shipped. The general research instructions already address many of these themes; the traces show that instructions alone do not enforce them. No task-specific selector, product ID, benchmark answer or rubric was added to the harness. These datasets have informed development, so a broad SOTA claim requires held-out tasks and replication.

The completed Luna audit checked all 60 judge records: five were zeroed for unsupported/fabricated claims; none reported canary leakage or answer-key access. Fifty-eight detailed judge records came from Laminar spans; two came from their GitHub artifacts. One task (`bub2-060`) reached its one-hour agent deadline. Its final model-turn span was open for 44 minutes 42 seconds, so no later turn could trigger the between-turn delivery reserve. This identifies a deadline-coverage gap, not the exact stalled provider/compaction operation.

## What to build next, without recreating BrowserCode

1. **An explicit task contract and final evidence audit.** Check the original request, exact identities, allowed source/retention rules, row caps, required fields and coverage before accepting delivery. Keep this separate from schema validity. The existing `validateResult` hook can enforce application-specific constraints, but the default harness has no general factual validator.
2. **A small scroll-discovery helper.** Expose scrollable regions, their viewport bounds and before/after offsets. Keep targeting explicit. Test nested panes, frames, shadow roots and virtualized lists on local fixtures before a benchmark comparison.
3. **A record-level evidence ledger.** Preserve raw observed values, URLs, timestamps and scope; distinguish unknown, absent, blocked and never attempted. Generic validation can reject internally inconsistent provenance; it cannot prove that a page observation was truthful.
4. **A deliberate provider recovery policy.** If remote Chrome is dead, local files should remain usable. Replacing a cloud browser must account for lost login state, downloads and actions whose outcome is unknown; no replay of a purchase or submission.

These are scoped candidate remedies, not guaranteed score gains. A blanket second-model “truth checker” would add cost and another source of mistakes without a grounding contract. Do not add delegation, LSP or a plugin platform solely to match BrowserCode’s feature count. Test one concrete remedy against held-out fixtures and a frozen cohort; retain regressions and extra cost.

## Verification and shipping state

Pre-vision reliability package checks: **64/64 tests passed in one full Node 22.23.2 invocation**, using the project Python for the eval adapter. The additional retry-failure test covers exhausted step/cost budgets, cancellation, permanent provider errors and repeated interrupted streams without executing failed-response tools. Six Python integration tests and strict TypeScript checks passed. The suite uses scripted provider responses and real local Chrome fixtures; it proves the exercised lifecycle, browser, schema, recovery and compatibility contracts, not factual research quality. Earlier macOS Python-launcher failures were resolved by selecting the working project interpreter; no failing result is hidden.

Platform tests: 74 Python and 31 UI tests, UI typecheck/build pass. Two pre-existing lint errors remain in unrelated `harnesses/browser-use-harness-sdk/run.py`; that file was not changed. The platform's pre-existing README/packages changes were preserved.

The runtime is pushed to `codex/raw-cdp-k7m2`. No merge, npm publication or production deployment occurred. Roll back by pinning the preceding SDK SHA; existing histories remain readable and ordinary workspace files stay in place. Optional coding tools retain their default-off SDK behavior; they are enabled for the findings evaluation.

Luna cleanup diagnostics: four SDK close attempts failed (`002`, `040`, `054`, `057`); no Cloud stop-request errors were reported across the 60 outcomes. Five observer timeouts on four tasks were contained, and one other task reported a coalesced observer event. Task `038` reported one failed summary because the summarizer hit its output-token cap; the original context was retained and the task completed. This is in addition to the 20 successful compactions, not a successful compaction counted twice.

## Audit archive correction

The frozen full runs predate `2fd83d33ce2ad30383e3a66cd4fe802b13c09140`, which changes only eval artifact packaging, tests and docs. GitHub's default uploader omitted `.browser-use` despite those paths appearing in result manifests. Visible event streams, ordinary deliverables, screenshots and compaction counts survived; hidden summary contents did not. They cannot be recovered retrospectively from those uploaded bundles.

The correction creates `sdk-audit.tar.gz` from regular SDK context/cell/journal files after cleanup. It excludes unrelated dotfiles and symlinks and records archive failures explicitly. Both local browser-backed adapter cases pass as part of the four adapter tests. Remote [smoke 34078962158](https://github.com/browser-use/new-eval-platform/actions/runs/34078962158) passed 1/1 and uploaded 32 cell files plus two journals, with no archive or cleanup errors. Local tests verified summary-file retention too; that remote smoke did not trigger compaction. This evidence correction does not alter the running cohorts or their scores.

Recorder callback counters are separate from the outer observer warnings reported above: this first cohort logged 488 callback errors across 67/106 Hard tasks and 1,635 across all 60 Luna tasks. The counter mixes missing active-page targets and actual capture failures; it is not a count of missing native model images. Luna retained 5,442 judge screenshot paths. See the [latest recorder audit](./vision-results.md#trace-checks-after-the-image-change) for the subsequent cohort and the limits of the bounded error-detail records.
