# Recover observations after compaction

An exploratory runtime treatment. Pi still produces the summary. The change stores the text that summary replaced in the same checkpoint file, then gives the model a path for selective retrieval.

## Observed failure

In the original Luna comparison, `bub2-041` scored 100/100 at reference `b430a91` and 66/100 at candidate `0baa51d`. Both compacted once and recorded no SDK inference retries. The candidate extracted quarterly operating cash flow and free cash flow, then omitted them from its summary and all later tool results and deliverables. The official source files remained on disk.

The reference's summary also omitted those figures, but its generated dataset and reconciliation files already contained them. It compacted after covering 203 transcript messages; the candidate compacted after 117. This points to a difference in when source observations became durable structured data, not proof that the new summary wording caused the regression. Other candidate failures were an omitted regional aggregate and unsubstantiated cross-document verification claims. Do not attribute the entire 34-point loss to compaction.

Source runs: [reference](https://github.com/browser-use/new-eval-platform/actions/runs/34173710531) and [candidate](https://github.com/browser-use/new-eval-platform/actions/runs/34173712013). Both retain their original judgments.

## Treatment and limits

Before replacing context, save a redacted archive of the covered messages alongside the generated summary. Preserve standard user/assistant text, tool calls, tool-result text and error states. Omit image bytes, reasoning, signatures and auxiliary metadata. This preserves the observed tool text, not any portion that the tool had already truncated before delivering it. Ordinary source files and saved cell output remain separate evidence.

The checkpoint tells the model how to find the archive and read relevant excerpts. Successive archives retain earlier checkpoint messages, so the previous archive paths remain available even when a later summary omits them. The archive adds no model call, browser action, judge access, benchmark-specific rule or new tool. It does not force the model to retrieve evidence or make its claims correct.

Files use exclusive names and mode 0600 under `.browser-use/context/`. Redaction covers configured secret values; this is not a filesystem sandbox. Archives follow existing workspace retention and remain excluded from `files()` deliverables. A failed archive write leaves original context in place. Cancellation is checked again before installing the checkpoint. History version and public API remain unchanged. Roll back by pinning the preceding SDK commit; existing archives stay ordinary files.

## Verification

Local fault tests check an omitted observation's survival, configured-secret redaction, reasoning/image/signature omission, tool error status, file permissions, repeated-compaction links, unchanged original messages, and original-context retention after a write failure. A scripted-model integration test runs the actual Pi loop and JavaScript worker: compaction deliberately omits an observed count, the agent reads it from the archive, and delivery succeeds without repeating the source action. Existing deadline tests check late summary rejection.

These prove recovery capability under controlled conditions. They do not establish a remote score improvement. The running extraction-only cohorts are pinned to `4a09ee3` and do not contain this treatment. Any real-model diagnostic must be retained separately; full candidate selection and fresh confirmation still follow the [iteration protocol](./iteration-protocol.md).

## Frozen diagnostic

One paired diagnostic on `bub2-041` was dispatched after 81 local tests, typecheck and docs build passed. Both arms use Luna xhigh, Findings Luna xhigh, platform `ddc48ee93ea863c26d78c45a09760e4951b48a3d`, the full 3600-second/1000-turn/800000-character budgets, a US proxy and 70-minute browser, and one parallel task per arm. Workspace and temporary-provider-error fixes are identical in both arms. There are no replacement attempts.

| Arm | SDK | Execution | Evaluation |
| --- | --- | --- | --- |
| Reference | `1f1952bbf98676e9995acde47949e3236c078e0d` | [34180143452](https://github.com/browser-use/new-eval-platform/actions/runs/34180143452) | `173b4a3f-a1d5-4913-85cb-ee1bc8631a7d` |
| Archive | `0f99a63a9812cd59d267954fbcde170d277f22dc` | [34180148395](https://github.com/browser-use/new-eval-platform/actions/runs/34180148395) | `bd99a0f7-1454-4bb4-ae94-238b97f84829` |

Both workflows completed successfully. The candidate did **not compact**, created no context archive, and therefore never exercised archive retrieval. Its higher score cannot be attributed to that mechanism.

| Measure | Reference | Archive candidate |
| --- | ---: | ---: |
| Score / 100 | 86 | 90 |
| Compactions | 1 | 0 |
| Agent duration | 669.989 s | 646.756 s |
| Recorded agent inference cost | $0.29093108 | $0.32776182 |
| Delivered files / clipped previews | 30 / 17 | 37 / 14 |

Both delivered quarterly operating and free cash flow in their metric ledgers and reports. The reference lost points for an incorrect/incomplete source publication date. The candidate lost points because one brief sentence called a calculated margin a reported figure, despite correct labeling elsewhere. Neither recorded SDK inference retries, warnings or cleanup errors; that is not independent proof of every browser lifecycle event. Costs exclude judge, browser and runner charges.

This closes the diagnostic without a remote archive-retrieval validation or causal score claim. Local forced-omission tests remain the proof of recovery capability. This is one previously inspected task, not ranking evidence.
