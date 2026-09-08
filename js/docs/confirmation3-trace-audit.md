# Third comparison: trace findings

Both Hard cohorts are complete; the two Luna cohorts are still running. This page records selected mechanisms, not an aggregate score or a new acceptance rule. All original outcomes remain in their assigned cohorts.

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

## Missing listings: both extractors pass a positive control

Task `l3gywi` requests a CSV for 27 exact CarMax URLs. Both runs return the same 27 URLs in the same order, with unavailable vehicle data. The reference passes; the candidate fails. Reading only those judgments would miss a significant control in the candidate trace.

The candidate's extractor successfully reads a current control vehicle, including VIN, mileage, price and title, at event 87. It then runs that extractor on every requested URL and records 27 HTTP 404 responses with the page title “404 Error.” Its saved status file agrees with the batch output. There are no candidate tool errors. The reference likewise gets valid vehicle JSON for a current control through CarMax's compare API, then 27 missing car objects with HTTP 404 for the requested IDs.

Both controls support the source-miss interpretation. They do not prove the missing vehicles were permanently unavailable through every possible route, but this pair does not demonstrate a candidate extractor regression. The reference fills the title column with an unavailable label; the candidate leaves it blank and explains the 404s outside the CSV.

Neither initial judge prompt includes the corresponding positive-control stock number. The reference judge later reads its control in a small, untruncated events excerpt. Candidate raw judge command outputs contain its control among large outputs marked truncated. That raises an evidence-discovery question without proving exactly what the judge retained or isolating judge randomness. Both original scores remain unchanged. Do not change extraction logic merely to imitate the passing unavailable-row wording.

## Access differences and an unsupported archive fallback

Three further completed Hard losses show distinct access and verification boundaries:

- **McGrath, `0x65mu`:** the reference reaches live Manly/2095 results. The candidate encounters a Vercel checkpoint and validates selectors on 12 archived homepage cards, including unrelated Hunters Hill and Kellyville Ridge properties. Its final JSON omits the archive/block disclosure and adds unvalidated listing-field and pagination selectors. The fallback yields useful examples but does not establish selectors for the requested live result page. This is a confirmed source-scope gap following different observed access.
- **LoopNet, `55j2o7`:** the candidate's homepage and search route are already Access Denied before it overrides the user agent. The override also fails. It cannot explain the initial block. The reference reaches the filtered listing workflow and reports 52 listings. This audit verifies the access sequence, not all 52 reference records.
- **Instagram, `74rs7g`:** both begin at the same Google profile URL. The reference observes “Here to help” and `linkin.bio/google`; the candidate immediately redirects to login. Its reader fallback also returns login, and two profile API routes return 429. The evidence establishes different access outcomes, not their underlying IP, browser or runtime cause.

The generalized distinction is between source access, target identity and evidence-backed completion. A successful archived-page test cannot certify a blocked live target. A positive control plus per-record misses is stronger than a blanket unavailable claim. A score loss following different site access is not, by itself, evidence for another CDP helper patch. No source-specific fallback or judge change enters the running candidate.

[Four paired manifests, positive controls, exact event checks and original judgments](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/confirmation3-access-and-absence-pairs.json).

## Contradictory source states across delivered files

Task `bub2-019` requests an exact Adidas product record, controls and a comparison workbook. The reference scores 52/100; the candidate scores 37/100. Both encounter an exact-source block. The candidate explicitly separates fallback option groups from its empty exact-page `optionGroups`; the missing exact-source scope remains unresolved.

A separate comparator error is directly reproducible from the saved files. The New Balance product and homepage visits return “Oops! Something went wrong” at events 211 and 247. Event 278 nevertheless assigns `officialHomepageObserved: true` to every comparator. Both New Balance rows retain that flag. The final access log correctly labels those same attempts `access_failed` and describes the support error.

Event 346 reads seven delivered files and checks their counts, brand distribution, model identities, ranks and sizes. Those checks pass without comparing the homepage flag to the access log. The contradiction is already in the transcript archived through event 356, before compaction. Source observations survive; the derived statements disagree.

This reinforces the need to derive status from the corresponding source-result record and reconcile shared claims across delivered files. It does not justify a New Balance-specific classifier. The exact Adidas source is missing in both runs, and the full 15-point score difference cannot be assigned solely to these two boolean values. The original judgments remain unchanged.

[Cross-file values, source errors, validation code and compaction ordering](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/confirmation3-cross-file-state-pair.json).

## Bounded acquisition gain, with an incomplete recovery checkpoint

Task `bub2-006` requests H&M Singapore children's T-shirts, detail verification and material comparisons. The candidate scores 78/100 against the reference's 32/100. Neither compacts or uses the SDK inference retry.

The candidate fetches complete HTML responses in the browser context and parses them with `DOMParser`, in batches of 12 parallel requests. Its final dataset has 295 unique detail URLs with recorded HTTP 200/accessibility states and observed timestamps, consistent with its aggregate verification log. All 295 garment-care fields remain explicitly unknown; generic care-guide links are kept separately. These checks establish internal record consistency, not independent truth for every product attribute.

The reference instead repeatedly navigates several live tabs. It encounters three whole-cell timeouts and worker resets during the wider run. A later raw-navigation path waits only for the product-data script to exist, then receives incomplete JSON while parsing the page. That is a page-data error, not evidence of a corrupted on-disk checkpoint.

The candidate's progress file is weaker than its successful completion suggests: it saves counters and the last batch summary, not all acquired detail records or the pending URL inventory. No worker reset interrupts its detail acquisition. This run therefore supports the bounded acquisition strategy but does not validate full recovery from its checkpoint.

Source scope also differs. The candidate chooses gender filters on a mixed category with reported counts 251/205, while the reference uses dedicated gender paths with counts 274/269. The candidate loses the dedicated-path requirement, and both lose full-catalog boundary credit. Do not present 295 versus 272 unique URLs as a matched product-level coverage comparison or attribute the entire score gain to batching.

Preserve complete response parsing and bounded batches as available strategies. Save records and pending work alongside counters when recovery matters. Keep the original source boundary separate from subsequent expansion. No H&M-specific parser or boundary rule is added to the frozen SDK.

[Batch events, 295-row checks, checkpoint contents and original judgments](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/confirmation3-bounded-acquisition-pair.json).

## Screenshot-error counts are not an outage count

The candidate's final Hard task, `6dpbhs`, has 241 JavaScript completions, 197 without `observationTargetId`, and 44 saved screenshots. Its reported screenshot-error count is also 197. All 20 retained error messages say “Active page target unavailable after cell,” which the adapter raises before attempting a screenshot. The remaining individual error messages are not retained.

Those counts are consistent with missing observation targets, not evidence of 197 renderer stalls or capture timeouts. Browser-independent work can continue without an initialized observation target; a retained primary recovery target is a separate concept. The task fails because the final historical name lacks a verified source chain, with that limitation explicitly disclosed. Keep the delivery failure separate from this capture-metadata count.

[Complete counts, retained messages, final judgment and artifact hashes](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/confirmation3-observer-count-scope.json).

## A reference pass does not resolve contradictory historical clues

The paired reference for `6dpbhs` returns **E. Franklin Tucker** and passes. Its source really identifies the partnership of R.E. Benson and E.F. Tucker, followed by Benson's later photography business. However, the literal task asks for a business in the northwestern United States and a wife with initials G.F.P.

The retrieved partnership record places the business in Revelstoke, British Columbia, in 1907. Benson's later numbered-street addresses are in Prince Rupert, British Columbia, Canada. His spouse is explicitly Gertrude Amelia Freshwater, also listed as Amelia Gertrude Freshwater and Amelia Gertrude Benson. Those observations do not establish either the US business location or the requested initials. The spouse record does mention Mount Vernon, Washington, as both spouses' residence at marriage; that does not establish the business-location sequence. The partnership record also says it was not listed in the 1910 Revelstoke directory, which does not establish a disappearance after 1910.

This is a suspected reference false positive against the literal prompt, or a task-clue inconsistency requiring independent adjudication. The audit does not establish the correct answer. The candidate's unsupported **Ira W. Webster** answer remains a real delivery failure. Both original scores stay unchanged: reference 1, candidate 0.

This completes a detailed audit of the ten negative Hard pairs in the third comparison. They include acquisition and delivery errors, different source access, and questionable judgments. They do not establish ten runtime regressions or one common CDP failure. The remaining source-truth problems warrant general experiments in evidence-backed delivery, not a rule for this historical puzzle.

[Paired manifests, literal clues, source excerpts, original judgments and hashes](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/confirmation3-historical-identity-pair.json).

## Retrieved requirements disappear during normalization

Task `bub2-025` requests official-source technician hiring evidence across eight companies. The candidate scores 40/100; the reference scores 76/100. Four directly checked experience fields among the candidate's six retained Blanchard records contradict their own delivered source excerpts:

| Role                                    | Source excerpt                              | Delivered experience              |
| --------------------------------------- | ------------------------------------------- | --------------------------------- |
| Shop Lead Technician                    | 10+ years preferred                         | not stated                        |
| Shop Technician II                      | 3+ years required                           | 3+ years preferred                |
| Field Preventive Maintenance Technician | One year or equivalent education/experience | not stated                        |
| Shop Technician I                       | 3+ years required                           | Experience preferred; no duration |

The model creates these values as literals in `bMeta` at event 402, attaching the full raw source text separately. The final CSV reproduces the JSON experience and source-excerpt fields exactly for all 40 rows. This is a normalization error, not CSV corruption or a missing browser response. Other fields were not exhaustively audited.

This run compacts before normalization: its archive covers 183 messages through event 364. The summary points to `blanchard-raw.json` and live `bDetails`, but omits the Shop Lead ten-year requirement. Subsequent inspection initially uses wrong object-field names, then previews the beginning of the first raw record before constructing metadata. Full source text remains available in the final records. This supports investigating evidence rediscovery after compaction; it does not isolate compaction as the cause. Several earlier audited contradictions arose before compaction.

Final checks at events 502 and 530 verify required keys, nonempty values, excerpt length, row counts and company access states. They do not compare experience fields against their source excerpts. The general failure is converting an unextracted value into a claim that the source did not state it, and weakening required/preferred distinctions during summarization.

The reference is not a matched record-level extraction control. It uses another Blanchard ATS host, observes ten listings and retains one different role; the candidate observes 48 and retains six. Both lose Blanchard population and summary-consistency credit. Candidate judgment also rejects membership, deliverable shape and boundary quarantine. These four checked values do not explain the entire 36-point score difference. Both scores remain unchanged.

[Field comparisons, compaction ordering, validation code, manifests and hashes](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/confirmation3-source-field-loss-pair.json).

## A recovered timestamp never updates the source record

For `bub2-020`, the candidate scores 48/100 against the reference's 73/100. The original judge findings assign the 25-point difference to observation honesty (15 points) and parser analysis (10 points). Both fail the eBay row-coverage and implied-rate items: neither supplies qualifying marketplace records or establishes complete source exhaustion.

At candidate event 492, the agent assigns the literal `2026-09-08T11:00:00Z` as the common ECB observation time. At event 520 it reconstructs later timestamps, `11:01:00.163Z` and `11:03:43.011Z`, yet the earlier literal remains in both `/standards/ecb/observedAt` and `/sources/6/observationAt` in the delivered source archive. Both the invented literal and the later recovered times precede compaction; the archive ends after event 537. Source timing recovery therefore occurred without correcting its dependent records.

The candidate brief discusses display precision and minor units, but gives no explicit rounding rule or quantified headline/detail comparison. The reference preserves `$3,239` versus `$3,238.39`, explains the $0.61 difference, and states a rule to retain both. The two agents use different Airbnb listings and stay dates, so detail availability differs. This is missing requested analysis, not a demonstrated arithmetic or browser parsing bug.

The general target is to derive repeated facts from one corrected source record and recheck dependent deliverables after corrections. A hardcoded time plus later clock inspection is insufficient. The original scores remain unchanged, and no eBay-specific acquisition rule or currency-specific validator is added.

[Timestamp creation and recovery, original judge findings, weights and artifact hashes](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/confirmation3-timestamp-and-coverage-pair.json).

## Real tests cover the wrong transformation

Task `bub2-039` compares opening jump balls and first made baskets across three NBA games. The candidate scores 64/100; the reference scores 84/100. Neither compacts. The candidate's saved roster places Mark Sears on Denver, and ESPN's play-by-play says he gains possession. Its generated record nevertheless assigns the tip team to Toronto, which scored the first basket.

At event 234 the agent really tests its `classify` function with same-team, different-team, missing and unavailable inputs. The function compares the two team strings correctly. However, the records supplied to it contain manually assigned team names, so those tests do not check the raw-roster-to-team mapping. Recomputing the relation from the original saved rosters and first made field goals gives **2/3**, while the delivered brief claims **3/3**. This is evidence of validation at the wrong layer, not evidence that the model never tests.

All three candidate `winner` fields identify the possession recipient rather than one of the two jumpers; the Denver game's team assignment is an additional, independently checkable error. Both arms also add a game ID inside `game_details`, beyond the requested fields. The candidate prints the key lists at event 254 but does not assert an exact allowed-key set.

The general lesson is to validate source-to-record mappings, entity roles and joins before testing downstream arithmetic. A correct comparison cannot repair incorrect inputs. The offline audit uses the recorded roster/event relationship; it adds no NBA parser, task-specific rule, runtime change or new judgment.

[Three-game source re-derivation, actual generated tests, original judgments and hashes](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/confirmation3-source-mapping-pair.json).

## Coverage replacement triggers a whole-task penalty

For Toronto rental task `bub2-038`, both arms earn **62/100 rubric weight**, on different items. The candidate's official score becomes **0/100** after a suspected-reward-hacking flag; the reference retains 62. That categorical penalty is not evidence that all candidate work was absent, or proof of intentional gaming.

The saved coverage transformation contains independently checkable errors. HotPads query output at event 239 reports **8, 14, 12, 752**; event 470 replaces all four with the constant **752**. The liv.rent query loop reports **null, null, 7, 15**; the coverage file instead records **0, 0, 0, 1**, mixing later category-page observations into the earlier query timestamps. Those different source scopes should remain separate. This audit verifies the replacements, not the true full platform populations.

Two original screenshots corroborate additional discrepancies. `014.png` shows Kijiji garden-suite results **1–40 of 51**, while the report uses 41 extracted links/cards and claims exhaustion. `077.png` shows listing cards and prices behind Facebook's login modal; the log says no listings were visible. Public card visibility and access to deeper details are separate states.

The coverage code is written at event 470. Compaction later archives through event 515, including the incorrect coverage. The final checks count files, records, queries and links; they do not reconcile query-level counts with their observations. These errors precede compaction. The reference also has unsupported inventory and duplicate claims, so its retained 62 does not certify a fully correct result.

Preserve each observation's query, source scope, count and time together; derive coverage tables from those records instead of substituting constants. Retain the original scores and flag, with no task-specific rule or changed judge.

[Exact count replacements, visual checks, original penalty and source hashes](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/confirmation3-coverage-replacement-pair.json).
