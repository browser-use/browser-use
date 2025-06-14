import asyncio
import inspect
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Union

import anyio
from pydantic import BaseModel
from uuid_extensions import uuid7str

from browser_use.eventbus.models import BaseEvent, UUIDStr

logger = logging.getLogger(__name__)

# Type alias for event handlers
EventHandler = Union[Callable[[BaseEvent], Any], Callable[[BaseEvent], Awaitable[Any]]]


class EventBus:
	"""
	Async event bus with write-ahead logging and guaranteed FIFO processing.

	Features:
	- Enqueue events synchronously, await their results using await event.result()
	- FIFP Write-ahead logging with UUIDs and timestamps,
	- Serial event processing, parallel handler execution per event
	"""

	name: str
	event_queue: asyncio.Queue[BaseEvent]
	event_history: dict[UUIDStr, BaseEvent]
	handlers: dict[str, list[EventHandler]]
	wal_path: Path | None = None
	parallel_handlers: bool = True

	id: UUIDStr
	_is_running: bool = False
	_runloop_task: asyncio.Task | None = None
	_runloop_lock: asyncio.Lock
	_on_idle: asyncio.Event

	def __init__(self, name: str | None = None, wal_path: Path | str | None = None, parallel_handlers: bool = True):
		self.id = uuid7str()
		self.name = name or f'EventBus_{self.id[-8:]}'
		assert self.name.isidentifier(), f'EventBus name must be a unique identifier string, got: {self.name}'
		self.event_queue = asyncio.Queue()
		self.event_history = {}
		self.handlers = defaultdict(list)
		self.parallel_handlers = parallel_handlers
		self._runloop_lock = asyncio.Lock()
		self._on_idle = asyncio.Event()
		self._on_idle.set()  # Start in idle state

		# Set up WAL path and create parent directory if needed
		if wal_path:
			self.wal_path = Path(wal_path)
			self.wal_path.parent.mkdir(parents=True, exist_ok=True)

		# Register default logger handler
		self.on('*', self._default_log_handler)

	def __del__(self):
		"""Auto-cleanup on garbage collection"""
		if self._is_running:
			try:
				loop = asyncio.get_running_loop()
				loop.create_task(self.stop())
			except RuntimeError:
				# No event loop, nothing to clean
				pass

	def __str__(self) -> str:
		return self.name

	def __repr__(self) -> str:
		return self.name

	@property
	def events_queued(self) -> list[BaseEvent]:
		"""Get events that haven't started processing yet"""
		return [event for event in self.event_history.values() if event.event_started_at is None]

	@property
	def events_started(self) -> list[BaseEvent]:
		"""Get events currently being processed"""
		return [event for event in self.event_history.values() if event.event_started_at and not event.event_completed_at]

	@property
	def events_completed(self) -> list[BaseEvent]:
		"""Get events that have completed processing"""
		return [event for event in self.event_history.values() if event.event_completed_at is not None]

	def on(self, event_pattern: str | type[BaseModel], handler: EventHandler) -> None:
		"""
		Subscribe to events matching a pattern, event type name, or event model class.
		Use event_pattern='*' to subscribe to all events. Handler can be sync or async function or method.

		Examples:
			eventbus.on('TaskStartedEvent', handler)  # Specific event type
			eventbus.on(TaskStartedEvent, handler)  # Event model class
			eventbus.on('*', handler)  # Subscribe to all events
			eventbus.on('*', other_eventbus.dispatch)  # Forward all events to another EventBus
		"""
		# Allow both sync and async handlers
		if event_pattern == '*':
			# Subscribe to all events using '*' as the key
			self.handlers['*'].append(handler)
		elif isinstance(event_pattern, type) and issubclass(event_pattern, BaseModel):
			# Subscribe by model class
			self.handlers[event_pattern.__name__].append(handler)
		else:
			# Subscribe by string event type
			self.handlers[str(event_pattern)].append(handler)

	def dispatch(self, event: BaseEvent) -> BaseEvent:
		"""
		Enqueue an event for processing by the handlers. Returns awaitable event object.
		(Auto-starts the EventBus's async _run_loop() if not already running)

		Similar to JS EventListener.dispatchEvent() or eventbus.dispatch() in other languages.
		"""
		assert event.event_id, 'Missing event.event_id: UUIDStr = uuid7str()'
		assert event.event_created_at, 'Missing event.queued_at: datetime = datetime.now(UTC)'
		assert event.event_type and event.event_type.isidentifier(), 'Missing event.event_type: str'
		assert event.event_schema and '@' in event.event_schema, 'Missing event.event_schema: str (with @version)'

		# Add this EventBus to the event_path if not already there
		if self.name not in event.event_path:
			# preserve identity of the original object instead of creating a new one, so that the original object remains awaitable to get the result
			# NOT: event = event.model_copy(update={'event_path': event.event_path + [self.name]})
			event.event_path.append(self.name)

		assert event.event_path, 'Missing event.event_path: list[str] (with at least the origin function name recorded in it)'
		assert all(entry.isidentifier() for entry in event.event_path), (
			f'Event.event_path must be a list of valid EventBus names, got: {event.event_path}'
		)

		# Add event to history
		self.event_history[event.event_id] = event

		self._start()

		# Put event in queue synchronously using put_nowait
		try:
			logger.debug(f'📋 {self} Dispatching event {event.event_type} to queue')
			self.event_queue.put_nowait(event)
		except asyncio.QueueFull:
			logger.error(f'⚠️ {self} Event queue is full! Dropping event {event.event_type}:\n{event.model_dump_json()}')

		return event

	def _start(self) -> None:
		"""Start the event bus if not already running"""
		if not self._is_running:
			try:
				loop = asyncio.get_running_loop()
				self._is_running = True
				self._runloop_task = loop.create_task(self._run_loop())
			except RuntimeError:
				pass  # No event loop - will start when one becomes available

	async def stop(self, timeout: float | None = None) -> None:
		"""Stop the event bus, optionally waiting for events to complete"""
		if not self._is_running:
			return

		# Log current state

		# Wait for completion if timeout specified
		if timeout is not None:
			await self.wait_until_idle(timeout=timeout)

		if self.event_queue.qsize() or self.events_queued or self.events_started:
			logger.warning(
				f'⚠️ {self} stopping with pending events: Queued {self.event_queue.qsize()} | Pending {len(self.events_queued)} | Processing {len(self.events_started)} | Completed {len(self.events_completed)}'
			)

		# Force shutdown
		self._is_running = False
		if self._runloop_task:
			self._runloop_task.cancel()
			try:
				await self._runloop_task
			except asyncio.CancelledError:
				pass

		logger.debug(f'⏹ {self} stopped gracefully' if timeout is not None else f'🛑 {self} stopped immediately')

	async def wait_until_idle(self, timeout: float | None = None) -> None:
		"""Wait until the event bus is idle (no events being processed)"""

		self._start()

		# First wait for the queue to be empty
		await self.event_queue.join()
		# logger.debug(f'Queue joined, processing events: {len(self.events_started)}')

		# Then wait for idle state with timeout
		try:
			await asyncio.wait_for(self._on_idle.wait(), timeout=timeout)
		except TimeoutError:
			logger.warning(
				f'⌛️ {self} Timeout waiting for event bus to be idle after {timeout}s (processing: {len(self.events_started)})'
			)

	async def _run_loop(self) -> None:
		"""Main event processing loop"""
		while self._is_running:
			try:
				# Check if we're idle
				if self.event_queue.empty() and len(self.events_started) == 0:
					self._on_idle.set()
				else:
					self._on_idle.clear()

				try:
					await self._run_loop_step()
				except TimeoutError:
					continue  # No events in queue, continue to idle
			except asyncio.CancelledError:
				break
			except Exception as e:
				logger.exception(f'❌ {self} Error in event loop: {type(e).__name__} {e}')
				# Continue running even if there's an error

	async def _run_loop_step(self, event: BaseEvent | None = None) -> BaseEvent:
		"""Process a single event from the queue"""

		# Wait for next event with timeout to periodically check idle state
		event = event or await asyncio.wait_for(self.event_queue.get(), timeout=0.1)

		# Clear idle state when we get an event
		self._on_idle.clear()

		# Process the event
		async with self._runloop_lock:
			event.event_started_at = datetime.now(UTC)

			# Execute all handlers for this event
			applicable_handlers = self._get_applicable_handlers(event)

			await self._execute_handlers(event, handlers=applicable_handlers)

			# Mark event as completed with empty results dict
			event.record_results(complete=True)

			# Persist to WAL if configured
			if self.wal_path:
				wal_result = await self._default_wal_handler(event)
				# logger.debug(f'WAL persistence result: {wal_result}')

			# Mark task as done
			self.event_queue.task_done()
		return event

	def _get_applicable_handlers(self, event: BaseEvent) -> dict[str, EventHandler]:
		"""Get all handlers that should process the given event, filtering out those that would create loops"""
		applicable_handlers = []

		# Add event-type-specific handlers
		applicable_handlers.extend(self.handlers.get(event.event_type, []))

		# Add wildcard handlers (handlers registered for '*')
		applicable_handlers.extend(self.handlers.get('*', []))

		# Filter out handlers that would create loops and build name->handler mapping
		filtered_handlers = {}
		for handler in applicable_handlers:
			if self._would_create_loop(event, handler):
				logger.debug(f'Skipping {handler.__name__} to prevent loop for {event.event_type}')
				continue
			else:
				filtered_handlers[handler.__name__] = handler

		return filtered_handlers

	async def _execute_handlers(self, event: BaseEvent, handlers: dict[str, EventHandler] | None = None) -> None:
		"""Execute all handlers for an event in parallel"""
		applicable_handlers = handlers if (handlers is not None) else self._get_applicable_handlers(event)
		if not applicable_handlers:
			return

		# Execute all handlers in parallel
		if self.parallel_handlers:
			handler_tasks = {}
			for handler_name, handler in applicable_handlers.items():
				task = asyncio.create_task(self._execute_sync_or_async_handler(event, handler))
				handler_tasks[handler_name] = task

			# Wait for all handlers to complete and record results incrementally
			for handler_name, task in handler_tasks.items():
				try:
					result = await task
					event.record_results({handler_name: result}, complete=False)
				except Exception as e:
					event.event_errors[handler_name] = str(e)
					logger.error(
						f'❌ {self} Handler {handler_name} failed for event {event.event_id}: {type(e).__name__} {e}\n{event.model_dump()}'
					)
		else:
			# otherwise, execute handlers serially, wait until each one completes before moving on to the next
			for handler_name, handler in applicable_handlers.items():
				try:
					result = await self._execute_sync_or_async_handler(event, handler)
					event.record_results({handler_name: result}, complete=False)
				except Exception as e:
					event.event_errors[handler_name] = str(e)
					logger.error(
						f'❌ {self} Handler {handler_name} failed for event {event.event_id}: {type(e).__name__} {e}\n{event.model_dump()}'
					)

	async def _execute_sync_or_async_handler(self, event: BaseEvent, handler: EventHandler) -> Any:
		"""Safely execute a single handler"""
		try:
			if inspect.iscoroutinefunction(handler):
				return await handler(event)
			else:
				# Run sync handler in thread pool to avoid blocking
				loop = asyncio.get_event_loop()
				return await loop.run_in_executor(None, handler, event)
		except Exception as e:
			logger.exception(
				f'❌ {self} Error in handler {handler.__name__} for event {event.event_id}: {type(e).__name__} {e}\n{event.model_dump()}'
			)
			raise

	@staticmethod
	def _would_create_loop(event: BaseEvent, handler: EventHandler) -> bool:
		"""Check if calling this handler would create a loop (i.e. re-process an event that has already been processed by this EventBus)"""
		# If handler is another EventBus.dispatch method
		if hasattr(handler, '__self__') and isinstance(handler.__self__, EventBus) and handler.__name__ == 'dispatch':
			target_bus = handler.__self__
			return target_bus.name in event.event_path
		return False

	async def _default_log_handler(self, event: BaseEvent) -> str:
		"""Default handler that logs all events"""
		logger.debug(
			f'✅ {self} Event processed: {event.event_type} [{event.event_id}] -> {len(event.event_results)} results @ {event.event_completed_at}'
		)
		return 'logged'

	async def _default_wal_handler(self, event: BaseEvent) -> str:
		"""Persist completed event to WAL file as JSONL"""
		if not self.wal_path:
			return 'skipped'

		try:
			# Use model_dump_json which already handles datetime serialization
			event_json = event.model_dump_json()

			# Append as JSONL (one JSON object per line)
			async with await anyio.open_file(self.wal_path, 'a') as f:
				await f.write(event_json + '\n')

			return 'appended'

		except Exception as e:
			logger.error(
				f'❌ {self} Failed to save event {event.event_id} to WAL file: {type(e).__name__} {e}\n{event.model_dump()}'
			)
			return 'failed'
