# Verify tab removal after closing

A full local suite failed the external-browser ownership check: two tabs remained immediately after `close()` where only the caller's one tab should remain. The isolated rerun passed. That intermittent observation alone does not identify the precise browser scheduling event.

Inspection found a deterministic gap: cleanup awaited `Target.closeTarget` acknowledgements, then returned without verifying target disappearance. An acknowledgement can precede destruction. Forced real-Chrome tests hold the target open after a successful acknowledgement; the prior runtime reports successful cleanup in both the delayed-removal and never-removed cases.

## Change

Keep the existing ownership inventory and descendant discovery. Send each owned-target close once. Then poll `Target.getTargets` until those known targets are absent, or the operation-timeout polling window expires. Each protocol request remains separately bounded by `operationTimeoutMs`; a request already in flight can finish after the polling deadline. The connection is always closed. Caller-owned targets are excluded, and no close action is replayed.

If owned targets remain, `close()` rejects with their IDs instead of silently reporting success. The SDK does not terminate an external browser to hide failed cleanup. The caller can inspect those reported targets through its own browser connection. The session itself remains closed; this does not add automatic cleanup retries. A locally launched Chrome still follows its existing process-close path in `finally`.

Normal cleanup adds a read-only target query and, while destruction is pending, waits up to the existing polling window plus an in-flight request timeout. There are no model calls or changes to browser actions during tasks, profiles, cookies, session history, output files, or legacy Python Browser Use.

## Evidence

The two new fault tests fail against the previous built runtime: the delayed case returns before removal; the permanent case fails to reject. After the patch, both pass. The tests verify one close request, observed disappearance for the delayed case, explicit failure for the permanent case, and survival of the caller's tab. The preexisting real-Chrome timeout/ownership/cookie test also passes. The final working tree, including the separately prepared semantic guidance, passes **94/94 Node tests**, **7/7 tests of the rebuilt Python engine**, typecheck and the docs build.

These tests prove the cleanup contract under forced delayed acknowledgements. They do not establish that this mechanism caused every prior Cloud cleanup warning, nor do they prove a benchmark score gain. The current full benchmark runs remain unchanged at `f41c5b7`. [Verification record](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/cleanup-verification.json).

Rollback removes the verification loop and restores previous connection timeout selection. It does not alter saved artifacts or external profiles. The Python engine must be rebuilt with the runtime. No publication or merge is part of this patch.
