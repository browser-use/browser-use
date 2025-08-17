"""Base watchdog class for browser monitoring components."""

import inspect
import time
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
		arbitrary_types_allowed=True,  # allow non-serializable objects like EventBus/BrowserSession in fields
		extra='forbid',  # dont allow implicit class/instance state, everything must be a properly typed Field or PrivateAttr
		validate_assignment=False,  # avoid re-triggering  __init__ / validators on values on every assignment
		revalidate_instances='never',  # avoid re-triggering __init__ / validators and erasing private attrs
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

	@staticmethod
	def attach_handler_to_session(browser_session: 'BrowserSession', event_class: type[BaseEvent[Any]], handler) -> None:
		"""Attach a single event handler to a browser session.

		Args:
			browser_session: The browser session to attach to
			event_class: The event class to listen for
			handler: The handler method (must start with 'on_' and end with event type)
		"""
		event_bus = browser_session.event_bus

		# Validate handler naming convention
		assert hasattr(handler, '__name__'), 'Handler must have a __name__ attribute'
		assert handler.__name__.startswith('on_'), f'Handler {handler.__name__} must start with "on_"'
		assert handler.__name__.endswith(event_class.__name__), (
			f'Handler {handler.__name__} must end with event type {event_class.__name__}'
		)

		# Get the watchdog instance if this is a bound method
		watchdog_instance = getattr(handler, '__self__', None)
		watchdog_class_name = watchdog_instance.__class__.__name__ if watchdog_instance else 'Unknown'

		# Color codes for logging
		red = '\033[91m'
		green = '\033[92m'
		yellow = '\033[93m'
		magenta = '\033[95m'
		cyan = '\033[96m'
		reset = '\033[0m'

		# Create a wrapper function with unique name to avoid duplicate handler warnings
		# Capture handler by value to avoid closure issues
		def make_unique_handler(actual_handler):
			async def unique_handler(event):
				# just for debug logging, not used for anything else
				parent_event = event_bus.event_history.get(event.event_parent_id) if event.event_parent_id else None
				grandparent_event = (
					event_bus.event_history.get(parent_event.event_parent_id)
					if parent_event and parent_event.event_parent_id
					else None
				)
				parent = (
					f'{yellow}↲  triggered by {cyan}on_{parent_event.event_type}#{parent_event.event_id[-4:]}{reset}'
					if parent_event
					else f'{magenta}👈 by Agent{reset}'
				)
				grandparent = (
					(
						f'{yellow}↲  under {cyan}{grandparent_event.event_type}#{grandparent_event.event_id[-4:]}{reset}'
						if grandparent_event
						else f'{magenta}👈 by Agent{reset}'
					)
					if parent_event
					else ''
				)
				event_str = f'#{event.event_id[-4:]}'
				time_start = time.time()
				watchdog_and_handler_str = f'[{watchdog_class_name}.{actual_handler.__name__}({event_str})]'.ljust(54)
				browser_session.logger.debug(
					f'{cyan}🚌 {watchdog_and_handler_str} ⏳ Starting...      {reset} {parent} {grandparent}'
				)

				try:
					# **EXECUTE THE EVENT HANDLER FUNCTION**
					result = await actual_handler(event)

					if isinstance(result, Exception):
						raise result

					# just for debug logging, not used for anything else
					time_end = time.time()
					time_elapsed = time_end - time_start
					result_summary = '' if result is None else f' ➡️ {magenta}<{type(result).__name__}>{reset}'
					parents_summary = f' {parent}'.replace('↲  triggered by ', f'⤴  {green}returned to  {cyan}').replace(
						'👈 by Agent', f'👉 {green}returned to  {magenta}Agent{reset}'
					)
					browser_session.logger.debug(
						f'{green}🚌 {watchdog_and_handler_str} ✅ Succeeded ({time_elapsed:.2f}s){reset}{result_summary}{parents_summary}'
					)
					return result
				except Exception as e:
					time_end = time.time()
					time_elapsed = time_end - time_start
					original_error = e
					browser_session.logger.error(
						f'{red}🚌 {watchdog_and_handler_str} ❌ Failed ({time_elapsed:.2f}s): {type(e).__name__}: {e}{reset}'
					)

					# attempt to repair potentially crashed CDP session
					try:
						if browser_session.agent_focus and browser_session.agent_focus.target_id:
							# Common issue with CDP, some calls need the target to be active/foreground to succeed:
							#   screenshot, scroll, Page.handleJavaScriptDialog, and some others
							browser_session.logger.debug(
								f'{yellow}🚌 {watchdog_and_handler_str} ⚠️ Re-foregrounding target to try and recover crashed CDP session\n\t{browser_session.agent_focus}{reset}'
							)
							del browser_session._cdp_session_pool[browser_session.agent_focus.target_id]
							browser_session.agent_focus = await browser_session.get_or_create_cdp_session(
								target_id=browser_session.agent_focus.target_id, new_socket=True
							)
							await browser_session.agent_focus.cdp_client.send.Target.activateTarget(
								params={'targetId': browser_session.agent_focus.target_id}
							)
						else:
							await browser_session.get_or_create_cdp_session(target_id=None, new_socket=True, focus=True)
					except Exception as sub_error:
						if 'ConnectionClosedError' in str(type(sub_error)) or 'ConnectionError' in str(type(sub_error)):
							browser_session.logger.error(
								f'{red}🚌 {watchdog_and_handler_str} ❌ Browser closed or CDP Connection disconnected by remote. {red}{type(sub_error).__name__}: {sub_error}{reset}\n'
							)
							raise
						else:
							browser_session.logger.error(
								f'{red}🚌 {watchdog_and_handler_str} ❌ CDP connected but failed to re-create CDP session after error "{type(original_error).__name__}: {original_error}" in {cyan}{actual_handler.__name__}({event.event_type}#{event.event_id[-4:]}){reset}: due to {red}{type(sub_error).__name__}: {sub_error}{reset}\n'
							)

					raise

			return unique_handler

		unique_handler = make_unique_handler(handler)
		unique_handler.__name__ = f'{watchdog_class_name}.{handler.__name__}'

		# Check if this handler is already registered - throw error if duplicate
		existing_handlers = event_bus.handlers.get(event_class.__name__, [])
		handler_names = [getattr(h, '__name__', str(h)) for h in existing_handlers]

		if unique_handler.__name__ in handler_names:
			raise RuntimeError(
				f'[{watchdog_class_name}] Duplicate handler registration attempted! '
				f'Handler {unique_handler.__name__} is already registered for {event_class.__name__}. '
				f'This likely means attach_to_session() was called multiple times.'
			)

		event_bus.on(event_class, unique_handler)

	def attach_to_session(self) -> None:
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

					# Use the static helper to attach the handler
					self.attach_handler_to_session(self.browser_session, event_class, handler)
					registered_events.add(event_class)

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
