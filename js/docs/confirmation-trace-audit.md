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

The complete Hard comparison has four losses. Two content failures were also inspected in both arms: `6gvwrd` uses an agent-written prose regex to fill brand fields, producing description fragments as brand names; `mb5m9j` delivers 76 mobile rows with 10 provider-logo placeholders and 30 null plan names. These are field-validation defects despite successful browsing and JSON delivery. The retailer reference and candidate both produced 188 products; the candidate judge's broader inventory-coverage complaint is not independently established here. The other two losses are judge-classified access blocks and are not yet a causal diagnosis. [Full Hard comparison](./iteration-protocol.md#complete-fresh-hard-comparison).

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
