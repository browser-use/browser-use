# Validate before batching

An exploratory prompt treatment, prepared while the first matched cohorts run. It changes no browser helper, model setting, deadline, output schema, evidence renderer or judge.

The first candidate's `y72ivg` trace returned an empty extraction on a loaded search page, then reused the same extractor across nine model searches. Later navigation hit an access challenge. The reference also began with an empty extraction, inspected the observed structure, repaired its selector and obtained prices before batching. These different trajectories support testing an extraction-validation rule; they do not prove that a prompt change will reproduce the reference's access or score.

The separate SEC smoke selected a subset of statement tables and truncated rows. It had a reduced turn budget, so its score is not comparable with the full cohort. The task gives examples of statement titles rather than explicitly requiring every statement family; judge acceptance of additional families varied. Truncated rows are a separate, concrete completeness problem.

## Treatment

- Validate extraction on the observed page before batching. Empty extraction needs a verified empty state or a repaired extractor.
- Stop a batch after extraction failure, preserve per-record status, and avoid repeatedly applying the same failing code.
- Reconcile the original request with a source inventory, including pagination and continuation content. A self-selected subset cannot establish completeness.
- Preserve raw field labels, values and units; verify exact entity/variant identity and use the user's explicit fallback for missing items.

The prompt contains no benchmark IDs, site selectors, expected answers or grader rules. Existing overlapping research guidance is condensed. This remains model guidance, not a factual validator.

## Diagnostic and full runs

The paired diagnostic on `y72ivg` and `nngh8r` finished **2/2 in both arms**, using the full Hard per-task budgets. It showed no score advantage. The new `y72ivg` trace did show the intended behavior: inspect the page structure, repair the extractor, and obtain prices before batching. These are development cases, not general improvement or SOTA evidence.

After both original Hard cohorts finished and all outcomes were retained, the extraction-only commit `4a09ee3db96e8cbdda3c2e794d5916c9e687c335` was dispatched on both complete benchmarks:

| Cohort  | GitHub execution                                                                         | Laminar evaluation                     |
| ------- | ---------------------------------------------------------------------------------------- | -------------------------------------- |
| Hard106 | [34177962942](https://github.com/browser-use/new-eval-platform/actions/runs/34177962942) | `74cc6d1a-175d-4ffd-ab1d-e7d9ec2930de` |
| Luna60  | [34177966044](https://github.com/browser-use/new-eval-platform/actions/runs/34177966044) | `eceb7b97-1623-44cf-8266-d0a839a629ae` |

These exploratory runs keep the original platform, task IDs, model/reasoning, judge, per-task budgets, and 12-job concurrency. They compare against the existing `0baa51d` cohorts, with different run timing. No task outcomes are replaced. Fresh confirmation is still required after selecting a candidate. The later [workspace delivery fix](./workspace-experiment.md) is **not** part of this extraction-only treatment.

## Complete Hard result

The extraction-only candidate scored **90/106**, with **106 actual judgments** and **$120.97502** recorded agent inference cost. The workflow completed successfully. This is one task below the historical 91/106 peak. The later workspace, additional provider-retry, and context-archive fixes are not included in this result.

| Comparison | Reference passes | Candidate passes | Gains / ties / losses | Paired delta | 95% task-bootstrap interval | One-sided 95% lower bound |
| --- | ---: | ---: | --- | ---: | --- | ---: |
| Prior candidate `0baa51d` | 82/106 | 90/106 | 15 / 84 / 7 | +7.55 pp | [−0.94, +16.04] pp | 0.00 pp |
| Historical-reference SDK `58ed778`, rerun | 84/106 | 90/106 | 13 / 86 / 7 | +5.66 pp | [−2.83, +14.15] pp | −0.94 pp |

Both exploratory lower bounds clear the prespecified −3-point margin. Neither comparison is fresh confirmation: cohorts ran at different times, and this candidate was developed using inspected failures. The intervals do not establish a causal improvement or public SOTA. Historical scores remain descriptive; the historical reference's 84/106 rerun does not replace the 91/106 target.

The candidate recorded no compactions or SDK inference retries. Its 16 zero scores have judge-assigned classes: seven site-blocked, four source-scope-drift, two source-limited, and one each wrong-record, missing-required-fields, and empty-result. One task (`aoim45`) recorded an SDK cleanup error from a CDP target-list timeout. These classes do not establish root causes.

The last workflow job, `sw2292`, published a passing judgment before finishing its telemetry work. It eventually succeeded and uploaded artifact `10039161155`, which was downloaded and checked against its completed result and actual judgment. Its job log reports a Laminar trace-export `DEADLINE_EXCEEDED`; root and model spans subsequently became queryable. This separates a telemetry-delivery problem from an agent failure. Exhaustive span completeness and the cause of every minute of delay were not verified.

## What the passing traces actually show

- **Extractor repair (`y72ivg`):** the diagnostic demonstrated inspecting the loaded structure and repairing an empty extractor before batching. Both diagnostic arms passed, so that observation alone proves no score advantage.
- **Provider recovery (`mb5m9j`):** the full candidate inspected unknown providers and used logo filenames to recover their identities. The ten provider placeholders observed in the prior candidate fell to zero. However, its plan-name fallback still synthesizes a label from provider plus data allowance. Filled fields are not proof that source plan names were recovered. The pass is retained with that factual limitation.
- **Accepted empty state (`eo2t8f`):** after the requested URL failed, the candidate used an official EnerGov/Civic Access search and returned empty permit, inspection, and code arrays consistent with its later UI evidence. This was a pass for a supported empty result, not recovery of the historical reference's 19 records. Source/jurisdiction equivalence and full original-source coverage remain concerns.

These examples support testing general extraction discipline while showing why a passing score cannot certify every field. No task-specific repair, alternative judgment, or substituted outcome was added.

[Per-task scores, frozen inputs, costs, and comparisons](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/extraction-hard.json). Costs exclude judge, browser, runner, and diagnostic runs.

## Complete Luna result

The same extraction-only SDK finished at **59.22/100 across all 60 assigned tasks**, with **60 actual judgments**, a successful workflow, and **$19.98612436** recorded agent inference cost. It recorded 24 compactions, one SDK inference retry, and one task with an SDK cleanup error. All outcomes remain in the report, including seven official global zeros classified by the judge as suspected reward hacking. That classification does not establish intent.

| Comparison | Reference mean / 100 | Candidate mean / 100 | Paired delta | 95% task-bootstrap interval | One-sided 95% lower bound |
| --- | ---: | ---: | ---: | --- | ---: |
| Prior candidate `0baa51d` | 59.63 | 59.22 | −0.42 pp | [−9.17, +8.80] pp | −7.77 pp |
| Historical-reference SDK `b430a91`, rerun | 58.45 | 59.22 | +0.77 pp | [−8.13, +9.80] pp | −6.73 pp |

Neither lower bound clears the −3-point margin. Both comparators retain one provider-failure zero without an actual judgment. On each comparison's 59 shared actual judgments, the candidate delta is −1.92 points against the prior candidate, or −0.41 against the strongest-reference rerun. Their lower bounds are −9.08 and −7.86 points respectively. The candidate is 2.78 points below the historical 62.00 point estimate; that descriptive proximity does not establish statistical parity.

The extraction rule's apparent Hard gain did not transfer into a clear Luna gain. These nonconcurrent development runs cannot establish that the prompt caused either change. Large gains and losses coexist: for example, `bub2-021` moved from 0 to 94, while `bub2-041` moved from 66 to 6. No retry or alternate judgment replaces either result.

### Audited failure mechanisms

- **Files outside the collected workspace (`bub2-041`, 66 → 6):** the agent explicitly created a sibling directory before compaction. The downloaded artifact contains 44 files there, including a valid 12-sheet workbook and 366-row ledger retaining the relevant cash-flow figures. The official output-file list is empty. This is primarily a delivery failure, unlike the prior cohort's summary omission. The later workspace prompt is absent from this experiment; its native-write warning would not intercept this Bash/Python write path.
- **Observed facts changed before delivery (`bub2-003`, 70 → 0):** source tool results preserve bylines and dates that the final records omit or change. The compaction summary already contains a wrong date and an unresolved coverage warning. The final still claims completion. Its official global zero is retained; this does not prove compaction alone caused the failure.
- **Recovery loops plus unsupported facts (`bub2-023`, 68 → 0):** the candidate issued 178 tool starts with 36 errors, including 23 CDP command timeouts. Thirteen cells reconnected, compared with one in the prior candidate. Unsupported fields were already in files before compaction. The old timeout guidance incorrectly implied that every timeout resets the worker. The selected recovery SDK corrects that guidance, but these traces do not establish it as the cause of the score loss.
- **Unknown converted into false (`bub2-049`, 70 → 0):** two rows in the actual verification CSV have null grid prices and concrete product-page prices, yet `price_mismatch=false`. The code also backfills six unknown search-result sellers from product-page observations, changing the source represented by the summary. Both runs had zero compactions. This is a source-semantics and three-valued-logic failure, not evidence that a context archive would fix it. The judge awarded 62 raw rubric points before its official global zero; zero remains the reported score.
- **Coverage checks over the wrong unit (`bub2-010`, 86 → 18):** the delivered inventory contains 13 US, 11 GB, 13 CA, and 13 AU concepts. Independent parsing finds Library IDs repeated across different concept rows in US, CA, and AU. The report calls this an up-to-15 selection without clearly marking the shortfall incomplete. Both runs had zero compactions. A final row-count check succeeded, but it did not validate unique source identities or the original coverage requirement.

The combined extraction-only result is therefore **90/106 Hard and 59.22/100 Luna at `4a09ee3`**. It excludes the later workspace, extra transient-error retry coverage, context archive, and timeout-guidance fixes. Those are frozen together at `f41c5b7` for a separate fresh confirmation.

[All 180 outcomes, exact controls, costs, and assigned/shared comparisons](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/extraction-luna.json). Costs exclude judge, browser, runner, and diagnostic runs. Recorded failed-response usage may be incomplete. Bootstrap uncertainty is across tasks and does not independently measure judge sampling variance.
