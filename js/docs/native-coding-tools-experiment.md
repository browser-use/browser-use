# Native coding tools on Hard

Hard historically exposes JavaScript and finish tools. Findings also exposes Pi read/write/edit/bash. Judge evidence format should not silently choose this capability: `research_tools` now selects it explicitly, while omission keeps existing behavior.

## Isolated treatment

Run `v18kgy` once in each arm at the same frozen SDK, platform, GPT-5.5 medium model, Laith/GPT-5.5 judge, 1,700-second agent budget, 1,000 turns, 800,000-character context, US proxy and 60-minute browser lifetime. Only `research_tools: false` versus `true` differs. Both arms include the native synchronous-evaluation deadline and the between-cell reset-reporting fix; neither can explain a treatment difference. No prompt, task, selector, expected answer, evidence renderer or judge changes.

This task is deliberately selected from inspected development failures. Its earlier agent-produced scraper lost JavaScript escapes inside a nested shell heredoc, and the agent never syntax-checked the saved file. Native file tools remove one encoding layer. They cannot force the model to validate code, preserve verified fields, or collect the complete requested inventory.

## Inspect before expanding

Retain the original workflow, actual judgment, trace, artifacts and browser cleanup for both arms. Check frozen manifest/config/dependency identity. Count native-tool selections and coding errors. Inspect scripts without executing their generated browser/network code; syntax checks do not prove regeneration or factual correctness. Check spreadsheet field coverage separately. Do not modify submitted artifacts, substitute a repaired answer, or rejudge.

A model that never selects the native tools only tests compatibility. A passing task without valid delivered code does not validate the proposed mechanism. One task cannot establish score parity or SOTA. Only after the original pair is audited, select the next full confirmation on both original benchmarks, using one candidate runtime and the unchanged protocol.

The explicit eval option is backward compatible. Node execution already had filesystem/network capability; these tools are not a new sandbox. Shell environment filtering and existing deadlines remain in force. No login/profile/history or Python API migration. Rollback is `research_tools: false` or omission on default evidence. No publication or merge.

[Exact frozen inputs and audit gate](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/native-coding-tools-plan.json) · [Underlying script failure](./confirmation3-trace-audit.md#reusable-script-delivery-loses-escapes-before-the-shell-receives-it)

## Original executions

Both original arms completed successfully, with actual failure judgments: **0/1 versus 0/1**. Neither replaces an earlier outcome.

- native-coding-tools-hard-control: [workflow 34234054610](https://github.com/browser-use/new-eval-platform/actions/runs/34234054610).
- native-coding-tools-hard-candidate: [workflow 34234058141](https://github.com/browser-use/new-eval-platform/actions/runs/34234058141).

[Recorded original inputs and handles](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/native-coding-tools-dispatch.json). No full-cohort run has been selected yet.


## Completed diagnostic

Both runs used runtime `ef19eac636da4f12d0a567590b49059adf41ac7d`. Manifest/config, task, model, dependency lock, image retention and stopped owned browsers were checked. Tool availability and delivery work; this pair establishes no score or speed gain.

| Measure | Tools off | Tools on |
| --- | ---: | ---: |
| Actual judgment | 0/1 | 0/1 |
| Steps | 44 | 56 |
| Agent seconds | 648.139 | 832.383 |
| Agent inference cost | $1.889764 | $1.969978 |
| Native bash calls | 0 | 8 |
| JavaScript failures / completions | 3/42 | 7/47 |
| Screenshots / capture errors | 41 / 1 | 37 / 10 |
| Delivered rows | 915 | 701 |
| Kickstarter rows | 334 | 120 |
| Gamefound rows | 581 | 581 |
| Creator websites: Kickstarter / Gamefound | 139 / 0 | 0 / 0 |

The candidate used eight native bash calls, including direct heredocs, and no native read/write/edit calls. Both delivered scripts in each arm pass syntax checks. After reviewing each complete workbook generator, we executed it on copies of the original saved data in disposable directories with empty environments. Control: all seven workbook ZIP-entry payloads match. Candidate: seven of eight match; only the Run Notes generation timestamp differs. All original workbook data rows match the respective canonical JSON. No scraper network code ran, submitted artifact changed, or judgment was replaced. Regeneration does not prove source completeness or factual correctness.

### A timeout loses inventory already collected

The candidate's event 158 grows an in-memory array and prints 889 records at page 75. Its checkpoint stores only `pagesDone`, `count` and `total`, not the records, and is unawaited. Event 159 reaches the 120-second cell limit and loses the worker. Event 162 fetches the first ten pages again and saves 120 records, which become the delivered subset. The printed count does not independently establish 889 unique valid records. No larger raw-array checkpoint survives.

The final answer attributes the subset to rate limits. The retained trace also demonstrates reduction after a timeout. General remedies are bounded batches and awaited checkpoints of the actual records, then recovery from those files. The SDK already exposes these capabilities; adding native tools does not ensure the model uses them correctly. Neither arm supplies the requested first-appearance date for Gamefound; the observation date is a disclosed fallback.

### A separate Node compatibility bug

Control event 78 uses `const fetch = global.fetch`; event 79 fails because the REPL lacks Node's `global` alias. Its failed lexical declaration subsequently shadows the preloaded `fetch` binding, producing another error at event 83. The compatibility correction is separate from these original runs and must not be credited to this diagnostic.

[Control audit](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/native-coding-tools-hard-control.json) · [Candidate audit](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/native-coding-tools-hard-candidate.json) · [Artifact regeneration and inventory audit](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/native-coding-tools-artifact-verification.json).
