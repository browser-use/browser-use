# Reliability and BrowserCode comparison

This candidate keeps Pi upstream and raw CDP. It repairs long-task execution and adds selected coding-agent capabilities. Both full evaluation iterations are complete. [Latest scores and comparisons](./vision-results.md) · [First reliability results and remaining problems](./reliability-results.md).

## What BrowserCode adds

The inspected BrowserCode checkout is `613bd61fdf2bab7f107927961936f456ed522b56`. It is newer than the historical evaluation; features in that checkout must not be attributed automatically to the old score.

| Capability                                                                   | Source / evidence                                                                                             | Decision here                                                                                                                                                        |
| ---------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Context summaries, recent-turn preservation, old-output pruning              | `packages/opencode/src/session/compaction.ts`                                                                 | Use upstream Pi `generateSummaryWithUsage` and token estimation; preserve recent complete tool groups.                                                               |
| Dedicated read, write, edit, shell tools                                     | `packages/opencode/src/tool/registry.ts`; historical tasks 056 and 058 used saved scripts                     | Opt-in upstream Pi tools, independent of CDP, with filtered shell environment and bounded execution.                                                                 |
| Reusable scripts, syntax checks and durable datasets                         | Historical AutoTrader 056 and property 058 traces                                                             | Ordinary workspace files plus atomic checkpoints; explicit instructions to save small batches.                                                                       |
| Strategy changes after no progress                                           | `packages/opencode/src/tool/browser-execute.txt`                                                              | General progress/verification guidance; no domain selectors or task answers.                                                                                         |
| Explicit screenshot auto-attachment                                          | `packages/bcode-browser/src/browser-execute.ts` response tap; Luna 040 saved a mobile image without seeing it | Attach native images for explicit captures on the worker connection, including page helpers, other tabs and raw CDP. Preserve saved bytes and bound images per cell. |
| Web fetch/search                                                             | Tool registry and historical system instructions                                                              | Permit public source APIs/search on the research benchmark; preserve hard-benchmark search restriction. Node fetch/browser remain available.                         |
| Skills, todo/task delegation, LSP, plugin registry, broader session platform | Current tool registry                                                                                         | Not copied wholesale. A progress file supplies task bookkeeping. Delegation/LSP/platform features are not demonstrated remedies for this audit's failures.           |

Pi's coding-agent package is pinned to 0.85.1, matching the existing Pi agent-core and model package. We consume supported exports; no Pi fork or copied compactor. Pi provides summary generation and token estimation. The bu-pi wrapper owns when to compact, which recent messages to retain, checkpoint persistence and budget accounting. Merely using Pi agent-core would not wire that lifecycle automatically. This adds dependencies, including Pi's UI packages, even though our SDK uses its programmatic API. The existing Python bundle still builds and is tested.

## Problem → implementation → limit

| Observed problem                                   | Implemented response                                                                                                                         | What it does not prove                                                                 |
| -------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| Encrypted reasoning charged as ordinary text       | Exclude signatures from text accounting; use Pi token estimates and recent provider usage                                                    | Signature bytes are not free provider context.                                         |
| No compaction; research stranded at context cap    | Automatic Pi summaries before exhaustion, last two complete assistant/tool groups retained, original user requests pinned, checkpoints saved | Summaries can omit facts. Failure retains original context and reports a warning.      |
| No delivery reserve                                | Near time/step exhaustion, switch to existing finish tools; retain original hard limits                                                      | Forced cancellation or provider outage cannot guarantee a final answer.                |
| Worker timeout destroys data                       | `checkpoint(name, value)` atomically replaces a JSON checkpoint; prompt asks for each successful bounded batch                               | Arbitrary JavaScript heaps/closures are not serializable. Checkpoints remain explicit. |
| Browser failure prevents local recovery            | Lazy CDP and deferred Page initialization; Pi file tools are browser-independent                                                             | A remote browser may remain unhealthy.                                                 |
| Unclear reconnection / action outcome              | Explicit `reconnect()`, preserving Node state/files and no automatic action replay                                                           | Reconnect cannot establish whether a prior external action happened.                   |
| Exceptions discard output                          | Each cell captures bounded stdout in a parent-chosen file; `CellError` includes partial result and `stateReset`                              | In-memory data never printed or checkpointed can still be lost.                        |
| Screenshot observer blocks/aborts run              | Separate best-effort observer, one active/one pending event, short command deadlines, cancellation and bounded final flush                   | Observer events may be coalesced; recording can lose frames.                           |
| Opaque covered-element error                       | Include target, obstruction and URL while retaining the hit-test rejection                                                                   | Some visual/native controls still require screenshots and reasoning.                   |
| Unsupported “verified” claims and missed conflicts | Explicit evidence status/timestamp/identity/conflict guidance and incremental deliverables                                                   | This is model guidance, not a factual truth validator.                                 |
| Interrupted provider stream                        | One additional inference retry for specific transient stream errors, within original budgets; failed-response tools never execute            | Persistent provider errors still fail. No task reruns or browser-action retries.       |

## Public interface

```ts
const agent = await BrowserUse.create({
  model: 'openai/gpt-5.6-luna',
  researchTools: true, // optional read/write/edit/bash; default false
  workspace: './research',
});
const result = await agent.run('Research the requested products', {
  compaction: true, // default; false keeps hard-stop context behavior
  maxContextChars: 800_000,
  observe: async (event, signal) => {
    // Best effort, tool-completion events. Honor signal; no irreversible actions here.
  },
  observerTimeoutMs: 3_000,
});
```

`onEvent` retains its awaited, lossless/backpressure semantics. `beforeToolCall`, `afterToolCall` and `validateResult` remain blocking controls. Their failure is not silently ignored. `observe` is a separate, best-effort channel; it must not implement authorization or validation.

The REPL adds `checkpoint('progress.json', value)` and `reconnect()`. Standard Node files/imports remain available. The initial page attaches only when browser work begins; pure JavaScript no longer creates an extra tab. After reconnect, reacquire previously cached page/frame handles. Existing tab ownership rules remain.

`RunResult` additionally reports `compactions`, `providerRetries` and warnings. Summary model usage is included in total run usage/cost. Main response output is capped at the smaller of 32,768 tokens, the model maximum, and 15% of the model context window, leaving space for reasoning/output within the input guard. This is a new effective configuration, not an unchanged-baseline claim.

The same single inference retry also covers the explicit temporary errors `Unable to verify model access right now. Please retry.` and `An error occurred while processing your request. You can retry your request, ...`. Invalid keys and permanent model-access denials still fail immediately. This does not replay browser actions or reset step, time, cost or cancellation limits. Repeated failures stop after that one additional attempt.

History version 1 remains readable. Saved context contains the compacted projection; the run event journal retains the original trajectory. Context checkpoint files and per-cell output live under `.browser-use/`. Existing workspace and artifact files remain in place. The user controls their retention.

New compaction checkpoints also retain the covered messages as a text evidence archive. The model receives its path and can search omitted observations with ordinary JavaScript/file tools. Standard message text, tool calls and tool-result error states survive independently of the summary; configured secrets are redacted, and images, reasoning and signatures are omitted. Each later checkpoint links previous archives. This is observational evidence, not replayable history or a correctness validator. An archive-write failure retains the original context. Old checkpoints remain usable but cannot recover source messages they never stored. See the [experiment](./context-archive-experiment.md).

The eval adapter separately archives SDK audit files as `sdk-audit.tar.gz`, because GitHub's default artifact uploader omits hidden directories. This correction followed the `a7fe3d4` benchmark dispatch: those runs retain visible event logs and compaction counts, but their hidden summary files were not uploaded. Archive errors are explicit metadata, and unrelated hidden files and symlinks are excluded.

## Verification and evaluation

Local tests use scripted models or mock provider responses; real Chrome tests use isolated temporary profiles and local fixtures. They prove execution, cancellation, recovery, schema and compatibility behavior. They do not establish benchmark gains.

The temporary-error cases came from retained Luna failures: `bub2-046` at `0baa51d` ([run](https://github.com/browser-use/new-eval-platform/actions/runs/34173712013)), after 38 turns, and `bub2-051` at `b430a91` ([run](https://github.com/browser-use/new-eval-platform/actions/runs/34173710531)), after 85 turns. Both retain their original runner zeros without actual judgments. Fault tests verify that the retry preserves prior JavaScript data and never executes tools from a failed partial response; these tests do not prove a recovered remote score. The running extraction cohorts use `4a09ee3` and contain neither temporary-error extension.

The first frozen reliability runs are Internal Bench Hard (106 tasks, GPT-5.5 medium) and BU_Bench_v2 (60 tasks, Luna xhigh). Use the prior task sets, judges, time/step caps, US proxy and browser lifetimes. Freeze exact SDK/platform SHAs and dependency lock; retain every outcome, compaction/retry count, artifact and judgment. Research tools/search permission, compaction, recording and response cap are deliberate treatment changes.

No benchmark answers, rubrics, task IDs or site-specific extraction rules are added to the agent. Known trace failures are development evidence, so a gain on these benchmarks still needs replication and held-out validation before a broad SOTA claim.

Roll back by pinning the prior SDK SHA. New checkpoint/output files remain ordinary files; older SDKs ignore them. Disable `researchTools`, `observe` or compaction individually to diagnose behavior. No Python Browser Use implementation, customer sessions or production deployment is modified.
