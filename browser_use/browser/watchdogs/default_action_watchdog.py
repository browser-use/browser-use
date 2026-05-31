"""Default browser action handlers using CDP."""

import asyncio
from typing import Literal

from browser_use.browser.events import (
	ClickCoordinateEvent,
	ClickElementEvent,
	GetDropdownOptionsEvent,
	GoBackEvent,
	GoForwardEvent,
	RefreshEvent,
	ScrollEvent,
	ScrollToTextEvent,
	SelectDropdownOptionEvent,
	SendKeysEvent,
	TypeTextEvent,
	UploadFileEvent,
	WaitEvent,
)
from browser_use.browser.watchdog_base import BaseWatchdog
from browser_use.dom.service import EnhancedDOMTreeNode
from browser_use.observability import observe_debug

# Import EnhancedDOMTreeNode and rebuild event models that have forward references to it
# This must be done after all imports are complete
ClickCoordinateEvent.model_rebuild()
ClickElementEvent.model_rebuild()
GetDropdownOptionsEvent.model_rebuild()
SelectDropdownOptionEvent.model_rebuild()
TypeTextEvent.model_rebuild()
ScrollEvent.model_rebuild()
UploadFileEvent.model_rebuild()


class DefaultActionWatchdog(BaseWatchdog):
	"""Handles default browser actions like click, type, and scroll using CDP."""

	async def _execute_click_with_download_detection(
		self,
		click_coro,
		download_start_timeout: float = 0.5,
		download_complete_timeout: float = 30.0,
	) -> dict | None:
		"""Compatibility wrapper for old direct helper callers."""
		from browser_use.browser.services import ClickService

		return await ClickService(browser_session=self.browser_session)._execute_click_with_download_detection(
			click_coro,
			download_start_timeout=download_start_timeout,
			download_complete_timeout=download_complete_timeout,
		)

	def _is_print_related_element(self, element_node: EnhancedDOMTreeNode) -> bool:
		"""Compatibility wrapper for old direct helper callers."""
		from browser_use.browser.services import ClickService

		return ClickService(browser_session=self.browser_session)._is_print_related_element(element_node)

	async def _handle_print_button_click(self, element_node: EnhancedDOMTreeNode) -> dict | None:
		"""Compatibility wrapper for old direct helper callers."""
		from browser_use.browser.services import ClickService

		return await ClickService(browser_session=self.browser_session)._handle_print_button_click(element_node)

	@observe_debug(ignore_input=True, ignore_output=True, name='click_element_event')
	async def on_ClickElementEvent(self, event: ClickElementEvent) -> dict | None:
		"""Compatibility adapter for legacy event-based click dispatch."""
		return await self.click_element(event.node, button=event.button)

	async def click_element(
		self,
		element_node: EnhancedDOMTreeNode,
		*,
		button: Literal['left', 'right', 'middle'] = 'left',
	) -> dict | None:
		"""Compatibility adapter for direct click calls that still reference this handler."""
		from browser_use.browser.services import ClickService

		return await ClickService(browser_session=self.browser_session).click_node(element_node, button=button)

	async def on_ClickCoordinateEvent(self, event: ClickCoordinateEvent) -> dict | None:
		"""Compatibility adapter for legacy event-based coordinate click dispatch."""
		return await self.click_coordinates(
			event.coordinate_x,
			event.coordinate_y,
			button=event.button,
			force=event.force,
		)

	async def click_coordinates(
		self,
		coordinate_x: int,
		coordinate_y: int,
		*,
		button: Literal['left', 'right', 'middle'] = 'left',
		force: bool = False,
	) -> dict | None:
		"""Compatibility adapter for direct coordinate-click calls that still reference this handler."""
		from browser_use.browser.services import ClickService

		return await ClickService(browser_session=self.browser_session).click_coordinates(
			coordinate_x,
			coordinate_y,
			button=button,
			force=force,
		)

	async def on_TypeTextEvent(self, event: TypeTextEvent) -> dict | None:
		"""Compatibility adapter for legacy event-based text entry dispatch."""
		return await self.type_text(
			event.node,
			event.text,
			clear=event.clear,
			is_sensitive=event.is_sensitive,
			sensitive_key_name=event.sensitive_key_name,
		)

	async def type_text(
		self,
		element_node: EnhancedDOMTreeNode,
		text: str,
		*,
		clear: bool = True,
		is_sensitive: bool = False,
		sensitive_key_name: str | None = None,
	) -> dict | None:
		"""Compatibility adapter for direct text-entry calls that still reference this handler."""
		from browser_use.browser.services import TypeService

		return await TypeService(browser_session=self.browser_session).type_node(
			element_node,
			text,
			clear=clear,
			is_sensitive=is_sensitive,
			sensitive_key_name=sensitive_key_name,
		)

	async def on_ScrollEvent(self, event: ScrollEvent) -> None:
		"""Compatibility adapter for legacy event-based scroll requests."""
		from browser_use.browser.services import ScrollService

		await ScrollService(browser_session=self.browser_session).scroll_page(
			event.amount,
			direction=event.direction,
			node=event.node,
		)
		return None

	# ========== Implementation Methods ==========

	async def _check_element_occlusion(self, backend_node_id: int, x: float, y: float, cdp_session) -> bool:
		"""Compatibility wrapper for old direct helper callers."""
		from browser_use.browser.services import ClickService

		return await ClickService(browser_session=self.browser_session)._check_element_occlusion(
			backend_node_id, x, y, cdp_session
		)

	async def _click_element_node_impl(self, element_node) -> dict | None:
		"""Compatibility wrapper for old direct helper callers."""
		from browser_use.browser.services import ClickService

		return await ClickService(browser_session=self.browser_session)._click_element_node_impl(element_node)

	async def _click_on_coordinate(
		self,
		coordinate_x: int,
		coordinate_y: int,
		force: bool = False,
		button: Literal['left', 'right', 'middle'] = 'left',
	) -> dict | None:
		"""Compatibility wrapper for old direct helper callers."""
		from browser_use.browser.services import ClickService

		return await ClickService(browser_session=self.browser_session)._click_on_coordinate(
			coordinate_x,
			coordinate_y,
			force=force,
			button=button,
		)

	async def _type_to_page(self, text: str):
		"""Compatibility wrapper for old direct helper callers."""
		from browser_use.browser.services import TypeService

		return await TypeService(browser_session=self.browser_session)._type_to_page(text)

	def _get_char_modifiers_and_vk(self, char: str) -> tuple[int, int, str]:
		"""Compatibility wrapper for old direct helper callers."""
		from browser_use.browser.services import TypeService

		return TypeService(browser_session=self.browser_session)._get_char_modifiers_and_vk(char)

	def _get_key_code_for_char(self, char: str) -> str:
		"""Compatibility wrapper for old direct helper callers."""
		from browser_use.browser.services import TypeService

		return TypeService(browser_session=self.browser_session)._get_key_code_for_char(char)

	async def _clear_text_field(self, object_id: str, cdp_session) -> bool:
		"""Compatibility wrapper for old direct helper callers."""
		from browser_use.browser.services import TypeService

		return await TypeService(browser_session=self.browser_session)._clear_text_field(object_id, cdp_session)

	async def _focus_element_simple(
		self,
		backend_node_id: int,
		object_id: str,
		cdp_session,
		input_coordinates: dict | None = None,
	) -> bool:
		"""Compatibility wrapper for old direct helper callers."""
		from browser_use.browser.services import TypeService

		return await TypeService(browser_session=self.browser_session)._focus_element_simple(
			backend_node_id,
			object_id,
			cdp_session,
			input_coordinates=input_coordinates,
		)

	def _requires_direct_value_assignment(self, element_node: EnhancedDOMTreeNode) -> bool:
		"""Compatibility wrapper for old direct helper callers."""
		from browser_use.browser.services import TypeService

		return TypeService(browser_session=self.browser_session)._requires_direct_value_assignment(element_node)

	async def _set_value_directly(self, element_node: EnhancedDOMTreeNode, text: str, object_id: str, cdp_session) -> None:
		"""Compatibility wrapper for old direct helper callers."""
		from browser_use.browser.services import TypeService

		return await TypeService(browser_session=self.browser_session)._set_value_directly(
			element_node, text, object_id, cdp_session
		)

	async def _input_text_element_node_impl(
		self,
		element_node: EnhancedDOMTreeNode,
		text: str,
		clear: bool = True,
		is_sensitive: bool = False,
	) -> dict | None:
		"""Compatibility wrapper for old direct helper callers."""
		from browser_use.browser.services import TypeService

		return await TypeService(browser_session=self.browser_session)._input_text_element_node_impl(
			element_node,
			text,
			clear=clear,
			is_sensitive=is_sensitive,
		)

	async def _trigger_framework_events(self, object_id: str, cdp_session) -> None:
		"""Compatibility wrapper for old direct helper callers."""
		from browser_use.browser.services import TypeService

		return await TypeService(browser_session=self.browser_session)._trigger_framework_events(object_id, cdp_session)

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

	async def _scroll_element_container(self, element_node, pixels: int) -> bool:
		"""Try to scroll an element's container using CDP."""
		try:
			cdp_session = await self.browser_session.cdp_client_for_node(element_node)

			# Check if this is an iframe - if so, scroll its content directly
			if element_node.tag_name and element_node.tag_name.upper() == 'IFRAME':
				# For iframes, we need to scroll the content document, not the iframe element itself
				# Use JavaScript to directly scroll the iframe's content
				backend_node_id = element_node.backend_node_id

				# Resolve the node to get an object ID
				result = await cdp_session.cdp_client.send.DOM.resolveNode(
					params={'backendNodeId': backend_node_id},
					session_id=cdp_session.session_id,
				)

				if 'object' in result and 'objectId' in result['object']:
					object_id = result['object']['objectId']

					# Scroll the iframe's content directly
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

					if scroll_result and 'result' in scroll_result and 'value' in scroll_result['result']:
						result_value = scroll_result['result']['value']
						if result_value.get('success'):
							self.logger.debug(f'Successfully scrolled iframe content by {result_value.get("scrolled", 0)}px')
							return True
						else:
							self.logger.debug(f'Failed to scroll iframe: {result_value.get("error", "Unknown error")}')

			# For non-iframe elements, use the standard mouse wheel approach
			# Get element bounds to know where to scroll
			backend_node_id = element_node.backend_node_id
			box_model = await cdp_session.cdp_client.send.DOM.getBoxModel(
				params={'backendNodeId': backend_node_id}, session_id=cdp_session.session_id
			)
			content_quad = box_model['model']['content']

			# Calculate center point
			center_x = (content_quad[0] + content_quad[2] + content_quad[4] + content_quad[6]) / 4
			center_y = (content_quad[1] + content_quad[3] + content_quad[5] + content_quad[7]) / 4

			# Dispatch mouse wheel event at element location
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
			self.logger.debug(f'Failed to scroll element container via CDP: {e}')
			return False

	async def _get_session_id_for_element(self, element_node: EnhancedDOMTreeNode) -> str | None:
		"""Get the appropriate CDP session ID for an element based on its frame."""
		if element_node.frame_id:
			# Element is in an iframe, need to get session for that frame
			try:
				all_targets = self.browser_session.session_manager.get_all_targets()

				# Find the target for this frame
				for target_id, target in all_targets.items():
					if target.target_type == 'iframe' and element_node.frame_id in str(target_id):
						# Create temporary session for iframe target without switching focus
						temp_session = await self.browser_session.get_or_create_cdp_session(target_id, focus=False)
						return temp_session.session_id

				# If frame not found in targets, use main target session
				self.logger.debug(f'Frame {element_node.frame_id} not found in targets, using main session')
			except Exception as e:
				self.logger.debug(f'Error getting frame session: {e}, using main session')

		# Use main target session - get_or_create_cdp_session validates focus automatically
		cdp_session = await self.browser_session.get_or_create_cdp_session()
		return cdp_session.session_id

	async def on_GoBackEvent(self, event: GoBackEvent) -> None:
		"""Compatibility adapter for legacy event-based back navigation."""
		from browser_use.browser.services import NavigationService

		url = await NavigationService(browser_session=self.browser_session).go_back()
		if url is None:
			self.logger.warning('⚠️ Cannot go back - no previous entry in history')
			return
		self.logger.info(f'🔙 Navigated back to {url}')

	async def on_GoForwardEvent(self, event: GoForwardEvent) -> None:
		"""Compatibility adapter for legacy event-based forward navigation."""
		from browser_use.browser.services import NavigationService

		url = await NavigationService(browser_session=self.browser_session).go_forward()
		if url is None:
			self.logger.warning('⚠️ Cannot go forward - no next entry in history')
			return
		self.logger.info(f'🔜 Navigated forward to {url}')

	async def on_RefreshEvent(self, event: RefreshEvent) -> None:
		"""Compatibility adapter for legacy event-based refresh requests."""
		from browser_use.browser.services import NavigationService

		await NavigationService(browser_session=self.browser_session).refresh()
		self.logger.info('🔄 Target refreshed')

	@observe_debug(ignore_input=True, ignore_output=True, name='wait_event_handler')
	async def on_WaitEvent(self, event: WaitEvent) -> None:
		"""Handle wait request."""
		try:
			# Cap wait time at maximum
			actual_seconds = min(max(event.seconds, 0), event.max_seconds)
			if actual_seconds != event.seconds:
				self.logger.info(f'🕒 Waiting for {actual_seconds} seconds (capped from {event.seconds}s)')
			else:
				self.logger.info(f'🕒 Waiting for {actual_seconds} seconds')

			await asyncio.sleep(actual_seconds)
		except Exception as e:
			raise

	async def on_SendKeysEvent(self, event: SendKeysEvent) -> None:
		"""Compatibility adapter for legacy event-based keyboard requests."""
		from browser_use.browser.services import KeyboardService

		await KeyboardService(browser_session=self.browser_session).send_keys(event.keys)

	async def on_UploadFileEvent(self, event: UploadFileEvent) -> None:
		"""Compatibility adapter for legacy event-based upload requests."""
		from browser_use.browser.services import UploadService

		await UploadService(browser_session=self.browser_session).upload_file(event.node, event.file_path)

	async def on_ScrollToTextEvent(self, event: ScrollToTextEvent) -> None:
		"""Compatibility adapter for legacy event-based scroll-to-text requests."""
		from browser_use.browser.services import ScrollService

		await ScrollService(browser_session=self.browser_session).scroll_to_text(event.text)
		return None

	async def on_GetDropdownOptionsEvent(self, event: GetDropdownOptionsEvent) -> dict[str, str]:
		"""Compatibility adapter for legacy event-based dropdown option requests."""
		return await self.get_dropdown_options(event.node)

	async def get_dropdown_options(self, element_node: EnhancedDOMTreeNode) -> dict[str, str]:
		"""Compatibility adapter for direct dropdown option calls that still reference this handler."""
		from browser_use.browser.services import DropdownService

		return await DropdownService(browser_session=self.browser_session).get_dropdown_options(element_node)

	async def on_SelectDropdownOptionEvent(self, event: SelectDropdownOptionEvent) -> dict[str, str]:
		"""Compatibility adapter for legacy event-based dropdown selection requests."""
		return await self.select_dropdown_option(event.node, event.text)

	async def select_dropdown_option(self, element_node: EnhancedDOMTreeNode, target_text: str) -> dict[str, str]:
		"""Compatibility adapter for direct dropdown selection calls that still reference this handler."""
		from browser_use.browser.services import DropdownService

		return await DropdownService(browser_session=self.browser_session).select_dropdown_option(element_node, target_text)
