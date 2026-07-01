"""
Retry decorator + Circuit Breaker for all Comet tools.
No tool should crash the agent — every failure is handled gracefully.
"""
import asyncio
import functools
import time
from enum import Enum
from typing import Callable, Type, TypeVar, Any

T = TypeVar("T")


class CircuitState(Enum):
    CLOSED    = "CLOSED"
    OPEN      = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    def __init__(self, name: str, failure_threshold: int = 5,
                 recovery_timeout: float = 60.0):
        self.name              = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout  = recovery_timeout
        self.state             = CircuitState.CLOSED
        self.failure_count     = 0
        self.last_failure_time = 0.0

    def call_succeeded(self):
        self.failure_count = 0
        self.state = CircuitState.CLOSED

    def call_failed(self):
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN

    def can_attempt(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                return True
            return False
        return True  # HALF_OPEN — let one through


_breakers: dict[str, CircuitBreaker] = {}


def get_breaker(name: str) -> CircuitBreaker:
    if name not in _breakers:
        _breakers[name] = CircuitBreaker(name)
    return _breakers[name]


def with_retry(
    max_attempts: int = 3,
    wait_seconds: float = 2.0,
    exceptions: tuple[Type[Exception], ...] = (Exception,),
    circuit_name: str | None = None,
):
    """
    Async retry decorator with exponential back-off + optional circuit breaker.

    Usage:
        @with_retry(max_attempts=3, circuit_name="browser")
        async def my_fn(...): ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            cb = get_breaker(circuit_name) if circuit_name else None

            if cb and not cb.can_attempt():
                return (f"ERREUR circuit ouvert [{circuit_name}] — "
                        f"trop d'échecs récents.")

            last_err = None
            for attempt in range(1, max_attempts + 1):
                try:
                    result = func(*args, **kwargs)
                    if asyncio.isfuture(result) or asyncio.iscoroutine(result):
                        result = await result
                    if cb:
                        cb.call_succeeded()
                    return result
                except exceptions as e:
                    last_err = e
                    if cb:
                        cb.call_failed()
                    if attempt < max_attempts:
                        wait = wait_seconds * (2 ** (attempt - 1))
                        await asyncio.sleep(wait)

            return f"ERREUR après {max_attempts} tentatives : {last_err}"
        return wrapper
    return decorator
