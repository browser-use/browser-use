# Third comparison: trace findings

The four full cohorts are still running. This page records selected mechanisms, not an aggregate score or a new acceptance rule. All original outcomes remain in their assigned cohorts.

## First differing Hard pair: a repair replaced good fields

Task `3qsqcq` requests product titles, prices and sellers from an Amazon search page. Reference `769ea14` passes; candidate `29e2b5e` fails. The reference delivers 15 rows. The candidate delivers 56, with four colour/pattern navigation labels in the title column.

The candidate initially extracts titles from headings, but cannot find product links through its assumed heading/link structure. While fixing links, it also changes the title extractor to prefer the first product-link text longer than 20 characters. That can select “+4 other colours/patterns” instead of the product name. The earlier source observation already contained the real title for one corresponding priced card.

The agent inspects the first five and last five records, then the first ten unique records. The bad final titles occur at rows 12, 16, 18 and 24, outside those samples. Its final verification checks counts, page identity and merchant IDs. It never compares changed title fields with its earlier heading observations.

`finish_from_js` then delivers the constructed table unchanged. Both artifacts' final text equals the SDK result text. Neither run has a tool error. This is a model-written extraction error, not a demonstrated transport regression. The candidate openly maps a shared merchant ID to the seller name observed in one buy box; that is different from individually checking 56 offers, but this audit does not establish that the mapping itself is false.

The general problem is **repairing one field while silently degrading another**. A potential mitigation is to preserve verified fields by stable record identity and compare replacements against earlier observations. Nonempty fields and head/tail samples are insufficient validation. The current prompt already asks for field-meaning checks; this trace shows the model did not perform the relevant check.

No site-specific selector, blacklist, row cap or extra model review enters the frozen candidate. One selected loss cannot establish which SDK change caused the model's choice. The reference also chose a smaller output scope, and the live result sets differ. Reassess after the full paired comparison.

[Exact event indices, artifact hashes, manifests and original judgments](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/confirmation3-first-pair.json).

## Coverage loss after successful source discovery

Task `rlexdw` asks for each row of a court opinions/orders table. The reference delivers 18,928 rows and passes. The candidate delivers the 25 visible rows and fails.

The candidate discovers the table's server-side source, reads its reported total of 18,928 records, and successfully requests three records using the observed AJAX parameters. It then switches back to extracting the visible DOM rows. Its final answer explicitly says “currently displayed table rows” and includes “Showing 1 to 25 of 18,928 entries.” No intervening tool failure explains that choice.

The candidate finishes after 65.529 seconds and 11 steps, within budgets of 1,700 seconds and 1,000 steps. There is no compaction, provider retry or delivery repair. Its one earlier CDP serialization error was followed by successful source inspection and the successful request. `finish_from_js` delivers the 25-row answer unchanged.

The reference requests all 18,928 records using the page's AJAX parameters, receives them in 2,894 ms, checks required fields and count, and delivers 4,301,497 bytes of JSON. The complete reference run takes 90.911 seconds. These observations establish a premature reduction in delivered scope, not a transport limit. They do not prove that an unattempted complete request in the candidate's separate session would have succeeded.

The candidate already has instructions to reconcile pagination and source inventory before delivery. It did not perform that check. Keeping requested coverage explicit through completion is a generalized mitigation to investigate; adding another reminder is not yet a demonstrated fix. No endpoint rule, fixed row count or extra review is added to the frozen candidate. The pair does not isolate which SDK or prompt change caused the model's choice.

[Coverage evidence, original judgments and artifact hashes](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/confirmation3-coverage-pair.json).

## Similar blockers, different judgments

Task `84xyjo` asks for the complete Copilot response to an exact query, at an exact URL. Both runs encounter a sign-in wall, inspect the page, try Escape, wait, and return a blocker report without submitting the query. Both saved screenshots were visually inspected: they show three sign-in choices and no visible chat composer or dismissal control.

The reference judge passes the documented impossibility. The candidate judge fails the missing requested response. This difference does not demonstrate a browser capability that the reference had and the candidate lost. It also does not isolate pure judge randomness: the trajectories differ, including additional cookie/cache clearing and same-origin API/script exploration by the candidate. The judges' explanations do not cite those actions as the reason for the different verdicts.

Both original scores remain in the comparison. No rejudgment or replacement score is used, and the harness is not changed to imitate the passing final wording.

[Blocker evidence and original judgments](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/confirmation3-blocker-pair.json).

## A candidate win: saved rows survive a worker reset

Task `0oxfq8` requests laptop details from individual product pages across two Amazon search pages. The candidate passes with 43 records; the reference fails with 42 partial records derived from search results after repeated browser/runtime errors.

The candidate saves its records after each product. A batch then reaches the 120-second cell timeout and loses JavaScript state after processing row 32. The next cell reloads exactly 32 saved records. It skips saved ASINs during subsequent collection and delivers 43 records. The final JSON exactly projects the requested fields from the saved records. This is direct evidence that saving incremental results helped recovery through a worker reset.

The passing trace still has a gap: it did not save the original pending inventory or extractor code. It recollects the live search after reset and observes 42 unique items instead of the original 43. It then reconstructs its remaining work. Final count alone cannot establish that the original inventory was preserved. The extractor's `observed` label is also a model-written classification, not an independent check of every field.

The general lesson is to persist pending targets and reusable code alongside completed data. This selected win supports the recovery mechanism without proving that every current recovery path preserves task scope. It does not justify replacing the frozen candidate mid-run.

[Recovery events, artifact checks and original judgments](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/confirmation3-recovery-pair.json).

## Review access: retrieval strategy and an unverified sort

Task `cfzw0l` asks for a smartwatch with more than 20 reviews and a summary of its most recent reviews. The reference passes with a summary; the candidate reports that review text is blocked and fails. They select different products.

Both encounter access problems. The reference tries several feedback URLs and obtains JSON from one endpoint after an HTML endpoint reports “System is busy.” The candidate tries the HTML endpoint, a legacy service that returns empty records, script inspection, speculative review API names and alternative page forms. Its recorded JavaScript never explicitly calls the reference's successful `searchEvaluation` endpoint. It stops after 71 steps and 521.658 seconds with product statistics but no review summary. This is a difference in retrieval strategy and observed access, not an isolated loss of raw-CDP capability.

The reference's pass also needs qualification. Its nine sort-parameter trials return the same 20-date sequence, and none is descending. It subsequently collects 120 reviews from six pages, sorts them locally, and selects 60. That establishes the newest reviews within its retrieved subset, not the globally newest reviews among the reported 2,140. The official pass remains unchanged.

Two general problems follow: distinguish an unavailable route from unavailable source data, and verify filter/order behavior from returned records. Repeated speculative requests are not progress without new usable evidence. No AliExpress endpoint rule or CAPTCHA bypass is added to the SDK from this pair.

[Access paths, sort checks and original judgments](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/confirmation3-review-access-pair.json).

## Interaction loss followed by unsupported completion

Task `mlgses` asks to pass the first trending chess puzzle. The reference reaches a visible solved state and passes. The candidate returns “Done” after an API submission and fails.

The candidate initially reads the welcome dialog successfully. Its next accessibility calls time out, followed by JavaScript evaluation failures. Reconnecting does not restore control: `Page.enable` times out, while browser-level target listing still works. A separate tab also stalls. The candidate has eight tool errors and 48 evaluator screenshot errors. These observations locate the failure around page/session control, but do not establish its cause. Screenshot errors correlate with the stall; the trace does not prove the observer caused it.

The reference dismisses the dialogs, enters the rated puzzle workflow, moves pieces through browser clicks, and reads “Solved” and “Great stuff!” from the page. The candidate instead fetches a rated puzzle through RPC and submits the returned moves. Rated submission returns 401; unrated submission returns 200 with empty JSON. A subsequent request returns a different puzzle. None of that establishes the requested trending identity or an on-page solved state, yet the final answer says “Done.”

Browser recovery and outcome verification are separate problems here. A transport reconnect does not fix every renderer stall, and success from another execution mode does not by itself prove the requested outcome. The reference judge also accepts a rated puzzle without strong evidence of trending rank. Both official scores remain unchanged; no external actions are replayed to repair this comparison.

[Interaction sequence, errors and original judgments](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/confirmation3-interaction-pair.json).

## Luna research loss: working files became delivered content

Task `bub2-003` requests a current Modi briefing, article spreadsheet and supporting analysis, with no full article reproduction. The reference scores 78/100; the candidate scores 50/100. This was the largest loss among seven shared completed Luna pairs at selection.

The candidate writes three raw extraction batches while researching. Their 15 records contain 80,762 characters of page text, including an empty article body. All three files enter the evaluator's output-file collection in full, without clipping. The final brief uses paraphrases, but those raw files are surfaced alongside it. The existing collector treats ordinary workspace files as outputs; the SDK does not distinguish working evidence from files selected for delivery.

The candidate also retains the article with no body evidence and labels a primary itinerary page “verified page” after finding it in search. Its explicit direct-page loop does not open that itinerary. An additional exact event date is unsupported according to the judge. These are different problems from losing source text in compaction: the raw evidence survives, but canonical claims and delivered content exceed it. The reference also loses record-fidelity and primary-document criteria; it is not a perfect factual reference.

A possible general improvement is explicit delivery selection around a persistent workspace, with all working evidence retained for audit. This must not become an evaluator trick that hides mistakes: scratch evidence remains available, and the original score cannot change. Source discovery, metadata access, body access and verified claims also need to remain distinct when the agent builds its records. File existence and article counts do not prove those transitions were justified.

[Raw-file accounting, event indices and original findings](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/confirmation3-research-delivery-pair.json).

## Luna coverage gain: resolve empty slots rather than exclude them

Task `bub2-005` requests every card in Target's first category-page grid, preserving repeats and recording unloaded cards. The candidate scores 88/100; the reference scores 60/100. This was the largest gain among the same seven completed pairs.

The candidate observes 20 loaded cards, registers a condition wait and scrolls. The next result reports 29 loaded cards; a wrapper inventory confirms all 29 slots. It inspects grid children to separate ad modules from product cards and extracts one record per wrapper, including an explicit unloaded fallback. The delivered ledger has 29 ordered rows and 28 unique product IDs.

The reference's own final page observation reports 29 wrappers, 24 loaded cards and five empty wrapper IDs. It delivers 24 rows and claims the other five are outside the page-one boundary. Its evidence does not establish that exclusion. Separating structural inventory from loaded records explains the visible behavioral advantage here; it does not isolate which runtime change caused it.

The candidate still delivers contradictory breadcrumb metadata. It adds a corrected visible breadcrumb but also retains the stale, incorrect breadcrumb list. Correcting one copy does not update the others. This repeats the broader issue of canonical observations and derived outputs drifting apart.

The two sessions have different logged-out locations and result inventories: Waterford/286 results versus Baldwin Park/267. The comparison therefore does not isolate prices or identical product sets. Neither task uses compaction or provider retry. All original outcomes remain unchanged.

[Grid transitions, file checks and original findings](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/confirmation3-grid-coverage-pair.json).

## Verification loss: correct observations became contradictory claims

Task `bub2-009` requests a browser-automation project landscape with per-project source verification. The reference scores 38/100. The candidate earns 50 rubric points but receives an overall zero for suspected fabricated verification. Both have one compaction.

The candidate successfully fetches the Grizzly package from PyPI: version 1.3.0, released August 20. It then correctly records the package and installation command. But its manually built package-version map omits that project, so the final verification table says no relevant registry package was located. The exact successful response survives in the SDK's archived cell output. This is a contradiction introduced during output construction, not missing source access.

Another final row contains both `pushed_at = 2026-02-19` and a generated claim that the project was pushed September 6. The table assigns all 50 projects the same “Verified in project README/docs” installation status. License, runtime and activity verification labels are also constructed from generated row values rather than retrieval outcomes.

These errors precede compaction. The archived transcript includes the erroneous generation at events 337 and 357 and ends at event 407, after the table was created. Compaction therefore cannot explain the initial creation of these particular contradictions. This does not establish that compaction is harmless on other tasks.

The reference also assigns blanket `PASS` to its 52 verification rows, including rows with blocked or missing registry checks. The original judgments remain 38 and 0. Shared weak labels do not prove equivalent severity or isolate judge randomness; this audit does not infer deliberate intent.

The general problem is converting observations into claims without preserving their connection. Derive verification status from actual checks, preserve unknown states, and compare final canonical fields with their source observations. More retained context alone would not resolve this case. No project-specific mappings or prompt reminders are added to the frozen candidate.

[Contradictory rows, preserved source response and compaction ordering](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/confirmation3-verification-contradiction-pair.json).

## Stream recovery gain: progress resumes, coverage remains incomplete

Task `bub2-007` requests a complete Walmart search sequence and per-record Walmart, Nike and authorized-retailer checks. The reference scores 0 after inventing checked access outcomes for 40 supplemental records. The candidate scores 66/100. Neither compacts.

The candidate's model stream exceeds its 300-second deadline at event 121. Its incomplete JavaScript call never receives a tool-execution event. A new page-five navigation executes at event 123 and succeeds. The next assistant message's timestamp is 300,009 ms later; these timestamps do not identify the last successful stream chunk. The evidence supports recovery without executing the partial call, not a diagnosis of why the provider stopped completing the response.

The run continues to 219 placements and 209 deduplicated cohorts. Its saved Walmart checks contain 80 observed pages and two blocked/error pages. The detailed product file marks the other 127 records not attempted. It derives final outputs from those saved files. The summary verification log still merges blocked and unattempted Walmart states, showing how status distinctions can disappear between output formats.

Recovery does not establish full coverage. The visually inspected screenshot after step 68 shows page six selected and pages seven and eight exposed; those pages are absent from the collected sequence. Only ten of 73 discovered style identifiers receive Nike searches and ten receive Foot Locker searches. The final output reports zero strictly verified products, three partially supported, and 206 unknown/unverified.

The reference instead assigns `blocked_robot_or_human` to every supplemental record after attempting two different, non-cohort product URLs. The judge zeroes those unsupported per-record access claims. The candidate's PII flag concerns public reviewer names captured from product pages; the judge separately confirms no personal-data entry and awards the conduct constraint.

Preserving incomplete streams without executing their calls is useful recovery behavior. Persisting the pending inventory and retaining per-record attempt states across every output remains a separate requirement. The candidate initially had Walmart access while the reference was blocked, so this pair cannot isolate how much of the score difference recovery caused. Its SDK cleanup reports a timeout; the independent owned-browser audit verifies Cloud cleanup separately. Both original scores remain unchanged.

[Stream events, per-record counts, screenshot hash and original judgments](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/confirmation3-stream-recovery-pair.json).
