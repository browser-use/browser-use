"""KafCa decorators — concise resilience wrappers for async functions.

Two decorators, no ceremony:

    @kafca_timeout(5.0)
    async def fetch(url): ...

    @kafca_retry(attempts=3, base_delay=0.5)
    async def call(url): ...

Compose them: ``@kafca_retry(...)`` outermost, ``@kafca_timeout(...)`` inner.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from typing import Awaitable, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar('T')
AsyncFn = Callable[..., Awaitable[T]]


def kafca_timeout(seconds: float) -> Callable[[AsyncFn[T]], AsyncFn[T]]:
	"""Wrap an async function with a hard timeout. Raises ``asyncio.TimeoutError``."""
	assert seconds > 0, 'timeout seconds must be positive'

	def decorator(fn: AsyncFn[T]) -> AsyncFn[T]:
		@functools.wraps(fn)
		async def wrapper(*args, **kwargs) -> T:
			return await asyncio.wait_for(fn(*args, **kwargs), timeout=seconds)
		return wrapper
	return decorator


def kafca_retry(
	attempts: int = 3,
	base_delay: float = 0.5,
	max_delay: float = 30.0,
	exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> Callable[[AsyncFn[T]], AsyncFn[T]]:
	"""Retry an async function on exception with exponential backoff.

	delay_n = min(base_delay * 2**n, max_delay). Re-raises the last exception
	after ``attempts`` failures.
	"""
	assert attempts >= 1, 'attempts must be >= 1'
	assert base_delay > 0, 'base_delay must be positive'
	assert max_delay >= base_delay, 'max_delay must be >= base_delay'

	def decorator(fn: AsyncFn[T]) -> AsyncFn[T]:
		@functools.wraps(fn)
		async def wrapper(*args, **kwargs) -> T:
			last_exc: BaseException | None = None
			for attempt in range(attempts):
				try:
					return await fn(*args, **kwargs)
				except exceptions as exc:
					last_exc = exc
					if attempt == attempts - 1:
						break
					delay = min(base_delay * (2 ** attempt), max_delay)
					logger.info(
						'kafca_retry: %s attempt %d/%d failed (%s); sleeping %.2fs',
						fn.__name__, attempt + 1, attempts, type(exc).__name__, delay,
					)
					await asyncio.sleep(delay)
			assert last_exc is not None
			raise last_exc
		return wrapper
	return decorator
