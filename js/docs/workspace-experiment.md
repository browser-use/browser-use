# Workspace delivery experiment

The `0baa51d` Luna run exposed a concrete delivery failure on development task `bub2-021`: three successful Pi `write` calls saved the report, evidence JSON, and progress file one directory above the SDK workspace. The final response linked those paths, but the Findings adapter received zero deliverable files. The adapter collected the declared workspace correctly; it did not lose files saved inside that directory.

The task scored zero after the judge flagged unsupported claims. File placement was one issue, alongside inaccurate common-observation timing and unsupported video attribution. The pre-zero rubric score was 51/100. The reference scored 94/100. Correct file placement alone does not establish that the candidate would pass, and these outcomes will not be changed or rejudged.

## Treatment

- Put the exact workspace path in the system context as a JSON string. Explain how relative file paths, JavaScript, and `BrowserUse.files()` relate to that directory.
- After a successful native Pi `write`, inspect the path Pi actually resolved. Warn if its real path is outside the workspace, including a symlink escape. Preserve the successful write and tell the model how to deliver a copy inside the workspace.
- If that observation fails, return a warning without turning the completed mutation into a failed tool call. Each invocation owns its path state; concurrent calls cannot mix their observations.

No path rewriting, file relocation, automatic replay, sandbox claim, Pi fork, judge change, or expanded artifact collection. Other tools can still write outside the workspace. This is delivery feedback for the native `write` tool, not comprehensive filesystem enforcement. Hidden paths and symlinks also remain subject to the existing inventory rules.

This candidate builds on the separate extraction guidance at `4a09ee3`. A one-task paired diagnostic compares against that exact commit, with the same full Luna task budget. It must show actual output files reaching the unchanged evidence renderer before a broader evaluation. A diagnostic on this observed failure cannot establish general accuracy or SOTA.

The frozen candidate is `4cade93461cbfc366b7e8b7e929a0349de6d5b17`. Both diagnostic workflows completed successfully: [reference execution 34177518105](https://github.com/browser-use/new-eval-platform/actions/runs/34177518105), evaluation `0a960cff-41fc-4809-a7d9-c6932f9c535e`; [candidate execution 34177519663](https://github.com/browser-use/new-eval-platform/actions/runs/34177519663), evaluation `f22f3eec-994f-461d-b1ea-af89f7f414a8`. Both used the unchanged Luna xhigh/Findings xhigh controls, 3600 seconds, 1000 turns, and one parallel job per arm.

| Observed diagnostic result      | Reference `4a09ee3` | Candidate `4cade93` |
| ------------------------------- | ------------------: | ------------------: |
| Task score                      |              90/100 |              90/100 |
| Judge-visible deliverable files |                   3 |                   8 |
| Clipped deliverables            |                   0 |                   0 |
| Agent time                      |     766.933 seconds |     955.598 seconds |
| Recorded agent inference cost   |         $0.25768839 |         $0.43109896 |

There was **no score gain**. The candidate used JavaScript to save its files inside the workspace; it did not call the native Pi `write` tool, so it did not exercise the new outside-write warning. That warning is verified by the local forced-failure tests. The remote run establishes correct delivery for this trajectory, not causal prevention of the earlier mistake. Additional files are not inherently higher quality, and the candidate used more time and cost on this one task.

Both judges found ROI-ledger errors. The candidate omitted an observed deployment duration and included background/video-caption figures in its outcome-metric ledger. There were no missing artifact previews in this comparison; those content errors cannot be attributed to file placement. The original zero remains unchanged.

## Verification and compatibility

Local tests reproduce an outside write, confirm that the file exists but is absent from the workspace inventory, and verify that a subsequent in-workspace write becomes discoverable. They cover relative traversal, symlink escape, sibling paths sharing the workspace prefix, concurrent writes, cancellation before mutation, and the exact workspace string reaching the model context.

Existing permitted outside writes still succeed. The warning adds model-visible text and may cause additional work; that behavior and the explicit path are the treatment. There is no public option, transcript-version change, profile migration, or legacy Python Browser Use change. SDK Python callers receive the same underlying runtime behavior. Rollback is the preceding SDK commit.
