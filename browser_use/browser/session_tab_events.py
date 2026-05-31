"""BrowserSession tab, focus, and download event handlers."""

from __future__ import annotations

from typing import Any, cast

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
		return await self.switch_tab_direct(event.target_id, require_existing_focus=True, emit_event=True)

	async def switch_tab_direct(
		self: Any,
		target_id: TargetID | None = None,
		*,
		require_existing_focus: bool = False,
		emit_event: bool = False,
	) -> TargetID:
		"""Switch the active tab without routing through a request event."""

		if require_existing_focus and not self.agent_focus_target_id:
			raise RuntimeError('Cannot switch tabs - browser not connected')

		if self.agent_focus_target_id is None and target_id is None:
			cdp_session = await self.get_or_create_cdp_session(target_id=None, focus=True)
			return cdp_session.target_id

		page_targets = self.session_manager.get_all_page_targets()
		if target_id is None:
			if page_targets:
				target_id = page_targets[-1].target_id
			else:
				assert self._cdp_client_root is not None, 'CDP client root not initialized - browser may not be connected yet'
				new_target = await self._cdp_client_root.send.Target.createTarget(params={'url': 'about:blank'})
				target_id = cast(TargetID, new_target['targetId'])
				await self._apply_viewport_to_target(target_id)
				await self._set_agent_focus_direct(target_id=target_id, url='about:blank', emit_event=emit_event)
				return target_id

		selected_target_id = cast(TargetID, target_id)
		cdp_session = await self.get_or_create_cdp_session(target_id=selected_target_id, focus=True)

		await cdp_session.cdp_client.send.Target.activateTarget(params={'targetId': selected_target_id})

		target = self.session_manager.get_target(selected_target_id)

		await self._set_agent_focus_direct(target_id=target.target_id, url=target.url, emit_event=emit_event)
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
		await self._apply_viewport_to_target(event.target_id)

	async def _apply_viewport_to_target(self: Any, target_id: TargetID) -> None:
		"""Apply configured viewport directly without relying on event-bus routing."""
		if self.browser_profile.viewport and not self.browser_profile.no_viewport:
			try:
				viewport_width = self.browser_profile.viewport.width
				viewport_height = self.browser_profile.viewport.height
				device_scale_factor = self.browser_profile.device_scale_factor or 1.0

				self.logger.info(
					f'Setting viewport to {viewport_width}x{viewport_height} with device scale factor {device_scale_factor} whereas original device scale factor was {self.browser_profile.device_scale_factor}'
				)
				await self._cdp_set_viewport(viewport_width, viewport_height, device_scale_factor, target_id=target_id)

				self.logger.debug(f'Applied viewport {viewport_width}x{viewport_height} to tab {target_id[-8:]}')
			except Exception as e:
				self.logger.warning(f'Failed to set viewport for tab {target_id[-8:]}: {e}')

	async def on_TabClosedEvent(self: Any, event: TabClosedEvent) -> None:
		"""Handle tab closure - update focus if needed."""
		if not self.agent_focus_target_id:
			return

		current_target_id = self.agent_focus_target_id

		if current_target_id == event.target_id:
			await self.switch_tab_direct(None)

	async def on_AgentFocusChangedEvent(self: Any, event: AgentFocusChangedEvent) -> None:
		"""Handle agent focus change - update focus and clear cache."""
		await self._set_agent_focus_direct(target_id=event.target_id, url=event.url, emit_event=False)

	def _clear_browser_state_cache_direct(self: Any, *, reason: str = 'browser state changed') -> None:
		"""Clear DOM/browser-state caches without routing through focus events."""
		if self._dom_watchdog:
			self._dom_watchdog.clear_cache()

		self._cached_browser_state_summary = None
		self._cached_selector_map.clear()
		self.logger.debug(f'🔄 Cached browser state cleared ({reason})')

	async def _set_agent_focus_direct(
		self: Any,
		*,
		target_id: TargetID,
		url: str | None = None,
		emit_event: bool = True,
	) -> None:
		"""Set active tab state directly; optionally notify event subscribers."""
		self.logger.debug(f'🔄 Agent focus direct set: target_id=...{target_id[-4:]} url={url}')
		self._clear_browser_state_cache_direct(reason='agent focus changed')

		await self.get_or_create_cdp_session(target_id=target_id, focus=True)
		await self._apply_viewport_to_target(target_id)

		if emit_event:
			try:
				self.event_bus.dispatch(AgentFocusChangedEvent(target_id=target_id, url=url or ''))
			except Exception as e:
				self.logger.debug(f'AgentFocusChangedEvent subscriber notification failed: {type(e).__name__}: {e}')

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
