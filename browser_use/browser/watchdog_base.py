"""Base watchdog class for browser monitoring components."""

import inspect
from collections.abc import Iterable
from typing import Any, ClassVar

from bubus import BaseEvent, EventBus
from pydantic import BaseModel, ConfigDict, Field

from browser_use.browser.session import BrowserSession


class BaseWatchdog(BaseModel):
	"""Base class for all browser watchdogs.

	Watchdogs monitor browser state and emit events based on changes.
	They automatically register event handlers based on method names.

	Handler methods should be named: on_EventTypeName(self, event: EventTypeName)
	"""

	model_config = ConfigDict(
		arbitrary_types_allowed=True, validate_assignment=True, extra='forbid', revalidate_instances='never'
	)

	# Class variables to statically define the list of events relevant to each watchdog
	# (not enforced, just to make it easier to understand the code and debug watchdogs at runtime)
	LISTENS_TO: ClassVar[list[type[BaseEvent[Any]]]] = []  # Events this watchdog listens to
	EMITS: ClassVar[list[type[BaseEvent[Any]]]] = []  # Events this watchdog emits

	# Core dependencies
	event_bus: EventBus = Field()
	browser_session: BrowserSession = Field()

	# Shared state that other watchdogs might need to access should not be defined on BrowserSession, not here!
	# Shared helper methods needed by other watchdogs should be defined on BrowserSession, not here!
	# Alternatively, expose some events on the watchdog to allow access to state/helpers via event_bus system.

	# Private state internal to the watchdog can be defined like this on BaseWatchdog subclasses:
	# _screenshot_cache: dict[str, bytes] = PrivateAttr(default_factory=dict)
	# _browser_crash_watcher_task: asyncio.Task | None = PrivateAttr(default=None)
	# _cdp_download_tasks: WeakSet[asyncio.Task] = PrivateAttr(default_factory=WeakSet)
	# ...

	@property
	def logger(self):
		"""Get the logger from the browser session."""
		return self.browser_session.logger

	async def attach_to_session(self) -> None:
		"""Attach watchdog to its browser session and start monitoring.

		This method handles event listener registration. The watchdog is already
		bound to a browser session via self.browser_session from initialization.
		"""
		# Register event handlers automatically based on method names

		assert self.browser_session is not None, 'Root CDP client not initialized - browser may not be connected yet'

		from browser_use.browser import events

		event_classes = {}
		for name in dir(events):
			obj = getattr(events, name)
			if inspect.isclass(obj) and issubclass(obj, BaseEvent) and obj is not BaseEvent:
				event_classes[name] = obj

		# Find all handler methods (on_EventName)
		registered_events = set()
		for method_name in dir(self):
			if method_name.startswith('on_') and callable(getattr(self, method_name)):
				# Extract event name from method name (on_EventName -> EventName)
				event_name = method_name[3:]  # Remove 'on_' prefix

				if event_name in event_classes:
					event_class = event_classes[event_name]

					# ASSERTION: If LISTENS_TO is defined, enforce it
					if self.LISTENS_TO:
						assert event_class in self.LISTENS_TO, (
							f'[{self.__class__.__name__}] Handler {method_name} listens to {event_name} '
							f'but {event_name} is not declared in LISTENS_TO: {[e.__name__ for e in self.LISTENS_TO]}'
						)

					handler = getattr(self, method_name)

					# Create a wrapper function with unique name to avoid duplicate handler warnings
					# Capture handler by value to avoid closure issues
					def make_unique_handler(actual_handler):
						async def unique_handler(event):
							self.logger.debug(
								f'[{self.__class__.__name__}] calling {actual_handler.__name__}({event.__class__.__name__})'
							)
							try:
								result = await actual_handler(event)
								self.logger.debug(
									f'[{self.__class__.__name__}] {actual_handler.__name__} completed successfully'
								)
								return result
							except Exception as e:
								self.logger.error(
									f'[{self.__class__.__name__}] {actual_handler.__name__} failed: {e}'
								)
								raise

						return unique_handler

					unique_handler = make_unique_handler(handler)
					unique_handler.__name__ = f'{self.__class__.__name__}.{method_name}'

					# Check if this handler is already registered - throw error if duplicate
					existing_handlers = self.event_bus.handlers.get(event_class.__name__, [])
					handler_names = [getattr(h, '__name__', str(h)) for h in existing_handlers]
					
					if unique_handler.__name__ in handler_names:
						raise RuntimeError(
							f'[{self.__class__.__name__}] Duplicate handler registration attempted! '
							f'Handler {unique_handler.__name__} is already registered for {event_name}. '
							f'This likely means attach_to_session() was called multiple times.'
						)
					
					self.event_bus.on(event_class, unique_handler)
					registered_events.add(event_class)
					# logger.debug(
					# 	f'[{self.__class__.__name__}] Registered handler {method_name} for {event_name}, event_class ID: {id(event_class)}, module: {event_class.__module__}'
					# )

					# Debug: Verify handler was actually stored
					# stored_handlers = self.event_bus.handlers.get(event_class, [])
					# logger.debug(
					# 	f'[{self.__class__.__name__}] After registration, {event_name} has {len(stored_handlers)} handlers in EventBus'
					# )

		# ASSERTION: If LISTENS_TO is defined, ensure all declared events have handlers
		if self.LISTENS_TO:
			missing_handlers = set(self.LISTENS_TO) - registered_events
			if missing_handlers:
				missing_names = [e.__name__ for e in missing_handlers]
				self.logger.warning(
					f'[{self.__class__.__name__}] LISTENS_TO declares {missing_names} '
					f'but no handlers found (missing on_{"_, on_".join(missing_names)} methods)'
				)

	def __del__(self) -> None:
		"""Clean up any running tasks during garbage collection."""

		# A BIT OF MAGIC: Cancel any private attributes that look like asyncio tasks
		try:
			for attr_name in dir(self):
				# e.g. _browser_crash_watcher_task = asyncio.Task
				if attr_name.startswith('_') and attr_name.endswith('_task'):
					try:
						task = getattr(self, attr_name)
						if hasattr(task, 'cancel') and callable(task.cancel) and not task.done():
							task.cancel()
							# self.logger.debug(f'[{self.__class__.__name__}] Cancelled {attr_name} during cleanup')
					except Exception:
						pass  # Ignore errors during cleanup

				# e.g. _cdp_download_tasks = WeakSet[asyncio.Task] or list[asyncio.Task]
				if attr_name.startswith('_') and attr_name.endswith('_tasks') and isinstance(getattr(self, attr_name), Iterable):
					for task in getattr(self, attr_name):
						try:
							if hasattr(task, 'cancel') and callable(task.cancel) and not task.done():
								task.cancel()
								# self.logger.debug(f'[{self.__class__.__name__}] Cancelled {attr_name} during cleanup')
						except Exception:
							pass  # Ignore errors during cleanup
		except Exception as e:
			from browser_use.utils import logger

			logger.error(f'⚠️ Error during BrowserSession {self.__class__.__name__} gargabe collection __del__(): {type(e)}: {e}')
