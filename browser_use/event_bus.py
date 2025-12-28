"""Browser-use specific EventBus tweaks to allow per-bus concurrency.

This module wraps bubus.EventBus to remove the global cross-bus lock that
serialized all event processing. Each EventBus instance gets its own
re-entrant lock so multiple buses can run in parallel without blocking each
other, while still keeping per-bus ordering guarantees.
"""

import asyncio
import contextvars
from typing import Any

from bubus import BaseEvent
from bubus import EventBus as BubusEventBus
from bubus.service import holds_global_lock, logger as bubus_logger


class _InstanceReentrantLock:
	"""A re-entrant lock scoped to a single EventBus instance."""

	def __init__(self) -> None:
		self._semaphore: asyncio.Semaphore | None = None
		self._loop: asyncio.AbstractEventLoop | None = None
		self._owner: contextvars.ContextVar[asyncio.Task[Any] | None] = contextvars.ContextVar(
			'browser_eventbus_lock_owner', default=None
		)
		self._depth: contextvars.ContextVar[int] = contextvars.ContextVar(
			'browser_eventbus_lock_depth', default=0
		)

	def _get_semaphore(self) -> asyncio.Semaphore:
		current_loop = asyncio.get_running_loop()
		if self._semaphore is None or self._loop != current_loop:
			self._semaphore = asyncio.Semaphore(1)
			self._loop = current_loop
		return self._semaphore

	async def __aenter__(self) -> '_InstanceReentrantLock':
		current_task = asyncio.current_task()
		if current_task is None:
			raise RuntimeError('EventBus lock requires a running asyncio task')

		if self._owner.get() is current_task:
			# Re-entrant path for nested usage on the same task
			self._depth.set(self._depth.get() + 1)
			return self

		await self._get_semaphore().acquire()
		self._owner.set(current_task)
		self._depth.set(1)
		holds_global_lock.set(True)
		return self

	async def __aexit__(
		self,
		exc_type: type[BaseException] | None,
		exc_val: BaseException | None,
		exc_tb: Any,
	) -> None:
		current_task = asyncio.current_task()
		if current_task is None or self._owner.get() is not current_task:
			return

		depth = self._depth.get() - 1
		if depth <= 0:
			self._owner.set(None)
			self._depth.set(0)
			holds_global_lock.set(False)
			self._get_semaphore().release()
		else:
			self._depth.set(depth)

	def locked(self) -> bool:
		"""Return True if the lock is currently held in this loop."""
		try:
			current_loop = asyncio.get_running_loop()
		except RuntimeError:
			return False

		if self._semaphore is None or self._loop != current_loop:
			return False
		return self._semaphore.locked()


class EventBus(BubusEventBus):
	"""EventBus variant that avoids the bubus global lock."""

	def __init__(
		self,
		name: str | None = None,
		wal_path: str | None = None,
		parallel_handlers: bool = False,
		max_history_size: int | None = 50,
	) -> None:
		super().__init__(
			name=name,
			wal_path=wal_path,
			parallel_handlers=parallel_handlers,
			max_history_size=max_history_size,
		)
		self._instance_lock = _InstanceReentrantLock()

	async def step(
		self, event: BaseEvent[Any] | None = None, timeout: float | None = None, wait_for_timeout: float = 0.1
	) -> BaseEvent[Any] | None:
		"""Process a single event without the global cross-bus lock."""
		assert self._on_idle and self.event_queue, 'EventBus._start() must be called before step()'

		from_queue = False
		if event is None:
			event = await self._get_next_event(wait_for_timeout=wait_for_timeout)
			from_queue = True
		if event is None:
			return None

		bubus_logger.debug(f'🏃 {self}.step({event}) STARTING')
		self._on_idle.clear()

		async with self._instance_lock:
			await self.process_event(event, timeout=timeout)
			if from_queue:
				self.event_queue.task_done()

		bubus_logger.debug(f'✅ {self}.step({event}) COMPLETE')
		return event
