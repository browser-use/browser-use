"""BrowserSession lifecycle and event-handler wiring."""

from __future__ import annotations

import asyncio
from typing import Any

from bubus import EventBus

from browser_use.browser.events import (
	AgentFocusChangedEvent,
	BrowserStartEvent,
	BrowserStopEvent,
	CloseTabEvent,
	FileDownloadedEvent,
	NavigateToUrlEvent,
	SwitchTabEvent,
	TabClosedEvent,
	TabCreatedEvent,
)
from browser_use.observability import observe_debug


class BrowserSessionLifecycleMixin:
	"""Lifecycle entrypoints and event handler registration for BrowserSession."""

	def model_post_init(self: Any, __context: Any) -> None:
		"""Register event handlers after model initialization."""
		self._connection_lock = asyncio.Lock()
		self._reconnect_event = asyncio.Event()
		self._reconnect_event.set()

		from browser_use.browser.watchdog_base import BaseWatchdog

		start_handlers = self.event_bus.handlers.get('BrowserStartEvent', [])
		start_handler_names = [getattr(h, '__name__', str(h)) for h in start_handlers]

		if any('on_BrowserStartEvent' in name for name in start_handler_names):
			raise RuntimeError(
				'[BrowserSession] Duplicate handler registration attempted! '
				'on_BrowserStartEvent is already registered. '
				'This likely means BrowserSession was initialized multiple times with the same EventBus.'
			)

		BaseWatchdog.attach_handler_to_session(self, BrowserStartEvent, self.on_BrowserStartEvent)
		BaseWatchdog.attach_handler_to_session(self, BrowserStopEvent, self.on_BrowserStopEvent)
		BaseWatchdog.attach_handler_to_session(self, NavigateToUrlEvent, self.on_NavigateToUrlEvent)
		BaseWatchdog.attach_handler_to_session(self, SwitchTabEvent, self.on_SwitchTabEvent)
		BaseWatchdog.attach_handler_to_session(self, TabCreatedEvent, self.on_TabCreatedEvent)
		BaseWatchdog.attach_handler_to_session(self, TabClosedEvent, self.on_TabClosedEvent)
		BaseWatchdog.attach_handler_to_session(self, AgentFocusChangedEvent, self.on_AgentFocusChangedEvent)
		BaseWatchdog.attach_handler_to_session(self, FileDownloadedEvent, self.on_FileDownloadedEvent)
		BaseWatchdog.attach_handler_to_session(self, CloseTabEvent, self.on_CloseTabEvent)

	@observe_debug(ignore_input=True, ignore_output=True, name='browser_session_start')
	async def start(self: Any) -> None:
		"""Start the browser session."""
		start_event = self.event_bus.dispatch(BrowserStartEvent())
		await start_event
		await start_event.event_result(raise_if_any=True, raise_if_none=False)

	async def kill(self: Any) -> None:
		"""Kill the browser session and reset all state."""
		self._intentional_stop = True
		self.logger.debug('🛑 kill() called - stopping browser with force=True and resetting state')

		from browser_use.browser.events import SaveStorageStateEvent

		save_event = self.event_bus.dispatch(SaveStorageStateEvent())
		await save_event

		await self.event_bus.dispatch(BrowserStopEvent(force=True))
		await self.event_bus.stop(clear=True, timeout=5)
		await self.reset()
		self.event_bus = EventBus()

	async def stop(self: Any) -> None:
		"""Stop the browser session without killing the browser process."""
		self._intentional_stop = True
		self.logger.debug('⏸️  stop() called - stopping browser gracefully (force=False) and resetting state')

		from browser_use.browser.events import SaveStorageStateEvent

		save_event = self.event_bus.dispatch(SaveStorageStateEvent())
		await save_event

		await self.event_bus.dispatch(BrowserStopEvent(force=False))
		await self.event_bus.stop(clear=True, timeout=5)
		await self.reset()
		self.event_bus = EventBus()

	async def close(self: Any) -> None:
		"""Alias for stop()."""
		await self.stop()
