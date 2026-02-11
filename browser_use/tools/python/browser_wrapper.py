"""Browser wrapper for the Python execution tool.

Provides convenient async methods for browser interaction from within
the python REPL namespace.
"""

import asyncio
import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
	from browser_use.browser import BrowserSession


class BrowserWrapper:
	"""Wrapper providing convenient browser methods for Python execution.

	Available methods:
	- get_html(selector=None) - Get raw HTML from page or specific element
	- evaluate(js_code, variables=None) - Execute JavaScript, return Python data
	- navigate(url) - Navigate to URL
	- go_back() - Go back in browser history
	- click(index=None, selector=None) - Click element
	- input(index, text, clear=True) - Type text into element
	- scroll(down=True, pages=1.0) - Scroll page
	- wait(seconds) - Wait for specified seconds
	- send_keys(keys) - Send keyboard keys
	"""

	def __init__(self, session: 'BrowserSession'):
		self._session = session

	async def get_html(self, selector: str | None = None) -> str:
		"""Get raw HTML from page or specific element.

		Args:
			selector: CSS selector for specific element (None for full page)

		Returns:
			HTML string
		"""
		await self._session.start()
		cdp = await self._session.get_or_create_cdp_session()

		if selector:
			js = f'document.querySelector({json.dumps(selector)})?.outerHTML || ""'
		else:
			js = 'document.documentElement.outerHTML'

		result = await cdp.cdp_client.send.Runtime.evaluate(
			params={'expression': js, 'returnByValue': True},
			session_id=cdp.session_id,
		)
		return result.get('result', {}).get('value', '')

	async def evaluate(self, js_code: str, variables: dict[str, Any] | None = None) -> Any:
		"""Execute JavaScript and return Python data.

		Args:
			js_code: JavaScript code (wrap in IIFE or use function with variables)
			variables: Python dict to pass as params to JS function

		Returns:
			Python object (dict, list, str, number, bool, None)
		"""
		await self._session.start()
		cdp = await self._session.get_or_create_cdp_session()

		if variables:
			wrapper = f'({js_code})({json.dumps(variables)})'
		else:
			wrapper = js_code

		result = await cdp.cdp_client.send.Runtime.evaluate(
			params={'expression': wrapper, 'returnByValue': True, 'awaitPromise': True},
			session_id=cdp.session_id,
		)

		if result.get('exceptionDetails'):
			error = result['exceptionDetails'].get('text', 'Unknown JS error')
			raise RuntimeError(f'JavaScript error: {error}')

		return result.get('result', {}).get('value')

	async def navigate(self, url: str) -> None:
		"""Navigate to URL."""
		await self._session.start()

		from browser_use.browser.events import NavigateToUrlEvent

		event = self._session.event_bus.dispatch(NavigateToUrlEvent(url=url, new_tab=False))
		await event
		await event.event_result(raise_if_any=True, raise_if_none=False)

	async def click(self, index: int | None = None, selector: str | None = None) -> None:
		"""Click element by index or CSS selector.

		Args:
			index: Element index from browser_state
			selector: CSS selector
		"""
		await self._session.start()

		if index is not None:
			node = await self._session.get_element_by_index(index)
			if node is None:
				raise RuntimeError(f'Element {index} not found. Page may have changed.')

			from browser_use.browser.events import ClickElementEvent

			event = self._session.event_bus.dispatch(ClickElementEvent(node=node))
			await event
			await event.event_result(raise_if_any=True, raise_if_none=False)
		elif selector is not None:
			cdp = await self._session.get_or_create_cdp_session()
			js = f'''
				(function() {{
					const el = document.querySelector({json.dumps(selector)});
					if (!el) return false;
					el.click();
					return true;
				}})()
			'''
			result = await cdp.cdp_client.send.Runtime.evaluate(
				params={'expression': js, 'returnByValue': True},
				session_id=cdp.session_id,
			)
			if not result.get('result', {}).get('value'):
				raise RuntimeError(f'Element not found: {selector}')
		else:
			raise ValueError('Must provide either index or selector')

	async def input(self, index: int, text: str, clear: bool = True) -> None:
		"""Type text into element by index.

		Args:
			index: Element index from browser_state
			text: Text to type
			clear: Whether to clear existing text first (default True)
		"""
		await self._session.start()

		node = await self._session.get_element_by_index(index)
		if node is None:
			raise RuntimeError(f'Element {index} not found. Page may have changed.')

		from browser_use.browser.events import TypeTextEvent

		event = self._session.event_bus.dispatch(TypeTextEvent(node=node, text=text, clear=clear))
		await event
		await event.event_result(raise_if_any=True, raise_if_none=False)

	async def scroll(self, down: bool = True, pages: float = 1.0) -> None:
		"""Scroll the page.

		Args:
			down: True to scroll down, False to scroll up
			pages: Number of viewport heights to scroll
		"""
		await self._session.start()

		from browser_use.browser.events import ScrollEvent

		try:
			cdp = await self._session.get_or_create_cdp_session()
			metrics = await cdp.cdp_client.send.Page.getLayoutMetrics(session_id=cdp.session_id)
			viewport = metrics.get('cssVisualViewport', {})
			viewport_height = int(viewport.get('clientHeight', 1000))
		except Exception:
			viewport_height = 1000

		pixels = int(pages * viewport_height)
		direction = 'down' if down else 'up'

		event = self._session.event_bus.dispatch(ScrollEvent(direction=direction, amount=pixels, node=None))
		await event
		await event.event_result(raise_if_any=True, raise_if_none=False)

	async def wait(self, seconds: float) -> None:
		"""Wait for specified seconds."""
		await asyncio.sleep(seconds)

	async def send_keys(self, keys: str) -> None:
		"""Send keyboard keys (Enter, Escape, Tab, etc.)."""
		await self._session.start()

		from browser_use.browser.events import SendKeysEvent

		event = self._session.event_bus.dispatch(SendKeysEvent(keys=keys))
		await event
		await event.event_result(raise_if_any=True, raise_if_none=False)

	async def go_back(self) -> None:
		"""Go back in browser history."""
		await self._session.start()

		from browser_use.browser.events import GoBackEvent

		event = self._session.event_bus.dispatch(GoBackEvent())
		await event
		await event.event_result(raise_if_any=True, raise_if_none=False)
