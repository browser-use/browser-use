"""Safari watchdog that maps Browser Use events to the Safari backend."""

from __future__ import annotations

import asyncio
from typing import cast

from browser_use.browser.backends.safari_backend import SafariRealProfileBackend
from browser_use.browser.events import (
	AgentFocusChangedEvent,
	BrowserStateRequestEvent,
	ClickCoordinateEvent,
	ClickElementEvent,
	CloseTabEvent,
	GetDropdownOptionsEvent,
	GoBackEvent,
	GoForwardEvent,
	NavigateToUrlEvent,
	NavigationCompleteEvent,
	NavigationStartedEvent,
	RefreshEvent,
	ScrollEvent,
	ScrollToTextEvent,
	SelectDropdownOptionEvent,
	SendKeysEvent,
	SwitchTabEvent,
	TabClosedEvent,
	TypeTextEvent,
	UploadFileEvent,
	WaitEvent,
)
from browser_use.browser.views import BrowserStateSummary
from browser_use.browser.watchdog_base import BaseWatchdog


class SafariWatchdog(BaseWatchdog):
	"""Handle browser events for the Safari real-profile backend."""

	def _backend(self) -> SafariRealProfileBackend:
		backend = self.browser_session._backend
		assert isinstance(backend, SafariRealProfileBackend)
		return backend

	def _clear_cache(self) -> None:
		self.browser_session._cached_browser_state_summary = None
		self.browser_session._cached_selector_map.clear()

	async def on_BrowserStateRequestEvent(self, event: BrowserStateRequestEvent) -> BrowserStateSummary:
		state = await self._backend().get_browser_state_summary(
			include_screenshot=event.include_screenshot,
			include_recent_events=event.include_recent_events,
		)
		return state

	async def on_NavigateToUrlEvent(self, event: NavigateToUrlEvent) -> None:
		await self.event_bus.dispatch(
			NavigationStartedEvent(
				url=event.url,
				target_id=self.browser_session.agent_focus_target_id or 'safari:0:0',
			)
		)
		await self._backend().navigate_to(event.url, new_tab=event.new_tab)
		url = await self._backend().get_current_page_url()
		target_id = self.browser_session.agent_focus_target_id or 'safari:0:0'
		await self.event_bus.dispatch(NavigationCompleteEvent(url=url, target_id=target_id))

	async def on_ClickElementEvent(self, event: ClickElementEvent) -> dict | None:
		self._clear_cache()
		return await self._backend().click_element(event.node, button=event.button)

	async def on_ClickCoordinateEvent(self, event: ClickCoordinateEvent) -> dict | None:
		self._clear_cache()
		return await self._backend().click_coordinate(event.coordinate_x, event.coordinate_y, button=event.button)

	async def on_TypeTextEvent(self, event: TypeTextEvent) -> dict | None:
		self._clear_cache()
		return await self._backend().type_text(event.node, event.text, clear=event.clear)

	async def on_ScrollEvent(self, event: ScrollEvent) -> None:
		self._clear_cache()
		await self._backend().scroll(event.direction, event.amount, node=event.node)

	async def on_GoBackEvent(self, event: GoBackEvent) -> None:
		self._clear_cache()
		await self._backend().go_back()

	async def on_GoForwardEvent(self, event: GoForwardEvent) -> None:
		self._clear_cache()
		await self._backend().go_forward()

	async def on_RefreshEvent(self, event: RefreshEvent) -> None:
		self._clear_cache()
		await self._backend().refresh()

	async def on_WaitEvent(self, event: WaitEvent) -> None:
		await asyncio.sleep(min(event.seconds, event.max_seconds))

	async def on_SendKeysEvent(self, event: SendKeysEvent) -> None:
		self._clear_cache()
		await self._backend().send_keys(event.keys)

	async def on_UploadFileEvent(self, event: UploadFileEvent) -> None:
		self._clear_cache()
		await self._backend().upload_file(event.node, event.file_path)

	async def on_GetDropdownOptionsEvent(self, event: GetDropdownOptionsEvent) -> dict[str, str]:
		return await self._backend().get_dropdown_options(event.node)

	async def on_SelectDropdownOptionEvent(self, event: SelectDropdownOptionEvent) -> dict[str, str]:
		self._clear_cache()
		return await self._backend().select_dropdown_option(event.node, event.text)

	async def on_ScrollToTextEvent(self, event: ScrollToTextEvent) -> None:
		self._clear_cache()
		await self._backend().scroll_to_text(event.text, direction=event.direction)

	async def on_SwitchTabEvent(self, event: SwitchTabEvent) -> str:
		self._clear_cache()
		target_id = await self._backend().focus_tab(cast(str | None, event.target_id))
		tabs = await self._backend().get_tabs()
		url = next((tab.url for tab in tabs if tab.target_id == target_id), 'about:blank')
		await self.event_bus.dispatch(AgentFocusChangedEvent(target_id=target_id, url=url))
		return target_id

	async def on_CloseTabEvent(self, event: CloseTabEvent) -> None:
		self._clear_cache()
		await self._backend().close_tab(cast(str, event.target_id))
		await self.event_bus.dispatch(TabClosedEvent(target_id=cast(str, event.target_id)))
		tabs = await self._backend().get_tabs()
		if tabs:
			current = next((tab for tab in tabs if tab.target_id == self.browser_session.agent_focus_target_id), tabs[0])
			await self.event_bus.dispatch(AgentFocusChangedEvent(target_id=current.target_id, url=current.url))
		else:
			self.browser_session.agent_focus_target_id = None

	async def on_AgentFocusChangedEvent(self, event: AgentFocusChangedEvent) -> None:
		self.browser_session.agent_focus_target_id = event.target_id
		self._clear_cache()
