# Recovering observation times from the existing journal

This is a separate experiment after confirmation candidate `f41c5b7`. It changes neither the running cohorts nor their recorded outcomes.

## Observed failure

In the completed Luna candidate task `bub2-043`, the directory files were delivered but the judge applied its global integrity penalty. The generated script assigned `new Date().toISOString()` to the original Google-page observation while constructing the final files. There was no corresponding page observation at that new time. This task had zero compactions.

The existing SDK journal was present inside its saved audit archive. It contains 80 tool-end records and no truncated records. The relevant page-snapshot tool started at **05:05:50.637 UTC** and ended at **05:05:51.105 UTC** on September 8. The final ledger instead reports **05:20:35.889 UTC**. The source observation's execution window was recoverable without revisiting Google, but the agent did not consult it. The journal bounds the tool execution; it is not proof that every result was captured at one exact instant.

Other inspected tasks also conflated observation and report timestamps. That motivates exposing existing evidence rather than adding another storage system. It does not show that a path hint will fix every case.

## Small change

The SDK already writes a live, redacted JSONL event journal under `.browser-use/runs/`. It now passes the exact current journal path into the agent prompt. A short hint tells the agent to recover original execution times and observations, and to keep event windows distinct from simultaneous page snapshots and report time.

The implementation reuses the same logger and tools. It schedules no browser request, model call, or action replay, and adds no public option or history-format migration. The model may choose additional journal reads. `RunResult.eventsPath` remains unchanged. Follow-ups point to their new run journal. Direct internal `runAgent()` calls without a session journal make no claim that one exists.

To read a specific prior tool call in ordinary JavaScript:

```js
const events = require('node:fs')
  .readFileSync(journalPath, 'utf8')
  .split('\n')
  .filter(Boolean)
  .map(JSON.parse);
const matched = events.filter((entry) => entry.event?.toolCallId === observedToolCallId);
```

Use only the relevant entries. The top-level `timestamp` is UTC epoch milliseconds; nested `tool_execution_start` and `tool_execution_end` events identify the execution window. These are host-clock event times, not a timestamp for every URL mentioned in a tool result. Redaction, truncated records, absent entries, copied data from earlier calls, and uncertain side effects remain limitations. The journal is ordinary workspace evidence, not a tamper-proof ledger or a factual validator. Do not replace unavailable timing with a new clock reading.

## Verification and limits

The previous built runtime failed the new discovery test because the live path was absent from the prompt. A local real-Chrome fixture then verified that the agent can read its original observation and timestamps from the journal during the same run, preserve a literal Unicode line separator, respect configured secret redaction, and recover the data without repeating the source action. A follow-up test checks that the prompt points to that follow-up's journal.

The first longer explanation caused an existing tight-context compaction test to fail at its unchanged 35,000-character budget. The explanation was shortened; both journal retrieval and the existing compaction-retrieval boundary then passed. The budget, compaction thresholds, and retained-message policy were not changed. This is a concrete example of why additional instructions need regression checks even when no browser code changes.

Local scripted-model tests establish discoverability and mechanics. They do not establish that Luna will choose to read the journal, repair a timestamp, or improve a benchmark score. This candidate requires a separate real-model diagnostic and frozen full evaluation before a quality claim. Rollback removes the prompt hint and internal path plumbing; existing journals and histories remain readable.
