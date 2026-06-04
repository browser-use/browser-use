"""Direct action execution for CLI daemon — no event bus dispatch.

Wraps DefaultActionWatchdog methods and DomService for direct calling.
The watchdog instance is NOT registered on the event bus — it's just
used as a library of action implementations.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from bubus import EventBus

from browser_use.browser.events import (
	GoBackEvent,
	SelectDropdownOptionEvent,
	SendKeysEvent,
	TypeTextEvent,
	UploadFileEvent,
)
from browser_use.browser.watchdogs.default_action_watchdog import DefaultActionWatchdog
from browser_use.dom.service import DomService
from browser_use.dom.views import EnhancedDOMTreeNode, SerializedDOMState

if TYPE_CHECKING:
	from browser_use.browser.session import BrowserSession
	from browser_use.browser.views import BrowserStateSummary, PageInfo

logger = logging.getLogger('browser_use.skill_cli.actions')


class ActionHandler:
	"""Execute browser actions directly without the event bus.

	Uses DefaultActionWatchdog methods for complex actions (click, type, keys, etc.)
	and DomService for DOM snapshots. All other actions use direct CDP calls.
	"""

	def __init__(self, browser_session: BrowserSession) -> None:
		self.bs = browser_session
		# Create watchdog instance — NOT registered on event bus
		self._watchdog = DefaultActionWatchdog(
			event_bus=EventBus(),  # dummy, never dispatched to
			browser_session=browser_session,
		)
		self._dom_service: DomService | None = None

	async def navigate(self, url: str) -> None:
		"""Navigate the focused tab to a URL."""
		assert self.bs.agent_focus_target_id is not None, 'No focused tab'
		await self.bs._navigate_and_wait(url, self.bs.agent_focus_target_id)

	async def click_element(self, node: EnhancedDOMTreeNode) -> dict[str, Any] | None:
		"""Click an element using the watchdog's full implementation (with fallbacks)."""
		return await self._watchdog._click_element_node_impl(node)

	async def click_coordinate(self, x: int, y: int) -> dict[str, Any] | None:
		"""Click at coordinates."""
		from browser_use.browser.events import ClickCoordinateEvent

		event = ClickCoordinateEvent(coordinate_x=x, coordinate_y=y)
		return await self._watchdog.on_ClickCoordinateEvent(event)

	async def type_text(self, node: EnhancedDOMTreeNode, text: str) -> dict[str, Any] | None:
		"""Type text into an element."""
		event = TypeTextEvent(node=node, text=text)
		return await self._watchdog.on_TypeTextEvent(event)

	async def scroll(self, direction: str, amount: int) -> None:
		"""Scroll the page using JS (CDP gesture doesn't work in --connect mode)."""
		if direction in ('down', 'up'):
			x, y = 0, (amount if direction == 'down' else -amount)
		else:
			x, y = (amount if direction == 'right' else -amount), 0
		cdp_session = await self.bs.get_or_create_cdp_session()
		assert cdp_session is not None, 'No CDP session for scroll'
		await cdp_session.cdp_client.send.Runtime.evaluate(
			params={'expression': f'window.scrollBy({x}, {y})', 'awaitPromise': False},
			session_id=cdp_session.session_id,
		)

	async def go_back(self) -> None:
		"""Go back in history."""
		event = GoBackEvent()
		await self._watchdog.on_GoBackEvent(event)

	async def send_keys(self, keys: str) -> None:
		"""Send keyboard keys."""
		event = SendKeysEvent(keys=keys)
		await self._watchdog.on_SendKeysEvent(event)

	async def select_dropdown(self, node: EnhancedDOMTreeNode, text: str) -> dict[str, str]:
		"""Select a dropdown option."""
		event = SelectDropdownOptionEvent(node=node, text=text)
		return await self._watchdog.on_SelectDropdownOptionEvent(event)

	async def upload_file(self, node: EnhancedDOMTreeNode, file_path: str) -> None:
		"""Upload a file to a file input element."""
		event = UploadFileEvent(node=node, file_path=file_path)
		await self._watchdog.on_UploadFileEvent(event)

	async def get_state(self) -> BrowserStateSummary:
		"""Build DOM via DomService directly (no DOMWatchdog, no event bus)."""
		from browser_use.browser.views import BrowserStateSummary, PageInfo

		if self._dom_service is None:
			self._dom_service = DomService(browser_session=self.bs)

		page_url = await self.bs.get_current_page_url()

		# Fast path for non-http pages
		if page_url.lower().split(':', 1)[0] not in ('http', 'https'):
			return BrowserStateSummary(
				dom_state=SerializedDOMState(_root=None, selector_map={}),
				url=page_url,
				title='Empty Tab',
				tabs=await self.bs.get_tabs(),
				screenshot=None,
				page_info=None,
			)

		# Build DOM and take screenshot in parallel
		import asyncio

		dom_task = asyncio.create_task(self._dom_service.get_serialized_dom_tree())
		screenshot_task = asyncio.create_task(self.bs.take_screenshot())

		dom_state: SerializedDOMState | None = None
		screenshot_b64: str | None = None

		try:
			dom_state, _tree, _timing = await dom_task
		except Exception as e:
			logger.warning(f'DOM build failed: {e}')
			dom_state = SerializedDOMState(_root=None, selector_map={})

		try:
			screenshot_bytes = await screenshot_task
			import base64

			screenshot_b64 = base64.b64encode(screenshot_bytes).decode() if screenshot_bytes else None
		except Exception as e:
			logger.warning(f'Screenshot failed: {e}')

		# Update cached selector map for element lookups
		if dom_state and dom_state.selector_map:
			self.bs.update_cached_selector_map(dom_state.selector_map)

		# Get page info
		page_info: PageInfo | None = None
		try:
			cdp_session = await self.bs.get_or_create_cdp_session(target_id=None, focus=False)
			if cdp_session:
				metrics = await cdp_session.cdp_client.send.Page.getLayoutMetrics(session_id=cdp_session.session_id)
				css_metrics = metrics.get('cssLayoutViewport', {})
				content_size = metrics.get('cssContentSize', metrics.get('contentSize', {}))
				visual_viewport = metrics.get('cssVisualViewport', metrics.get('visualViewport', {}))
				page_info = PageInfo(
					viewport_width=int(css_metrics.get('clientWidth', 0)),
					viewport_height=int(css_metrics.get('clientHeight', 0)),
					page_width=int(content_size.get('width', 0)),
					page_height=int(content_size.get('height', 0)),
					scroll_x=int(visual_viewport.get('pageX', 0)),
					scroll_y=int(visual_viewport.get('pageY', 0)),
					pixels_above=int(visual_viewport.get('pageY', 0)),
					pixels_below=max(
						0,
						int(content_size.get('height', 0))
						- int(css_metrics.get('clientHeight', 0))
						- int(visual_viewport.get('pageY', 0)),
					),
					pixels_left=0,
					pixels_right=0,
				)
		except Exception as e:
			logger.debug(f'Failed to get page info: {e}')

		tabs = await self.bs.get_tabs()

		# Use focused tab's title, not tabs[0]
		title = ''
		focused_id = self.bs.agent_focus_target_id
		found_focused = False
		for tab in tabs:
			if tab.target_id == focused_id:
				title = tab.title
				found_focused = True
				break
		if not found_focused and tabs:
			title = tabs[0].title

		return BrowserStateSummary(
			dom_state=dom_state,
			url=page_url,
			title=title,
			tabs=tabs,
			screenshot=screenshot_b64,
			page_info=page_info,
			closed_popup_messages=self.bs._closed_popup_messages.copy(),
		)
