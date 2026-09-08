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
