---
name: rrss
description: >
  RRSS — Robust, Reliable, Solid, Systematic. Resilience design discipline for
  any production system. Triggers on "rrss", "make this robust", "harden",
  "circuit breaker", "resilience review", "rrss audit", or any mention of RRSS
  principles. Provides a 4-axis checklist + canonical code patterns (ARM
  HostCircuitBreaker, kafca decorators, idempotent operations, per-component
  isolation). Overlays on any skill — works alongside KafCa, KafCade,
  EvoMetaClaw, DevFlow.
---

# RRSS — Robust, Reliable, Solid, Systematic
## Version 1.0 · Design Discipline · Works With Any Skill

RRSS is the **resilience layer** of the KafCa family. Where KafCa governs
communication and code style, RRSS governs **how systems behave under stress**.

---

## THE FOUR AXES

### R — Robust
> Failures are isolated. One bad component cannot poison the rest.

**Patterns:**
- **Per-host circuit breaker** (see `rrss-arm.HostCircuitBreaker`). State machine: closed → open → half_open. Don't share state across upstreams.
- **Bulkheads.** Separate connection pools, separate queues, separate threads per domain.
- **Timeouts everywhere.** No unbounded await. Use `kafca_timeout`.
- **Graceful degradation.** Return partial results rather than failing the whole request.

**Anti-patterns:**
- Global retry loop that hits all upstreams (one bad host → everyone retries).
- Catch-all `try/except Exception: pass` (failures invisible, state corrupt).
- Shared mutable state between independent workflows.

### R — Reliable
> The same input produces the same output. Concurrent calls are safe. Lost work is bounded.

**Patterns:**
- **Idempotent operations.** `PUT`/`DELETE` semantics; deduplicate via request id.
- **Per-resource locks.** `asyncio.Lock` keyed by resource id (see ARM `_HostState.lock`).
- **Atomic state transitions.** No "compute then write" without a lock.
- **Checkpointing.** Long-running work writes progress; resumes from last good state.

**Anti-patterns:**
- "Almost" idempotent (sends twice on retry → duplicate side effects).
- Lock-free read-modify-write on shared state.
- "It works on my machine" (single-threaded test → broken under concurrency).

### S — Solid
> O(1) where possible. Zero unnecessary dependencies. Predictable resource usage.

**Patterns:**
- **Bounded memory.** Caps on queue depth, retry attempts, recursion depth.
- **Constant-time lookups.** Dicts/sets keyed by id; no linear scans on hot path.
- **Minimal dependency surface.** Stdlib > 3rd party where it matters.
- **Explicit limits.** `max_concurrent`, `max_retries`, `timeout` — all configurable, all default-safe.

**Anti-patterns:**
- Unbounded queues / lists growing without limit.
- Pulling in heavy framework for a 50-line concern.
- O(n) where O(1) is trivial (e.g., `for x in list: if x.id == target`).

### S — Systematic
> Every transition is observable. Lineage is auditable. Failure modes are documented.

**Patterns:**
- **Structured logging at boundaries.** Log on state transitions, not every function call.
- **Lineage.** Record what changed, when, and why (see KafCade EvoMetaClaw Lineage block).
- **Explicit state machine.** Use `Literal['closed','open','half_open']` not magic strings.
- **Audit trail.** Every mutation has a recorded cause.

**Anti-patterns:**
- Silent failures (log and continue, but no metric, no alert).
- Implicit state ("the system gets faster after a while" — why?).
- Stack trace tells you what failed but not what was happening.

---

## CANONICAL PATTERNS (with code)

### Circuit breaker (the ARM pattern)

```python
from rrss_arm import HostCircuitBreaker, CircuitOpenError

breaker = HostCircuitBreaker(failure_threshold=3, cooldown_seconds=30.0)

async def safe_call(url):
    try:
        await breaker.allow(url)
    except CircuitOpenError:
        return None
    try:
        result = await fetch(url)
    except Exception:
        await breaker.record_failure(url)
        raise
    await breaker.record_success(url)
    return result
```

### Timeout + retry (KafCa decorators)

```python
from rrss_arm import kafca_retry, kafca_timeout

@kafca_retry(attempts=3, base_delay=0.5)
@kafca_timeout(5.0)
async def fetch(url): ...
```

`@kafca_retry` outermost so each retry gets a fresh timeout. Exponential backoff: `base_delay * 2**n`, capped at `max_delay`.

### Idempotent write

```python
async def create_or_get_resource(request_id: str, payload: dict) -> Resource:
    """Idempotent. Retries with same request_id return the same Resource."""
    existing = await store.get_by_request_id(request_id)
    if existing:
        return existing
    resource = await build_resource(payload)
    await store.put(request_id, resource)
    return resource
```

### Per-resource lock

```python
locks: dict[str, asyncio.Lock] = {}
registry_lock = asyncio.Lock()

async def get_lock(resource_id: str) -> asyncio.Lock:
    if resource_id in locks:
        return locks[resource_id]
    async with registry_lock:
        if resource_id not in locks:
            locks[resource_id] = asyncio.Lock()
        return locks[resource_id]
```

---

## RRSS AUDIT CHECKLIST

Run this on any code that handles external calls, persistence, or concurrent access:

```
Robust
[ ] Every external call has a timeout
[ ] Failures isolated per upstream/resource (circuit breaker or bulkhead)
[ ] No global try/except Exception: pass
[ ] Graceful degradation path exists for partial failure

Reliable
[ ] All mutating operations are idempotent (or guarded by lock + check)
[ ] Concurrent calls produce deterministic output
[ ] State transitions are atomic (under a lock)
[ ] Long-running work checkpoints progress

Solid
[ ] No unbounded queues / lists / recursion
[ ] Hot-path lookups are O(1)
[ ] Configurable limits exist and have safe defaults
[ ] Dependency footprint justified (no framework for a script)

Systematic
[ ] State transitions logged at INFO+
[ ] Failure modes documented (docstring or comment)
[ ] State machines are explicit (typed, not magic strings)
[ ] Lineage / audit trail captured for material changes
```

Score: tally per axis. Anything below 3/4 in a single axis is a risk.

---

## INTEGRATION

| Combined with | Effect |
|---------------|--------|
| `kafca RRSS` | Audit + terse report (metrics first, no narrative) |
| `kc Im` (KafCade Improve) | Improve step prioritises RRSS findings P0-P3 |
| `kc E` (KafCade Evaluate) | Adds RRSS axis scores to the evaluation report |
| `EvoMetaClaw` | RRSS audit findings become evolutionary signal |
| `DevFlow CI` | RRSS gate added before Im/E/C steps |

---

## RRSS ARM EXTENSION (KafCade v2.2)

Beyond the four engineering axes, RRSS extends to the **shipping layer**:

- **A**doption — install grid sorted lowest-friction first (pip > brew > sh > clone).
- **R**etention — pricing tier with upgrade path baked in.
- **M**onetisation — 3-tier (OSS €0 / Pro €X / Enterprise contact).

This is the surface-level RRSS — the same discipline applied to distribution and revenue, not just code.

---

## VERSIONING

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-06-22 | Initial release. 4 axes, canonical patterns, audit checklist, integration matrix, ARM shipping extension. Extracted from KafCa+KafCade+ARM as a standalone overlay skill. |
