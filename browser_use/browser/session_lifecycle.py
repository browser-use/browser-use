"""BrowserSession lifecycle and event-handler wiring."""

from __future__ import annotations

import asyncio
import contextlib
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

		if getattr(self, '_storage_state_watchdog', None) is not None:
			if self.is_cdp_connected:
				from browser_use.browser.services import StorageStateService

				await StorageStateService(browser_session=self).save()
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
			self._intentional_stop = True
			await self._cancel_reconnect_task()

			if notify_watchdogs:
				await self._notify_watchdogs_before_stop()

			if self.browser_profile.keep_alive and not force:
				await self._notify_browser_stopped_compatibility('Kept alive due to keep_alive=True')
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

			await self._notify_browser_stopped_compatibility('Stopped by request')

		except Exception as e:
			self.event_bus.dispatch(
				BrowserErrorEvent(
					error_type='BrowserStopEventError',
					message=f'Failed to stop browser: {type(e).__name__} {e}',
					details={'cdp_url': self.cdp_url, 'is_local': self.is_local},
				)
			)

	async def _cancel_reconnect_task(self: Any) -> None:
		"""Stop pending CDP reconnect work before intentional shutdown."""
		reconnect_task = getattr(self, '_reconnect_task', None)
		current_task = asyncio.current_task()
		if reconnect_task is not None and reconnect_task is not current_task and not reconnect_task.done():
			reconnect_task.cancel()
			with contextlib.suppress(asyncio.CancelledError):
				await reconnect_task
		self._reconnect_task = None
		self._reconnecting = False
		self._reconnect_event.set()

	async def _notify_browser_stopped_compatibility(self: Any, reason: str) -> None:
		"""Notify BrowserStoppedEvent listeners without making them control stop semantics."""

		try:
			stop_event = self.event_bus.dispatch(BrowserStoppedEvent(reason=reason))
			await stop_event
		except Exception as exc:
			self.logger.debug(f'BrowserStoppedEvent compatibility notification failed: {type(exc).__name__}: {exc}')

	async def _notify_watchdogs_before_stop(self: Any) -> None:
		"""Finalize stop-aware watchdogs on the direct public stop path."""
		from browser_use.browser.services import LifecycleService

		await LifecycleService(browser_session=self).finalize_before_stop()

	async def _initialize_browser_connected_services_direct(self: Any) -> None:
		"""Initialize browser-connected services without relying on BrowserConnectedEvent."""
		from browser_use.browser.services import LifecycleService

		await LifecycleService(browser_session=self).initialize_connected_services()

	async def _initialize_target_services_direct(self: Any, target_id: str, url: str = '') -> None:
		"""Initialize per-target services without relying on TabCreatedEvent subscribers."""
		from browser_use.browser.services import LifecycleService

		await LifecycleService(browser_session=self).initialize_target_services(target_id, url)

	async def _notify_tab_created_compatibility(self: Any, target_id: str, url: str = '') -> None:
		"""Notify TabCreatedEvent listeners without making them own target setup."""

		try:
			tab_event = self.event_bus.dispatch(TabCreatedEvent(url=url, target_id=target_id))
			await tab_event
		except Exception as exc:
			self.logger.debug(f'TabCreatedEvent compatibility notification failed: {type(exc).__name__}: {exc}')
