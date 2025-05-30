import asyncio
import inspect
import json
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Any, Union

import anyio
from pydantic import BaseModel

from browser_use.event_bus.views import Event

logger = logging.getLogger(__name__)

# Type alias for event handlers
EventHandler = Union[Callable[[Event], Any], Callable[[Event], Awaitable[Any]]]


class EventBus:
	"""
	Async event bus with write-ahead logging and guaranteed FIFO processing.

	Features:
	- Sync and async event enqueueing
	- Blocking and non-blocking dispatch
	- Write-ahead logging with UUIDs and timestamps
	- FIFO event processing
	- Parallel handler execution per event
	- Serial event processing
	"""

	def __init__(self, name: str | None = None):
		self.name = name or f'EventBus_{hex(id(self))[-6:]}'
		self.event_queue: asyncio.Queue[Event] = asyncio.Queue()
		self.write_ahead_log: list[Event] = []
		self.handlers: dict[str, list[EventHandler]] = defaultdict(list)
		self.all_event_handlers: list[EventHandler] = []
		self.running = False
		self.runner_task: asyncio.Task | None = None
		self.lock = asyncio.Lock()

		# Register default logger handler
		self.on('*', self._default_log_handler)

	async def _default_log_handler(self, event: Event) -> str:
		"""Default handler that logs all events"""
		logger.debug(f'Event processed: {event.event_type} [{event.event_id}] - {event.model_dump_json()}')
		return 'logged'

	def on(self, event_pattern: str | type[BaseModel], handler: EventHandler) -> None:
		"""Subscribe to events matching a pattern, event type name, or event model class.
		Use '*' for all events.

		Examples:
			event_bus.on('*', handler)  # All events
			event_bus.on('TaskStartedEvent', handler)  # Specific event type
			event_bus.on(TaskStartedEvent, handler)  # Event model class
		"""
		# Allow both sync and async handlers
		if event_pattern == '*':
			# Subscribe to all events
			self.all_event_handlers.append(handler)
		elif isinstance(event_pattern, type) and issubclass(event_pattern, BaseModel):
			# Subscribe by model class
			self.handlers[event_pattern.__name__].append(handler)
		else:
			# Subscribe by string event type
			self.handlers[str(event_pattern)].append(handler)

	def _log_event(self, event: Event) -> Event:
		"""Log an event to the write-ahead log"""
		self.write_ahead_log.append(event)
		return event

	async def enqueue(self, event: BaseModel) -> Event:
		"""
		Enqueue an event (non-blocking).
		Returns the event object immediately with UUID but no results.
		Can be awaited to get results when processing completes.
		"""
		# Cloud events inherit from Event, so just use them directly
		if isinstance(event, Event):
			actual_event = event
		else:
			# For other BaseModels, wrap in Event
			event_data = event.model_dump()
			actual_event = Event(data=event_data)

		# Add this EventBus to the path if not already there
		if self.name not in actual_event.path:
			actual_event = actual_event.model_copy(update={'path': actual_event.path + [self.name]})

		self._log_event(actual_event)
		await self.event_queue.put(actual_event)
		return actual_event

	def enqueue_sync(self, event: BaseModel) -> Event:
		"""
		Enqueue an event from sync context (non-blocking).
		Returns the event object immediately with UUID but no results.
		"""
		# Cloud events inherit from Event, so just use them directly
		if isinstance(event, Event):
			actual_event = event
		else:
			# For other BaseModels, wrap in Event
			event_data = event.model_dump()
			actual_event = Event(data=event_data)

		# Add this EventBus to the path if not already there
		if self.name not in actual_event.path:
			actual_event = actual_event.model_copy(update={'path': actual_event.path + [self.name]})

		self._log_event(actual_event)

		# Get or create event loop
		try:
			loop = asyncio.get_running_loop()
			# If loop is running, schedule the coroutine
			asyncio.create_task(self.event_queue.put(actual_event))
		except RuntimeError:
			# No event loop in current thread
			pass

		return actual_event

	async def enqueue_and_wait(self, event: BaseModel) -> Event:
		"""
		Enqueue an event and wait for all handlers to complete (blocking).
		Returns the event object with results included.
		"""
		event_obj = await self.enqueue(event)
		await event_obj.wait_for_completion()
		return event_obj

	def enqueue_and_wait_sync(self, event: BaseModel) -> Event:
		"""
		Enqueue an event and wait for all handlers to complete from sync context (blocking).
		Returns the event object with results included.
		"""
		# Check if there's a running event loop
		try:
			loop = asyncio.get_running_loop()
			# If we get here, we're in an async context
			raise RuntimeError('Cannot call enqueue_and_wait_sync from within running event loop. Use enqueue_and_wait instead.')
		except RuntimeError as e:
			# Check the specific error message
			error_msg = str(e).lower()
			if 'no running loop' in error_msg or 'no current event loop' in error_msg or 'no running event loop' in error_msg:
				# No event loop in current thread, create a new one
				loop = asyncio.new_event_loop()
				asyncio.set_event_loop(loop)
				try:
					return loop.run_until_complete(self.enqueue_and_wait(event))
				finally:
					# Clean up the loop
					loop.close()
					asyncio.set_event_loop(None)
			else:
				# Some other error, re-raise
				raise

	async def enqueue_batch_and_wait(self, events: list[BaseModel]) -> list[Event]:
		"""
		Enqueue a list of events and wait for all of them to complete (blocking).
		Events are processed in FIFO order but this method waits for all to finish.
		Returns a list of completed event objects with results included.
		"""
		if not events:
			return []

		# Enqueue all events (non-blocking)
		event_objects = []
		for event in events:
			event_obj = await self.enqueue(event)
			event_objects.append(event_obj)

		# Wait for all events to complete
		await asyncio.gather(*[event_obj.wait_for_completion() for event_obj in event_objects])

		return event_objects

	def enqueue_batch_and_wait_sync(self, events: list[BaseModel]) -> list[Event]:
		"""
		Enqueue a list of events and wait for all of them to complete from sync context (blocking).
		Events are processed in FIFO order but this method waits for all to finish.
		Returns a list of completed event objects with results included.
		"""
		# Check if there's a running event loop
		try:
			loop = asyncio.get_running_loop()
			# If we get here, we're in an async context
			raise RuntimeError(
				'Cannot call enqueue_batch_and_wait_sync from within running event loop. Use enqueue_batch_and_wait instead.'
			)
		except RuntimeError as e:
			# Check the specific error message
			error_msg = str(e).lower()
			if 'no running loop' in error_msg or 'no current event loop' in error_msg or 'no running event loop' in error_msg:
				# No event loop in current thread, create a new one
				loop = asyncio.new_event_loop()
				asyncio.set_event_loop(loop)
				try:
					return loop.run_until_complete(self.enqueue_batch_and_wait(events))
				finally:
					# Clean up the loop
					loop.close()
					asyncio.set_event_loop(None)
			else:
				# Some other error, re-raise
				raise

	async def _execute_handlers(self, event: Event) -> None:
		"""Execute all handlers for an event in parallel"""
		# Get all applicable handlers
		applicable_handlers = []

		# Add type-specific handlers
		applicable_handlers.extend(self.handlers.get(event.event_type, []))

		# Add all-event handlers
		applicable_handlers.extend(self.all_event_handlers)

		if not applicable_handlers:
			return

		# Execute all handlers in parallel
		tasks = []
		for handler in applicable_handlers:
			# Check for forwarding loops
			if self._would_create_loop(handler, event):
				logger.debug(f'Skipping {handler.__name__} to prevent loop for {event.event_type}')
				continue
			task = asyncio.create_task(self._safe_execute_handler(handler, event))
			tasks.append((handler.__name__, task))

		# Wait for all handlers to complete
		for handler_name, task in tasks:
			try:
				result = await task
				event.results[handler_name] = result
			except Exception as e:
				event.errors[handler_name] = e
				logger.error(f'Handler {handler_name} failed for event {event.event_id}: {e}')

	async def _safe_execute_handler(self, handler: EventHandler, event: Event) -> Any:
		"""Safely execute a single handler"""
		try:
			if inspect.iscoroutinefunction(handler):
				return await handler(event)
			else:
				# Run sync handler in thread pool to avoid blocking
				loop = asyncio.get_event_loop()
				return await loop.run_in_executor(None, handler, event)
		except Exception as e:
			logger.exception(f'Error in handler {handler.__name__} for event {event.event_id}')
			raise

	async def _step(self) -> None:
		"""Process a single event from the queue"""
		try:
			# Get next event (this will block if queue is empty)
			event = await self.event_queue.get()

			# Record start time
			event.started_at = datetime.utcnow()

			# Execute all handlers for this event
			await self._execute_handlers(event)

			# Mark event as completed
			event.mark_completed()

			# Mark task as done
			self.event_queue.task_done()

		except Exception as e:
			logger.exception(f'Error processing event: {e}')

	async def _run_loop(self) -> None:
		"""Main event processing loop"""
		while self.running:
			try:
				async with self.lock:
					await self._step()
			except asyncio.CancelledError:
				break
			except Exception as e:
				logger.exception(f'Error in event loop: {e}')
				# Continue running even if there's an error

	async def start(self) -> None:
		"""Start the event bus processing loop"""
		if self.running:
			return

		self.running = True
		self.runner_task = asyncio.create_task(self._run_loop())
		logger.info('EventBus started')

	async def stop(self) -> None:
		"""Stop the event bus processing loop"""
		if not self.running:
			return

		self.running = False

		if self.runner_task:
			self.runner_task.cancel()
			try:
				await self.runner_task
			except asyncio.CancelledError:
				pass

		logger.info('EventBus stopped')

	async def wait_for_empty_queue(self) -> None:
		"""Wait for all queued events to be processed"""
		await self.event_queue.join()

	def get_event_log(self) -> list[Event]:
		"""Get the write-ahead log of all events"""
		return self.write_ahead_log.copy()

	async def serialize_events_to_file(self, file_path: Path | str) -> None:
		"""Serialize all events to a JSON file

		Args:
			file_path: Path to save the events to
		"""
		file_path = Path(file_path)
		events_data = []

		for event in self.write_ahead_log:
			event_dict = event.model_dump()
			# Convert datetime objects to ISO format strings
			for key in ['timestamp', 'started_at', 'completed_at']:
				if key in event_dict and event_dict[key]:
					event_dict[key] = event_dict[key].isoformat()

			# Convert exception objects to strings in errors dict
			if 'errors' in event_dict:
				event_dict['errors'] = {k: str(v) for k, v in event_dict['errors'].items()}

			events_data.append(event_dict)

		async with asyncio.Lock():
			async with await anyio.open_file(file_path, 'w') as f:
				await f.write(json.dumps(events_data, indent=2, default=str))

	def serialize_events_to_file_sync(self, file_path: Path | str) -> None:
		"""Serialize all events to a JSON file (sync version)

		Args:
			file_path: Path to save the events to
		"""
		file_path = Path(file_path)
		events_data = []

		for event in self.write_ahead_log:
			event_dict = event.model_dump()
			# Convert datetime objects to ISO format strings
			for key in ['timestamp', 'started_at', 'completed_at']:
				if key in event_dict and event_dict[key]:
					event_dict[key] = event_dict[key].isoformat()

			# Convert exception objects to strings in errors dict
			if 'errors' in event_dict:
				event_dict['errors'] = {k: str(v) for k, v in event_dict['errors'].items()}

			events_data.append(event_dict)

		with open(file_path, 'w') as f:
			json.dump(events_data, f, indent=2, default=str)

	# Convenience method that matches the old API
	def emit(self, event: BaseModel) -> Event:
		"""Queue an event for processing. Can be called from sync or async context."""
		return self.enqueue_sync(event)

	def _would_create_loop(self, handler: EventHandler, event: Event) -> bool:
		"""Check if calling this handler would create a loop"""
		# If handler is another EventBus.emit method
		if hasattr(handler, '__self__') and isinstance(handler.__self__, EventBus):
			target_bus = handler.__self__
			return target_bus.name in event.path
		return False

	def fires_on_enter(self, event_type: str | type[Event], params: Callable | None = None):
		"""Decorator that fires an event when entering a function"""
		from functools import wraps

		def decorator(func):
			# Get the actual event class/type
			if isinstance(event_type, str):
				# String event type - will create generic Event
				event_class = Event
				type_name = event_type
			else:
				# Event subclass
				event_class = event_type
				type_name = event_class.__name__

			origin = f'{func.__qualname__}'

			@wraps(func)
			async def async_wrapper(self, *args, **kwargs):
				# Build event parameters
				event_params = {}
				if params:
					if asyncio.iscoroutinefunction(params):
						event_params = await params(self, *args, **kwargs)
					else:
						event_params = params(self, *args, **kwargs)

				# Create and emit event with origin as first path entry
				if event_class == Event:
					# Generic event with string type
					event = Event(data={'event_type': type_name, **event_params}, path=[origin])
				else:
					# Specific event subclass
					event = event_class(**event_params, path=[origin])

				self.event_bus.emit(event)

				# Execute the function
				return await func(self, *args, **kwargs)

			@wraps(func)
			def sync_wrapper(self, *args, **kwargs):
				# Build event parameters
				event_params = {}
				if params:
					event_params = params(self, *args, **kwargs)

				# Create and emit event with origin as first path entry
				if event_class == Event:
					# Generic event with string type
					event = Event(data={'event_type': type_name, **event_params}, path=[origin])
				else:
					# Specific event subclass
					event = event_class(**event_params, path=[origin])

				self.event_bus.emit(event)

				# Execute the function
				return func(self, *args, **kwargs)

			return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper

		return decorator

	def fires_on_exit(self, event_type: str | type[Event], params: Callable | None = None):
		"""Decorator that fires an event when exiting a function (success or failure)"""
		from functools import wraps

		def decorator(func):
			# Get the actual event class/type
			if isinstance(event_type, str):
				event_class = Event
				type_name = event_type
			else:
				event_class = event_type
				type_name = event_class.__name__

			origin = f'{func.__qualname__}'

			@wraps(func)
			async def async_wrapper(self, *args, **kwargs):
				result = None
				error = None
				try:
					# Execute the function
					result = await func(self, *args, **kwargs)
					return result
				except Exception as e:
					error = e
					raise
				finally:
					# Build event parameters
					event_params = {}
					if params:
						if asyncio.iscoroutinefunction(params):
							event_params = await params(self, result, *args, **kwargs)
						else:
							event_params = params(self, result, *args, **kwargs)

					# Create and emit event
					if event_class == Event:
						event = Event(data={'event_type': type_name, **event_params}, path=[origin])
					else:
						event = event_class(**event_params, path=[origin])

					self.event_bus.emit(event)

			@wraps(func)
			def sync_wrapper(self, *args, **kwargs):
				result = None
				error = None
				try:
					# Execute the function
					result = func(self, *args, **kwargs)
					return result
				except Exception as e:
					error = e
					raise
				finally:
					# Build event parameters
					event_params = {}
					if params:
						event_params = params(self, result, *args, **kwargs)

					# Create and emit event
					if event_class == Event:
						event = Event(data={'event_type': type_name, **event_params}, path=[origin])
					else:
						event = event_class(**event_params, path=[origin])

					self.event_bus.emit(event)

			return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper

		return decorator

	def fires_on_error(self, event_type: str | type[Event], params: Callable | None = None):
		"""Decorator that fires an event only when a function raises an exception"""
		from functools import wraps

		def decorator(func):
			# Get the actual event class/type
			if isinstance(event_type, str):
				event_class = Event
				type_name = event_type
			else:
				event_class = event_type
				type_name = event_class.__name__

			origin = f'{func.__qualname__}'

			@wraps(func)
			async def async_wrapper(self, *args, **kwargs):
				try:
					# Execute the function
					return await func(self, *args, **kwargs)
				except Exception as error:
					# Build event parameters
					event_params = {}
					if params:
						if asyncio.iscoroutinefunction(params):
							event_params = await params(self, error, *args, **kwargs)
						else:
							event_params = params(self, error, *args, **kwargs)

					# Create and emit event
					if event_class == Event:
						event = Event(data={'event_type': type_name, 'error': str(error), **event_params}, path=[origin])
					else:
						event = event_class(**event_params, path=[origin])

					self.event_bus.emit(event)
					raise

			@wraps(func)
			def sync_wrapper(self, *args, **kwargs):
				try:
					# Execute the function
					return func(self, *args, **kwargs)
				except Exception as error:
					# Build event parameters
					event_params = {}
					if params:
						event_params = params(self, error, *args, **kwargs)

					# Create and emit event
					if event_class == Event:
						event = Event(data={'event_type': type_name, 'error': str(error), **event_params}, path=[origin])
					else:
						event = event_class(**event_params, path=[origin])

					self.event_bus.emit(event)
					raise

			return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper

		return decorator
