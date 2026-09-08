# Second confirmation: trace audit

September 8, 2026 UTC. These are early completed negative pairs from the [frozen second confirmation](./iteration-protocol.md#second-frozen-confirmation). The full cohorts are still running. This selected audit diagnoses mechanisms; it does not estimate their prevalence or establish a ranking. No official score changes.

## Access differs before extraction

**Apartments.com, `f8cgvy`: reference 1, candidate 0.** The candidate's initial unmodified homepage and city-page navigation showed Access Denied. Its user-agent override came later and cannot explain that initial denial. The reference loaded the site and exported 37 Burleson rows from 43 loaded cards. It also recorded some 403 detail requests. Its page reported 747 rentals, while the export was scoped to loaded cards; the relationship between rental units and card count was not independently established. Different access outcomes do not identify whether IP, reputation, timing, origin behavior or another browser setting caused them.

**AliExpress, `cfzw0l`: reference 1, candidate 0.** Both reached search, then selected different products. The candidate encountered product-page CAPTCHA and mobile sign-in, probed review API variants, obtained aggregate rating counts, and ultimately returned no review text. The reference loaded a different product, selected latest in the review UI and extracted dated comments. The official candidate class is `site-blocked`, but the trace does not establish that every qualifying product or public UI path was unavailable. This is a combination of product choice, access and strategy, not an independently proven CDP action regression.

An exact-source comparison of Hard reference `58ed778` and candidate `65a16cb` confirms identical Cloud browser-creation payloads and identical `Tabs` source. Both request the same US proxy setting, 1440×900 screen, lifetime and recording flag; both create an about:blank target, attach, then navigate. Connection initialization and observer attachment behavior did change. Neither that source difference nor matching requested settings establish the cause of different access outcomes: actual exit IP, reputation, browser version and site timing were not independently matched. [Setup audit](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/confirmation2-browser-setup-audit.json).

## A label is not selected state

**Target, `bub2-005`: reference 100/100, candidate 68/100.** Both executed the category task and delivered artifacts with zero compactions. Each retained its original logged-out context: the reference showed Harker Heights/76522 and 29 cards; the candidate showed Laurel/20707 and 30 cards. Those different live grids are not themselves extraction errors.

The candidate wrote its sort field from:

```js
sort_display: clean(
  sortButtons.find(b => b.dataset.test === 'facet-button-New & Top Rated')?.innerText
)
```

That reads a separate filter facet. It does not establish the selected sort. The reference opened the Sort dialog and observed `{ value: 'Featured-Featured', checked: true }` without changing it. The candidate's actual selected sort was not independently captured. The source-state defect is claiming a selection from an adjacent label.

The candidate also summarized four displayed prices, **6.29, 3.59, 2.99 and 5.99**, as a mean of **4.71**. Their exact decimal mean is **4.715**, or **4.72** under decimal rounding to the nearest cent with ties rounded up. The generated code averages binary floating-point numbers and calls `toFixed(2)`. A local reproduction returns `4.7149999999999999` and then `4.71`. The final CSV and Markdown contain that value. This is generated arithmetic behavior, not an SDK serialization defect. The official judge penalized internal consistency separately from the sort claim.

The task did not specify a rounding convention. This reproduction explains the disagreement with the judge's decimal expectation; it does not establish a browser failure or justify changing the recorded score.

## Recovery lost product identity

**Amazon, `0oxfq8`: reference 1, candidate 0.** The candidate delivered 29 rows but only 28 distinct URLs. Its search inventory identified `B0HCBWJNQ6` as an Aurant laptop; its progress record assigned that ID the title, specifications and URL of the preceding search product, `B0HF7SXJT8`. The final export retained the duplicate. The candidate recorded zero compactions; the reference's older result has no compaction counter. The reference's 51-row output passed the official judge, which is not an independent exhaustive audit of that output.

The candidate hit three 120-second JavaScript cell limits and recovered from saved progress. Before the third batch it had 23 records. That batch introduced the affected record with a generated `extractFast` helper:

```js
try { await page.cdp('Page.navigate', { url: product.url }); } catch {}
await page.waitFor(() => document.querySelector('#productTitle') ||
  /* challenge text or */ document.readyState === 'complete',
  undefined, { timeoutMs: 9000 }).catch(() => {});
try { await page.cdp('Page.stopLoading', {}); } catch {}
// Extract current DOM, but assign ASIN from the requested product.
```

The readiness predicate accepts any product title. Extraction sets `URL` from `location.href` and `ASIN` from the input without checking that they refer to the same product. It also allows the search title to establish `retrieval_status: 'observed'`. Subsequent retries select only records not marked observed, so they skip the mismatched record. Final validation counts missing fields and rows; it does not check product identity or duplicate URLs.

A deterministic mock running the unchanged generated functions reproduces the defect: navigation throws while product A remains readable; the helper returns A's URL/title with requested ID B and marks it observed. This proves the helper accepts stale content after a failed navigation. It does **not** establish which CDP response or redirect occurred during the original Amazon batch. These are batched tool traces without per-command navigation events. The helper bypasses `page.goto`, so this case does not prove a bug in that SDK method.

The general lesson is to validate source identity after uncertain navigation, preserve failure/unknown states, and include those states in helper tests. A blanket navigation retry could repeat actions or hide a legitimate redirect. No site-specific identity rule or SDK patch was added from this audit.

## Recovery and artifact delivery

**Luna, `bub2-001`: 73/100.** One inference retry followed `OpenAI Responses stream ended before a terminal response event`. The failed response contained thinking, with no partial tool call; 55 completed tool calls followed. This exercises the existing truncated-stream recovery branch, not the new generic-error branch or partial-tool suppression. Failed-response usage was recorded as zero, so the recorded agent inference cost can undercount provider usage.

**Luna, `bub2-011`: 60/100, task job succeeded.** The SDK recorded a 20-second `Target.getTargets` cleanup timeout, but the Cloud browser was independently confirmed stopped. The error does not distinguish initial enumeration from final disappearance verification. The judge logged its score at 07:15:21 UTC; the same original task job uploaded evidence at 07:29:27–28 UTC. Its log recorded a Laminar trace-export `DEADLINE_EXCEEDED` at 07:29:25 UTC. This confirms an exporter failure near job completion, not the cause of the entire delay. The original artifact is available and the actual judgment is retained; no task was redispatched.

## Implication for the next decision

Three additional pairs sharpen the distinction between execution and quality:

- **Home Depot, `bub2-004`: 92 → 70/100.** The candidate recovered from a five-minute model-response timeout containing the partial JavaScript argument `const genQs=['`. Its tool ID never appears in an execution or result event; 141 tool-end events followed. This observes partial-call suppression and continued work, not a score benefit or proof the model was stalled. The candidate's original Home Depot searches returned error pages where the reference reached results. Both omitted a sample-product duplicate from delivery; the candidate preserved a pallet duplicate that the reference omitted. The candidate also retained a conflicting Pro Desk number from an indexed Home Depot review/home-services result, explicitly labelled as conflicting while the primary phone was correct. The judge penalized its lack of direct official-page verification. That ruling is not a reason to delete observed conflicts or call the number invented.
- **Vodafone, `hukwqv`: 1 → 0.** The candidate observed the requested 280 GB option after changing age eligibility. Its extractor still searched the adult radio group, `option-picker-gm-tariff`, while the actual group had become `option-picker-young-tariff`; the saved young-plan array was empty. A later inspection exposed the correct controls, but the agent changed bundle eligibility and delivered the adult 120 GB substitute with an adult-scope caveat. It did not preserve the observed 280 GB option with its price unresolved. The candidate had zero compactions. The reference included the young 280 GB plan and disclosed the missing exact 10 GB tier, so its pass does not establish perfect tier coverage either.
- **Banana Republic, `95g3v2`: 0 → 1.** This gain is not proof of better source preservation. Both final answers omitted the 2024 sale and reached similar conclusions. The reference scanned stripped raw HTML, found 40% plus 20% sale text, then broadly claimed no such promotion was found. The candidate inspected rendered text from selected weekly snapshots. At its September 3 timestamp, the reference's own scan also lacked that sale text. Snapshot selection, raw HTML versus rendered evidence, and judge interpretation differ; visibility of every raw scan hit was not independently established. The candidate also saved intermediate extraction files despite the user's no-files instruction. Keep the official pass and those limits.

[Exact controls, source hashes, retry events and case evidence](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/confirmation2-additional-pairs.json).

Successful browser execution, delivered files and matching row counts still leave source interpretation and numerical validation unchecked. A generic instruction to verify does not prove those checks happened. Keep these outcomes and the completed [semantic diagnostic](./semantic-validation-experiment.md#completed-diagnostic) alongside the full results before selecting another full-cohort treatment. Candidate `65a16cb`, references, tasks, judge and budgets remain frozen. Separate source inspection found that `snapshot()` discarded Chrome's control states; the [prepared accessibility correction](./accessibility-state-experiment.md) is independently testable but is not established as the cause or cure of these score differences. No task-specific selector or changed judgment was added.

[Early paired cases](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/confirmation2-early-trace-audit.json) · [Amazon identity evidence and mock](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/confirmation2-amazon-identity.json) · [Inference retry evidence](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/confirmation2-retry.json).
