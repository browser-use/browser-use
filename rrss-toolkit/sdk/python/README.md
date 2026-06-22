# rrss-arm

**ARM (Adaptive Rate Management) — per-host async circuit breaker + KafCa decorators.**

Extracted from `browser-use`. Zero dependencies. Python 3.11+. Async-native.

## Install

```bash
pip install rrss-arm
```

## Use

### Circuit breaker per host

```python
import asyncio
from rrss_arm import HostCircuitBreaker, CircuitOpenError

breaker = HostCircuitBreaker(failure_threshold=3, cooldown_seconds=30.0)

async def safe_fetch(url):
    try:
        await breaker.allow(url)
    except CircuitOpenError:
        return None  # host is unhealthy; skip
    try:
        result = await fetch(url)
    except Exception:
        await breaker.record_failure(url)
        raise
    await breaker.record_success(url)
    return result
```

State machine:
- **closed** — requests flow normally
- **open** — after `failure_threshold` consecutive failures; fails fast for `cooldown_seconds`
- **half_open** — after cooldown, one trial request; success closes, failure reopens

Per-host. One flaky upstream doesn't poison healthy ones.

### KafCa decorators

```python
from rrss_arm import kafca_timeout, kafca_retry

@kafca_retry(attempts=3, base_delay=0.5)
@kafca_timeout(5.0)
async def fetch(url):
    ...
```

Compose `@kafca_retry` outermost so each retry gets a fresh timeout.

## Why "RRSS"

- **R**obust — circuit breaker isolates failures per host
- **R**eliable — async-safe via per-host locks
- **S**olid — O(1) operations, zero deps
- **S**ystematic — explicit state transitions, every action logged

## License

MIT
