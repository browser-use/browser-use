"""BrowserSession tab, focus, and download event handlers."""

from __future__ import annotations

from typing import Any

from cdp_use.cdp.target import TargetID

from browser_use.browser.events import (
	AgentFocusChangedEvent,
	CloseTabEvent,
	FileDownloadedEvent,
	SwitchTabEvent,
	TabClosedEvent,
	TabCreatedEvent,
)


class BrowserSessionTabEventsMixin:
	"""Tab, focus, and download event handlers for BrowserSession."""

	async def on_SwitchTabEvent(self: Any, event: SwitchTabEvent) -> TargetID:
		"""Handle tab switching - core browser functionality."""
		if not self.agent_focus_target_id:
			raise RuntimeError('Cannot switch tabs - browser not connected')

		page_targets = self.session_manager.get_all_page_targets()
		if event.target_id is None:
			if page_targets:
				event.target_id = page_targets[-1].target_id
			else:
				assert self._cdp_client_root is not None, 'CDP client root not initialized - browser may not be connected yet'
				new_target = await self._cdp_client_root.send.Target.createTarget(params={'url': 'about:blank'})
				target_id = new_target['targetId']
				self.event_bus.dispatch(TabCreatedEvent(url='about:blank', target_id=target_id))
				self.event_bus.dispatch(AgentFocusChangedEvent(target_id=target_id, url='about:blank'))
				return target_id

		assert event.target_id is not None, 'target_id must be set at this point'
		cdp_session = await self.get_or_create_cdp_session(target_id=event.target_id, focus=True)

		await cdp_session.cdp_client.send.Target.activateTarget(params={'targetId': event.target_id})

		target = self.session_manager.get_target(event.target_id)

		await self.event_bus.dispatch(
			AgentFocusChangedEvent(
				target_id=target.target_id,
				url=target.url,
			)
		)
		return target.target_id

	async def on_CloseTabEvent(self: Any, event: CloseTabEvent) -> None:
		"""Handle tab closure - update focus if needed."""
		try:
			await self.event_bus.dispatch(TabClosedEvent(target_id=event.target_id))

			try:
				cdp_session = await self.get_or_create_cdp_session(target_id=None, focus=False)
				await cdp_session.cdp_client.send.Target.closeTarget(params={'targetId': event.target_id})
			except Exception as e:
				self.logger.debug(f'Target may already be closed: {e}')
		except Exception as e:
			self.logger.warning(f'Error during tab close cleanup: {e}')

	async def on_TabCreatedEvent(self: Any, event: TabCreatedEvent) -> None:
		"""Handle tab creation - apply viewport settings to new tab."""
		if self.browser_profile.viewport and not self.browser_profile.no_viewport:
			try:
				viewport_width = self.browser_profile.viewport.width
				viewport_height = self.browser_profile.viewport.height
				device_scale_factor = self.browser_profile.device_scale_factor or 1.0

				self.logger.info(
					f'Setting viewport to {viewport_width}x{viewport_height} with device scale factor {device_scale_factor} whereas original device scale factor was {self.browser_profile.device_scale_factor}'
				)
				await self._cdp_set_viewport(viewport_width, viewport_height, device_scale_factor, target_id=event.target_id)

				self.logger.debug(f'Applied viewport {viewport_width}x{viewport_height} to tab {event.target_id[-8:]}')
			except Exception as e:
				self.logger.warning(f'Failed to set viewport for new tab {event.target_id[-8:]}: {e}')

	async def on_TabClosedEvent(self: Any, event: TabClosedEvent) -> None:
		"""Handle tab closure - update focus if needed."""
		if not self.agent_focus_target_id:
			return

		current_target_id = self.agent_focus_target_id

		if current_target_id == event.target_id:
			await self.event_bus.dispatch(SwitchTabEvent(target_id=None))

	async def on_AgentFocusChangedEvent(self: Any, event: AgentFocusChangedEvent) -> None:
		"""Handle agent focus change - update focus and clear cache."""
		self.logger.debug(f'🔄 AgentFocusChangedEvent received: target_id=...{event.target_id[-4:]} url={event.url}')

		if self._dom_watchdog:
			self._dom_watchdog.clear_cache()

		self._cached_browser_state_summary = None
		self._cached_selector_map.clear()
		self.logger.debug('🔄 Cached browser state cleared')

		if event.target_id:
			await self.get_or_create_cdp_session(target_id=event.target_id, focus=True)

			if self.browser_profile.viewport and not self.browser_profile.no_viewport:
				try:
					viewport_width = self.browser_profile.viewport.width
					viewport_height = self.browser_profile.viewport.height
					device_scale_factor = self.browser_profile.device_scale_factor or 1.0

					await self._cdp_set_viewport(viewport_width, viewport_height, device_scale_factor, target_id=event.target_id)

					self.logger.debug(f'Applied viewport {viewport_width}x{viewport_height} to tab {event.target_id[-8:]}')
				except Exception as e:
					self.logger.warning(f'Failed to set viewport for tab {event.target_id[-8:]}: {e}')
		else:
			raise RuntimeError('AgentFocusChangedEvent received with no target_id for newly focused tab')

	async def on_FileDownloadedEvent(self: Any, event: FileDownloadedEvent) -> None:
		"""Track downloaded files during this session."""
		self.logger.debug(f'FileDownloadedEvent received: {event.file_name} at {event.path}')
		if event.path and event.path not in self._downloaded_files:
			self._downloaded_files.append(event.path)
			self.logger.info(f'📁 Tracked download: {event.file_name} ({len(self._downloaded_files)} total downloads in session)')
		else:
			if not event.path:
				self.logger.warning(f'FileDownloadedEvent has no path: {event}')
			else:
				self.logger.debug(f'File already tracked: {event.path}')
