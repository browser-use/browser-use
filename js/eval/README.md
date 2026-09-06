# Evaluation adapter

`run.mjs` runs the pinned SDK through the eval platform's executable contract. It provisions and closes one cloud browser per task. The SDK's agent loop is unchanged.

Default evidence remains compatible with Laith. Set `evidence_format: "findings"` for the BU_Bench_v2 findings judge: the adapter includes numbered trajectory entries, PNG screenshots tied to those entries, and rendered workspace deliverables. It never reads rubrics or answer keys.

Findings text budgets match the BrowserCode adapter: 2,000 characters of tool input, 20,000 of tool output, 4,000 of assistant text/thinking; 50 rendered files sharing 600,000 characters. Truncation keeps both ends and is marked. All ordinary output paths remain available for the judge's raw canary scan. SDK internals, observer screenshots, packages and symlinks are excluded from deliverable inventory. XLSX/PDF rendering uses the baseline's pinned openpyxl/pypdf and copied rendering functions; it happens after execution and adds no agent tools.

`task_timeout_seconds` accepts 1–7,200. The platform must allow an additional 90 seconds, and browser lifetime must exceed the task budget by 30 seconds. Defaults remain 1,700 seconds and a 60-minute browser.

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
