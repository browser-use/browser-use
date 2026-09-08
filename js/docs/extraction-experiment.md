# Validate before batching

An exploratory prompt treatment, prepared while the first matched cohorts run. It changes no browser helper, model setting, deadline, output schema, evidence renderer or judge.

The first candidate's `y72ivg` trace returned an empty extraction on a loaded search page, then reused the same extractor across nine model searches. Later navigation hit an access challenge. The reference also began with an empty extraction, inspected the observed structure, repaired its selector and obtained prices before batching. These different trajectories support testing an extraction-validation rule; they do not prove that a prompt change will reproduce the reference's access or score.

The separate SEC diagnostic also selected a subset of statement tables and described it as complete, omitting other statement families and continuation content. That diagnostic had a reduced turn budget, so its score is not comparable with the full cohort. The same coverage error was observed in the previous full run.

## Treatment

- Validate extraction on the observed page before batching. Empty extraction needs a verified empty state or a repaired extractor.
- Stop a batch after extraction failure, preserve per-record status, and avoid repeatedly applying the same failing code.
- Reconcile the original request with a source inventory, including pagination and continuation content. A self-selected subset cannot establish completeness.
- Preserve raw field labels, values and units; verify exact entity/variant identity and use the user's explicit fallback for missing items.

The prompt contains no benchmark IDs, site selectors, expected answers or grader rules. Existing overlapping research guidance is condensed. This remains model guidance, not a factual validator.

The next diagnostic uses exact tasks `y72ivg` and `nngh8r` with the full Hard per-task budgets, paired against runtime `0baa51d`. These tasks are development cases. Preserve both arms and inspect the trajectories; their scores cannot establish a general improvement or SOTA. The four original full cohorts remain pinned to their original commits.
