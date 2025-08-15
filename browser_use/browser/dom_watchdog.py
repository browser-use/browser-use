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

		self.logger.debug('💉 Injecting DOM Service init script to track event listeners added to DOM elements by JS...')

		init_script = """
			// check to make sure we're not inside the PDF viewer
			window.isPdfViewer = !!document?.body?.querySelector('body > embed[type="application/pdf"][width="100%"]')
			if (!window.isPdfViewer) {

				// Permissions
				const originalQuery = window.navigator.permissions.query;
				window.navigator.permissions.query = (parameters) => (
					parameters.name === 'notifications' ?
						Promise.resolve({ state: Notification.permission }) :
						originalQuery(parameters)
				);
				(() => {
					if (window._eventListenerTrackerInitialized) return;
					window._eventListenerTrackerInitialized = true;

					const originalAddEventListener = EventTarget.prototype.addEventListener;
					const eventListenersMap = new WeakMap();

					EventTarget.prototype.addEventListener = function(type, listener, options) {
						if (typeof listener === "function") {
							let listeners = eventListenersMap.get(this);
							if (!listeners) {
								listeners = [];
								eventListenersMap.set(this, listeners);
							}

							listeners.push({
								type,
								listener,
								listenerPreview: listener.toString().slice(0, 100),
								options
							});
						}

						return originalAddEventListener.call(this, type, listener, options);
					};

					window.getEventListenersForNode = (node) => {
						const listeners = eventListenersMap.get(node) || [];
						return listeners.map(({ type, listenerPreview, options }) => ({
							type,
							listenerPreview,
							options
						}));
					};
				})();
			}
		"""

		# Try to inject the script, but don't fail if the Page domain isn't ready yet
		# This can happen when a new tab is created and the CDP session isn't fully attached
		try:
			await self.browser_session._cdp_add_init_script(init_script)
		except Exception as e:
			if "'Page.addScriptToEvaluateOnNewDocument' wasn't found" in str(e):
				self.logger.debug(f'Page domain not ready for new tab, skipping init script injection: {e}')
				# The script will be injected when the page actually navigates
			else:
				# Re-raise other errors
				raise

	def _get_recent_events_csv(self, limit: int = 10) -> str | None:
		"""Get the most recent event names from the event bus as CSV.

		Args:
			limit: Maximum number of recent events to include

		Returns:
			CSV string of recent event names or None if not available
		"""
		try:
			# Get all events from history, sorted by creation time (most recent first)
			all_events = sorted(
				self.browser_session.event_bus.event_history.values(), key=lambda e: e.event_created_at.timestamp(), reverse=True
			)

			# Take the most recent events and get their names
			recent_event_names = [event.event_type for event in all_events[:limit]]

			if recent_event_names:
				return ', '.join(recent_event_names)
		except Exception as e:
			self.logger.debug(f'Failed to get recent events: {e}')

		return None

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
				f'📍 Current page URL: {page_url}, target_id: {self.browser_session.agent_focus.target_id}, session_id: {self.browser_session.agent_focus.session_id}'
			)
		else:
			self.logger.debug(f'📍 Current page URL: {page_url}, no cdp_session attached')

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
				self.logger.info(f'📸 Not taking screenshot for empty page: {page_url} (non-http/https URL)')

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
					recent_events=self._get_recent_events_csv() if event.include_recent_events else None,
				)

			# Normal path: Build DOM tree if requested
			if event.include_dom:
				self.logger.debug('🔍 DOMWatchdog.on_BrowserStateRequestEvent: 🌳 Building DOM tree...')

				# Build the DOM directly using the internal method
				previous_state = (
					self.browser_session._cached_browser_state_summary.dom_state
					if self.browser_session._cached_browser_state_summary
					else None
				)

				try:
					# Call the DOM building method directly
					self.logger.debug('🔍 DOMWatchdog.on_BrowserStateRequestEvent: Starting _build_dom_tree...')
					content = await self._build_dom_tree(previous_state)
					self.logger.debug('🔍 DOMWatchdog.on_BrowserStateRequestEvent: ✅ _build_dom_tree completed')
				except Exception as e:
					self.logger.warning(f'🔍 DOMWatchdog.on_BrowserStateRequestEvent: DOM build failed: {e}, using minimal state')
					content = SerializedDOMState(_root=None, selector_map={})

				if not content:
					# Fallback to minimal DOM state
					self.logger.warning('DOM build returned no content, using minimal state')
					content = SerializedDOMState(_root=None, selector_map={})
			else:
				# Skip DOM building if not requested
				content = SerializedDOMState(_root=None, selector_map={})

			# re-focus top-level page session context
			assert self.browser_session.agent_focus is not None, 'No current target ID'
			await self.browser_session.get_or_create_cdp_session(target_id=self.browser_session.agent_focus.target_id, focus=True)

			# Get screenshot if requested
			screenshot_b64 = None
			if event.include_screenshot:
				self.logger.debug(
					f'🔍 DOMWatchdog.on_BrowserStateRequestEvent: 📸 DOM watchdog requesting screenshot, include_screenshot={event.include_screenshot}'
				)
				try:
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
				except TimeoutError:
					self.logger.warning('📸 Screenshot timed out after 6 seconds - no handler registered or slow page?')

				except Exception as e:
					self.logger.warning(f'📸 Screenshot failed: {type(e).__name__}: {e}')
			else:
				self.logger.debug(f'📸 Skipping screenshot, include_screenshot={event.include_screenshot}')

			# Tabs info already fetched at the beginning

			# Get target title safely
			try:
				self.logger.debug('🔍 DOMWatchdog.on_BrowserStateRequestEvent: Getting page title...')
				title = await asyncio.wait_for(self.browser_session.get_current_page_title(), timeout=2.0)
				self.logger.debug(f'🔍 DOMWatchdog.on_BrowserStateRequestEvent: Got title: {title}')
			except Exception as e:
				self.logger.debug(f'🔍 DOMWatchdog.on_BrowserStateRequestEvent: Failed to get title: {e}')
				title = 'Page'

			# Get comprehensive page info from CDP
			try:
				self.logger.debug('🔍 DOMWatchdog.on_BrowserStateRequestEvent: Getting page info from CDP...')
				page_info = await self._get_page_info()
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
				recent_events=self._get_recent_events_csv() if event.include_recent_events else None,
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

	async def _build_dom_tree(self, previous_state: SerializedDOMState | None = None) -> SerializedDOMState:
		"""Internal method to build and serialize DOM tree.

		This is the actual implementation that does the work, called by both
		on_BrowserStateRequestEvent.

		Returns:
			SerializedDOMState with serialized DOM and selector map
		"""
		try:
			self.logger.debug('🔍 DOMWatchdog._build_dom_tree: STARTING DOM tree build')
			# Remove any existing highlights before building new DOM
			try:
				self.logger.debug('🔍 DOMWatchdog._build_dom_tree: Removing existing highlights...')
				await self.browser_session.remove_highlights()
				# self.logger.debug('🔍 DOMWatchdog._build_dom_tree: ✅ Highlights removed')
			except Exception as e:
				self.logger.debug(f'🔍 DOMWatchdog._build_dom_tree: Failed to remove existing highlights: {e}')

			# Create or reuse DOM service
			if self._dom_service is None:
				# self.logger.debug('🔍 DOMWatchdog._build_dom_tree: Creating DomService...')
				self._dom_service = DomService(browser_session=self.browser_session, logger=self.logger)
				# self.logger.debug('🔍 DOMWatchdog._build_dom_tree: ✅ DomService created')
			# else:
			# self.logger.debug('🔍 DOMWatchdog._build_dom_tree: Reusing existing DomService')

			# Get serialized DOM tree using the service
			self.logger.debug('🔍 DOMWatchdog._build_dom_tree: Calling DomService.get_serialized_dom_tree...')
			start = time.time()
			self.current_dom_state, self.enhanced_dom_tree, timing_info = await self._dom_service.get_serialized_dom_tree(
				previous_cached_state=previous_state,
			)
			end = time.time()
			self.logger.debug('🔍 DOMWatchdog._build_dom_tree: ✅ DomService.get_serialized_dom_tree completed')

			self.logger.debug(f'Time taken to get DOM tree: {end - start} seconds')
			self.logger.debug(f'Timing breakdown: {timing_info}')

			# Update selector map for other watchdogs
			self.logger.debug('🔍 DOMWatchdog._build_dom_tree: Updating selector maps...')
			self.selector_map = self.current_dom_state.selector_map
			# Update BrowserSession's cached selector map
			if self.browser_session:
				self.browser_session.update_cached_selector_map(self.selector_map)
			self.logger.debug(f'🔍 DOMWatchdog._build_dom_tree: ✅ Selector maps updated, {len(self.selector_map)} elements')

			# Inject highlighting for visual feedback if we have elements
			if self.selector_map and self._dom_service:
				try:
					self.logger.debug('🔍 DOMWatchdog._build_dom_tree: Injecting highlighting script...')
					from browser_use.dom.debug.highlights import inject_highlighting_script

					await inject_highlighting_script(self._dom_service, self.selector_map)
					self.logger.debug(
						f'🔍 DOMWatchdog._build_dom_tree: ✅ Injected highlighting for {len(self.selector_map)} elements'
					)
				except Exception as e:
					self.logger.debug(f'🔍 DOMWatchdog._build_dom_tree: Failed to inject highlighting: {e}')

			self.logger.debug('🔍 DOMWatchdog._build_dom_tree: ✅ COMPLETED DOM tree build')
			return self.current_dom_state

		except Exception as e:
			self.logger.error(f'Failed to build DOM tree: {e}')
			self.event_bus.dispatch(
				BrowserErrorEvent(
					error_type='DOMBuildFailed',
					message=str(e),
				)
			)
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
			await self._build_dom_tree()

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
