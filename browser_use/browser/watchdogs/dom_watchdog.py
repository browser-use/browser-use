"""DOM watchdog for browser DOM tree management using CDP."""

import asyncio
import time
from typing import TYPE_CHECKING

from browser_use.browser.events import (
	BrowserErrorEvent,
	BrowserStateRequestEvent,
	ScreenshotEvent,
	TabCreatedEvent,
)
from browser_use.browser.watchdog_base import BaseWatchdog
from browser_use.dom.service import DomService
from browser_use.dom.views import (
	EnhancedDOMTreeNode,
	SerializedDOMState,
)
from browser_use.observability import observe_debug
from browser_use.utils import time_execution_async

if TYPE_CHECKING:
	from browser_use.browser.views import BrowserStateSummary, PageInfo


class DOMWatchdog(BaseWatchdog):
	"""Handles DOM tree building, serialization, and element access via CDP.

	This watchdog acts as a bridge between the event-driven browser session
	and the DomService implementation, maintaining cached state and providing
	helper methods for other watchdogs.
	"""

	LISTENS_TO = [TabCreatedEvent, BrowserStateRequestEvent]
	EMITS = [BrowserErrorEvent]

	# Public properties for other watchdogs
	selector_map: dict[int, EnhancedDOMTreeNode] | None = None
	current_dom_state: SerializedDOMState | None = None
	enhanced_dom_tree: EnhancedDOMTreeNode | None = None

	# Internal DOM service
	_dom_service: DomService | None = None

	async def on_TabCreatedEvent(self, event: TabCreatedEvent) -> None:
		# self.logger.debug('Setting up init scripts in browser')
		return None

	def _get_recent_events_str(self, limit: int = 10) -> str | None:
		"""Get the most recent events from the event bus as JSON.

		Args:
			limit: Maximum number of recent events to include

		Returns:
			JSON string of recent events or None if not available
		"""
		import json

		try:
			# Get all events from history, sorted by creation time (most recent first)
			all_events = sorted(
				self.browser_session.event_bus.event_history.values(), key=lambda e: e.event_created_at.timestamp(), reverse=True
			)

			# Take the most recent events and create JSON-serializable data
			recent_events_data = []
			for event in all_events[:limit]:
				event_data = {
					'event_type': event.event_type,
					'timestamp': event.event_created_at.isoformat(),
				}
				# Add specific fields for certain event types
				if hasattr(event, 'url'):
					event_data['url'] = getattr(event, 'url')
				if hasattr(event, 'error_message'):
					event_data['error_message'] = getattr(event, 'error_message')
				if hasattr(event, 'target_id'):
					event_data['target_id'] = getattr(event, 'target_id')
				recent_events_data.append(event_data)

			return json.dumps(recent_events_data)  # Return empty array if no events
		except Exception as e:
			self.logger.debug(f'Failed to get recent events: {e}')

		return json.dumps([])  # Return empty JSON array on error

	@observe_debug(ignore_input=True, ignore_output=True, name='browser_state_request_event')
	async def on_BrowserStateRequestEvent(self, event: BrowserStateRequestEvent) -> 'BrowserStateSummary':
		"""Handle browser state request by coordinating DOM building and screenshot capture.

		This is the main entry point for getting the complete browser state.

		Args:
			event: The browser state request event with options

		Returns:
			Complete BrowserStateSummary with DOM, screenshot, and target info
		"""
		from browser_use.browser.views import BrowserStateSummary, PageInfo

		self.logger.debug('🔍 DOMWatchdog.on_BrowserStateRequestEvent: STARTING browser state request')
		page_url = await self.browser_session.get_current_page_url()
		self.logger.debug(f'🔍 DOMWatchdog.on_BrowserStateRequestEvent: Got page URL: {page_url}')
		if self.browser_session.agent_focus:
			self.logger.debug(
				f'Current page URL: {page_url}, target_id: {self.browser_session.agent_focus.target_id}, session_id: {self.browser_session.agent_focus.session_id}'
			)
		else:
			self.logger.debug(f'Current page URL: {page_url}, no cdp_session attached')

		# check if we should skip DOM tree build for pointless pages
		not_a_meaningful_website = page_url.lower().split(':', 1)[0] not in ('http', 'https')

		# Wait for page stability using browser profile settings (main branch pattern)
		if not not_a_meaningful_website:
			self.logger.debug('🔍 DOMWatchdog.on_BrowserStateRequestEvent: ⏳ Waiting for page stability...')
			try:
				await self._wait_for_stable_network()
				self.logger.debug('🔍 DOMWatchdog.on_BrowserStateRequestEvent: ✅ Page stability complete')
			except Exception as e:
				self.logger.warning(
					f'🔍 DOMWatchdog.on_BrowserStateRequestEvent: Network waiting failed: {e}, continuing anyway...'
				)

		# Get tabs info once at the beginning for all paths
		self.logger.debug('🔍 DOMWatchdog.on_BrowserStateRequestEvent: Getting tabs info...')
		tabs_info = await self.browser_session.get_tabs()
		self.logger.debug(f'🔍 DOMWatchdog.on_BrowserStateRequestEvent: Got {len(tabs_info)} tabs')
		self.logger.debug(f'🔍 DOMWatchdog.on_BrowserStateRequestEvent: Tabs info: {tabs_info}')

		# Get viewport / scroll position info, remember changing scroll position should invalidate selector_map cache because it only includes visible elements
		# cdp_session = await self.browser_session.get_or_create_cdp_session(focus=True)
		# scroll_info = await cdp_session.cdp_client.send.Runtime.evaluate(
		# 	params={'expression': 'JSON.stringify({y: document.body.scrollTop, x: document.body.scrollLeft, width: document.documentElement.clientWidth, height: document.documentElement.clientHeight})'},
		# 	session_id=cdp_session.session_id,
		# )
		# self.logger.debug(f'🔍 DOMWatchdog.on_BrowserStateRequestEvent: Got scroll info: {scroll_info["result"]}')

		try:
			# Fast path for empty pages
			if not_a_meaningful_website:
				self.logger.debug(f'⚡ Skipping BuildDOMTree for empty target: {page_url}')
				self.logger.debug(f'📸 Not taking screenshot for empty page: {page_url} (non-http/https URL)')

				# Create minimal DOM state
				content = SerializedDOMState(_root=None, selector_map={})

				# Skip screenshot for empty pages
				screenshot_b64 = None

				# Try to get page info from CDP, fall back to defaults if unavailable
				try:
					page_info = await self._get_page_info()
				except Exception as e:
					self.logger.debug(f'Failed to get page info from CDP for empty page: {e}, using fallback')
					# Use default viewport dimensions
					viewport = self.browser_session.browser_profile.viewport or {'width': 1280, 'height': 720}
					page_info = PageInfo(
						viewport_width=viewport['width'],
						viewport_height=viewport['height'],
						page_width=viewport['width'],
						page_height=viewport['height'],
						scroll_x=0,
						scroll_y=0,
						pixels_above=0,
						pixels_below=0,
						pixels_left=0,
						pixels_right=0,
					)

				return BrowserStateSummary(
					dom_state=content,
					url=page_url,
					title='Empty Tab',
					tabs=tabs_info,
					screenshot=screenshot_b64,
					page_info=page_info,
					pixels_above=0,
					pixels_below=0,
					browser_errors=[],
					is_pdf_viewer=False,
					recent_events=self._get_recent_events_str() if event.include_recent_events else None,
				)

			# Execute DOM building and screenshot capture in parallel
			dom_task = None
			screenshot_task = None

			# Start DOM building task if requested
			if event.include_dom:
				self.logger.debug('🔍 DOMWatchdog.on_BrowserStateRequestEvent: 🌳 Starting DOM tree build task...')

				previous_state = (
					self.browser_session._cached_browser_state_summary.dom_state
					if self.browser_session._cached_browser_state_summary
					else None
				)

				dom_task = asyncio.create_task(self._build_dom_tree_without_highlights(previous_state))

			# Start clean screenshot task if requested (without JS highlights)
			if event.include_screenshot:
				self.logger.debug('🔍 DOMWatchdog.on_BrowserStateRequestEvent: 📸 Starting clean screenshot task...')
				screenshot_task = asyncio.create_task(self._capture_clean_screenshot())

			# Wait for both tasks to complete
			content = None
			screenshot_b64 = None

			if dom_task:
				try:
					content = await dom_task
					self.logger.debug('🔍 DOMWatchdog.on_BrowserStateRequestEvent: ✅ DOM tree build completed')
				except Exception as e:
					self.logger.warning(f'🔍 DOMWatchdog.on_BrowserStateRequestEvent: DOM build failed: {e}, using minimal state')
					content = SerializedDOMState(_root=None, selector_map={})
			else:
				content = SerializedDOMState(_root=None, selector_map={})

			if screenshot_task:
				try:
					screenshot_b64 = await screenshot_task
					self.logger.debug('🔍 DOMWatchdog.on_BrowserStateRequestEvent: ✅ Clean screenshot captured')
				except Exception as e:
					self.logger.warning(f'🔍 DOMWatchdog.on_BrowserStateRequestEvent: Clean screenshot failed: {e}')
					screenshot_b64 = None

			# Apply Python-based highlighting if both DOM and screenshot are available
			if screenshot_b64 and content and content.selector_map and self.browser_session.browser_profile.highlight_elements:
				try:
					self.logger.debug('🔍 DOMWatchdog.on_BrowserStateRequestEvent: 🎨 Applying Python-based highlighting...')
					from browser_use.browser.python_highlights import create_highlighted_screenshot_async

					# Get CDP session for viewport info
					cdp_session = await self.browser_session.get_or_create_cdp_session()
					start = time.time()
					screenshot_b64 = await create_highlighted_screenshot_async(
						screenshot_b64,
						content.selector_map,
						cdp_session,
						self.browser_session.browser_profile.filter_highlight_ids,
					)
					self.logger.debug(
						f'🔍 DOMWatchdog.on_BrowserStateRequestEvent: ✅ Applied highlights to {len(content.selector_map)} elements in {time.time() - start:.2f}s'
					)
				except Exception as e:
					self.logger.warning(f'🔍 DOMWatchdog.on_BrowserStateRequestEvent: Python highlighting failed: {e}')

			# Add browser-side highlights for user visibility
			if content and content.selector_map and self.browser_session.browser_profile.dom_highlight_elements:
				try:
					self.logger.debug('🔍 DOMWatchdog.on_BrowserStateRequestEvent: 🎨 Adding browser-side highlights...')
					await self.browser_session.add_highlights(content.selector_map)
					self.logger.debug(
						f'🔍 DOMWatchdog.on_BrowserStateRequestEvent: ✅ Added browser highlights for {len(content.selector_map)} elements'
					)
				except Exception as e:
					self.logger.warning(f'🔍 DOMWatchdog.on_BrowserStateRequestEvent: Browser highlighting failed: {e}')

			# Ensure we have valid content
			if not content:
				content = SerializedDOMState(_root=None, selector_map={})

			# Tabs info already fetched at the beginning

			# Get target title safely
			try:
				self.logger.debug('🔍 DOMWatchdog.on_BrowserStateRequestEvent: Getting page title...')
				title = await asyncio.wait_for(self.browser_session.get_current_page_title(), timeout=1.0)
				self.logger.debug(f'🔍 DOMWatchdog.on_BrowserStateRequestEvent: Got title: {title}')
			except Exception as e:
				self.logger.debug(f'🔍 DOMWatchdog.on_BrowserStateRequestEvent: Failed to get title: {e}')
				title = 'Page'

			# Get comprehensive page info from CDP with timeout
			try:
				self.logger.debug('🔍 DOMWatchdog.on_BrowserStateRequestEvent: Getting page info from CDP...')
				page_info = await asyncio.wait_for(self._get_page_info(), timeout=1.0)
				self.logger.debug(f'🔍 DOMWatchdog.on_BrowserStateRequestEvent: Got page info from CDP: {page_info}')
			except Exception as e:
				self.logger.debug(
					f'🔍 DOMWatchdog.on_BrowserStateRequestEvent: Failed to get page info from CDP: {e}, using fallback'
				)
				# Fallback to default viewport dimensions
				viewport = self.browser_session.browser_profile.viewport or {'width': 1280, 'height': 720}
				page_info = PageInfo(
					viewport_width=viewport['width'],
					viewport_height=viewport['height'],
					page_width=viewport['width'],
					page_height=viewport['height'],
					scroll_x=0,
					scroll_y=0,
					pixels_above=0,
					pixels_below=0,
					pixels_left=0,
					pixels_right=0,
				)

			# Check for PDF viewer
			is_pdf_viewer = page_url.endswith('.pdf') or '/pdf/' in page_url

			# Build and cache the browser state summary
			if screenshot_b64:
				self.logger.debug(
					f'🔍 DOMWatchdog.on_BrowserStateRequestEvent: 📸 Creating BrowserStateSummary with screenshot, length: {len(screenshot_b64)}'
				)
			else:
				self.logger.debug(
					'🔍 DOMWatchdog.on_BrowserStateRequestEvent: 📸 Creating BrowserStateSummary WITHOUT screenshot'
				)

			browser_state = BrowserStateSummary(
				dom_state=content,
				url=page_url,
				title=title,
				tabs=tabs_info,
				screenshot=screenshot_b64,
				page_info=page_info,
				pixels_above=0,
				pixels_below=0,
				browser_errors=[],
				is_pdf_viewer=is_pdf_viewer,
				recent_events=self._get_recent_events_str() if event.include_recent_events else None,
			)

			# Cache the state
			self.browser_session._cached_browser_state_summary = browser_state

			self.logger.debug('🔍 DOMWatchdog.on_BrowserStateRequestEvent: ✅ COMPLETED - Returning browser state')
			return browser_state

		except Exception as e:
			self.logger.error(f'Failed to get browser state: {e}')

			# Return minimal recovery state
			return BrowserStateSummary(
				dom_state=SerializedDOMState(_root=None, selector_map={}),
				url=page_url if 'page_url' in locals() else '',
				title='Error',
				tabs=[],
				screenshot=None,
				page_info=PageInfo(
					viewport_width=1280,
					viewport_height=720,
					page_width=1280,
					page_height=720,
					scroll_x=0,
					scroll_y=0,
					pixels_above=0,
					pixels_below=0,
					pixels_left=0,
					pixels_right=0,
				),
				pixels_above=0,
				pixels_below=0,
				browser_errors=[str(e)],
				is_pdf_viewer=False,
				recent_events=None,
			)

	@time_execution_async('build_dom_tree_without_highlights')
	@observe_debug(ignore_input=True, ignore_output=True, name='build_dom_tree_without_highlights')
	async def _build_dom_tree_without_highlights(self, previous_state: SerializedDOMState | None = None) -> SerializedDOMState:
		"""Build DOM tree without injecting JavaScript highlights (for parallel execution)."""
		try:
			self.logger.debug('🔍 DOMWatchdog._build_dom_tree_without_highlights: STARTING DOM tree build')

			# Create or reuse DOM service
			if self._dom_service is None:
				self._dom_service = DomService(
					browser_session=self.browser_session,
					logger=self.logger,
					cross_origin_iframes=self.browser_session.browser_profile.cross_origin_iframes,
					paint_order_filtering=self.browser_session.browser_profile.paint_order_filtering,
					max_iframes=self.browser_session.browser_profile.max_iframes,
					max_iframe_depth=self.browser_session.browser_profile.max_iframe_depth,
				)

			# Get serialized DOM tree using the service
			self.logger.debug('🔍 DOMWatchdog._build_dom_tree_without_highlights: Calling DomService.get_serialized_dom_tree...')
			start = time.time()
			self.current_dom_state, self.enhanced_dom_tree, timing_info = await self._dom_service.get_serialized_dom_tree(
				previous_cached_state=previous_state,
			)
			end = time.time()
			self.logger.debug(
				'🔍 DOMWatchdog._build_dom_tree_without_highlights: ✅ DomService.get_serialized_dom_tree completed'
			)

			self.logger.debug(f'Time taken to get DOM tree: {end - start} seconds')
			self.logger.debug(f'Timing breakdown: {timing_info}')

			# Update selector map for other watchdogs
			self.logger.debug('🔍 DOMWatchdog._build_dom_tree_without_highlights: Updating selector maps...')
			self.selector_map = self.current_dom_state.selector_map
			# Update BrowserSession's cached selector map
			if self.browser_session:
				self.browser_session.update_cached_selector_map(self.selector_map)
			self.logger.debug(
				f'🔍 DOMWatchdog._build_dom_tree_without_highlights: ✅ Selector maps updated, {len(self.selector_map)} elements'
			)

			# Skip JavaScript highlighting injection - Python highlighting will be applied later
			self.logger.debug('🔍 DOMWatchdog._build_dom_tree_without_highlights: ✅ COMPLETED DOM tree build (no JS highlights)')
			return self.current_dom_state

		except Exception as e:
			self.logger.error(f'Failed to build DOM tree without highlights: {e}')
			self.event_bus.dispatch(
				BrowserErrorEvent(
					error_type='DOMBuildFailed',
					message=str(e),
				)
			)
			raise

	@time_execution_async('capture_clean_screenshot')
	@observe_debug(ignore_input=True, ignore_output=True, name='capture_clean_screenshot')
	async def _capture_clean_screenshot(self) -> str:
		"""Capture a clean screenshot without JavaScript highlights."""
		try:
			self.logger.debug('🔍 DOMWatchdog._capture_clean_screenshot: Capturing clean screenshot...')

			# Ensure we have a focused CDP session
			assert self.browser_session.agent_focus is not None, 'No current target ID'
			await self.browser_session.get_or_create_cdp_session(target_id=self.browser_session.agent_focus.target_id, focus=True)

			# Check if handler is registered
			handlers = self.event_bus.handlers.get('ScreenshotEvent', [])
			handler_names = [getattr(h, '__name__', str(h)) for h in handlers]
			self.logger.debug(f'📸 ScreenshotEvent handlers registered: {len(handlers)} - {handler_names}')

			screenshot_event = self.event_bus.dispatch(ScreenshotEvent(full_page=False))
			self.logger.debug('📸 Dispatched ScreenshotEvent, waiting for event to complete...')

			# Wait for the event itself to complete (this waits for all handlers)
			await screenshot_event

			# Get the single handler result
			screenshot_b64 = await screenshot_event.event_result(raise_if_any=True, raise_if_none=True)
			if screenshot_b64 is None:
				raise RuntimeError('Screenshot handler returned None')
			self.logger.debug('🔍 DOMWatchdog._capture_clean_screenshot: ✅ Clean screenshot captured successfully')
			return str(screenshot_b64)

		except TimeoutError:
			self.logger.warning('📸 Clean screenshot timed out after 6 seconds - no handler registered or slow page?')
			raise
		except Exception as e:
			self.logger.warning(f'📸 Clean screenshot failed: {type(e).__name__}: {e}')
			raise

	async def _wait_for_stable_network(self):
		"""Wait for page stability - simplified for CDP-only branch."""
		start_time = time.time()

		# Apply minimum wait time first (let page settle)
		min_wait = self.browser_session.browser_profile.minimum_wait_page_load_time
		if min_wait > 0:
			self.logger.debug(f'⏳ Minimum wait: {min_wait}s')
			await asyncio.sleep(min_wait)

		# Apply network idle wait time (for dynamic content like iframes)
		network_idle_wait = self.browser_session.browser_profile.wait_for_network_idle_page_load_time
		if network_idle_wait > 0:
			self.logger.debug(f'⏳ Network idle wait: {network_idle_wait}s')
			await asyncio.sleep(network_idle_wait)

		elapsed = time.time() - start_time
		self.logger.debug(f'✅ Page stability wait completed in {elapsed:.2f}s')

	async def _get_page_info(self) -> 'PageInfo':
		"""Get comprehensive page information using a single CDP call.

		TODO: should we make this an event as well?

		Returns:
			PageInfo with all viewport, page dimensions, and scroll information
		"""

		from browser_use.browser.views import PageInfo

		# Get CDP session for the current target
		if not self.browser_session.agent_focus:
			raise RuntimeError('No active CDP session - browser may not be connected yet')

		cdp_session = await self.browser_session.get_or_create_cdp_session(
			target_id=self.browser_session.agent_focus.target_id, focus=True
		)

		# Get layout metrics which includes all the information we need
		metrics = await asyncio.wait_for(
			cdp_session.cdp_client.send.Page.getLayoutMetrics(session_id=cdp_session.session_id), timeout=10.0
		)

		# Extract different viewport types
		layout_viewport = metrics.get('layoutViewport', {})
		visual_viewport = metrics.get('visualViewport', {})
		css_visual_viewport = metrics.get('cssVisualViewport', {})
		css_layout_viewport = metrics.get('cssLayoutViewport', {})
		content_size = metrics.get('contentSize', {})

		# Calculate device pixel ratio to convert between device pixels and CSS pixels
		# This matches the approach in dom/service.py _get_viewport_ratio method
		css_width = css_visual_viewport.get('clientWidth', css_layout_viewport.get('clientWidth', 1280.0))
		device_width = visual_viewport.get('clientWidth', css_width)
		device_pixel_ratio = device_width / css_width if css_width > 0 else 1.0

		# For viewport dimensions, use CSS pixels (what JavaScript sees)
		# Prioritize CSS layout viewport, then fall back to layout viewport
		viewport_width = int(css_layout_viewport.get('clientWidth') or layout_viewport.get('clientWidth', 1280))
		viewport_height = int(css_layout_viewport.get('clientHeight') or layout_viewport.get('clientHeight', 720))

		# For total page dimensions, content size is typically in device pixels, so convert to CSS pixels
		# by dividing by device pixel ratio
		raw_page_width = content_size.get('width', viewport_width * device_pixel_ratio)
		raw_page_height = content_size.get('height', viewport_height * device_pixel_ratio)
		page_width = int(raw_page_width / device_pixel_ratio)
		page_height = int(raw_page_height / device_pixel_ratio)

		# For scroll position, use CSS visual viewport if available, otherwise CSS layout viewport
		# These should already be in CSS pixels
		scroll_x = int(css_visual_viewport.get('pageX') or css_layout_viewport.get('pageX', 0))
		scroll_y = int(css_visual_viewport.get('pageY') or css_layout_viewport.get('pageY', 0))

		# Calculate scroll information - pixels that are above/below/left/right of current viewport
		pixels_above = scroll_y
		pixels_below = max(0, page_height - viewport_height - scroll_y)
		pixels_left = scroll_x
		pixels_right = max(0, page_width - viewport_width - scroll_x)

		page_info = PageInfo(
			viewport_width=viewport_width,
			viewport_height=viewport_height,
			page_width=page_width,
			page_height=page_height,
			scroll_x=scroll_x,
			scroll_y=scroll_y,
			pixels_above=pixels_above,
			pixels_below=pixels_below,
			pixels_left=pixels_left,
			pixels_right=pixels_right,
		)

		return page_info

	# ========== Public Helper Methods ==========

	async def get_element_by_index(self, index: int) -> EnhancedDOMTreeNode | None:
		"""Get DOM element by index from cached selector map.

		Builds DOM if not cached.

		Returns:
			EnhancedDOMTreeNode or None if index not found
		"""
		if not self.selector_map:
			# Build DOM if not cached
			await self._build_dom_tree_without_highlights()

		return self.selector_map.get(index) if self.selector_map else None

	def clear_cache(self) -> None:
		"""Clear cached DOM state to force rebuild on next access."""
		self.selector_map = None
		self.current_dom_state = None
		self.enhanced_dom_tree = None
		# Keep the DOM service instance to reuse its CDP client connection

	def is_file_input(self, element: EnhancedDOMTreeNode) -> bool:
		"""Check if element is a file input."""
		return element.node_name.upper() == 'INPUT' and element.attributes.get('type', '').lower() == 'file'

	@staticmethod
	def is_element_visible_according_to_all_parents(node: EnhancedDOMTreeNode, html_frames: list[EnhancedDOMTreeNode]) -> bool:
		"""Check if the element is visible according to all its parent HTML frames.

		Delegates to the DomService static method.
		"""
		return DomService.is_element_visible_according_to_all_parents(node, html_frames)

	async def __aexit__(self, exc_type, exc_value, traceback):
		"""Clean up DOM service on exit."""
		if self._dom_service:
			await self._dom_service.__aexit__(exc_type, exc_value, traceback)
			self._dom_service = None

	def __del__(self):
		"""Clean up DOM service on deletion."""
		super().__del__()
		# DOM service will clean up its own CDP client
		self._dom_service = None
