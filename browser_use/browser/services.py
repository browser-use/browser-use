from __future__ import annotations

import asyncio
import json
import mimetypes
import os
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from cdp_use.cdp.input.commands import DispatchKeyEventParameters
from cdp_use.cdp.target import TargetID
from pydantic import BaseModel, ConfigDict

from browser_use.actor.utils import get_key_info
from browser_use.browser.events import (
	FileDownloadedEvent,
)
from browser_use.browser.session import BrowserSession
from browser_use.browser.views import BrowserError, BrowserStateSummary, TabInfo
from browser_use.dom.service import EnhancedDOMTreeNode


class BrowserService(BaseModel):
	"""Base class for explicit browser services."""

	model_config = ConfigDict(arbitrary_types_allowed=True)

	browser_session: BrowserSession

	@property
	def logger(self) -> Any:
		return self.browser_session.logger

	def _default_action_watchdog(self) -> Any:
		default_action_watchdog = getattr(self.browser_session, '_default_action_watchdog', None)
		if default_action_watchdog is None:
			raise BrowserError(
				'Default action handler is not attached to this browser session. '
				'Start the BrowserSession before using click, type, or dropdown services.'
			)
		return default_action_watchdog


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

	async def navigate(self, url: str, *, new_tab: bool = False, verify_not_empty: bool = True) -> None:
		self._ensure_url_allowed(url)
		target_id = await self._target_for_navigation(new_tab=new_tab)
		await self.browser_session._navigate_and_wait(url, target_id)
		await self.browser_session._close_extension_options_pages()
		if verify_not_empty and not new_tab:
			await self._ensure_page_not_empty(url)

	async def go_back(self) -> str | None:
		cdp_session = await self.browser_session.get_or_create_cdp_session(target_id=None, focus=True)
		history = await cdp_session.cdp_client.send.Page.getNavigationHistory(session_id=cdp_session.session_id)
		current_index = history['currentIndex']
		entries = history['entries']
		if current_index <= 0:
			return None

		previous_entry = entries[current_index - 1]
		await cdp_session.cdp_client.send.Page.navigateToHistoryEntry(
			params={'entryId': previous_entry['id']},
			session_id=cdp_session.session_id,
		)
		await asyncio.sleep(0.5)
		return str(previous_entry.get('url', ''))

	async def go_forward(self) -> str | None:
		cdp_session = await self.browser_session.get_or_create_cdp_session(target_id=None, focus=True)
		history = await cdp_session.cdp_client.send.Page.getNavigationHistory(session_id=cdp_session.session_id)
		current_index = history['currentIndex']
		entries = history['entries']
		if current_index >= len(entries) - 1:
			return None

		next_entry = entries[current_index + 1]
		await cdp_session.cdp_client.send.Page.navigateToHistoryEntry(
			params={'entryId': next_entry['id']},
			session_id=cdp_session.session_id,
		)
		await asyncio.sleep(0.5)
		return str(next_entry.get('url', ''))

	async def refresh(self) -> None:
		cdp_session = await self.browser_session.get_or_create_cdp_session(target_id=None, focus=True)
		await cdp_session.cdp_client.send.Page.reload(session_id=cdp_session.session_id)
		await asyncio.sleep(1.0)

	async def current_url(self) -> str:
		return await self.browser_session.get_current_page_url()

	async def current_title(self) -> str:
		return await self.browser_session.get_current_page_title()

	async def _target_for_navigation(self, *, new_tab: bool) -> TargetID:
		if self.browser_session.agent_focus_target_id is None:
			cdp_session = await self.browser_session.get_or_create_cdp_session(target_id=None, focus=True)
			return cdp_session.target_id

		if not new_tab:
			return self.browser_session.agent_focus_target_id

		target_id = await self.browser_session._cdp_create_new_page('about:blank')
		await self.browser_session.get_or_create_cdp_session(target_id=target_id, focus=True)
		return target_id

	def _ensure_url_allowed(self, url: str) -> None:
		security_watchdog = getattr(self.browser_session, '_security_watchdog', None)
		if security_watchdog is not None and not security_watchdog._is_url_allowed(url):
			raise ValueError(f'Navigation to {url} blocked by security policy')

	async def _ensure_page_not_empty(self, url: str) -> None:
		state = await self.browser_session.get_browser_state_summary(include_screenshot=False)
		url_is_http = state.url.lower().startswith(('http://', 'https://'))
		if not url_is_http or not _page_appears_empty(state):
			return

		self.browser_session.logger.warning(f'⚠️ Empty DOM detected after navigation to {url}, waiting 3s and rechecking...')
		await asyncio.sleep(3.0)
		state = await self.browser_session.get_browser_state_summary(include_screenshot=False)
		if not state.url.lower().startswith(('http://', 'https://')) or not _page_appears_empty(state):
			return

		self.browser_session.logger.warning(f'⚠️ Still empty after 3s, attempting page reload for {url}...')
		target_id = self.browser_session.agent_focus_target_id
		if target_id is None:
			cdp_session = await self.browser_session.get_or_create_cdp_session(target_id=None, focus=True)
			target_id = cdp_session.target_id
		await self.browser_session._navigate_and_wait(url, target_id)
		await asyncio.sleep(5.0)
		state = await self.browser_session.get_browser_state_summary(include_screenshot=False)
		if state.url.lower().startswith(('http://', 'https://')) and state.dom_state._root is None:
			raise RuntimeError(
				f'Page loaded but returned empty content for {url}. '
				f'The page may require JavaScript that failed to render, use anti-bot measures, '
				f'or have a connection issue (e.g. tunnel/proxy error). Try a different URL or approach.'
			)


class TabService(BrowserService):
	"""Tab listing and focus operations."""

	async def list_tabs(self) -> list[TabInfo]:
		return await self.browser_session.get_tabs()

	async def switch(self, target_id: TargetID | None = None) -> TargetID:
		if target_id is None:
			if self.browser_session.agent_focus_target_id is None:
				cdp_session = await self.browser_session.get_or_create_cdp_session(target_id=None, focus=True)
				return cdp_session.target_id
			return self.browser_session.agent_focus_target_id

		await self.browser_session.cdp_client.send.Target.activateTarget(params={'targetId': target_id})
		await self.browser_session.get_or_create_cdp_session(target_id=target_id, focus=True)
		return target_id

	async def close(self, target_id: TargetID) -> None:
		await self.browser_session._cdp_close_page(target_id)


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
		return await self.click_node(node, button=button)

	async def click_node(
		self,
		node: EnhancedDOMTreeNode,
		*,
		button: Literal['left', 'right', 'middle'] = 'left',
	) -> dict[str, Any] | None:
		"""Click an element while preserving current safety, print, and download heuristics."""
		_ = button  # Element clicking currently preserves the historical left-click behavior.
		action_handler = self._default_action_watchdog()
		if not self.browser_session.agent_focus_target_id:
			error_msg = 'Cannot execute click: browser session is corrupted (target_id=None). Session may have crashed.'
			self.browser_session.logger.error(error_msg)
			raise BrowserError(error_msg)

		index_for_logging = node.backend_node_id or 'unknown'
		if self.browser_session.is_file_input(node):
			msg = (
				f'Index {index_for_logging} - has an element which opens file upload dialog. '
				'To upload files please use a specific function to upload files'
			)
			self.browser_session.logger.info(msg)
			return {'validation_error': msg}

		if action_handler._is_print_related_element(node):
			self.browser_session.logger.info(
				f'🖨️ Detected print button (index {index_for_logging}), generating PDF directly instead of opening dialog...'
			)
			click_metadata = await action_handler._handle_print_button_click(node)
			if click_metadata and click_metadata.get('pdf_generated'):
				self.browser_session.logger.info(f'💾 Generated PDF: {click_metadata.get("path")}')
				return click_metadata
			self.browser_session.logger.warning('⚠️ PDF generation failed, falling back to regular click')

		click_metadata = await action_handler._execute_click_with_download_detection(
			action_handler._click_element_node_impl(node)
		)
		if isinstance(click_metadata, dict) and 'validation_error' in click_metadata:
			self.browser_session.logger.info(f'{click_metadata["validation_error"]}')
			return click_metadata

		if 'download' not in (click_metadata or {}):
			msg = f'Clicked button {node.node_name}: {node.get_all_children_text(max_depth=2)}'
			self.browser_session.logger.debug(f'🖱️ {msg}')
		self.browser_session.logger.debug(f'Element xpath: {node.xpath}')
		return click_metadata

	async def click_coordinates(
		self,
		coordinate_x: int,
		coordinate_y: int,
		*,
		button: Literal['left', 'right', 'middle'] = 'left',
		force: bool = False,
	) -> dict[str, Any] | None:
		action_handler = self._default_action_watchdog()
		if not self.browser_session.agent_focus_target_id:
			error_msg = 'Cannot execute click: browser session is corrupted (target_id=None). Session may have crashed.'
			self.browser_session.logger.error(error_msg)
			raise BrowserError(error_msg)

		if force:
			self.browser_session.logger.debug(f'Force clicking at coordinates ({coordinate_x}, {coordinate_y})')
			return await action_handler._execute_click_with_download_detection(
				action_handler._click_on_coordinate(coordinate_x, coordinate_y, force=True, button=button)
			)

		node = await self.browser_session.get_dom_element_at_coordinates(coordinate_x, coordinate_y)
		if node is None:
			self.browser_session.logger.debug(
				f'No element found at coordinates ({coordinate_x}, {coordinate_y}), proceeding with click anyway'
			)
			return await action_handler._execute_click_with_download_detection(
				action_handler._click_on_coordinate(coordinate_x, coordinate_y, force=False, button=button)
			)

		if self.browser_session.is_file_input(node):
			msg = (
				f'Cannot click at ({coordinate_x}, {coordinate_y}) - element is a file input. '
				'To upload files please use upload_file action'
			)
			self.browser_session.logger.info(msg)
			return {'validation_error': msg}

		tag_name = node.tag_name.lower() if node.tag_name else ''
		if tag_name == 'select':
			msg = (
				f'Cannot click at ({coordinate_x}, {coordinate_y}) - element is a <select>. Use dropdown_options action instead.'
			)
			self.browser_session.logger.info(msg)
			return {'validation_error': msg}

		if action_handler._is_print_related_element(node):
			self.browser_session.logger.info(
				f'🖨️ Detected print button at ({coordinate_x}, {coordinate_y}), generating PDF directly instead of opening dialog...'
			)
			click_metadata = await action_handler._handle_print_button_click(node)
			if click_metadata and click_metadata.get('pdf_generated'):
				self.browser_session.logger.info(f'💾 Generated PDF: {click_metadata.get("path")}')
				return click_metadata
			self.browser_session.logger.warning('⚠️ PDF generation failed, falling back to regular click')

		return await action_handler._execute_click_with_download_detection(
			action_handler._click_on_coordinate(coordinate_x, coordinate_y, force=False, button=button)
		)


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
		return await self.type_node(
			node,
			text,
			clear=clear,
			is_sensitive=is_sensitive,
			sensitive_key_name=sensitive_key_name,
		)

	async def type_node(
		self,
		node: EnhancedDOMTreeNode,
		text: str,
		*,
		clear: bool = True,
		is_sensitive: bool = False,
		sensitive_key_name: str | None = None,
	) -> dict[str, Any] | None:
		"""Type text into an element, falling back to the focused page when needed."""
		action_handler = self._default_action_watchdog()
		index_for_logging = node.backend_node_id or 'unknown'

		if not node.backend_node_id or node.backend_node_id == 0:
			await action_handler._type_to_page(text)
			if is_sensitive:
				if sensitive_key_name:
					self.browser_session.logger.info(f'⌨️ Typed <{sensitive_key_name}> to the page (current focus)')
				else:
					self.browser_session.logger.info('⌨️ Typed <sensitive> to the page (current focus)')
			else:
				self.browser_session.logger.info(f'⌨️ Typed "{text}" to the page (current focus)')
			return None

		try:
			input_metadata = await action_handler._input_text_element_node_impl(
				node,
				text,
				clear=clear or (not text),
				is_sensitive=is_sensitive,
			)
			if is_sensitive:
				if sensitive_key_name:
					self.browser_session.logger.info(
						f'⌨️ Typed <{sensitive_key_name}> into element with index {index_for_logging}'
					)
				else:
					self.browser_session.logger.info(f'⌨️ Typed <sensitive> into element with index {index_for_logging}')
			else:
				self.browser_session.logger.info(f'⌨️ Typed "{text}" into element with index {index_for_logging}')
			self.browser_session.logger.debug(f'Element xpath: {node.xpath}')
			return input_metadata
		except Exception as exc:
			self.browser_session.logger.warning(
				f'Failed to type to element {index_for_logging}: {exc}. Falling back to page typing.'
			)
			try:
				await asyncio.wait_for(action_handler._click_element_node_impl(node), timeout=10.0)
			except Exception:
				pass
			await action_handler._type_to_page(text)
			if is_sensitive:
				if sensitive_key_name:
					self.browser_session.logger.info(f'⌨️ Typed <{sensitive_key_name}> to the page as fallback')
				else:
					self.browser_session.logger.info('⌨️ Typed <sensitive> to the page as fallback')
			else:
				self.browser_session.logger.info(f'⌨️ Typed "{text}" to the page as fallback')
			return None


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


class KeyboardService(BrowserService):
	"""Keyboard input operations."""

	async def send_keys(self, keys: str) -> None:
		cdp_session = await self.browser_session.get_or_create_cdp_session(focus=True)
		normalized_keys = self._normalize_keys(keys)

		if '+' in normalized_keys:
			parts = normalized_keys.split('+')
			modifiers = parts[:-1]
			main_key = parts[-1]

			modifier_value = 0
			modifier_map = {'Alt': 1, 'Control': 2, 'Meta': 4, 'Shift': 8}
			for mod in modifiers:
				modifier_value |= modifier_map.get(mod, 0)

			for mod in modifiers:
				await self._dispatch_key_event(cdp_session, 'keyDown', mod)

			await self._dispatch_key_event(cdp_session, 'keyDown', main_key, modifier_value)
			await self._dispatch_key_event(cdp_session, 'keyUp', main_key, modifier_value)

			for mod in reversed(modifiers):
				await self._dispatch_key_event(cdp_session, 'keyUp', mod)
		elif normalized_keys in self._special_keys():
			await self._dispatch_key_event(cdp_session, 'keyDown', normalized_keys)
			if normalized_keys == 'Enter':
				await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
					params={'type': 'char', 'text': '\r', 'key': 'Enter'},
					session_id=cdp_session.session_id,
				)
			await self._dispatch_key_event(cdp_session, 'keyUp', normalized_keys)
		else:
			for char in normalized_keys:
				if char in ('\n', '\r'):
					await self._dispatch_enter_text(cdp_session)
					continue

				modifiers, vk_code, base_key = self._get_char_modifiers_and_vk(char)
				key_code = self._get_key_code_for_char(base_key)

				await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
					params={
						'type': 'keyDown',
						'key': base_key,
						'code': key_code,
						'modifiers': modifiers,
						'windowsVirtualKeyCode': vk_code,
					},
					session_id=cdp_session.session_id,
				)
				await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
					params={'type': 'char', 'text': char, 'key': char},
					session_id=cdp_session.session_id,
				)
				await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
					params={
						'type': 'keyUp',
						'key': base_key,
						'code': key_code,
						'modifiers': modifiers,
						'windowsVirtualKeyCode': vk_code,
					},
					session_id=cdp_session.session_id,
				)
				await asyncio.sleep(0.010)

		self.browser_session.logger.info(f'⌨️ Sent keys: {keys}')
		if 'enter' in keys.lower() or 'return' in keys.lower():
			await asyncio.sleep(0.1)

	def _normalize_keys(self, keys: str) -> str:
		key_aliases = {
			'ctrl': 'Control',
			'control': 'Control',
			'alt': 'Alt',
			'option': 'Alt',
			'meta': 'Meta',
			'cmd': 'Meta',
			'command': 'Meta',
			'shift': 'Shift',
			'enter': 'Enter',
			'return': 'Enter',
			'tab': 'Tab',
			'delete': 'Delete',
			'backspace': 'Backspace',
			'escape': 'Escape',
			'esc': 'Escape',
			'space': ' ',
			'up': 'ArrowUp',
			'down': 'ArrowDown',
			'left': 'ArrowLeft',
			'right': 'ArrowRight',
			'pageup': 'PageUp',
			'pagedown': 'PageDown',
			'home': 'Home',
			'end': 'End',
		}
		if '+' in keys:
			return '+'.join(key_aliases.get(part.strip().lower(), part) for part in keys.split('+'))
		return key_aliases.get(keys.strip().lower(), keys)

	def _special_keys(self) -> set[str]:
		return {
			'Enter',
			'Tab',
			'Delete',
			'Backspace',
			'Escape',
			'ArrowUp',
			'ArrowDown',
			'ArrowLeft',
			'ArrowRight',
			'PageUp',
			'PageDown',
			'Home',
			'End',
			'Control',
			'Alt',
			'Meta',
			'Shift',
			'F1',
			'F2',
			'F3',
			'F4',
			'F5',
			'F6',
			'F7',
			'F8',
			'F9',
			'F10',
			'F11',
			'F12',
		}

	async def _dispatch_key_event(self, cdp_session, event_type: str, key: str, modifiers: int = 0) -> None:
		code, vk_code = get_key_info(key)
		params: DispatchKeyEventParameters = {
			'type': event_type,
			'key': key,
			'code': code,
		}
		if modifiers:
			params['modifiers'] = modifiers
		if vk_code is not None:
			params['windowsVirtualKeyCode'] = vk_code
		await cdp_session.cdp_client.send.Input.dispatchKeyEvent(params=params, session_id=cdp_session.session_id)

	async def _dispatch_enter_text(self, cdp_session) -> None:
		for params in (
			{'type': 'rawKeyDown', 'windowsVirtualKeyCode': 13, 'unmodifiedText': '\r', 'text': '\r'},
			{'type': 'char', 'windowsVirtualKeyCode': 13, 'unmodifiedText': '\r', 'text': '\r'},
			{'type': 'keyUp', 'windowsVirtualKeyCode': 13, 'unmodifiedText': '\r', 'text': '\r'},
		):
			await cdp_session.cdp_client.send.Input.dispatchKeyEvent(params=params, session_id=cdp_session.session_id)

	def _get_char_modifiers_and_vk(self, char: str) -> tuple[int, int, str]:
		shift_chars = {
			'!': ('1', 49),
			'@': ('2', 50),
			'#': ('3', 51),
			'$': ('4', 52),
			'%': ('5', 53),
			'^': ('6', 54),
			'&': ('7', 55),
			'*': ('8', 56),
			'(': ('9', 57),
			')': ('0', 48),
			'_': ('-', 189),
			'+': ('=', 187),
			'{': ('[', 219),
			'}': (']', 221),
			'|': ('\\', 220),
			':': (';', 186),
			'"': ("'", 222),
			'<': (',', 188),
			'>': ('.', 190),
			'?': ('/', 191),
			'~': ('`', 192),
		}
		if char in shift_chars:
			base_key, vk_code = shift_chars[char]
			return (8, vk_code, base_key)

		def _vk_from(c: str) -> int:
			up = c.upper()
			return ord(up) if len(up) == 1 else ord(c)

		if char.isupper():
			return (8, ord(char), char.lower()[:1] or char)
		if char.islower():
			return (0, _vk_from(char), char)
		if char.isdigit():
			return (0, ord(char), char)

		no_shift_chars = {
			' ': 32,
			'-': 189,
			'=': 187,
			'[': 219,
			']': 221,
			'\\': 220,
			';': 186,
			"'": 222,
			',': 188,
			'.': 190,
			'/': 191,
			'`': 192,
		}
		if char in no_shift_chars:
			return (0, no_shift_chars[char], char)
		return (0, _vk_from(char) if char.isalpha() else ord(char), char)

	def _get_key_code_for_char(self, char: str) -> str:
		key_codes = {
			' ': 'Space',
			'.': 'Period',
			',': 'Comma',
			'-': 'Minus',
			'_': 'Minus',
			'@': 'Digit2',
			'!': 'Digit1',
			'?': 'Slash',
			':': 'Semicolon',
			';': 'Semicolon',
			'(': 'Digit9',
			')': 'Digit0',
			'[': 'BracketLeft',
			']': 'BracketRight',
			'{': 'BracketLeft',
			'}': 'BracketRight',
			'/': 'Slash',
			'\\': 'Backslash',
			'=': 'Equal',
			'+': 'Equal',
			'*': 'Digit8',
			'&': 'Digit7',
			'%': 'Digit5',
			'$': 'Digit4',
			'#': 'Digit3',
			'^': 'Digit6',
			'~': 'Backquote',
			'`': 'Backquote',
			"'": 'Quote',
			'"': 'Quote',
		}
		if char.isdigit():
			return f'Digit{char}'
		if char.isalpha():
			return f'Key{char.upper()}'
		if char in key_codes:
			return key_codes[char]
		return f'Key{char.upper()}'


class UploadService(BrowserService):
	"""File upload operations."""

	async def upload_file(self, node: EnhancedDOMTreeNode, file_path: str) -> None:
		index_for_logging = node.backend_node_id or 'unknown'
		if not self.browser_session.is_file_input(node):
			msg = f'Upload failed - element {index_for_logging} is not a file input.'
			raise BrowserError(message=msg, long_term_memory=msg)

		if os.path.exists(file_path):
			file_size = os.path.getsize(file_path)
			if file_size == 0:
				msg = f'Upload failed - file {file_path} is empty (0 bytes).'
				raise BrowserError(message=msg, long_term_memory=msg)
			self.browser_session.logger.debug(f'📎 File {file_path} validated ({file_size} bytes)')

		cdp_session = await self.browser_session.cdp_client_for_node(node)
		await cdp_session.cdp_client.send.DOM.setFileInputFiles(
			params={
				'files': [file_path],
				'backendNodeId': node.backend_node_id,
			},
			session_id=cdp_session.session_id,
		)

		self.browser_session.logger.info(f'📎 Uploaded file {file_path} to element {index_for_logging}')


class DropdownService(BrowserService):
	"""Dropdown option inspection and selection."""

	async def get_options(self, node: EnhancedDOMTreeNode) -> dict[str, str]:
		return await self.get_dropdown_options(node)

	async def select_option(self, node: EnhancedDOMTreeNode, text: str) -> dict[str, str]:
		return await self.select_dropdown_option(node, text)

	async def get_dropdown_options(self, element_node: EnhancedDOMTreeNode) -> dict[str, str]:
		"""Get dropdown options from native, ARIA, and custom dropdown elements."""
		try:
			index_for_logging = element_node.backend_node_id or 'unknown'

			# Get CDP session for this node
			cdp_session = await self.browser_session.cdp_client_for_node(element_node)

			# Convert node to object ID for CDP operations
			try:
				object_result = await cdp_session.cdp_client.send.DOM.resolveNode(
					params={'backendNodeId': element_node.backend_node_id}, session_id=cdp_session.session_id
				)
				remote_object = object_result.get('object', {})
				object_id = remote_object.get('objectId')
				if not object_id:
					raise ValueError('Could not get object ID from resolved node')
			except Exception as e:
				raise ValueError(f'Failed to resolve node to object: {e}') from e

			# Check if this is an ARIA combobox that needs expansion
			# ARIA comboboxes have options in a separate element referenced by aria-controls
			check_combobox_script = """
			function() {
				const element = this;
				const role = element.getAttribute('role');
				const ariaControls = element.getAttribute('aria-controls');
				const ariaExpanded = element.getAttribute('aria-expanded');

				if (role === 'combobox' && ariaControls) {
					return {
						isCombobox: true,
						ariaControls: ariaControls,
						isExpanded: ariaExpanded === 'true',
						tagName: element.tagName.toLowerCase()
					};
				}
				return { isCombobox: false };
			}
			"""

			combobox_check = await cdp_session.cdp_client.send.Runtime.callFunctionOn(
				params={
					'functionDeclaration': check_combobox_script,
					'objectId': object_id,
					'returnByValue': True,
				},
				session_id=cdp_session.session_id,
			)
			combobox_info = combobox_check.get('result', {}).get('value', {})

			# If it's an ARIA combobox with aria-controls, handle it specially
			if combobox_info.get('isCombobox'):
				return await self._handle_aria_combobox_options(cdp_session, object_id, combobox_info, index_for_logging)

			# Use JavaScript to extract dropdown options (existing logic for non-combobox elements)
			options_script = """
			function() {
				const startElement = this;

				// Function to check if an element is a dropdown and extract options
				function checkDropdownElement(element) {
					// Check if it's a native select element
					if (element.tagName.toLowerCase() === 'select') {
						return {
							type: 'select',
							options: Array.from(element.options).map((opt, idx) => ({
								text: opt.text.trim(),
								value: opt.value,
								index: idx,
								selected: opt.selected
							})),
							id: element.id || '',
							name: element.name || '',
							source: 'target'
						};
					}

					// Check if it's an ARIA dropdown/menu (not combobox - handled separately)
					const role = element.getAttribute('role');
					if (role === 'menu' || role === 'listbox') {
						// Find all menu items/options
						const menuItems = element.querySelectorAll('[role="menuitem"], [role="option"]');
						const options = [];

						menuItems.forEach((item, idx) => {
							const text = item.textContent ? item.textContent.trim() : '';
							if (text) {
								options.push({
									text: text,
									value: item.getAttribute('data-value') || text,
									index: idx,
									selected: item.getAttribute('aria-selected') === 'true' || item.classList.contains('selected')
								});
							}
						});

						return {
							type: 'aria',
							options: options,
							id: element.id || '',
							name: element.getAttribute('aria-label') || '',
							source: 'target'
						};
					}

					// Check if it's a Semantic UI dropdown or similar
					if (element.classList.contains('dropdown') || element.classList.contains('ui')) {
						const menuItems = element.querySelectorAll('.item, .option, [data-value]');
						const options = [];

						menuItems.forEach((item, idx) => {
							const text = item.textContent ? item.textContent.trim() : '';
							if (text) {
								options.push({
									text: text,
									value: item.getAttribute('data-value') || text,
									index: idx,
									selected: item.classList.contains('selected') || item.classList.contains('active')
								});
							}
						});

						if (options.length > 0) {
							return {
								type: 'custom',
								options: options,
								id: element.id || '',
								name: element.getAttribute('aria-label') || '',
								source: 'target'
							};
						}
					}

					return null;
				}

				// Function to recursively search children up to specified depth
				function searchChildrenForDropdowns(element, maxDepth, currentDepth = 0) {
					if (currentDepth >= maxDepth) return null;

					// Check all direct children
					for (let child of element.children) {
						// Check if this child is a dropdown
						const result = checkDropdownElement(child);
						if (result) {
							result.source = `child-depth-${currentDepth + 1}`;
							return result;
						}

						// Recursively check this child's children
						const childResult = searchChildrenForDropdowns(child, maxDepth, currentDepth + 1);
						if (childResult) {
							return childResult;
						}
					}

					return null;
				}

				// First check the target element itself
				let dropdownResult = checkDropdownElement(startElement);
				if (dropdownResult) {
					return dropdownResult;
				}

				// If target element is not a dropdown, search children up to depth 4
				dropdownResult = searchChildrenForDropdowns(startElement, 4);
				if (dropdownResult) {
					return dropdownResult;
				}

				return {
					error: `Element and its children (depth 4) are not recognizable dropdown types (tag: ${startElement.tagName}, role: ${startElement.getAttribute('role')}, classes: ${startElement.className})`
				};
			}
			"""

			result = await cdp_session.cdp_client.send.Runtime.callFunctionOn(
				params={
					'functionDeclaration': options_script,
					'objectId': object_id,
					'returnByValue': True,
				},
				session_id=cdp_session.session_id,
			)

			dropdown_data = result.get('result', {}).get('value', {})

			if dropdown_data.get('error'):
				raise BrowserError(message=dropdown_data['error'], long_term_memory=dropdown_data['error'])

			if not dropdown_data.get('options'):
				msg = f'No options found in dropdown at index {index_for_logging}'
				return {
					'error': msg,
					'short_term_memory': msg,
					'long_term_memory': msg,
					'backend_node_id': str(index_for_logging),
				}

			# Format options for display
			formatted_options = []
			for opt in dropdown_data['options']:
				# Use JSON encoding to ensure exact string matching
				encoded_text = json.dumps(opt['text'])
				status = ' (selected)' if opt.get('selected') else ''
				formatted_options.append(f'{opt["index"]}: text={encoded_text}, value={json.dumps(opt["value"])}{status}')

			dropdown_type = dropdown_data.get('type', 'select')
			element_info = f'Index: {index_for_logging}, Type: {dropdown_type}, ID: {dropdown_data.get("id", "none")}, Name: {dropdown_data.get("name", "none")}'
			source_info = dropdown_data.get('source', 'unknown')

			if source_info == 'target':
				msg = f'Found {dropdown_type} dropdown ({element_info}):\n' + '\n'.join(formatted_options)
			else:
				msg = f'Found {dropdown_type} dropdown in {source_info} ({element_info}):\n' + '\n'.join(formatted_options)
			msg += (
				f'\n\nUse the exact text or value string (without quotes) in select_dropdown(index={index_for_logging}, text=...)'
			)

			if source_info == 'target':
				self.logger.info(f'📋 Found {len(dropdown_data["options"])} dropdown options for index {index_for_logging}')
			else:
				self.logger.info(
					f'📋 Found {len(dropdown_data["options"])} dropdown options for index {index_for_logging} in {source_info}'
				)

			# Create structured memory for the response
			short_term_memory = msg
			long_term_memory = f'Got dropdown options for index {index_for_logging}'

			# Return the dropdown data as a dict with structured memory
			return {
				'type': dropdown_type,
				'options': json.dumps(dropdown_data['options']),  # Convert list to JSON string for dict[str, str] type
				'element_info': element_info,
				'source': source_info,
				'formatted_options': '\n'.join(formatted_options),
				'message': msg,
				'short_term_memory': short_term_memory,
				'long_term_memory': long_term_memory,
				'backend_node_id': str(index_for_logging),
			}

		except BrowserError:
			# Re-raise BrowserError as-is to preserve structured memory
			raise
		except TimeoutError:
			msg = f'Failed to get dropdown options for index {index_for_logging} due to timeout.'
			self.logger.error(msg)
			raise BrowserError(message=msg, long_term_memory=msg)
		except Exception as e:
			msg = 'Failed to get dropdown options'
			error_msg = f'{msg}: {str(e)}'
			self.logger.error(error_msg)
			raise BrowserError(
				message=error_msg, long_term_memory=f'Failed to get dropdown options for index {index_for_logging}.'
			)

	async def _handle_aria_combobox_options(
		self,
		cdp_session,
		object_id: str,
		combobox_info: dict,
		index_for_logging: int | str,
	) -> dict[str, str]:
		"""Handle ARIA combobox elements with options in a separate listbox element.

		ARIA comboboxes (role="combobox") have options in a separate element referenced
		by aria-controls. Options may only be rendered when the combobox is expanded.

		This method:
		1. Expands the combobox if collapsed (by clicking/focusing it)
		2. Waits for options to render
		3. Finds options in the aria-controls referenced element
		4. Collapses the combobox after extracting options
		"""
		aria_controls_id = combobox_info.get('ariaControls')
		was_expanded = combobox_info.get('isExpanded', False)

		# If combobox is collapsed, expand it first to trigger option rendering
		if not was_expanded:
			# Use more robust expansion: dispatch proper DOM events that trigger event listeners
			expand_script = """
			function() {
				const element = this;

				// Dispatch focus event properly
				const focusEvent = new FocusEvent('focus', { bubbles: true, cancelable: true });
				element.dispatchEvent(focusEvent);

				// Also call native focus
				element.focus();

				// Dispatch focusin event (bubbles, unlike focus)
				const focusInEvent = new FocusEvent('focusin', { bubbles: true, cancelable: true });
				element.dispatchEvent(focusInEvent);

				// For some comboboxes, a click is needed
				const clickEvent = new MouseEvent('click', {
					bubbles: true,
					cancelable: true,
					view: window
				});
				element.dispatchEvent(clickEvent);

				// Some comboboxes respond to mousedown
				const mousedownEvent = new MouseEvent('mousedown', {
					bubbles: true,
					cancelable: true,
					view: window
				});
				element.dispatchEvent(mousedownEvent);

				return {
					success: true,
					ariaExpanded: element.getAttribute('aria-expanded')
				};
			}
			"""
			await cdp_session.cdp_client.send.Runtime.callFunctionOn(
				params={
					'functionDeclaration': expand_script,
					'objectId': object_id,
					'returnByValue': True,
				},
				session_id=cdp_session.session_id,
			)
			await asyncio.sleep(0.5)

		# Now extract options from the aria-controls referenced element
		extract_options_script = """
		function(ariaControlsId) {
			const combobox = this;

			// Find the listbox element referenced by aria-controls
			const listbox = document.getElementById(ariaControlsId);

			if (!listbox) {
				return {
					error: `Could not find listbox element with id "${ariaControlsId}" referenced by aria-controls`,
					ariaControlsId: ariaControlsId
				};
			}

			// Find all option elements in the listbox
			const optionElements = listbox.querySelectorAll('[role="option"]');
			const options = [];

			optionElements.forEach((item, idx) => {
				const text = item.textContent ? item.textContent.trim() : '';
				if (text) {
					options.push({
						text: text,
						value: item.getAttribute('data-value') || item.getAttribute('value') || text,
						index: idx,
						selected: item.getAttribute('aria-selected') === 'true' || item.classList.contains('selected')
					});
				}
			});

			// If no options with role="option", try other common patterns
			if (options.length === 0) {
				// Try li elements inside
				const liElements = listbox.querySelectorAll('li');
				liElements.forEach((item, idx) => {
					const text = item.textContent ? item.textContent.trim() : '';
					if (text) {
						options.push({
							text: text,
							value: item.getAttribute('data-value') || item.getAttribute('value') || text,
							index: idx,
							selected: item.getAttribute('aria-selected') === 'true' || item.classList.contains('selected')
						});
					}
				});
			}

			return {
				type: 'aria-combobox',
				options: options,
				id: combobox.id || '',
				name: combobox.getAttribute('aria-label') || combobox.getAttribute('name') || '',
				listboxId: ariaControlsId,
				source: 'aria-controls'
			};
		}
		"""

		result = await cdp_session.cdp_client.send.Runtime.callFunctionOn(
			params={
				'functionDeclaration': extract_options_script,
				'objectId': object_id,
				'arguments': [{'value': aria_controls_id}],
				'returnByValue': True,
			},
			session_id=cdp_session.session_id,
		)

		dropdown_data = result.get('result', {}).get('value', {})

		# Collapse the combobox if we expanded it (blur to close)
		if not was_expanded:
			collapse_script = """
			function() {
				this.blur();
				// Also dispatch escape key to close dropdowns
				const escEvent = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true });
				this.dispatchEvent(escEvent);
				return true;
			}
			"""
			await cdp_session.cdp_client.send.Runtime.callFunctionOn(
				params={
					'functionDeclaration': collapse_script,
					'objectId': object_id,
					'returnByValue': True,
				},
				session_id=cdp_session.session_id,
			)

		# Handle errors
		if dropdown_data.get('error'):
			raise BrowserError(message=dropdown_data['error'], long_term_memory=dropdown_data['error'])

		if not dropdown_data.get('options'):
			msg = f'No options found in ARIA combobox at index {index_for_logging} (listbox: {aria_controls_id})'
			return {
				'error': msg,
				'short_term_memory': msg,
				'long_term_memory': msg,
				'backend_node_id': str(index_for_logging),
			}

		# Format options for display
		formatted_options = []
		for opt in dropdown_data['options']:
			encoded_text = json.dumps(opt['text'])
			status = ' (selected)' if opt.get('selected') else ''
			formatted_options.append(f'{opt["index"]}: text={encoded_text}, value={json.dumps(opt["value"])}{status}')

		dropdown_type = dropdown_data.get('type', 'aria-combobox')
		element_info = f'Index: {index_for_logging}, Type: {dropdown_type}, ID: {dropdown_data.get("id", "none")}, Name: {dropdown_data.get("name", "none")}'
		source_info = f'aria-controls → {aria_controls_id}'

		msg = f'Found {dropdown_type} dropdown ({element_info}):\n' + '\n'.join(formatted_options)
		msg += f'\n\nUse the exact text or value string (without quotes) in select_dropdown(index={index_for_logging}, text=...)'

		self.logger.info(f'📋 Found {len(dropdown_data["options"])} options in ARIA combobox at index {index_for_logging}')

		return {
			'type': dropdown_type,
			'options': json.dumps(dropdown_data['options']),
			'element_info': element_info,
			'source': source_info,
			'formatted_options': '\n'.join(formatted_options),
			'message': msg,
			'short_term_memory': msg,
			'long_term_memory': f'Got dropdown options for ARIA combobox at index {index_for_logging}',
			'backend_node_id': str(index_for_logging),
		}

	async def select_dropdown_option(self, element_node: EnhancedDOMTreeNode, target_text: str) -> dict[str, str]:
		"""Select an option in native, ARIA, and custom dropdown elements."""
		try:
			index_for_logging = element_node.backend_node_id or 'unknown'

			# Get CDP session for this node
			cdp_session = await self.browser_session.cdp_client_for_node(element_node)

			# Convert node to object ID for CDP operations
			try:
				object_result = await cdp_session.cdp_client.send.DOM.resolveNode(
					params={'backendNodeId': element_node.backend_node_id}, session_id=cdp_session.session_id
				)
				remote_object = object_result.get('object', {})
				object_id = remote_object.get('objectId')
				if not object_id:
					raise ValueError('Could not get object ID from resolved node')
			except Exception as e:
				raise ValueError(f'Failed to resolve node to object: {e}') from e

			try:
				# Use JavaScript to select the option
				selection_script = """
				function(targetText) {
					const startElement = this;

					// Function to attempt selection on a dropdown element
					function attemptSelection(element) {
						// Handle native select elements
						if (element.tagName.toLowerCase() === 'select') {
							const options = Array.from(element.options);
							const targetTextLower = targetText.toLowerCase();

							for (const option of options) {
								const optionTextLower = option.text.trim().toLowerCase();
								const optionValueLower = option.value.toLowerCase();

								// Match against both text and value (case-insensitive)
								if (optionTextLower === targetTextLower || optionValueLower === targetTextLower) {
									const expectedValue = option.value;

									// Focus the element FIRST (important for Svelte/Vue/React and other reactive frameworks)
									// This simulates the user focusing on the dropdown before changing it
									element.focus();

									// Then set the value using multiple methods for maximum compatibility
									element.value = expectedValue;
									option.selected = true;
									element.selectedIndex = option.index;

									// Trigger all necessary events for reactive frameworks
									// 1. input event - critical for Vue's v-model and Svelte's bind:value
									const inputEvent = new Event('input', { bubbles: true, cancelable: true });
									element.dispatchEvent(inputEvent);

									// 2. change event - traditional form validation and framework reactivity
									const changeEvent = new Event('change', { bubbles: true, cancelable: true });
									element.dispatchEvent(changeEvent);

									// 3. blur event - completes the interaction, triggers validation
									element.blur();

									// Verification: Check if the selection actually stuck (avoid intercepting and resetting the value)
									if (element.value !== expectedValue) {
										// Selection was reverted - need to try clicking instead
										return {
											success: false,
											error: `Selection was set but reverted by page framework. The dropdown may require clicking.`,
											selectionReverted: true,
											targetOption: {
												text: option.text.trim(),
												value: expectedValue,
												index: option.index
											},
											availableOptions: Array.from(element.options).map(opt => ({
												text: opt.text.trim(),
												value: opt.value
											}))
										};
									}

									return {
										success: true,
										message: `Selected option: ${option.text.trim()} (value: ${option.value})`,
										value: option.value
									};
								}
							}

							// Return available options as separate field
							const availableOptions = options.map(opt => ({
								text: opt.text.trim(),
								value: opt.value
							}));

							return {
								success: false,
								error: `Option with text or value '${targetText}' not found in select element`,
								availableOptions: availableOptions
							};
						}

						// Handle ARIA dropdowns/menus
						const role = element.getAttribute('role');
						if (role === 'menu' || role === 'listbox' || role === 'combobox') {
							const menuItems = element.querySelectorAll('[role="menuitem"], [role="option"]');
							const targetTextLower = targetText.toLowerCase();

							for (const item of menuItems) {
								if (item.textContent) {
									const itemTextLower = item.textContent.trim().toLowerCase();
									const itemValueLower = (item.getAttribute('data-value') || '').toLowerCase();

									// Match against both text and data-value (case-insensitive)
									if (itemTextLower === targetTextLower || itemValueLower === targetTextLower) {
										// Clear previous selections
										menuItems.forEach(mi => {
											mi.setAttribute('aria-selected', 'false');
											mi.classList.remove('selected');
										});

										// Select this item
										item.setAttribute('aria-selected', 'true');
										item.classList.add('selected');

										// Trigger click and change events
										item.click();
										const clickEvent = new MouseEvent('click', { view: window, bubbles: true, cancelable: true });
										item.dispatchEvent(clickEvent);

										return {
											success: true,
											message: `Selected ARIA menu item: ${item.textContent.trim()}`
										};
									}
								}
							}

							// Return available options as separate field
							const availableOptions = Array.from(menuItems).map(item => ({
								text: item.textContent ? item.textContent.trim() : '',
								value: item.getAttribute('data-value') || ''
							})).filter(opt => opt.text || opt.value);

							return {
								success: false,
								error: `Menu item with text or value '${targetText}' not found`,
								availableOptions: availableOptions
							};
						}

						// Handle Semantic UI or custom dropdowns
						if (element.classList.contains('dropdown') || element.classList.contains('ui')) {
							const menuItems = element.querySelectorAll('.item, .option, [data-value]');
							const targetTextLower = targetText.toLowerCase();

							for (const item of menuItems) {
								if (item.textContent) {
									const itemTextLower = item.textContent.trim().toLowerCase();
									const itemValueLower = (item.getAttribute('data-value') || '').toLowerCase();

									// Match against both text and data-value (case-insensitive)
									if (itemTextLower === targetTextLower || itemValueLower === targetTextLower) {
										// Clear previous selections
										menuItems.forEach(mi => {
											mi.classList.remove('selected', 'active');
										});

										// Select this item
										item.classList.add('selected', 'active');

										// Update dropdown text if there's a text element
										const textElement = element.querySelector('.text');
										if (textElement) {
											textElement.textContent = item.textContent.trim();
										}

										// Trigger click and change events
										item.click();
										const clickEvent = new MouseEvent('click', { view: window, bubbles: true, cancelable: true });
										item.dispatchEvent(clickEvent);

										// Also dispatch on the main dropdown element
										const dropdownChangeEvent = new Event('change', { bubbles: true });
										element.dispatchEvent(dropdownChangeEvent);

										return {
											success: true,
											message: `Selected custom dropdown item: ${item.textContent.trim()}`
										};
									}
								}
							}

							// Return available options as separate field
							const availableOptions = Array.from(menuItems).map(item => ({
								text: item.textContent ? item.textContent.trim() : '',
								value: item.getAttribute('data-value') || ''
							})).filter(opt => opt.text || opt.value);

							return {
								success: false,
								error: `Custom dropdown item with text or value '${targetText}' not found`,
								availableOptions: availableOptions
							};
						}

						return null; // Not a dropdown element
					}

					// Function to recursively search children for dropdowns
					function searchChildrenForSelection(element, maxDepth, currentDepth = 0) {
						if (currentDepth >= maxDepth) return null;

						// Check all direct children
						for (let child of element.children) {
							// Try selection on this child
							const result = attemptSelection(child);
							if (result && result.success) {
								return result;
							}

							// Recursively check this child's children
							const childResult = searchChildrenForSelection(child, maxDepth, currentDepth + 1);
							if (childResult && childResult.success) {
								return childResult;
							}
						}

						return null;
					}

					// First try the target element itself
					let selectionResult = attemptSelection(startElement);
					if (selectionResult) {
						// If attemptSelection returned a result (success or failure), use it
						// Don't search children if we found a dropdown element but selection failed
						return selectionResult;
					}

					// Only search children if target element is not a dropdown element
					selectionResult = searchChildrenForSelection(startElement, 4);
					if (selectionResult && selectionResult.success) {
						return selectionResult;
					}

					return {
						success: false,
						error: `Element and its children (depth 4) do not contain a dropdown with option '${targetText}' (tag: ${startElement.tagName}, role: ${startElement.getAttribute('role')}, classes: ${startElement.className})`
					};
				}
				"""

				result = await cdp_session.cdp_client.send.Runtime.callFunctionOn(
					params={
						'functionDeclaration': selection_script,
						'arguments': [{'value': target_text}],
						'objectId': object_id,
						'returnByValue': True,
					},
					session_id=cdp_session.session_id,
				)

				selection_result = result.get('result', {}).get('value', {})

				# If selection failed and all options are empty, the dropdown may be lazily populated.
				# Focus the element (triggers lazy loaders) and retry once after a wait.
				if not selection_result.get('success'):
					available_options = selection_result.get('availableOptions', [])
					all_empty = available_options and all(
						(not opt.get('text', '').strip() and not opt.get('value', '').strip())
						if isinstance(opt, dict)
						else not str(opt).strip()
						for opt in available_options
					)
					if all_empty:
						self.logger.info(
							'⚠️ All dropdown options are empty — options may be lazily loaded. Focusing element and retrying...'
						)

						# Use element.focus() only — no synthetic mouse events that leak isTrusted=false
						try:
							await cdp_session.cdp_client.send.Runtime.callFunctionOn(
								params={
									'functionDeclaration': 'function() { this.focus(); }',
									'objectId': object_id,
								},
								session_id=cdp_session.session_id,
							)
						except Exception:
							pass  # non-fatal, best-effort

						await asyncio.sleep(1.0)

						retry_result = await cdp_session.cdp_client.send.Runtime.callFunctionOn(
							params={
								'functionDeclaration': selection_script,
								'arguments': [{'value': target_text}],
								'objectId': object_id,
								'returnByValue': True,
							},
							session_id=cdp_session.session_id,
						)
						selection_result = retry_result.get('result', {}).get('value', {})

				# Check if selection was reverted by framework - try clicking as fallback
				if selection_result.get('selectionReverted'):
					self.logger.info('⚠️ Selection was reverted by page framework, trying click fallback...')
					target_option = selection_result.get('targetOption', {})
					option_index = target_option.get('index', 0)

					# Try clicking on the option element directly
					click_fallback_script = """
					function(optionIndex) {
						const select = this;
						if (select.tagName.toLowerCase() !== 'select') return { success: false, error: 'Not a select element' };

						const option = select.options[optionIndex];
						if (!option) return { success: false, error: 'Option not found at index ' + optionIndex };

						// Method 1: Try using the native selectedIndex setter with a small delay
						const originalValue = select.value;

						// Simulate opening the dropdown (some frameworks need this)
						select.focus();
						const mouseDown = new MouseEvent('mousedown', { bubbles: true, cancelable: true, view: window });
						select.dispatchEvent(mouseDown);

						// Set using selectedIndex (more reliable for some frameworks)
						select.selectedIndex = optionIndex;

						// Click the option
						option.selected = true;
						const optionClick = new MouseEvent('click', { bubbles: true, cancelable: true, view: window });
						option.dispatchEvent(optionClick);

						// Close dropdown
						const mouseUp = new MouseEvent('mouseup', { bubbles: true, cancelable: true, view: window });
						select.dispatchEvent(mouseUp);

						// Fire change event
						const changeEvent = new Event('change', { bubbles: true, cancelable: true });
						select.dispatchEvent(changeEvent);

						// Blur to finalize
						select.blur();

						// Verify
						if (select.value === option.value || select.selectedIndex === optionIndex) {
							return {
								success: true,
								message: 'Selected via click fallback: ' + option.text.trim(),
								value: option.value
							};
						}

						return {
							success: false,
							error: 'Click fallback also failed - framework may block all programmatic selection',
							finalValue: select.value,
							expectedValue: option.value
						};
					}
					"""

					fallback_result = await cdp_session.cdp_client.send.Runtime.callFunctionOn(
						params={
							'functionDeclaration': click_fallback_script,
							'arguments': [{'value': option_index}],
							'objectId': object_id,
							'returnByValue': True,
						},
						session_id=cdp_session.session_id,
					)

					fallback_data = fallback_result.get('result', {}).get('value', {})
					if fallback_data.get('success'):
						msg = fallback_data.get('message', f'Selected option via click: {target_text}')
						self.logger.info(f'✅ {msg}')
						return {
							'success': 'true',
							'message': msg,
							'value': fallback_data.get('value', target_text),
							'backend_node_id': str(index_for_logging),
						}
					else:
						self.logger.warning(f'⚠️ Click fallback also failed: {fallback_data.get("error", "unknown")}')
						# Continue to error handling below

				if selection_result.get('success'):
					msg = selection_result.get('message', f'Selected option: {target_text}')
					self.logger.debug(f'{msg}')

					# Return the result as a dict
					return {
						'success': 'true',
						'message': msg,
						'value': selection_result.get('value', target_text),
						'backend_node_id': str(index_for_logging),
					}
				else:
					error_msg = selection_result.get('error', f'Failed to select option: {target_text}')
					available_options = selection_result.get('availableOptions', [])
					self.logger.error(f'❌ {error_msg}')
					self.logger.debug(f'Available options from JavaScript: {available_options}')

					# If we have available options, return structured error data
					if available_options:
						# Format options for short_term_memory (simple bulleted list)
						short_term_options = []
						for opt in available_options:
							if isinstance(opt, dict):
								text = opt.get('text', '').strip()
								value = opt.get('value', '').strip()
								if text:
									short_term_options.append(f'- {text}')
								elif value:
									short_term_options.append(f'- {value}')
							elif isinstance(opt, str):
								short_term_options.append(f'- {opt}')

						if short_term_options:
							short_term_memory = 'Available dropdown options  are:\n' + '\n'.join(short_term_options)
							long_term_memory = (
								f"Couldn't select the dropdown option as '{target_text}' is not one of the available options."
							)

							# Return error result with structured memory instead of raising exception
							return {
								'success': 'false',
								'error': error_msg,
								'short_term_memory': short_term_memory,
								'long_term_memory': long_term_memory,
								'backend_node_id': str(index_for_logging),
							}

					# Fallback to regular error result if no available options
					return {
						'success': 'false',
						'error': error_msg,
						'backend_node_id': str(index_for_logging),
					}

			except Exception as e:
				error_msg = f'Failed to select dropdown option: {str(e)}'
				self.logger.error(error_msg)
				raise ValueError(error_msg) from e

		except Exception as e:
			error_msg = f'Failed to select dropdown option "{target_text}" for element {index_for_logging}: {str(e)}'
			self.logger.error(error_msg)
			raise ValueError(error_msg) from e


def _page_appears_empty(state: BrowserStateSummary) -> bool:
	return state.dom_state._root is None or not state.dom_state.llm_representation().strip()


def _xpath_literal(value: str) -> str:
	if "'" not in value:
		return f"'{value}'"
	if '"' not in value:
		return f'"{value}"'
	parts = value.split("'")
	single_quote_literal = '"\'"'
	return 'concat(' + f', {single_quote_literal}, '.join(f"'{part}'" for part in parts) + ')'


def _download_filename(url: str, *, content_type: str | None, suggested_filename: str | None) -> str:
	if suggested_filename:
		return _sanitize_download_filename(suggested_filename)

	parsed = urlparse(url)
	filename = _sanitize_download_filename(os.path.basename(parsed.path))
	if filename != 'download' and '.' in filename:
		return filename
	if content_type and 'pdf' in content_type:
		return 'document.pdf'
	return filename


def _sanitize_download_filename(name: str | None) -> str:
	if not name:
		return 'download'
	name = name.replace('\x00', '')
	name = name.replace('\\', '/')
	name = os.path.basename(name.rsplit('/', 1)[-1])
	if name in ('', '.', '..'):
		return 'download'
	return name


def _unique_download_destination(downloads_dir: Path, filename: str) -> Path:
	destination = downloads_dir / filename
	if not destination.exists():
		return destination

	base = destination.stem
	ext = destination.suffix
	counter = 1
	while True:
		candidate = downloads_dir / f'{base} ({counter}){ext}'
		if not candidate.exists():
			return candidate
		counter += 1


def _is_path_contained(path: str | Path, directory: str | Path) -> bool:
	real_path = os.path.realpath(str(path))
	real_dir = os.path.realpath(str(directory))
	return real_path == real_dir or real_path.startswith(real_dir + os.sep)


class DownloadService(BrowserService):
	"""Downloaded file access."""

	def list_downloads(self) -> list[str]:
		return self.browser_session.downloaded_files

	async def download_url(
		self,
		url: str,
		*,
		target_id: TargetID | None = None,
		content_type: str | None = None,
		suggested_filename: str | None = None,
		timeout_s: float = 15.0,
	) -> dict[str, Any] | None:
		"""Download a URL through the browser context and track it without the event bus."""

		downloads_path = self.browser_session.browser_profile.downloads_path
		if not downloads_path:
			self.browser_session.logger.warning('[DownloadService] No downloads path configured')
			return None

		downloads_dir = Path(downloads_path).expanduser().resolve()
		downloads_dir.mkdir(parents=True, exist_ok=True)
		filename = _download_filename(url, content_type=content_type, suggested_filename=suggested_filename)
		destination = _unique_download_destination(downloads_dir, filename)
		if not _is_path_contained(destination, downloads_dir):
			self.browser_session.logger.error(
				f'[DownloadService] Refusing to write download outside downloads_dir: {destination}'
			)
			return None

		if target_id is None:
			if self.browser_session.agent_focus_target_id is None:
				cdp_session = await self.browser_session.get_or_create_cdp_session(target_id=None, focus=True)
			else:
				cdp_session = await self.browser_session.get_or_create_cdp_session(
					target_id=self.browser_session.agent_focus_target_id, focus=False
				)
		else:
			cdp_session = await self.browser_session.get_or_create_cdp_session(target_id=target_id, focus=False)

		result = await asyncio.wait_for(
			cdp_session.cdp_client.send.Runtime.evaluate(
				params={
					'expression': f"""
(async () => {{
	const response = await fetch({json.dumps(url)}, {{ cache: 'force-cache' }});
	if (!response.ok) {{
		throw new Error(`HTTP error! status: ${{response.status}}`);
	}}
	const blob = await response.blob();
	const arrayBuffer = await blob.arrayBuffer();
	const uint8Array = new Uint8Array(arrayBuffer);
	return {{ data: Array.from(uint8Array), responseSize: uint8Array.length }};
}})()
""",
					'awaitPromise': True,
					'returnByValue': True,
				},
				session_id=cdp_session.session_id,
			),
			timeout=timeout_s,
		)
		download_result = result.get('result', {}).get('value') or {}
		data = download_result.get('data') or []
		if not data:
			self.browser_session.logger.warning(f'[DownloadService] No data received when downloading from {url}')
			return None

		payload = bytes(data)
		await asyncio.to_thread(destination.write_bytes, payload)
		file_size = destination.stat().st_size
		resolved_content_type = content_type or mimetypes.guess_type(destination.name)[0]
		file_ext = destination.suffix.lower().lstrip('.') or None
		event = FileDownloadedEvent(
			url=url,
			path=str(destination),
			file_name=destination.name,
			file_size=file_size,
			file_type=file_ext,
			mime_type=resolved_content_type,
			auto_download=True,
		)
		await self.browser_session.on_FileDownloadedEvent(event)
		return {
			'url': url,
			'path': str(destination),
			'file_name': destination.name,
			'file_size': file_size,
			'file_type': file_ext,
			'mime_type': resolved_content_type,
		}


class DialogService(BrowserService):
	"""Dialog state captured by popup handling."""

	def closed_messages(self) -> list[str]:
		return list(self.browser_session._closed_popup_messages)

	def clear_closed_messages(self) -> None:
		self.browser_session._closed_popup_messages.clear()


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
	keyboard: KeyboardService
	upload: UploadService
	dropdown: DropdownService
	navigation: NavigationService
	tabs: TabService

	@classmethod
	def from_session(cls, browser_session: BrowserSession) -> ActionService:
		return cls(
			click=ClickService(browser_session=browser_session),
			type=TypeService(browser_session=browser_session),
			scroll=ScrollService(browser_session=browser_session),
			keyboard=KeyboardService(browser_session=browser_session),
			upload=UploadService(browser_session=browser_session),
			dropdown=DropdownService(browser_session=browser_session),
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
