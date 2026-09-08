# Evaluation adapter

`run.mjs` runs the pinned SDK through the eval platform's executable contract. It provisions and closes one cloud browser per task. The SDK's agent loop is unchanged.

Default evidence remains compatible with Laith. Set `evidence_format: "findings"` for the BU_Bench_v2 findings judge: the adapter includes numbered trajectory entries, PNG screenshots tied to those entries, and rendered workspace deliverables. It never reads rubrics or answer keys.

Findings text budgets match the BrowserCode adapter: 2,000 characters of tool input, 20,000 of tool output, 4,000 of assistant text/thinking; 50 rendered files sharing 600,000 characters. Truncation keeps both ends and is marked. All ordinary output paths remain available for the judge's raw canary scan. SDK internals, observer screenshots, packages and symlinks are excluded from deliverable inventory. XLSX/PDF rendering uses the baseline's pinned openpyxl/pypdf and copied rendering functions; it happens after execution and adds no agent tools.

SDK audit files live in a hidden directory, which GitHub Actions excludes from ordinary artifact uploads. After browser cleanup, the adapter packages regular files from `.browser-use/context`, `cells`, and `runs` into the visible `sdk-audit.tar.gz` artifact. Other hidden files and symlinks are excluded. Archive failures are reported in `metadata.sdk_audit_archive_error`; they do not replace the agent's result. This requires the runner's standard `tar` executable.

The reliability cohorts at `a7fe3d4` predate this archive correction. Their visible event streams, outputs and recorded compaction counts survive, but hidden summary/checkpoint audit files were omitted by the uploader. The archive correction cannot recover those files retroactively and does not change the agent loop or findings evidence.

`task_timeout_seconds` accepts 1–7,200. The platform must allow an additional 90 seconds, and browser lifetime must exceed the task budget by 30 seconds. Defaults remain 1,700 seconds and a 60-minute browser.

For viewport-changing tasks, `browser_allow_resizing: true` passes `allowResizing: true` to Browser Use Cloud. Omission preserves the existing provider request; explicit false disables resizing. Non-boolean values fail before provisioning. The option remains in the recorded options and configuration hash.

This changes the browser environment, not the agent loop. In the September 8 synthetic-page probe, default Cloud browsers acknowledged resize commands without changing their viewport. Enabling resizing made 390×844 layout, screenshots and media queries work. It also changed the initial viewport despite the same requested screen dimensions, and reported DPR still differed from the emulation request. Cloud documents reduced stealth with this option. Measure actual geometry; do not infer mobile-device fidelity or equal site access. Freeze the same setting in comparison arms and report the environment change. It is not enabled in the original confirmation cohorts. [Probe evidence](../docs/confirmation3-trace-audit.md#cloud-resizing-is-an-explicit-provisioning-capability).

## Coding tools independently of evidence format

`research_tools: true` enables upstream Pi read/write/edit/bash tools for either judge evidence format. `false` disables them. Omission preserves historical behavior: enabled for Findings, disabled for default Laith evidence. Non-boolean values fail before browser provisioning. The explicit option is retained in result metadata and the platform configuration hash.

This maps to the existing SDK `researchTools` option; it changes no SDK default or Python API. Prefer the explicit option when comparing tool availability so judge formatting does not implicitly select the agent's capabilities. Native tools can avoid nested JavaScript/shell escaping and provide file operations independently of the browser worker. They do not guarantee syntax checks, truthful fields or complete coverage. The agent already has unrestricted Node execution; file tools retain the existing workspace guidance, filtered shell environment and shared run budgets.

No original run used this new override. Any experiment must freeze it before dispatch, preserve old outcomes and separate this treatment from the execution-deadline patch. Rollback is omitting the option or restoring the previous adapter SHA.

## Local contract tests

```sh
npm run build
node --test test/eval.test.mjs
uv venv artifacts/eval-evidence-venv
uv pip install --python artifacts/eval-evidence-venv/bin/python openpyxl==3.1.5 pypdf==6.14.2
artifacts/eval-evidence-venv/bin/python test/findings_evidence.py
```

These use synthetic data and real local Chrome. The findings test checks that the provider request contains `gpt-5.6-luna` and `reasoning.effort: xhigh`, as well as screenshot/file/trajectory delivery and cleanup. It does not make a paid provider request.

## September 6 comparison

The 106-task regression is frozen at SDK `413ed34`, platform `ddc48ee`, GPT-5.5 medium and Laith/GPT-5.5, with the historical 1,700-second budget. The findings adapter changes are excluded from that run.

The new Luna xhigh cohort uses the same SDK runtime, a 3,600-second budget, a 70-minute browser, 1,000 model turns, an 800,000-character context guard, and findings/Luna xhigh. Dataset and judge code are byte-identical to the 60-task Astra comparison. The existing BrowserCode Luna xhigh result is a historical reference, not a simultaneous control. Browser provisioning, runner, agent tools, context handling and screenshot collection differ between harnesses. Compare end-to-end systems; do not attribute the entire difference to one tool or model.
