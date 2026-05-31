from __future__ import annotations

import asyncio
import json
from typing import Any, Literal

from browser_use.browser.service_base import BrowserService
from browser_use.browser.views import BrowserError
from browser_use.dom.service import EnhancedDOMTreeNode


def _xpath_literal(value: str) -> str:
	if "'" not in value:
		return f"'{value}'"
	if '"' not in value:
		return f'"{value}"'
	parts = value.split("'")
	single_quote_literal = '"\'"'
	return 'concat(' + f', {single_quote_literal}, '.join(f"'{part}'" for part in parts) + ')'


class ScrollService(BrowserService):
	"""Scrolling operations."""

	async def viewport_height(self, *, fallback: int = 1000) -> int:
		try:
			cdp_session = await self.browser_session.get_or_create_cdp_session(target_id=None, focus=True)
			metrics = await cdp_session.cdp_client.send.Page.getLayoutMetrics(session_id=cdp_session.session_id)
			css_viewport = metrics.get('cssVisualViewport', {})
			css_layout_viewport = metrics.get('cssLayoutViewport', {})
			return int(css_viewport.get('clientHeight') or css_layout_viewport.get('clientHeight', fallback))
		except Exception as exc:
			self.browser_session.logger.debug(f'Failed to get viewport height, using fallback {fallback}px: {exc}')
			return fallback

	async def scroll_pages(self, pages: float, *, direction: Literal['up', 'down'] = 'down') -> dict[str, Any]:
		return await self.scroll_pages_with_node(pages, direction=direction, node=None)

	async def scroll_pages_with_node(
		self,
		pages: float,
		*,
		direction: Literal['up', 'down'] = 'down',
		node: EnhancedDOMTreeNode | None = None,
	) -> dict[str, Any]:
		viewport_height = await self.viewport_height()
		completed_scrolls = 0.0
		total_pixels = 0

		if pages >= 1.0:
			num_full_pages = int(pages)
			remaining_fraction = pages - num_full_pages
			for _ in range(num_full_pages):
				await self.scroll_page(viewport_height, direction=direction, node=node)
				completed_scrolls += 1
				total_pixels += viewport_height
				await asyncio.sleep(0.15)
			if remaining_fraction > 0:
				pixels = int(remaining_fraction * viewport_height)
				await self.scroll_page(pixels, direction=direction, node=node)
				completed_scrolls += remaining_fraction
				total_pixels += pixels
		else:
			pixels = int(pages * viewport_height)
			await self.scroll_page(pixels, direction=direction, node=node)
			completed_scrolls = pages
			total_pixels = pixels

		return {
			'direction': direction,
			'pages': pages,
			'completed_pages': completed_scrolls,
			'viewport_height': viewport_height,
			'pixels': total_pixels,
		}

	async def scroll_page(
		self,
		amount: int,
		*,
		direction: Literal['up', 'down', 'left', 'right'] = 'down',
		node: EnhancedDOMTreeNode | None = None,
	) -> None:
		if node is not None:
			pixels = amount if direction in ('down', 'right') else -amount
			if await self._scroll_element_container(node, pixels):
				if self.browser_session._dom_watchdog:
					self.browser_session._dom_watchdog.clear_cache()
				if node.tag_name and node.tag_name.upper() == 'IFRAME':
					await asyncio.sleep(0.2)
				return

		delta_x = 0
		delta_y = 0
		if direction == 'down':
			delta_y = amount
		elif direction == 'up':
			delta_y = -amount
		elif direction == 'right':
			delta_x = amount
		elif direction == 'left':
			delta_x = -amount

		cdp_session = await self.browser_session.get_or_create_cdp_session(target_id=None, focus=True)
		await cdp_session.cdp_client.send.Runtime.evaluate(
			params={'expression': f'window.scrollBy({delta_x}, {delta_y})', 'returnByValue': True},
			session_id=cdp_session.session_id,
		)
		if self.browser_session._dom_watchdog:
			self.browser_session._dom_watchdog.clear_cache()

	async def _scroll_with_cdp_gesture(self, pixels: int) -> bool:
		"""
		Scroll using CDP Input.synthesizeScrollGesture to simulate realistic scroll gesture.

		Args:
			pixels: Number of pixels to scroll (positive = down, negative = up)

		Returns:
			True if successful, False if failed
		"""
		try:
			# Get focused CDP session using public API (validates and waits for recovery if needed)
			cdp_session = await self.browser_session.get_or_create_cdp_session()
			cdp_client = cdp_session.cdp_client
			session_id = cdp_session.session_id

			# Get viewport dimensions from cached value if available
			if self.browser_session._original_viewport_size:
				viewport_width, viewport_height = self.browser_session._original_viewport_size
			else:
				# Fallback: query layout metrics
				layout_metrics = await cdp_client.send.Page.getLayoutMetrics(session_id=session_id)
				viewport_width = layout_metrics['layoutViewport']['clientWidth']
				viewport_height = layout_metrics['layoutViewport']['clientHeight']

			# Calculate center of viewport
			center_x = viewport_width / 2
			center_y = viewport_height / 2

			# For scroll gesture, positive yDistance scrolls up, negative scrolls down
			# (opposite of mouseWheel deltaY convention)
			y_distance = -pixels

			# Synthesize scroll gesture - use very high speed for near-instant scrolling
			await cdp_client.send.Input.synthesizeScrollGesture(
				params={
					'x': center_x,
					'y': center_y,
					'xDistance': 0,
					'yDistance': y_distance,
					'speed': 50000,  # pixels per second (high = near-instant scroll)
				},
				session_id=session_id,
			)

			self.logger.debug(f'📄 Scrolled via CDP gesture: {pixels}px')
			return True

		except Exception as e:
			# Not critical - JavaScript fallback will handle scrolling
			self.logger.debug(f'CDP gesture scroll failed ({type(e).__name__}: {e}), falling back to JS')
			return False

	async def _scroll_element_container(self, element_node: EnhancedDOMTreeNode, pixels: int) -> bool:
		try:
			cdp_session = await self.browser_session.cdp_client_for_node(element_node)

			if element_node.tag_name and element_node.tag_name.upper() == 'IFRAME':
				backend_node_id = element_node.backend_node_id
				result = await cdp_session.cdp_client.send.DOM.resolveNode(
					params={'backendNodeId': backend_node_id},
					session_id=cdp_session.session_id,
				)

				if 'object' in result and 'objectId' in result['object']:
					object_id = result['object']['objectId']
					scroll_result = await cdp_session.cdp_client.send.Runtime.callFunctionOn(
						params={
							'functionDeclaration': f"""
								function() {{
									try {{
										const doc = this.contentDocument || this.contentWindow.document;
										if (doc) {{
											const scrollElement = doc.documentElement || doc.body;
											if (scrollElement) {{
												const oldScrollTop = scrollElement.scrollTop;
												scrollElement.scrollTop += {pixels};
												const newScrollTop = scrollElement.scrollTop;
												return {{
													success: true,
													oldScrollTop: oldScrollTop,
													newScrollTop: newScrollTop,
													scrolled: newScrollTop - oldScrollTop
												}};
											}}
										}}
										return {{success: false, error: 'Could not access iframe content'}};
									}} catch (e) {{
										return {{success: false, error: e.toString()}};
									}}
								}}
							""",
							'objectId': object_id,
							'returnByValue': True,
						},
						session_id=cdp_session.session_id,
					)

					result_value = scroll_result.get('result', {}).get('value')
					if isinstance(result_value, dict) and result_value.get('success'):
						self.browser_session.logger.debug(
							f'Successfully scrolled iframe content by {result_value.get("scrolled", 0)}px'
						)
						return True
					if isinstance(result_value, dict):
						self.browser_session.logger.debug(
							f'Failed to scroll iframe: {result_value.get("error", "Unknown error")}'
						)

			backend_node_id = element_node.backend_node_id
			box_model = await cdp_session.cdp_client.send.DOM.getBoxModel(
				params={'backendNodeId': backend_node_id}, session_id=cdp_session.session_id
			)
			content_quad = box_model['model']['content']

			center_x = (content_quad[0] + content_quad[2] + content_quad[4] + content_quad[6]) / 4
			center_y = (content_quad[1] + content_quad[3] + content_quad[5] + content_quad[7]) / 4

			await cdp_session.cdp_client.send.Input.dispatchMouseEvent(
				params={
					'type': 'mouseWheel',
					'x': center_x,
					'y': center_y,
					'deltaX': 0,
					'deltaY': pixels,
				},
				session_id=cdp_session.session_id,
			)

			return True
		except Exception as e:
			self.browser_session.logger.debug(f'Failed to scroll element container via CDP: {e}')
			return False

	async def scroll_to_text(self, text: str) -> None:
		cdp_session = await self.browser_session.get_or_create_cdp_session()
		cdp_client = cdp_session.cdp_client
		session_id = cdp_session.session_id

		await cdp_client.send.DOM.enable(session_id=session_id)
		await cdp_client.send.DOM.getDocument(params={'depth': -1}, session_id=session_id)

		search_queries = [
			f'//*[contains(text(), {_xpath_literal(text)})]',
			f'//*[contains(., {_xpath_literal(text)})]',
			f'//*[@*[contains(., {_xpath_literal(text)})]]',
		]

		for query in search_queries:
			search_id = None
			try:
				search_result = await cdp_client.send.DOM.performSearch(params={'query': query}, session_id=session_id)
				search_id = search_result['searchId']
				result_count = search_result['resultCount']
				if result_count <= 0:
					continue

				node_ids = await cdp_client.send.DOM.getSearchResults(
					params={'searchId': search_id, 'fromIndex': 0, 'toIndex': 1},
					session_id=session_id,
				)
				if node_ids['nodeIds']:
					await cdp_client.send.DOM.scrollIntoViewIfNeeded(
						params={'nodeId': node_ids['nodeIds'][0]}, session_id=session_id
					)
					self.browser_session.logger.debug(f'📜 Scrolled to text: "{text}"')
					return
			except Exception as e:
				self.browser_session.logger.debug(f'Search query failed: {query}, error: {e}')
			finally:
				if search_id:
					try:
						await cdp_client.send.DOM.discardSearchResults(params={'searchId': search_id}, session_id=session_id)
					except Exception:
						pass

		js_result = await cdp_client.send.Runtime.evaluate(
			params={
				'expression': f"""
					(() => {{
						const target = {json.dumps(text)};
						const walker = document.createTreeWalker(
							document.body,
							NodeFilter.SHOW_TEXT,
							null,
							false
						);
						let node;
						while ((node = walker.nextNode())) {{
							if (node.textContent.includes(target)) {{
								node.parentElement.scrollIntoView({{behavior: 'smooth', block: 'center'}});
								return true;
							}}
						}}
						return false;
					}})()
				"""
			},
			session_id=session_id,
		)

		if js_result.get('result', {}).get('value'):
			self.browser_session.logger.debug(f'📜 Scrolled to text: "{text}" (via JS)')
			return

		self.browser_session.logger.warning(f'⚠️ Text not found: "{text}"')
		raise BrowserError(f'Text not found: "{text}"', details={'text': text})
