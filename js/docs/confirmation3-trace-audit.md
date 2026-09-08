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
