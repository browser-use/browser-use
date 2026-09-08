# Fourth comparison: trace audit

Candidate `ce3d029607e103f137fc13ad176dcc97b819d8cf`; original Hard workflow [34237112140](https://github.com/browser-use/new-eval-platform/actions/runs/34237112140). This is an audit of the first two completed candidate tasks. The full four-arm comparison is still running, so these selected tasks establish no paired ranking or native-tool advantage.

## Recovery preserves an extracted inventory

Task `ekgysp` receives an actual pass. Its first extractor selected sustainability-badge headings as two product titles. At event 30 the agent inspected a problematic card's DOM, then revised the extractor at event 34. That cell also mistakenly referenced browser `location` in Node and failed at event 35. Reset metadata correctly remained false. The next cell used `page.info()` and reused the existing corrected records.

All 15 final table rows equal the saved corrected data, with product links normalized by ASIN. The repair preserves row order, ASIN, image, price and source for every row; it changes titles and description metadata. Both original and corrected files survive. Eleven screenshots are retained, with zero capture errors, and the owned browser is independently confirmed stopped. A visual check of screenshot 010 confirms the search page and result heading; it does not independently verify every row or variant.

The output includes other-brand sponsored cards among the first 15 observed results. Descriptions are result-card metadata rather than detail-page descriptions. These limits remain visible despite the pass. This is an observed example of the model repairing its own extractor, not proof that every repair succeeds.

## Direct delivery retains all observed cards

Task `dtjvzh` also receives an actual pass. All 60 final Alpha-GPC records equal the saved canonical records. Fourteen screenshots are retained, with zero capture errors, and the owned browser is stopped. These are observed cards, not necessarily unique ASINs. The agent discloses using `data-asin` because it observed no `data-dib-asin`. Its false Prime flag means the requested icon was absent, not that shipping eligibility was independently checked.

Both tasks use JavaScript and `finish_from_js`; neither selects native read/write/edit/bash. Their passes cannot demonstrate a native-tool effect. Original task, config, model, runtime, lock, judgment and artifact hashes were validated. No original artifact was modified, generated scraper rerun, or judgment replaced.

[Hash-backed artifact audit](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/confirmation4-first-delivery-audit.json) · [Frozen comparison](./iteration-protocol.md#fourth-frozen-comparison).


## Provider failures leave missing actual judgments

The original Luna candidate run [34237121250](https://github.com/browser-use/new-eval-platform/actions/runs/34237121250) has two early execution failures: `bub2-008` reports `OpenAI API error (520): 520 status code (no body)` after 34 steps; `bub2-010` reports `Connection error.` after 55 steps. Both report zero SDK provider retries and synthetic assigned zeros with empty rubrics. Neither is an actual judgment. Both owned browsers are independently confirmed stopped.

The downloaded original `bub2-008` event 133 contains the empty failed assistant response and exact 520 message. The `bub2-010` artifact is still pending at this inspection; its result/error and screenshot metadata are retained directly from Laminar. These errors are distinct from browser access or factual-quality failures. The pinned Pi provider supports optional request retries but defaults `maxRetries` to zero; the SDK does not set it. Its separate one-retry classifier missed both error forms.

This cohort is already ineligible under the frozen complete-actual-judgment requirement. All original runs continue to closure; no failure is replaced. A later compatibility patch may handle these transport error forms within the existing retry allowance, but that patch is not in the running candidate and cannot be credited to this cohort.

[Original failures, manifests, usage and evidence hashes](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/confirmation4-initial-provider-failures.json).
