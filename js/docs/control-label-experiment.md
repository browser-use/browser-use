# Native control label activation

This change fixes a locally reproduced browser-helper failure discovered in the completed [accessibility diagnostic](./accessibility-state-experiment.md). It is separate from the second frozen confirmation and has no live benchmark score yet.

## Failure and treatment

An accessibility node can identify a native radio or checkbox whose input is visually clipped while an associated HTML label provides the visible surface. The old `page.click(nodeId)` targets the input's box center, which fails its hit test. The diagnostic agent recovered by explicitly finding and clicking the associated label.

Keep the original click path first. If its hit test fails for a clipped native radio or checkbox, resolve its single visible associated label using the browser's `input.labels` and `label.control` semantics. Validate that label with the existing box/disabled/hit checks before sending physical CDP mouse input. No DOM click, checked-state assignment, domain selector, extra model tool, instruction expansion or automatic action replay is introduced. The ordinary successful click path adds no CDP calls.

A full-sized ordinary input covered by an overlay still fails even if another part of its label is exposed. Disabled controls, covered labels, ambiguous visible labels and an embedded unrelated interactive target also fail. Both resolved remote objects are released. The fallback is bounded to one associated surface before any input is dispatched.

## Verification

The four isolated-Chrome tests initially passed 2/4: both positive activation tests failed on the old implementation, while the rejection cases passed. After the change all four pass. They cover explicit and wrapping labels, native radio/checkbox state transitions, trusted click events, disabled fieldsets, ARIA-disabled inputs, overlays, embedded links, multiple labels, shadow DOM and an explicit frame. Directly clicking a label whose center lands on its own ordinary input remains supported.

The final targeted browser group passes 13/13 tests. The rebuilt Python engine passes 7/7 integration tests. The final full Node suite passes **100/100**, including compaction/journal boundaries and recovery tests; typecheck and docs build also pass. These are local Node/Chrome tests, not live-model quality evidence.

## Compatibility, limits and next evaluation

Public method signatures, snapshots, profiles, transcripts, workspaces, dependencies, model prompts and budgets are unchanged. Existing Python clients use the same rebuilt JavaScript engine. Controls without a layout box still need explicit targeting of their visible UI; this change addresses the observed clipped-input failure. Existing hit tests operate in the element's document; this test set does not establish protection against every ancestor-frame overlay or a page changing between inspection and input.

Rollback is the preceding runtime commit, `7d1c107`. No package publication, migration or legacy Python Browser Use change is involved. Keep all existing confirmation2 SDK pins and outcomes. A future frozen diagnostic must distinguish label-path use from task quality: the earlier live agent already recovered manually, so this fix is not a demonstrated cause of a better score. Complete paired benchmarks remain required for the original two-benchmark acceptance.

[Local verification and source hashes](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/control-label.json).
