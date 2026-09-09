# Historical benchmarks

These runs predate the simplified helper surface. **They are not scores for the current candidate.** Hard uses 106 tasks and GPT-5.5 medium. V2 uses Luna xhigh and a continuous score out of 100. Costs are recorded agent inference estimates, excluding judge/browser/runner costs.

| SDK revision | Hard /106 | V2 /100 | V2 agent cost |
| ------------ | --------: | ------: | ------------: |
| `58ed778`    |        91 | Not run |             — |
| `413ed34`    |        86 |   34.12 |        $10.99 |
| `a7fe3d4`    |        88 |   55.72 |        $17.22 |
| `b430a91`    |        85 |   62.00 |        $17.86 |
| `29e2b5e`    |        84 |   61.75 |        $20.25 |

The 91 result was an unstable peak: later original-code repeats scored 79, 85 and 84. These revisions changed more than one factor. This table does not establish causality, a matched BrowserCode advantage, or SOTA.

For `b430a91`, Hard evaluation ID is `ed2fb652-9858-4a36-bac2-60b0d3270302`; V2 is `bf521f51-7920-4e55-8833-f6413b91a73d`. V2 retained 60 assigned tasks: 59 judgments and one provisioning failure scored zero.

## Evidence

The old reports are preserved at immutable commit `416b9906f0dbb5784ea4aa162345453842c260c3`:

- [Run evidence](https://github.com/browser-use/browser-use-js/tree/416b9906f0dbb5784ea4aa162345453842c260c3/evidence)
- [Benchmark analysis](https://github.com/browser-use/browser-use-js/blob/416b9906f0dbb5784ea4aa162345453842c260c3/docs/benchmark-overview.md)
- [Trace audits](https://github.com/browser-use/browser-use-js/tree/416b9906f0dbb5784ea4aa162345453842c260c3/docs)

The current repository keeps the [eval adapter](https://github.com/browser-use/browser-use-js/blob/main/eval/README.md) and automated tests. For a performance claim, freeze SDK SHA, task IDs, model, reasoning, budgets, judge, environment and retries. Run matched arms and inspect failures. A tiny model smoke proves integration, not benchmark parity.
