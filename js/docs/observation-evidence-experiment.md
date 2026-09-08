# Preserve evidence across errors and named tabs

The completed delivery-review diagnostic exposed two concrete SDK defects. This candidate fixes evidence transport and observation routing. It does not change the task prompt, delivery-review default, judge, budgets, browser viewport, or retry policy.

## Observed failure and reproduction

A JavaScript cell can capture an image or mutate the browser and then fail. The worker returns `CellError.result` with the captured image, output path and page target. The SDK previously converted it to an ordinary thrown error. Pi consequently emitted text with empty details, discarding the image before the next model turn and leaving the evaluator no target to capture. A real-Chrome scripted-model test reproduces this by saving once, taking a screenshot and throwing: the next model turn must see one native image and `isError: true`, and the subsequent browser read must still say saved exactly once. The test failed before this patch.

Separately, the worker reported the global `page.targetId` even when code used `const other = await tabs.open(...)` or sent raw commands to another session. The diagnostic has 183 nonempty result target IDs, all for the primary page, despite successful named-tab work. The new two-tab test reproduces the mismatch. These defects explain specific evidence loss, not the entire aggregate benchmark regression.

## Change

- Restore a failed cell's native images and structured metadata through Pi's existing `afterToolCall` integration, preserving the error flag. Application hooks receive that evidence and retain their normal override authority. No Pi fork or action replay.
- Keep primary-page recovery and observation targets separate. An additive `observationTargetId` tracks the last protocol target, including named tabs and raw session commands. The evaluator uses it for the existing screenshot operation.
- Map out-of-process iframe observations to the owning top-level page using CDP's reported target/frame relationships. Chrome cannot screenshot an iframe target directly. Recording routes to that page and omits cursor coordinates when they belong to a child frame.
- Preserve the primary target returned with a failed initial cell, so a later worker reset can reconnect to the existing page. The browser action is never replayed.

Tracking is passive: no extra browser calls, automatic navigation, retries, selector rules, task-specific logic or rubric knowledge. A tab list alone does not select a page. An unknown or closed target remains unavailable; the observer does not guess a replacement. Work using separately constructed CDP connections outside the SDK's shared connection remains outside this tracking.

## Compatibility and test scope

No model, dependencies, user prompt, profile, transcript version, public options or legacy Python library change. `targetId` retains its primary-page meaning. Python bundles the same updated engine. Error events now carry images that were previously lost, so next-turn token/image use can increase. Existing caller hooks can replace the content before the model sees it. Whole-cell termination cannot recover images still only in the killed worker; durable files remain available.

Local regressions cover failed-cell image delivery through real Pi and hooks, no later-cell image leakage, exactly-once browser mutation, named tabs, raw session commands, cross-origin frames, reconnect, closed targets, primary recovery after an initial failure, and evaluator PNG dimensions from the named tab after an error. The existing suite also covers cancellation, policy hooks, session persistence and actual MP4/GIF export. The full suite passes **107/107 on Node 22.23.2** (also 107/107 on Node 23.11.0), and **7/7 Python integration tests** pass. Typecheck and the docs build pass. [Source and verification hashes](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/observation-evidence-verification.json). A subsequent **5/5 transport-test pass** includes one new case: a real screenshot from a failed cell reaches the next OpenAI-format HTTP request as a native `input_image`, retaining the error status. This uses a local SSE endpoint, not paid inference; the candidate runtime is unchanged. Remote quality remains unproven until the new frozen evaluations finish.

## Evaluation plan

Run one original-budget diagnostic on Hard task `hukwqv` and one on Luna task `bub2-020`, one attempt each. Freeze the candidate commit and inputs before dispatch. Retain every outcome, actual judgment, screenshot error, runtime error, artifact and usage record. Verify browser cleanup. A low score does not itself fail the integration gate, but missing/broken evidence or an uncontained runtime failure does.

Only after those diagnostics are terminal and audited, select the next full matched arms. Use the corrected screenshot-ownership reference pins `769ea148382cb9094662188a593b0410f6e9f0d5` (Hard) and `c3f7fac2d8a46a3801e06d89a3c3c9b1343db79e` (Luna), whose agent runtime trees remain byte-identical to their historical originals. Candidate evidence completeness is part of the treatment; the judge and evidence renderer remain unchanged. Do not interpret a score gain as pure improvement in agent reasoning.

The original 106/60 task sets, model/reasoning, judges, budgets, one attempt, 12-job full-arm concurrency, historical targets, 3-point margin and frozen 20,000-resample uncertainty procedure remain in force. All previous results remain. These are development benchmarks, not held-out SOTA evidence. Rollback is the prior SDK SHA; never replay uncertain browser actions during rollback.

## Original diagnostic executions

Runtime **`29e2b5e49f6bcd8d9f1ecf1b737d143488abfb2b`** was frozen in the plan before dispatch. Both prepare jobs succeeded, and both task jobs were verified running on September 8 UTC. No original outcome is replaced.

| Task       | GitHub workflow                                                                          | Laminar evaluation                     |
| ---------- | ---------------------------------------------------------------------------------------- | -------------------------------------- |
| `hukwqv`   | [34211867686](https://github.com/browser-use/new-eval-platform/actions/runs/34211867686) | `ad97de9c-b2ea-41c1-b846-5051afd65f23` |
| `bub2-020` | [34211870650](https://github.com/browser-use/new-eval-platform/actions/runs/34211870650) | `e520f1fa-cdf8-4688-8126-d364c9d7fd1b` |

[Exact frozen plan](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/observation-evidence-plan.json) · [Original dispatch record](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/observation-evidence-dispatch.json). These two diagnostics must finish and be audited before the full comparison is selected.

## Hard diagnostic: complete trace audit

The original `hukwqv` execution finished with an actual **Laith score of 0**. It used 65 steps, 892.035 seconds and $3.096148 in agent inference. The model delivered 24 objects, with three Freenet Flex rows missing the requested fields and a Vodafone 280 GB row missing its price. That is incomplete delivery. The zero remains; this audit does not rejudge it.

All **63 JavaScript completions** were inspected for failure and observation metadata. Nine failed: one ambiguous link, one covered link, one failed page fetch, one absent document body after navigation, four CDP timeouts, and one two-minute worker timeout. **Eight of nine** retain an observation target. The exception is the terminated worker, which returned no live result. The model subsequently delivered without replaying the uncertain browser actions.

The evaluator retained **56 captures with seven capture errors**: four screenshot timeouts, two attach timeouts, and one unavailable target after the worker reset. Four failed cells still have evaluator captures. Six cells identify a different observation target from the global primary page because opening or attaching a new page failed before the JavaScript assignment completed; two subsequent list/data-only cells retain that last observation. All six corresponding captures timed out. Thus this run validates retained target metadata, but does not validate successful remote pixels from a nonprimary page. No failed cell carried a native image in this trace either; the local real-Chrome/Pi transport tests cover that path.

The tab list contains 22 pages after speculative URL opens. Resource pressure is a hypothesis, not an established cause of the CDP timeouts. The SDK's final tab enumeration also timed out. The adapter still stopped its owned Cloud browser, independently verified through the Cloud API. Cleanup was contained, not error-free.

Some judge wording needs care: the observed Vodafone page really displays “35 GB instead of 30 GB,” and Otelo displays 125 GB. Their mismatch with requested tiers is not itself fabrication. However, the final's claim that Otelo's 125 GB offer replaces 100 GB is not established by the retained card; a separate unlimited offer says “200 GB instead of 100 GB.” The report preserves those distinctions and the original judgment.

**Decision:** the Hard integration audit is complete. No new runtime patch is justified by this trace alone. The full comparison remains gated on completion and audit of the original Luna diagnostic, with the frozen candidate unchanged. [Per-event classifications, source hashes and cleanup evidence](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/observation-evidence-hard.json).

## Luna diagnostic: complete trace audit

The original `bub2-020` execution completed with a **73/100 Findings judgment**, 191 steps, 1506.168 seconds and $0.54760781 in agent inference. The model produced its capture ledger, normalized data, conflict log and parser brief. Its missing eBay target-currency rows and same-day reference-rate comparison remain explicit; this is partial task success, not a benchmark result.

All **11 failed JavaScript cells retain observation metadata**. Of 139 JavaScript completions, 122 have retained evaluator PNGs and 17 have capture errors: one initial tab list had no selected page, and 16 screenshots timed out. Six failed cells have captures. There are **82 nonprimary observations and 77 corresponding retained captures**. A visual check of `judge_screenshots/048.png`, registered at step 100 after the covered currency-control error, shows the named Airbnb tab's language modal rather than the primary eBay page. No failed cell contains a native image; that transport path remains covered by the local test.

One compaction occurred. The agent then read archived browser observations and used them to construct deliverables. Independent local checks confirm that the JSON parses, four Airbnb rows reconcile subtotal plus tax to total, their raw Unicode codepoint arrays match their strings, and the persisted eBay checkpoint contains 40 pages. The trace separately reports reaching page 49 before page 50 stalled. The final preserves that distinction. These checks establish evidence recovery and internal consistency, not the truth of every delivered claim.

No worker reset or SDK cleanup error is recorded. The owned Cloud browser is confirmed stopped. Both original diagnostic audits are complete. **The next full comparison can now be frozen at the unchanged candidate `29e2b5e`.** The 73-point diagnostic score replaces no prior outcome and does not establish an improvement over earlier runs of this task. [Luna audit, error classifications and artifact hashes](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/observation-evidence-luna.json).
