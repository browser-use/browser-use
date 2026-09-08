# Confirmation trace audit

September 8, 2026 UTC. This is an interim mechanism audit of completed tasks, not a ranking of unfinished cohorts. The four confirmation runs remain pinned to the [frozen plan](./iteration-protocol.md).

## Delivery worked; evidence fidelity still failed

Three large candidate losses were inspected against their downloaded events, final files, and judge trace. Candidate SDK: `f41c5b7116ede9393696b67a166e38f91893163f`; Luna xhigh; [execution 34185579665](https://github.com/browser-use/new-eval-platform/actions/runs/34185579665). The official score is zero for each: the Findings judge applied its global integrity penalty. Those classifications are not proof of intent, and the recorded outcomes remain unchanged.

| Task       | Delivered files | Compactions | Observed mechanism                                                                                                                                                                                                                                                                        |
| ---------- | --------------: | ----------: | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `bub2-016` |              40 |           1 | A 30-row senior-career cohort retains roles whose own evidence describes specialist/planner work with two years' experience, or an expert/consultant title without captured senior-scope evidence. Row-count and employer-cap checks pass without establishing the requested eligibility. |
| `bub2-019` |               8 |           0 | The extraction records native DOM `disabled: false` for sold-out fallback controls. The output construction hardcodes `disabled: true`. It also cites some review pages discovered through search results without clearly recording that retrieval status in the matrix.                  |
| `bub2-021` |              11 |           0 | One final timestamp is copied into five story observations collected across multiple steps. A garbled auto-caption is normalized into a quote excerpt without preserving the raw wording alongside the correction.                                                                        |

All three produced delivered artifacts. Two did not compact at all. Missing files and compaction cannot explain those two failures. That does not isolate the effect of any particular prompt or runtime change.

The control-state finding distinguishes the native `disabled` property from stock status. The saved extraction did not establish every possible ARIA/CSS restriction, so it does not prove that the buttons were actionable. The defect is replacing an observed field with an unverified interpretation. Similarly, the shopper matrix labels older review families and excludes them from exact-variant waterproof claims; it is not accurate to describe every cited review as an invented exact-product test.

There are judge-evidence limits. In `bub2-016`, the judge could not corroborate some WPP summaries from clipped evidence. The full raw ATS payload is retained locally; clipping alone does not prove fabrication. In `bub2-021`, a screenshot supports the speaker identity and the captions contain the company-scale numbers that the judge excludes from its expected ROI population. Preserve the official verdict while separating source fidelity, category scope, and judge interpretation. No alternative scores are substituted.

## Generalized next experiments

The complete Hard comparison has four losses. Two content failures were also inspected in both arms: `6gvwrd` uses an agent-written prose regex to fill brand fields, producing description fragments as brand names; `mb5m9j` delivers 76 mobile rows with 10 provider-logo placeholders and 30 null plan names. These are field-validation defects despite successful browsing and JSON delivery. The retailer reference and candidate both produced 188 products; the candidate judge's broader inventory-coverage complaint is not independently established here. The other two losses are audited below; they involve different access and search-strategy outcomes. [Full Hard comparison](./iteration-protocol.md#complete-fresh-hard-comparison).

These observations motivate experiments, not benchmark-specific rules:

- Keep raw observed values separate from interpreted states and derived labels. Generate final tables from retained records instead of manually reconstructing the fields.
- Record retrieval status and observation time at collection. Keep search snippets, opened-page evidence, collection intervals, and report-generation timestamps distinct.
- Validate eligibility before counting a retained row. An explicit shortfall is preferable to weakening the user's criteria to meet a quota.
- Keep exact excerpts alongside any cleaned transcription or paraphrase. A corrected identity does not make altered text a verbatim excerpt.

The current prompt already requests source provenance, unknown states, canonical datasets, and final reconciliation. These traces show that instructions alone do not enforce those properties. No new evidence framework, source restriction, changed judge, or task-specific selector has been added on the strength of this interim audit. Select the next quality experiment after the complete paired outcomes.

Two further completed candidate losses were inspected: `bub2-035` assigns source authorities using broad text matches such as `ai` and `ust`, creating unrelated source mappings and assigning confidence without per-record verification; `bub2-043` collects a directory but replaces its page-observation timestamp during final file construction. Both have zero compactions. The latter already has a recoverable, timestamped SDK journal in its audit archive. A separate [journal discovery experiment](./journal-discovery-experiment.md) exposes that existing path to the model; it does not alter these outcomes or establish a quality gain.

## Separate provider recovery gap

The same confirmation candidate stopped `bub2-038` after 78 steps and 597.872 seconds with a terminal OpenAI Responses assistant error: `Sorry, something went wrong.` It had zero compactions and used zero SDK inference retries. Its trace ID is `05cadcfa-0373-ab0a-9192-4e1f6c356e3e`. The reference also recorded this error on `bub2-041`. The observed message does not reveal the provider's internal cause or guarantee that retrying will work.

A subsequent SDK patch adds this exact generic provider error to the existing one-inference recovery allowance, including Pi's exact `server_error:` and `unknown:` formatted variants. It applies only to terminal assistant error messages. It does not match an access-denial suffix, retry browser actions, increase the retry count, reset budgets, or turn an error into a successful result. It is separate from the running confirmation candidate and the image-preview fix.

The regression first failed against the previous runtime. Local tests cover preserved JavaScript work, discarded partial tool calls, repeat-error termination, budget/cancellation limits, and Pi's real Responses SSE parser. A synthetic `response.failed` carries a partial JavaScript call; only the later successful `finish` call may execute. Failed inference usage can remain unreported by the provider/Pi, so recorded costs can undercount retries.

No benchmark gain follows from these local tests. The existing full cohorts and their provider failures stay intact. No retry outcome replaces an assigned zero. Public API, profile ownership, history format, and existing Python Browser Use behavior are unchanged; rolling back the subsequent SDK commit restores the previous recovery list.

## Generated transformations can corrupt correct observations

Two additional completed candidate losses were inspected from downloaded tool arguments, canonical data, workbook-generation code, final files and judgments. Their official scores remain **44/100** (`bub2-009`, zero compactions) and **0/100** (`bub2-045`, one compaction, global integrity penalty).

In `bub2-009`, **92 of 95 exclusion reasons are booleans**, while only three are strings. The generated expression `(reason && reason !== 'placeholder') || fallback()` returns `true` for a valid reason, discarding its text. Subsequent validation checks only that reasons are nonblank, so all 92 corrupted values pass. A separate registry classifier calls a truthy JSON object without an `error` property “verified.” That accepts both a crates `errors` response and a PyPI `message: Not Found` response, while a successfully fetched HTML package page becomes “not found/timeout.” The final files contain all three contradictions. These are visible transformation defects, not evidence lost to compaction.

In `bub2-045`, two gated rows explicitly retain `timezone: "Not displayed"`. The workbook generator checks the string's truthiness and labels both “Explicit scheduler timezone.” It also searches for the substring `account` inside “No account observed; contact field required,” turning a phone-data gate into an account notice. The observed unknown/negative states survive in the canonical data but are corrupted by the reporting code. A compaction occurred in this task; it is unnecessary to infer a compaction cause for these directly observed transforms. The judge's additional concern about clipped scheduler evidence remains separate from these reproduced logic errors.

The corresponding `bub2-009` reference scored **82/100**, compacted once, and retained string reasons in all **159 screening rows**. Its generated registry parser explicitly recognizes `Not Found`, `errors`, and fetch-error states; it also compares exported CSV values against canonical records. Those checks are visible in the trace. The reference still failed activity/qualification requirements. The `bub2-045` reference scored **66/100** with 11 retained practices and its own source contradictions. Neither higher-scoring reference is a flawless output, and these paired observations do not isolate a particular SDK change.

The generalized candidate for further testing is semantic validation of generated transformations: test actual missing/error/negative cases, expected value types, and agreement between canonical records and final rendered fields. Presence, row counts and successful JSON parsing do not cover these failures. This observation does not justify hardcoded registry formats, benchmark-specific field checks, or claiming that another instruction guarantees fidelity. The current prompt already requests final reconciliation. Any additional enforcement or review step needs its own budget accounting and evaluation.

[Counts, exact faulty expressions, trace IDs and source hashes](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/confirmation-semantic-audit.json). Raw source payloads stay out of the repository.

## Remaining Hard access losses

Both arms of `pvs7hz` and `8hyexf` have now been inspected, completing the audit of all four negative Hard pairs. Neither is evidence of a CDP action failure.

- **Wikiwand (`pvs7hz`):** both agents encountered sign-in for timeline generation. The reference's direct generation request returned 401. It later inspected the public sitemap, opened an existing public timeline and extracted 34 events from its DOM. The candidate returned the sign-in blocker without inspecting that public source. The distinction is generation versus discovery of an already-public result. This does not prove that generation needs no login or that the candidate browser would have loaded the same public URL.
- **GoDaddy (`8hyexf`):** the candidate's first, unmodified navigation already showed Access Denied; the later user-agent override cannot explain that initial denial. A subsequent ordinary Node fetch returned 403. The reference loaded the same URL, applied the UI filters, and saved the captured export response as a 1,394,697-byte CSV with 10,000 data rows. Access diverged before the task interactions. The trace does not establish which IP, reputation, browser, timing or origin-side factor caused it.

These observations support separating access variability from search strategy and data fidelity. They do not justify changing authentication, browser identity or benchmark tasks to erase the losses. [Paired IDs, metrics and evidence hashes](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/confirmation-access-audit.json).
