# Evaluator screenshot ownership

The second Luna reference task `bub2-002` completed its agent run, but the Findings judge crashed before producing a rubric. Its official zero remains in the assigned denominator and its actual judgment remains missing.

## Reproduced failure

The adapter saved evaluator screenshots inside the agent's ordinary workspace, `agent_outputs/screenshots`. While cleaning deliverables, the agent enumerated that folder, checked whether its own reports referenced it, then deleted it with `fs.promises.rm(..., {recursive:true, force:true})`. Event 1065 contains that operation and event 1066 confirms removal. The result still registered 23 screenshot paths. All 23 are absent from the downloaded artifact; the judge log raises `FileNotFoundError` on `001.png` before a rubric exists.

This is an evidence-ownership failure with a directly observed deletion, not a provider failure or a zero from an actual quality judgment. The run had other browser problems, including 207 screenshot errors and two compactions; those do not account for this final missing-file exception.

## Correction

Store evaluator captures in `EVAL_WORKSPACE/judge_screenshots`, outside the agent's `agent_outputs` workspace, and explicitly include them in the result's artifact inventory. Keep the same capture observer, PNG/JPEG encoding, viewport, timing, step links, screenshot selection, evidence renderer and judge. Ordinary cleanup of the agent's screenshot deliverables no longer deletes the evaluator's captures.

No SDK API, model prompt, dependency, profile or history changes are involved. The location is a lifecycle boundary, not a security sandbox: unrestricted generated code could still access parent directories despite the task instructions. Existing results use their original relative paths and require no migration.

## Verification and comparison boundary

The new local adapter regression uses real isolated Chrome and scripted provider responses. It waits for a real capture, runs agent code that deletes its workspace screenshot folder, then checks that the originally captured bytes still exist, remain registered as artifacts, and are loadable through the judge-facing paths. It also verifies delivered content, one browser stop, and completed telemetry. Observers are nonblocking, so the test checks preservation of an already recorded image rather than assuming every last-cell capture completes.

The old adapter fails this regression; the corrected adapter passes all five adapter tests, including unchanged default and Findings flows. No paid model request or remote diagnostic was used. The full Node suite passes **101/101** and typecheck passes. The evidence renderer is byte-identical to the preceding adapter revision.

All four current confirmation runs remain unchanged. The reference's missing judgment makes this Luna confirmation ineligible under the frozen acceptance criteria even if its eventual score clears a margin. Do not replace the zero, restore screenshots into the old run, or rerun that task. Before a future matched comparison, apply the same evaluator-storage correction to both arms, retaining each selected runtime and explicitly pinning the derived adapter refs. Rollback is the prior adapter revision; no judge alteration or publication is part of this change.

[Failure evidence, exact generated cleanup and artifact hashes](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/confirmation2-screenshot-ownership.json).

## Corrected historical reference adapters

Both reference adapters now carry the same storage and inventory correction as the candidate. They are pinned for future comparisons, not substituted into any previous run.

| Reference runtime | Derived adapter commit | Local adapter tests |
| --- | --- | --- |
| Hard `58ed778` | `769ea148382cb9094662188a593b0410f6e9f0d5` | 3/4 before; 4/4 after |
| Luna `b430a91` | `c3f7fac2d8a46a3801e06d89a3c3c9b1343db79e` | 4/5 before; 5/5 after |

Both typechecks pass. Each regression waits for a real isolated-Chrome capture, then has scripted agent code remove its workspace screenshot directory. Before the correction, the cleanup causes a capture error. Afterward, the original image bytes survive and remain in the artifact inventory; delivered content, telemetry completion and one browser stop are also checked. No paid provider calls were made.

Git-object verification confirms that each entire `src/` tree, `package.json` and `package-lock.json` is byte-identical to its historical reference. Luna's `eval/findings.py` is also unchanged. Outside the tests, each derived adapter differs by exactly the screenshot destination and its explicit artifact inventory entry. The historical runtimes retain their original behavior and limitations. This is evidence-lifecycle preparation, not a new quality score.

[Exact refs, runtime trees, dependency hashes and verification](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/reference-screenshot-ownership.json).
