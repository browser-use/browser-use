"""BrowserSession lifecycle and event-handler wiring."""

from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import urlparse

from bubus import EventBus

from browser_use.browser.events import (
	AgentFocusChangedEvent,
	BrowserErrorEvent,
	BrowserStartEvent,
	BrowserStopEvent,
	BrowserStoppedEvent,
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
		await self.start_direct()

	async def kill(self: Any) -> None:
		"""Kill the browser session and reset all state."""
		self._intentional_stop = True
		self.logger.debug('🛑 kill() called - stopping browser with force=True and resetting state')

		await self._save_storage_state_before_stop()

		await self.stop_direct(force=True)
		await self.event_bus.stop(clear=True, timeout=5)
		await self.reset()
		self.event_bus = EventBus()

	async def stop(self: Any) -> None:
		"""Stop the browser session without killing the browser process."""
		self._intentional_stop = True
		self.logger.debug('⏸️  stop() called - stopping browser gracefully (force=False) and resetting state')

		await self._save_storage_state_before_stop()

		await self.stop_direct(force=False)
		await self.event_bus.stop(clear=True, timeout=5)
		await self.reset()
		self.event_bus = EventBus()

	async def close(self: Any) -> None:
		"""Alias for stop()."""
		await self.stop()

	async def _save_storage_state_before_stop(self: Any) -> None:
		"""Persist storage state directly when the storage watchdog is available."""

		storage_state_watchdog = getattr(self, '_storage_state_watchdog', None)
		if storage_state_watchdog is not None:
			if self.is_cdp_connected:
				await storage_state_watchdog.save_storage_state()
			return

		from browser_use.browser.events import SaveStorageStateEvent

		save_event = self.event_bus.dispatch(SaveStorageStateEvent())
		await save_event

	def _cloud_session_id_from_cdp_url(self: Any) -> str | None:
		"""Derive cloud browser session ID from a Browser Use CDP URL."""
		if not self.cdp_url:
			return None
		host = urlparse(self.cdp_url).hostname or ''
		match = re.match(r'^([0-9a-fA-F-]{36})\.cdp\d+\.browser-use\.com$', host)
		return match.group(1) if match else None

	async def on_BrowserStopEvent(self: Any, event: BrowserStopEvent) -> None:
		"""Compatibility adapter for browser stop events."""
		await self.stop_direct(force=event.force, notify_watchdogs=False)

	async def stop_direct(self: Any, *, force: bool = False, notify_watchdogs: bool = True) -> None:
		"""Stop the browser session without routing through a stop request event."""
		try:
			if notify_watchdogs:
				await self._notify_watchdogs_before_stop()

			if self.browser_profile.keep_alive and not force:
				self.event_bus.dispatch(BrowserStoppedEvent(reason='Kept alive due to keep_alive=True'))
				return

			local_browser_watchdog = self._local_browser_watchdog
			cloud_session_id = self._cloud_browser_client.current_session_id or self._cloud_session_id_from_cdp_url()
			if cloud_session_id:
				try:
					await self._cloud_browser_client.stop_browser(cloud_session_id)
					self.logger.info(f'🌤️ Cloud browser session cleaned up: {cloud_session_id}')
				except Exception as e:
					self.logger.debug(f'Failed to cleanup cloud browser session {cloud_session_id}: {e}')
				finally:
					try:
						await self._cloud_browser_client.close()
					except Exception:
						pass

			self.logger.info(f'📢 stop_direct() - Calling reset() (force={force}, keep_alive={self.browser_profile.keep_alive})')
			await self.reset()

			if self.is_local:
				self.browser_profile.cdp_url = None

			if notify_watchdogs and local_browser_watchdog is not None and self.is_local:
				await local_browser_watchdog.cleanup_browser()

			stop_event = self.event_bus.dispatch(BrowserStoppedEvent(reason='Stopped by request'))
			await stop_event

		except Exception as e:
			self.event_bus.dispatch(
				BrowserErrorEvent(
					error_type='BrowserStopEventError',
					message=f'Failed to stop browser: {type(e).__name__} {e}',
					details={'cdp_url': self.cdp_url, 'is_local': self.is_local},
				)
			)

	async def _notify_watchdogs_before_stop(self: Any) -> None:
		"""Finalize stop-aware watchdogs on the direct public stop path."""

		aboutblank_watchdog = self._aboutblank_watchdog
		if aboutblank_watchdog is not None:
			aboutblank_watchdog.mark_stopping()

		storage_state_watchdog = self._storage_state_watchdog
		if storage_state_watchdog is not None:
			await storage_state_watchdog.stop_monitoring()

		recording_watchdog = self._recording_watchdog
		if recording_watchdog is not None:
			await recording_watchdog.stop_recording()

		har_recording_watchdog = getattr(self, '_har_recording_watchdog', None)
		if har_recording_watchdog is not None:
			await har_recording_watchdog.save_har()
