from __future__ import annotations

from typing import Any, Literal

from cdp_use.cdp.target import TargetID
from pydantic import BaseModel, ConfigDict

from browser_use.browser.events import (
	ClickCoordinateEvent,
	ClickElementEvent,
	CloseTabEvent,
	ScrollEvent,
	SwitchTabEvent,
	TypeTextEvent,
)
from browser_use.browser.session import BrowserSession
from browser_use.browser.views import BrowserStateSummary, TabInfo


class BrowserService(BaseModel):
	"""Base class for explicit browser services."""

	model_config = ConfigDict(arbitrary_types_allowed=True)

	browser_session: BrowserSession


class BrowserStateService(BrowserService):
	"""Fresh browser state capture."""

	async def get_state(
		self,
		*,
		include_screenshot: bool = True,
		cached: bool = False,
		include_recent_events: bool = False,
	) -> BrowserStateSummary:
		return await self.browser_session.get_browser_state_summary(
			include_screenshot=include_screenshot,
			cached=cached,
			include_recent_events=include_recent_events,
		)

	async def get_text(self) -> str:
		return await self.browser_session.get_state_as_text()


class NavigationService(BrowserService):
	"""Page navigation operations."""

	async def navigate(self, url: str, *, new_tab: bool = False) -> None:
		await self.browser_session.navigate_to(url, new_tab=new_tab)

	async def current_url(self) -> str:
		return await self.browser_session.get_current_page_url()

	async def current_title(self) -> str:
		return await self.browser_session.get_current_page_title()


class TabService(BrowserService):
	"""Tab listing and focus operations."""

	async def list_tabs(self) -> list[TabInfo]:
		return await self.browser_session.get_tabs()

	async def switch(self, target_id: TargetID | None = None) -> TargetID:
		event = self.browser_session.event_bus.dispatch(SwitchTabEvent(target_id=target_id))
		await event
		result = await event.event_result(raise_if_any=True, raise_if_none=True)
		assert result is not None
		return result

	async def close(self, target_id: TargetID) -> None:
		event = self.browser_session.event_bus.dispatch(CloseTabEvent(target_id=target_id))
		await event
		await event.event_result(raise_if_any=True, raise_if_none=False)


class ClickService(BrowserService):
	"""Element and coordinate clicking.

	The current implementation intentionally delegates to the existing action
	handlers. This gives the new runtime one explicit call site that can later
	move the click heuristics out of the watchdog.
	"""

	async def click_index(self, index: int, *, button: Literal['left', 'right', 'middle'] = 'left') -> dict[str, Any] | None:
		node = await self.browser_session.get_element_by_index(index)
		if node is None:
			raise ValueError(f'No element found for index {index}')
		event = self.browser_session.event_bus.dispatch(ClickElementEvent(node=node, button=button))
		await event
		return await event.event_result(raise_if_any=True, raise_if_none=False)

	async def click_coordinates(
		self,
		coordinate_x: int,
		coordinate_y: int,
		*,
		button: Literal['left', 'right', 'middle'] = 'left',
		force: bool = False,
	) -> dict[str, Any] | None:
		event = self.browser_session.event_bus.dispatch(
			ClickCoordinateEvent(coordinate_x=coordinate_x, coordinate_y=coordinate_y, button=button, force=force)
		)
		await event
		return await event.event_result(raise_if_any=True, raise_if_none=False)


class TypeService(BrowserService):
	"""Text entry operations."""

	async def type_index(
		self,
		index: int,
		text: str,
		*,
		clear: bool = True,
		is_sensitive: bool = False,
		sensitive_key_name: str | None = None,
	) -> dict[str, Any] | None:
		node = await self.browser_session.get_element_by_index(index)
		if node is None:
			raise ValueError(f'No element found for index {index}')
		event = self.browser_session.event_bus.dispatch(
			TypeTextEvent(
				node=node,
				text=text,
				clear=clear,
				is_sensitive=is_sensitive,
				sensitive_key_name=sensitive_key_name,
			)
		)
		await event
		return await event.event_result(raise_if_any=True, raise_if_none=False)


class ScrollService(BrowserService):
	"""Scrolling operations."""

	async def scroll_page(self, amount: int, *, direction: Literal['up', 'down', 'left', 'right'] = 'down') -> None:
		event = self.browser_session.event_bus.dispatch(ScrollEvent(direction=direction, amount=amount, node=None))
		await event
		await event.event_result(raise_if_any=True, raise_if_none=False)


class DownloadService(BrowserService):
	"""Downloaded file access."""

	def list_downloads(self) -> list[str]:
		return self.browser_session.downloaded_files


class DialogService(BrowserService):
	"""Dialog state captured by popup handling."""

	def closed_messages(self) -> list[str]:
		return list(self.browser_session._closed_popup_messages)


class NetworkService(BrowserService):
	"""Network configuration helpers."""

	async def set_extra_headers(self, headers: dict[str, str], *, target_id: TargetID | None = None) -> None:
		await self.browser_session.set_extra_headers(headers, target_id=target_id)


class StorageStateService(BrowserService):
	"""Storage state import/export helpers."""

	async def export(self, output_path: str | None = None) -> dict[str, Any]:
		return await self.browser_session.export_storage_state(output_path=output_path)


class LifecycleService(BrowserService):
	"""Browser lifecycle operations."""

	async def start(self) -> None:
		await self.browser_session.start()

	async def stop(self) -> None:
		await self.browser_session.stop()

	async def kill(self) -> None:
		await self.browser_session.kill()


class ActionService(BaseModel):
	"""Grouped browser action services."""

	model_config = ConfigDict(arbitrary_types_allowed=True)

	click: ClickService
	type: TypeService
	scroll: ScrollService
	navigation: NavigationService
	tabs: TabService

	@classmethod
	def from_session(cls, browser_session: BrowserSession) -> ActionService:
		return cls(
			click=ClickService(browser_session=browser_session),
			type=TypeService(browser_session=browser_session),
			scroll=ScrollService(browser_session=browser_session),
			navigation=NavigationService(browser_session=browser_session),
			tabs=TabService(browser_session=browser_session),
		)


class BrowserServiceBundle(BaseModel):
	"""Explicit service bundle for browser runtime operations."""

	model_config = ConfigDict(arbitrary_types_allowed=True)

	state: BrowserStateService
	actions: ActionService
	navigation: NavigationService
	tabs: TabService
	downloads: DownloadService
	dialogs: DialogService
	network: NetworkService
	storage: StorageStateService
	lifecycle: LifecycleService

	@classmethod
	def from_session(cls, browser_session: BrowserSession) -> BrowserServiceBundle:
		navigation = NavigationService(browser_session=browser_session)
		tabs = TabService(browser_session=browser_session)
		return cls(
			state=BrowserStateService(browser_session=browser_session),
			actions=ActionService.from_session(browser_session),
			navigation=navigation,
			tabs=tabs,
			downloads=DownloadService(browser_session=browser_session),
			dialogs=DialogService(browser_session=browser_session),
			network=NetworkService(browser_session=browser_session),
			storage=StorageStateService(browser_session=browser_session),
			lifecycle=LifecycleService(browser_session=browser_session),
		)
