"""Opt-in adapter for Anthropic's asynchronous browser toolset helpers.

Requires an Anthropic SDK providing ``anthropic.tools.browser``. The normal
Browser Use dependency pin does not include those helpers yet; this prototype
does not change that pin or the existing Agent/ChatAnthropic integration.

With a compatible SDK installed::

    import os
    from anthropic import AsyncAnthropic
    from browser_use import Browser
    from browser_use.integrations.anthropic import BrowserUseToolset


    async def run(task: str):
        browser = Browser(use_cloud=True)  # BROWSER_USE_API_KEY; or Browser() locally
        async with BrowserUseToolset(browser, owns_browser=True) as tools:
            async with AsyncAnthropic() as client:  # ANTHROPIC_API_KEY
                async for message in client.beta.messages.tool_runner(
                    model=os.environ['ANTHROPIC_MODEL'],
                    max_tokens=4096,
                    max_iterations=30,
                    tools=[tools],
                    messages=[{'role': 'user', 'content': task}],
                ):
                    print(message.content)

This initial adapter supports screenshot-driven interaction, text and tabs.
Element references, DOM search, drag/held input, zoom, files and logs are not
implemented. Unsupported members remain disabled by the SDK. Coordinate
actions reject reference targets explicitly. No Agent or extra model is run.
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal, Self
from urllib.parse import urlsplit

try:
	from anthropic.tools.browser import (
		BetaAsyncAbstractBrowserToolset20260801,
		BetaBrowserNavigateResult,
		BetaBrowserScreenshotResult,
		BrowserState,
		BrowserStateChange,
		TabMissingError,
		ToolError,
		ToolsetCallContext,
	)
	from anthropic.types import beta
except ImportError as exc:
	raise ImportError(
		'BrowserUseToolset requires an Anthropic SDK with anthropic.tools.browser helpers. '
		'The standard Browser Use dependency pin does not provide them yet; '
		'use a separate environment with a compatible SDK for this opt-in prototype.'
	) from exc

from browser_use.actor.page import Page
from browser_use.browser.events import SendKeysEvent, SwitchTabEvent
from browser_use.browser.session import BrowserSession


class BrowserUseToolset(BetaAsyncAbstractBrowserToolset20260801):
	"""Execute Anthropic browser actions using an existing BrowserSession.

	By default, the caller starts and closes the borrowed session. With
	``owns_browser=True``, the context manager starts it and ``close()`` kills
	the session (including an owned cloud browser). Never transfer ownership
	of a shared session. Calls targeting a tab make it the agent's active tab.
	Other users must not operate the same session concurrently.

	SDK options such as ``configs``, ``confirm`` and ``url_policy`` are forwarded
	unchanged. BrowserSession's domain policy still handles URL navigation.
	"""

	def __init__(self, browser: BrowserSession, *, owns_browser: bool = False, **options: Any) -> None:
		super().__init__(**options)
		self.browser = browser
		self._owns_browser = owns_browser
		self._released = False
		self._reported_tabs = {t['tab_id'] for t in self._tabs()}

	async def __aenter__(self) -> Self:
		await super().__aenter__()
		if self._owns_browser:
			try:
				await self.browser.start()
			except BaseException:
				try:
					await self.close()
				except Exception:
					self.browser.logger.warning('Could not clean up browser after startup failed.')
				raise
		elif not self.browser.is_cdp_connected:
			raise RuntimeError('Start the borrowed BrowserSession before entering BrowserUseToolset.')
		self._reported_tabs = {t['tab_id'] for t in self._tabs()}
		return self

	async def close(self) -> None:
		"""Wait for accepted calls, then release only a session we own."""
		await super().close()
		if self._owns_browser and not self._released:
			await self.browser.kill()
			self._released = True

	def _tabs(self) -> list[beta.BetaBrowserStateTabEntryParam]:
		# Cached targets keep error reporting independent of further CDP calls.
		targets = self.browser.get_page_targets() if self.browser.is_cdp_connected else []
		active = self.browser.agent_focus_target_id
		if targets and active not in {target.target_id for target in targets}:
			active = targets[0].target_id
		return [{'tab_id': t.target_id, 'url': t.url, 'title': t.title or '', 'active': t.target_id == active} for t in targets]

	async def _browser_state(self, context: ToolsetCallContext) -> BrowserState:
		"""Report tab inventory after successful and failed calls, without screenshots."""
		tabs = self._tabs()
		changes: list[BrowserStateChange] = [
			{'type': 'tab_opened', 'tab_id': t['tab_id']} for t in tabs if t['tab_id'] not in self._reported_tabs
		]
		self._reported_tabs = {t['tab_id'] for t in tabs}
		return BrowserState(tabs=tabs, state_changes=changes)

	async def _page(self, tab_id: str | None) -> Page:
		tabs = self._tabs()
		target_id = tab_id or next((t['tab_id'] for t in tabs if t.get('active')), None)
		if target_id is None or not any(t['tab_id'] == target_id for t in tabs):
			raise TabMissingError()
		session = await self.browser.get_or_create_cdp_session(target_id, focus=True)
		return Page(self.browser, target_id, session.session_id)

	@staticmethod
	def _coordinate(target: beta.BetaBrowserClickTarget) -> beta.BetaBrowserCoordinateTarget:
		if target.type != 'coordinate':
			raise ToolError('Element references are not supported by this adapter. Use screenshot viewport coordinates.')
		return target

	async def navigate(self, context: ToolsetCallContext, input: beta.BetaBrowserNavigateInput) -> BetaBrowserNavigateResult:
		"""Navigate through BrowserSession's event pipeline, or traverse history."""
		page = await self._page(input.tab_id)
		if input.url == 'back':
			await page.go_back()
		elif input.url == 'forward':
			await page.go_forward()
		elif input.url == 'reload':
			await page.reload()
		else:
			url = input.url if urlsplit(input.url).scheme else f'https://{input.url}'
			await self.browser.navigate_to(url)
		return BetaBrowserNavigateResult(url=await page.get_url(), title=await page.get_title())

	async def screenshot(
		self, context: ToolsetCallContext, input: beta.BetaBrowserScreenshotInput
	) -> BetaBrowserScreenshotResult:
		"""Return a viewport screenshot with one image pixel per CSS pixel."""
		page = await self._page(input.tab_id)
		session_id = await page.session_id
		metrics = await self.browser.cdp_client.send.Page.getLayoutMetrics(session_id=session_id)
		viewport = metrics['cssVisualViewport']
		result = await self.browser.cdp_client.send.Page.captureScreenshot(
			params={
				'format': 'png',
				'captureBeyondViewport': False,
				'clip': {
					'x': viewport['pageX'],
					'y': viewport['pageY'],
					'width': viewport['clientWidth'],
					'height': viewport['clientHeight'],
					'scale': 1,
				},
			},
			session_id=session_id,
		)
		# CDP can emit device pixels on high-DPI browsers; normalize to CSS coordinates.
		import base64
		from io import BytesIO

		from PIL import Image

		with Image.open(BytesIO(base64.b64decode(result['data']))) as image:
			size = (round(viewport['clientWidth']), round(viewport['clientHeight']))
			if image.size == size:
				return BetaBrowserScreenshotResult(data=result['data'])
			output = BytesIO()
			image.resize(size).save(output, format='PNG')
		return BetaBrowserScreenshotResult(data=base64.b64encode(output.getvalue()).decode())

	async def _click(
		self,
		tab_id: str | None,
		target: beta.BetaBrowserClickTarget,
		modifiers: str | None,
		button: Literal['left', 'middle', 'right'],
		count: int = 1,
	) -> None:
		point = self._coordinate(target)
		bits = 0
		for key in modifiers.lower().split('+') if modifiers else []:
			mapping = {'alt': 1, 'ctrl': 2, 'control': 2, 'cmd': 4, 'meta': 4, 'shift': 8}
			if key not in mapping:
				raise ToolError(f'Unsupported mouse modifier: {key}')
			bits |= mapping[key]
		page = await self._page(tab_id)
		if not bits:
			await (await page.mouse).click(point.x, point.y, button=button, click_count=count)
			return
		session_id = await page.session_id
		try:
			await self.browser.cdp_client.send.Input.dispatchMouseEvent(
				params={
					'type': 'mousePressed',
					'x': point.x,
					'y': point.y,
					'button': button,
					'clickCount': count,
					'modifiers': bits,
				},
				session_id=session_id,
			)
		finally:
			await self.browser.cdp_client.send.Input.dispatchMouseEvent(
				params={
					'type': 'mouseReleased',
					'x': point.x,
					'y': point.y,
					'button': button,
					'clickCount': count,
					'modifiers': bits,
				},
				session_id=session_id,
			)

	async def left_click(self, context: ToolsetCallContext, input: beta.BetaBrowserLeftClickInput) -> None:
		"""Click a viewport coordinate with optional modifiers."""
		await self._click(input.tab_id, input.target, input.modifiers, 'left')

	async def right_click(self, context: ToolsetCallContext, input: beta.BetaBrowserRightClickInput) -> None:
		"""Open the context menu at a viewport coordinate."""
		await self._click(input.tab_id, input.target, input.modifiers, 'right')

	async def middle_click(self, context: ToolsetCallContext, input: beta.BetaBrowserMiddleClickInput) -> None:
		"""Middle-click a viewport coordinate."""
		await self._click(input.tab_id, input.target, input.modifiers, 'middle')

	async def double_click(self, context: ToolsetCallContext, input: beta.BetaBrowserDoubleClickInput) -> None:
		"""Double-click a viewport coordinate."""
		await self._click(input.tab_id, input.target, input.modifiers, 'left', 2)

	async def triple_click(self, context: ToolsetCallContext, input: beta.BetaBrowserTripleClickInput) -> None:
		"""Triple-click a viewport coordinate."""
		await self._click(input.tab_id, input.target, input.modifiers, 'left', 3)

	async def hover(self, context: ToolsetCallContext, input: beta.BetaBrowserHoverInput) -> None:
		"""Move the pointer to a viewport coordinate."""
		point = self._coordinate(input.target)
		await (await (await self._page(input.tab_id)).mouse).move(point.x, point.y)

	async def mouse_move(self, context: ToolsetCallContext, input: beta.BetaBrowserMouseMoveInput) -> None:
		"""Move without pressing a mouse button."""
		await (await (await self._page(input.tab_id)).mouse).move(input.target.x, input.target.y)

	async def scroll(self, context: ToolsetCallContext, input: beta.BetaBrowserScrollInput) -> None:
		"""Scroll at the given coordinate; one wheel notch maps to 100 CSS pixels."""
		amount = (input.scroll_amount if input.scroll_amount is not None else 3) * 100
		dx = amount if input.scroll_direction == 'right' else -amount if input.scroll_direction == 'left' else 0
		dy = amount if input.scroll_direction == 'down' else -amount if input.scroll_direction == 'up' else 0
		await (await (await self._page(input.tab_id)).mouse).scroll(input.target.x, input.target.y, dx, dy)

	async def type(self, context: ToolsetCallContext, input: beta.BetaBrowserTypeInput) -> None:
		"""Insert text into the currently focused field."""
		page = await self._page(input.tab_id)
		await self.browser.cdp_client.send.Input.insertText(params={'text': input.text}, session_id=await page.session_id)

	async def key(self, context: ToolsetCallContext, input: beta.BetaBrowserKeyInput) -> None:
		"""Press a chord or sequence using BrowserSession's existing keyboard action."""
		await self._page(input.tab_id)
		for _ in range(input.repeat if input.repeat is not None else 1):
			for chord in input.text.split():
				event = self.browser.event_bus.dispatch(SendKeysEvent(keys=chord))
				await event
				await event.event_result(raise_if_any=True, raise_if_none=False)

	async def get_page_text(self, context: ToolsetCallContext, input: beta.BetaBrowserGetPageTextInput) -> str:
		"""Read visible article/main text, falling back to the document body."""
		page = await self._page(input.tab_id)
		return await page.evaluate("() => (document.querySelector('article, main') || document.body)?.innerText || ''")

	async def wait(self, context: ToolsetCallContext, input: beta.BetaBrowserWaitInput) -> None:
		"""Wait for the SDK-validated duration (at most 30 seconds)."""
		await self._page(input.tab_id)
		await asyncio.sleep(input.duration)

	async def new_tab(
		self, context: ToolsetCallContext, input: beta.BetaBrowserNewTabInput
	) -> beta.BetaBrowserStateTabEntryParam:
		"""Open and focus an empty tab."""
		if len(self._tabs()) >= 100:
			raise ToolError('The browser toolset supports at most 100 tabs.')
		page = await self.browser.new_page()
		info = await page.get_target_info()
		# Unlike _page(), this waits for the new target's session registration.
		await self.browser.get_or_create_cdp_session(info['targetId'], focus=True)
		return next(t for t in self._tabs() if t['tab_id'] == info['targetId'])

	async def list_tabs(
		self, context: ToolsetCallContext, input: beta.BetaBrowserListTabsInput
	) -> list[beta.BetaBrowserStateTabEntryParam]:
		"""List open page targets using full, stable CDP target IDs."""
		return self._tabs()

	async def switch_tab(
		self, context: ToolsetCallContext, input: beta.BetaBrowserSwitchTabInput
	) -> beta.BetaBrowserStateTabEntryParam:
		"""Activate a tab and update BrowserSession's agent focus."""
		await self._page(input.tab_id)
		event = self.browser.event_bus.dispatch(SwitchTabEvent(target_id=input.tab_id))
		await event
		await event.event_result(raise_if_any=True)
		return next(t for t in self._tabs() if t['tab_id'] == input.tab_id)

	async def close_tab(self, context: ToolsetCallContext, input: beta.BetaBrowserCloseTabInput) -> None:
		"""Close the requested tab and let BrowserSession choose the next focus."""
		page = await self._page(input.tab_id)
		await self.browser.close_page(page)
		for _ in range(100):
			if not any(t['tab_id'] == input.tab_id for t in self._tabs()):
				return
			await asyncio.sleep(0.02)
		raise ToolError('Close was sent, but tab state has not caught up. Use list_tabs before attempting another close.')
