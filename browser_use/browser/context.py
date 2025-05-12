"""
Playwright browser on steroids.
"""

import asyncio
import base64
import gc
import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

import anyio
from playwright._impl._errors import TimeoutError
from playwright.async_api import Browser as PlaywrightBrowser
from playwright.async_api import (
	BrowserContext as PlaywrightBrowserContext,
)
from playwright.async_api import (
	ElementHandle,
	FrameLocator,
	Page,
)
from pydantic import BaseModel, ConfigDict, Field

from browser_use.browser.views import (
	BrowserError,
	BrowserState,
	TabInfo,
	URLNotAllowedError,
)
from browser_use.dom.clickable_element_processor.service import ClickableElementProcessor
from browser_use.dom.service import DomService
from browser_use.dom.views import DOMElementNode, SelectorMap
from browser_use.utils import time_execution_async, time_execution_sync

if TYPE_CHECKING:
	from browser_use.browser.browser import Browser

logger = logging.getLogger(__name__)

import platform

BROWSER_NAVBAR_HEIGHT = {
	'windows': 85,
	'darwin': 80,
	'linux': 90,
}.get(platform.system().lower(), 85)


class BrowserContextConfig(BaseModel):
	"""
	Configuration for the BrowserContext.

	Default values:
	    cookies_file: None
	        Path to cookies file for persistence

		disable_security: False
			Disable browser security features (dangerous, but cross-origin iframe support requires it)

	    minimum_wait_page_load_time: 0.5
	        Minimum time to wait before getting page state for LLM input

		wait_for_network_idle_page_load_time: 1.0
			Time to wait for network requests to finish before getting page state.
			Lower values may result in incomplete page loads.

	    maximum_wait_page_load_time: 5.0
	        Maximum time to wait for page load before proceeding anyway

	    wait_between_actions: 1.0
	        Time to wait between multiple per step actions

	    window_width: 1280
	    window_height: 1100
	        Default browser window dimensions

	    no_viewport: True
	        When True (default), the browser window size determines the viewport.
	        When False, forces a fixed viewport size using window_width and window_height. (constraint of the rendered content to a smaller area than the default of the entire window size)

	    save_recording_path: None
	        Path to save video recordings

	    save_downloads_path: None
	        Path to save downloads to

	    trace_path: None
	        Path to save trace files. It will auto name the file with the TRACE_PATH/{context_id}.zip

	    locale: None
	        Specify user locale, for example en-GB, de-DE, etc. Locale will affect navigator.language value, Accept-Language request header value as well as number and date formatting rules. If not provided, defaults to the system default locale.

	    user_agent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.102 Safari/537.36'
	        custom user agent to use.

	    highlight_elements: True
	        Highlight elements in the DOM on the screen

	    viewport_expansion: 0
	        Viewport expansion in pixels. This amount will increase the number of elements which are included in the state what the LLM will see. If set to -1, all elements will be included (this leads to high token usage). If set to 0, only the elements which are visible in the viewport will be included.

	    allowed_domains: None
	        List of allowed domains that can be accessed. If None, all domains are allowed.
	        Example: ['example.com', 'api.example.com']

	    include_dynamic_attributes: bool = True
	        Include dynamic attributes in the CSS selector. If you want to reuse the css_selectors, it might be better to set this to False.

		  http_credentials: None
	  Dictionary with HTTP basic authentication credentials for corporate intranets (only supports one set of credentials for all URLs at the moment), e.g.
	  {"username": "bill", "password": "pa55w0rd"}

	    is_mobile: None
	        Whether the meta viewport tag is taken into account and touch events are enabled.

	    has_touch: None
	        Whether to enable touch events in the browser.

	    geolocation: None
	        Geolocation to be used in the browser context. Example: {'latitude': 59.95, 'longitude': 30.31667}

	    permissions: ['clipboard-read', 'clipboard-write']
	        Browser permissions to grant. See full list here: https://playwright.dev/python/docs/api/class-browsercontext#browser-context-grant-permissions

	    timezone_id: None
	        Changes the timezone of the browser. Example: 'Europe/Berlin'

		force_new_context: False
			Forces a new browser context to be created. Useful when running locally with branded browser (e.g Chrome, Edge) and setting a custom config.
	"""

	model_config = ConfigDict(
		arbitrary_types_allowed=True,
		extra='ignore',
		populate_by_name=True,
		from_attributes=True,
		validate_assignment=True,
		revalidate_instances='subclass-instances',
	)

	cookies_file: str | None = None
	minimum_wait_page_load_time: float = 0.25
	wait_for_network_idle_page_load_time: float = 0.5
	maximum_wait_page_load_time: float = 5
	wait_between_actions: float = 0.5

	disable_security: bool = False  # disable_security=True is dangerous as any malicious URL visited could embed an iframe for the user's bank, and use their cookies to steal money

	window_width: int = 1280
	window_height: int = 1100
	no_viewport: bool = True  # True is the default for headful mode - browser window size determines viewport

	save_recording_path: str | None = None
	save_downloads_path: str | None = None
	save_har_path: str | None = None
	trace_path: str | None = None
	locale: str | None = None
	user_agent: str | None = None

	highlight_elements: bool = True
	viewport_expansion: int = 0
	allowed_domains: list[str] | None = None
	include_dynamic_attributes: bool = True
	http_credentials: dict[str, str] | None = None

	keep_alive: bool = Field(default=False, alias='_force_keep_context_alive')  # used to be called _force_keep_context_alive
	is_mobile: bool | None = None
	has_touch: bool | None = None
	geolocation: dict | None = None
	permissions: list[str] = Field(
		default_factory=lambda: [
			'clipboard-read',
			'clipboard-write',
		]
	)
	timezone_id: str | None = None

	force_new_context: bool = False


@dataclass
class CachedStateClickableElementsHashes:
	"""
	Clickable elements hashes for the last state
	"""

	url: str
	hashes: set[str]


class BrowserSession:
	def __init__(self, context: PlaywrightBrowserContext, cached_state: BrowserState | None = None):
		self.context = context
		self.cached_state = cached_state

		self.cached_state_clickable_elements_hashes: CachedStateClickableElementsHashes | None = None


@dataclass
class BrowserContextState:
	"""
	State of the browser context
	"""

	target_id: str | None = None  # CDP target ID


class BrowserContext:
	def __init__(
		self,
		browser: 'Browser',
		config: BrowserContextConfig | None = None,
		state: BrowserContextState | None = None,
	):
		self.context_id = str(uuid.uuid4())

		self.config = config or BrowserContextConfig(**(browser.config.model_dump() if browser.config else {}))
		self.browser = browser

		self.state = state or BrowserContextState()

		# Initialize these as None - they'll be set up when needed
		self.session: BrowserSession | None = None

		# Tab references - separate concepts for agent intent and browser state
		self.agent_current_page: Page | None = None  # The tab the agent intends to interact with
		self.human_current_page: Page | None = None  # The tab currently shown in the browser UI

	async def __aenter__(self):
		"""Async context manager entry"""
		await self._initialize_session()
		return self

	async def __aexit__(self, exc_type, exc_val, exc_tb):
		"""Async context manager exit"""
		await self.close()

	@time_execution_async('--close')
	async def close(self):
		"""Close the browser instance"""

		try:
			if self.session is None:
				return

			# Then remove CDP protocol listeners
			if self._page_event_handler and self.session.context:
				try:
					# This actually sends a CDP command to unsubscribe
					self.session.context.remove_listener('page', self._page_event_handler)
				except Exception as e:
					logger.debug(f'Failed to remove CDP listener: {e}')
				self._page_event_handler = None

			await self.save_cookies()

			if self.config.trace_path:
				try:
					await self.session.context.tracing.stop(path=os.path.join(self.config.trace_path, f'{self.context_id}.zip'))
				except Exception as e:
					logger.debug(f'Failed to stop tracing: {e}')

			# This is crucial - it closes the CDP connection
			if not self.config.keep_alive:
				logger.debug('Closing browser context')
				try:
					await self.session.context.close()
				except Exception as e:
					logger.debug(f'Failed to close context: {e}')

		finally:
			# Dereference everything
			self.agent_current_page = None
			self.human_current_page = None
			self.session = None
			self._page_event_handler = None

	def __del__(self):
		"""Cleanup when object is destroyed"""
		if not self.config.keep_alive and self.session is not None:
			logger.debug('BrowserContext was not properly closed before destruction')
			try:
				# Use sync Playwright method for force cleanup
				if hasattr(self.session.context, '_impl_obj'):
					asyncio.run(self.session.context._impl_obj.close())

				self.session = None
				self.agent_current_page = None
				self.human_current_page = None
				gc.collect()
			except Exception as e:
				logger.warning(f'Failed to force close browser context: {e}')

	@time_execution_async('--initialize_session')
	async def _initialize_session(self):
		"""Initialize the browser session"""
		logger.debug(f'🌎  Initializing new browser context with id: {self.context_id}')

		playwright_browser = await self.browser.get_playwright_browser()
		context = await self._create_context(playwright_browser)
		self._page_event_handler = None

		# auto-attach the foregrounding-detection listener to all new pages opened
		context.on('page', self._add_tab_foregrounding_listener)

		# Get or create a page to use
		pages = context.pages

		self.session = BrowserSession(
			context=context,
			cached_state=None,
		)

		current_page = None
		if self.browser.config.cdp_url:
			# If we have a saved target ID, try to find and activate it
			if self.state.target_id:
				targets = await self._get_cdp_targets()
				for target in targets:
					if target['targetId'] == self.state.target_id:
						# Find matching page by URL
						for page in pages:
							if page.url == target['url']:
								current_page = page
								break
						break

		# If no target ID or couldn't find it, use existing page or create new
		if not current_page:
			if (
				pages
				and pages[0].url
				and not pages[0].url.startswith('chrome://')  # skip chrome internal pages e.g. settings, history, etc
				and not pages[0].url.startswith('chrome-extension://')  # skip hidden extension background pages
			):
				current_page = pages[0]
				logger.debug('🔍  Using existing page: %s', current_page.url)
			else:
				current_page = await context.new_page()
				await current_page.goto('about:blank')
				logger.debug('🆕  Created new page: %s', current_page.url)

			# Get target ID for the active page
			if self.browser.config.cdp_url:
				targets = await self._get_cdp_targets()
				for target in targets:
					if target['url'] == current_page.url:
						self.state.target_id = target['targetId']
						break

		# Bring page to front
		logger.debug('🫨  Bringing tab to front: %s', current_page)
		await current_page.bring_to_front()
		await current_page.wait_for_load_state('load')

		# Set the viewport size for the active page
		await self.set_viewport_size(current_page)

		# Initialize both tab references to the same page initially
		self.agent_current_page = current_page
		self.human_current_page = current_page

		# Set up visibility listeners for all existing tabs
		for page in pages:
			if not page.url.startswith('chrome-extension://') and not page.url.startswith('chrome://') and not page.is_closed():
				await self._add_tab_foregrounding_listener(page)
				# logger.debug(f'👁️  Added visibility listener to existing tab: {page.url}')

		return self.session

	async def _add_tab_foregrounding_listener(self, page: Page):
		"""
		Attaches listeners that detect when the human steals active tab focus away from the agent.

		Uses a combination of:
		- visibilitychange events
		- window focus/blur events
		- pointermove events

		This multi-method approach provides more reliable detection across browsers.

		TODO: pester the playwright team to add a new event that fires when a headful tab is focused.
		OR implement a browser-use chrome extension that acts as a bridge to the chrome.tabs API.

		        - https://github.com/microsoft/playwright/issues/1290
		        - https://github.com/microsoft/playwright/issues/2286
		        - https://github.com/microsoft/playwright/issues/3570
		        - https://github.com/microsoft/playwright/issues/13989
		"""

		def trunc(s, max_len=None):
			s = s.replace('https://', '').replace('http://', '').replace('www.', '')
			if max_len is not None and len(s) > max_len:
				return s[:max_len] + '…'
			return s

		try:
			# Generate a unique function name for this page
			visibility_func_name = f'onVisibilityChange_{id(page)}{id(page.url)}'

			# Define the callback that will be called from browser when tab becomes visible
			async def on_visibility_change(data):
				source = data.get('source', 'unknown')

				# Log before and after for debugging
				old_foreground = self.human_current_page
				if old_foreground.url != page.url:
					logger.warning(
						f'👁️ Foregound tab changed by human from {trunc(old_foreground.url, 22) if old_foreground else "about:blank"} to {trunc(page.url, 22)} ({source}) but agent will stay on {trunc(self.agent_current_page.url, 22)}'
					)

				# Update foreground tab
				self.human_current_page = page

			# Expose the function to the browser
			await page.expose_function(visibility_func_name, on_visibility_change)

			# Set up multiple visibility detection methods in the browser
			js_code = """() => {
				// --- Method 1: visibilitychange event (unfortunately *all* tabs are always marked visible by playwright, usually does not fire) ---
				document.addEventListener('visibilitychange', () => {
					if (document.visibilityState === 'visible') {
						window.onVisibilityChange_TABID({ source: 'visibilitychange' });
					}
				});
				
				// --- Method 2: focus/blur events, most reliable method for headful browsers ---
				window.addEventListener('focus', () => {
					window.onVisibilityChange_TABID({ source: 'focus' });
				});
				
				// --- Method 3: pointermove events (may be fired by agent if we implement AI hover movements) ---
				// Use a throttled handler to avoid excessive calls
				// let lastMove = 0;
				// window.addEventListener('pointermove', () => {
				// 	const now = Date.now();
				// 	if (now - lastMove > 1000) {  // Throttle to once per second
				// 		lastMove = now;
				// 		window.onVisibilityChange_TABID({ source: 'pointermove' });
				// 	}
				// });
			}""".replace('onVisibilityChange_TABID', visibility_func_name)
			# multiple reasons for doing it this way ^: stealth, uniqueness, sometimes pageload is cancelled and it runs twice, etc.
			await page.evaluate(js_code)

			# re-add listener to the page for when it navigates to a new url, because previous listeners will be cleared
			page.on('domcontentloaded', self._add_tab_foregrounding_listener)
			logger.debug(f'👀 Added tab focus listeners to tab: {page.url}')

			if page.url != self.agent_current_page.url:
				await on_visibility_change({'source': 'navigation'})

		except Exception as e:
			logger.debug(f'Failed to add tab focus listener to {page.url}: {e}')

	async def get_session(self) -> BrowserSession:
		"""Lazy initialization of the browser and related components"""
		if self.session is None:
			try:
				return await self._initialize_session()
			except Exception as e:
				logger.error(f'❌  Failed to create new browser session: {e} (did the browser process quit?)')
				raise e
		return self.session

	async def get_current_page(self) -> Page:
		"""Legacy method for backwards compatibility, prefer get_agent_current_page()"""
		return await self.get_agent_current_page()

	async def _reconcile_tab_state(self) -> None:
		"""Reconcile tab state when tabs might be out of sync.

		This method ensures that:
		1. Both tab references (agent_current_page and human_current_page) are valid
		2. Recovers invalid tab references using valid ones
		3. Handles the case where both references are invalid
		"""
		session = await self.get_session()

		agent_tab_valid = (
			self.agent_current_page
			and self.agent_current_page in session.context.pages
			and not self.agent_current_page.is_closed()
		)

		human_current_page_valid = (
			self.human_current_page
			and self.human_current_page in session.context.pages
			and not self.human_current_page.is_closed()
		)

		# Case 1: Both references are valid - nothing to do
		if agent_tab_valid and human_current_page_valid:
			return

		# Case 2: Only agent_current_page is valid - update human_current_page
		if agent_tab_valid and not human_current_page_valid:
			self.human_current_page = self.agent_current_page
			return

		# Case 3: Only human_current_page is valid - update agent_current_page
		if human_current_page_valid and not agent_tab_valid:
			self.agent_current_page = self.human_current_page
			return

		# Case 4: Neither reference is valid - recover from available tabs
		non_extension_pages = [
			page
			for page in session.context.pages
			if not page.url.startswith('chrome-extension://') and not page.url.startswith('chrome://')
		]

		if non_extension_pages:
			# Update both tab references to the most recently opened non-extension page
			recovered_page = non_extension_pages[-1]
			self.agent_current_page = recovered_page
			self.human_current_page = recovered_page
			return

		# Case 5: No valid pages at all - create a new page
		try:
			new_page = await session.context.new_page()
			self.agent_current_page = new_page
			self.human_current_page = new_page
		except Exception:
			# Last resort - recreate the session
			logger.warning('⚠️  No browser window available, recreating session')
			await self._initialize_session()
			if session.context.pages:
				page = session.context.pages[0]
				self.agent_current_page = page
				self.human_current_page = page

	async def get_agent_current_page(self) -> Page:
		"""Get the page that the agent is currently working with.

		This method prioritizes agent_current_page over human_current_page, ensuring
		that agent operations happen on the intended tab regardless of user
		interaction with the browser.

		If agent_current_page is invalid or closed, it will attempt to recover
		with a valid tab reference by reconciling the tab state.
		"""
		session = await self.get_session()

		# First check if agent_current_page is valid
		if (
			self.agent_current_page
			and self.agent_current_page in session.context.pages
			and not self.agent_current_page.is_closed()
		):
			return self.agent_current_page

		# If we're here, reconcile tab state and try again
		await self._reconcile_tab_state()

		# After reconciliation, agent_current_page should be valid
		if (
			self.agent_current_page
			and self.agent_current_page in session.context.pages
			and not self.agent_current_page.is_closed()
		):
			return self.agent_current_page

		# If still invalid, fall back to first page method as last resort
		logger.warning('⚠️  Failed to get agent current page, falling back to first page')
		if session.context.pages:
			page = session.context.pages[0]
			self.agent_current_page = page
			self.human_current_page = page
			return page

		# If no pages, create one
		return await session.context.new_page()

	async def _create_context(self, browser: PlaywrightBrowser):
		"""Creates a new browser context with anti-detection measures and loads cookies if available."""
		if self.browser.config.cdp_url and len(browser.contexts) > 0 and not self.config.force_new_context:
			context = browser.contexts[0]
			# For existing contexts, we need to set the viewport size manually
			if context.pages and not self.browser.config.headless:
				for page in context.pages:
					await self.set_viewport_size(page)
		elif self.browser.config.browser_binary_path and len(browser.contexts) > 0 and not self.config.force_new_context:
			# Connect to existing Chrome instance instead of creating new one
			context = browser.contexts[0]
			# For existing contexts, we need to set the viewport size manually
			if context.pages and not self.browser.config.headless:
				for page in context.pages:
					await self.set_viewport_size(page)
		else:
			kwargs = {}
			# Set viewport for both headless and non-headless modes
			if self.browser.config.headless:
				# In headless mode, always set viewport and no_viewport=False
				kwargs['viewport'] = {'width': self.config.window_width, 'height': self.config.window_height}
				kwargs['no_viewport'] = False
			else:
				# In headful mode, use the no_viewport value from config (defaults to True)
				no_viewport_value = self.config.no_viewport
				kwargs['no_viewport'] = no_viewport_value

				# Only set viewport if no_viewport is False
				if not no_viewport_value:
					kwargs['viewport'] = {'width': self.config.window_width, 'height': self.config.window_height}

			if self.config.user_agent is not None:
				kwargs['user_agent'] = self.config.user_agent

			context = await browser.new_context(
				**kwargs,
				java_script_enabled=True,
				**({'bypass_csp': True, 'ignore_https_errors': True} if self.config.disable_security else {}),
				record_video_dir=self.config.save_recording_path,
				record_video_size={'width': self.config.window_width, 'height': self.config.window_height},
				record_har_path=self.config.save_har_path,
				locale=self.config.locale,
				http_credentials=self.config.http_credentials,
				is_mobile=self.config.is_mobile,
				has_touch=self.config.has_touch,
				geolocation=self.config.geolocation,
				permissions=self.config.permissions,
				timezone_id=self.config.timezone_id,
			)

		# Ensure required permissions are granted
		required_permissions = ['clipboard-read', 'clipboard-write']  # needed for google sheets automation
		if self.config.geolocation:
			required_permissions.append('geolocation')
		missing_permissions = [p for p in required_permissions if p not in self.config.permissions]
		if any(missing_permissions):
			logger.warning(
				f'⚠️ Some permissions required by browser-use {missing_permissions} are missing from BrowserContextConfig(permissions={self.config.permissions}), some features may not work properly!'
			)
		await context.grant_permissions(self.config.permissions)

		if self.config.trace_path:
			await context.tracing.start(screenshots=True, snapshots=True, sources=True)

		# Resize the window for non-headless mode
		if not self.browser.config.headless:
			await self._resize_window(context)

		# Load cookies if they exist
		if self.config.cookies_file and os.path.exists(self.config.cookies_file):
			async with await anyio.open_file(self.config.cookies_file, 'r') as f:
				try:
					cookies = json.loads(await f.read())

					valid_same_site_values = ['Strict', 'Lax', 'None']
					for cookie in cookies:
						if 'sameSite' in cookie:
							if cookie['sameSite'] not in valid_same_site_values:
								logger.warning(
									f"Fixed invalid sameSite value '{cookie['sameSite']}' to 'None' for cookie {cookie.get('name')}"
								)
								cookie['sameSite'] = 'None'
					logger.info(f'🍪  Loaded {len(cookies)} cookies from {self.config.cookies_file}')
					await context.add_cookies(cookies)

				except json.JSONDecodeError as e:
					logger.error(f'Failed to parse cookies file: {str(e)}')

		init_script = """
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
			"""

		# Expose anti-detection scripts
		await context.add_init_script(init_script)

		return context

	async def set_viewport_size(self, page: Page) -> None:
		"""
		Central method to set viewport size for a page.
		Simple for now, but we may need to add more logic here in the future to rezise surrounding window, change recording options, etc.
		"""
		try:
			# Only set viewport size if no_viewport is False (aka viewport=True)
			if self.config.no_viewport is False:
				viewport_size = {'width': self.config.window_width, 'height': self.config.window_height}
				await page.set_viewport_size(viewport_size)
				logger.debug(f'Set viewport size to {self.config.window_width}x{self.config.window_height}')
			# else:
			# logger.debug('Skipping viewport size setting because no_viewport is not False')
		except Exception as e:
			logger.debug(f'Failed to set viewport size for page: {e}')

	async def _wait_for_stable_network(self):
		page = await self.get_agent_current_page()

		pending_requests = set()
		last_activity = asyncio.get_event_loop().time()

		# Define relevant resource types and content types
		RELEVANT_RESOURCE_TYPES = {
			'document',
			'stylesheet',
			'image',
			'font',
			'script',
			'iframe',
		}

		RELEVANT_CONTENT_TYPES = {
			'text/html',
			'text/css',
			'application/javascript',
			'image/',
			'font/',
			'application/json',
		}

		# Additional patterns to filter out
		IGNORED_URL_PATTERNS = {
			# Analytics and tracking
			'analytics',
			'tracking',
			'telemetry',
			'beacon',
			'metrics',
			# Ad-related
			'doubleclick',
			'adsystem',
			'adserver',
			'advertising',
			# Social media widgets
			'facebook.com/plugins',
			'platform.twitter',
			'linkedin.com/embed',
			# Live chat and support
			'livechat',
			'zendesk',
			'intercom',
			'crisp.chat',
			'hotjar',
			# Push notifications
			'push-notifications',
			'onesignal',
			'pushwoosh',
			# Background sync/heartbeat
			'heartbeat',
			'ping',
			'alive',
			# WebRTC and streaming
			'webrtc',
			'rtmp://',
			'wss://',
			# Common CDNs for dynamic content
			'cloudfront.net',
			'fastly.net',
		}

		async def on_request(request):
			# Filter by resource type
			if request.resource_type not in RELEVANT_RESOURCE_TYPES:
				return

			# Filter out streaming, websocket, and other real-time requests
			if request.resource_type in {
				'websocket',
				'media',
				'eventsource',
				'manifest',
				'other',
			}:
				return

			# Filter out by URL patterns
			url = request.url.lower()
			if any(pattern in url for pattern in IGNORED_URL_PATTERNS):
				return

			# Filter out data URLs and blob URLs
			if url.startswith(('data:', 'blob:')):
				return

			# Filter out requests with certain headers
			headers = request.headers
			if headers.get('purpose') == 'prefetch' or headers.get('sec-fetch-dest') in [
				'video',
				'audio',
			]:
				return

			nonlocal last_activity
			pending_requests.add(request)
			last_activity = asyncio.get_event_loop().time()
			# logger.debug(f'Request started: {request.url} ({request.resource_type})')

		async def on_response(response):
			request = response.request
			if request not in pending_requests:
				return

			# Filter by content type if available
			content_type = response.headers.get('content-type', '').lower()

			# Skip if content type indicates streaming or real-time data
			if any(
				t in content_type
				for t in [
					'streaming',
					'video',
					'audio',
					'webm',
					'mp4',
					'event-stream',
					'websocket',
					'protobuf',
				]
			):
				pending_requests.remove(request)
				return

			# Only process relevant content types
			if not any(ct in content_type for ct in RELEVANT_CONTENT_TYPES):
				pending_requests.remove(request)
				return

			# Skip if response is too large (likely not essential for page load)
			content_length = response.headers.get('content-length')
			if content_length and int(content_length) > 5 * 1024 * 1024:  # 5MB
				pending_requests.remove(request)
				return

			nonlocal last_activity
			pending_requests.remove(request)
			last_activity = asyncio.get_event_loop().time()
			# logger.debug(f'Request resolved: {request.url} ({content_type})')

		# Attach event listeners
		page.on('request', on_request)
		page.on('response', on_response)

		try:
			# Wait for idle time
			start_time = asyncio.get_event_loop().time()
			while True:
				await asyncio.sleep(0.1)
				now = asyncio.get_event_loop().time()
				if len(pending_requests) == 0 and (now - last_activity) >= self.config.wait_for_network_idle_page_load_time:
					break
				if now - start_time > self.config.maximum_wait_page_load_time:
					logger.debug(
						f'Network timeout after {self.config.maximum_wait_page_load_time}s with {len(pending_requests)} '
						f'pending requests: {[r.url for r in pending_requests]}'
					)
					break

		finally:
			# Clean up event listeners
			page.remove_listener('request', on_request)
			page.remove_listener('response', on_response)

		logger.debug(f'⚖️  Network stabilized for {self.config.wait_for_network_idle_page_load_time} seconds')

	async def _wait_for_page_and_frames_load(self, timeout_overwrite: float | None = None):
		"""
		Ensures page is fully loaded before continuing.
		Waits for either network to be idle or minimum WAIT_TIME, whichever is longer.
		Also checks if the loaded URL is allowed.
		"""
		# Start timing
		start_time = time.time()

		# Wait for page load
		try:
			await self._wait_for_stable_network()

			# Check if the loaded URL is allowed
			page = await self.get_agent_current_page()
			await self._check_and_handle_navigation(page)
		except URLNotAllowedError as e:
			raise e
		except Exception:
			logger.warning('⚠️  Page load failed, continuing...')
			pass

		# Calculate remaining time to meet minimum WAIT_TIME
		elapsed = time.time() - start_time
		remaining = max((timeout_overwrite or self.config.minimum_wait_page_load_time) - elapsed, 0)

		logger.debug(f'--Page loaded in {elapsed:.2f} seconds, waiting for additional {remaining:.2f} seconds')

		# Sleep remaining time if needed
		if remaining > 0:
			await asyncio.sleep(remaining)

	def _is_url_allowed(self, url: str) -> bool:
		"""Check if a URL is allowed based on the whitelist configuration."""
		if not self.config.allowed_domains:
			return True

		try:
			from urllib.parse import urlparse

			# Special case: Allow 'about:blank' explicitly
			if url == 'about:blank':
				return True

			parsed_url = urlparse(url)

			# Extract only the hostname component (without auth credentials or port)
			# Hostname returns only the domain portion, ignoring username:password and port
			domain = parsed_url.hostname.lower() if parsed_url.hostname else ''

			# Check if domain matches any allowed domain pattern
			return any(
				domain == allowed_domain.lower() or domain.endswith('.' + allowed_domain.lower())
				for allowed_domain in self.config.allowed_domains
			)
		except Exception as e:
			logger.error(f'⛔️  Error checking URL allowlist: {str(e)}')
			return False

	async def _check_and_handle_navigation(self, page: Page) -> None:
		"""Check if current page URL is allowed and handle if not."""
		if not self._is_url_allowed(page.url):
			logger.warning(f'⛔️  Navigation to non-allowed URL detected: {page.url}')
			try:
				await self.go_back()
			except Exception as e:
				logger.error(f'⛔️  Failed to go back after detecting non-allowed URL: {str(e)}')
			raise URLNotAllowedError(f'Navigation to non-allowed URL: {page.url}')

	async def navigate_to(self, url: str):
		"""Navigate the agent's current tab to a URL"""
		if not self._is_url_allowed(url):
			raise BrowserError(f'Navigation to non-allowed URL: {url}')

		page = await self.get_agent_current_page()
		await page.goto(url)
		await page.wait_for_load_state()

	async def refresh_page(self):
		"""Refresh the agent's current page"""
		page = await self.get_agent_current_page()
		await page.reload()
		await page.wait_for_load_state()

	async def go_back(self):
		"""Navigate the agent's tab back in browser history"""
		page = await self.get_agent_current_page()
		try:
			# 10 ms timeout
			await page.go_back(timeout=10, wait_until='domcontentloaded')
			# await self._wait_for_page_and_frames_load(timeout_overwrite=1.0)
		except Exception as e:
			# Continue even if its not fully loaded, because we wait later for the page to load
			logger.debug(f'⏮️  Error during go_back: {e}')

	async def go_forward(self):
		"""Navigate the agent's tab forward in browser history"""
		page = await self.get_agent_current_page()
		try:
			await page.go_forward(timeout=10, wait_until='domcontentloaded')
		except Exception as e:
			# Continue even if its not fully loaded, because we wait later for the page to load
			logger.debug(f'⏭️  Error during go_forward: {e}')

	async def close_current_tab(self):
		"""Close the current tab that the agent is working with.

		This closes the tab that the agent is currently using (agent_current_page),
		not necessarily the tab that is visible to the user (human_current_page).
		If they are the same tab, both references will be updated.
		"""
		session = await self.get_session()
		page = await self.get_agent_current_page()

		# Check if this is the foreground tab as well
		is_foreground = page == self.human_current_page

		# Close the tab
		await page.close()

		# Clear agent's reference to the closed tab
		self.agent_current_page = None

		# Clear foreground reference if needed
		if is_foreground:
			self.human_current_page = None

		# Switch to the first available tab if any exist
		if session.context.pages:
			await self.switch_to_tab(0)
			# switch_to_tab already updates both tab references

		# Otherwise, the browser will be closed

	async def get_page_html(self) -> str:
		"""Get the HTML content of the agent's current page"""
		page = await self.get_agent_current_page()
		return await page.content()

	async def execute_javascript(self, script: str):
		"""Execute JavaScript code on the agent's current page"""
		page = await self.get_agent_current_page()
		return await page.evaluate(script)

	async def get_page_structure(self) -> str:
		"""Get a debug view of the page structure including iframes"""
		debug_script = """(() => {
			function getPageStructure(element = document, depth = 0, maxDepth = 10) {
				if (depth >= maxDepth) return '';

				const indent = '  '.repeat(depth);
				let structure = '';

				// Skip certain elements that clutter the output
				const skipTags = new Set(['script', 'style', 'link', 'meta', 'noscript']);

				// Add current element info if it's not the document
				if (element !== document) {
					const tagName = element.tagName.toLowerCase();

					// Skip uninteresting elements
					if (skipTags.has(tagName)) return '';

					const id = element.id ? `#${element.id}` : '';
					const classes = element.className && typeof element.className === 'string' ?
						`.${element.className.split(' ').filter(c => c).join('.')}` : '';

					// Get additional useful attributes
					const attrs = [];
					if (element.getAttribute('role')) attrs.push(`role="${element.getAttribute('role')}"`);
					if (element.getAttribute('aria-label')) attrs.push(`aria-label="${element.getAttribute('aria-label')}"`);
					if (element.getAttribute('type')) attrs.push(`type="${element.getAttribute('type')}"`);
					if (element.getAttribute('name')) attrs.push(`name="${element.getAttribute('name')}"`);
					if (element.getAttribute('src')) {
						const src = element.getAttribute('src');
						attrs.push(`src="${src.substring(0, 50)}${src.length > 50 ? '...' : ''}"`);
					}

					// Add element info
					structure += `${indent}${tagName}${id}${classes}${attrs.length ? ' [' + attrs.join(', ') + ']' : ''}\\n`;

					// Handle iframes specially
					if (tagName === 'iframe') {
						try {
							const iframeDoc = element.contentDocument || element.contentWindow?.document;
							if (iframeDoc) {
								structure += `${indent}  [IFRAME CONTENT]:\\n`;
								structure += getPageStructure(iframeDoc, depth + 2, maxDepth);
							} else {
								structure += `${indent}  [IFRAME: No access - likely cross-origin]\\n`;
							}
						} catch (e) {
							structure += `${indent}  [IFRAME: Access denied - ${e.message}]\\n`;
						}
					}
				}

				// Get all child elements
				const children = element.children || element.childNodes;
				for (const child of children) {
					if (child.nodeType === 1) { // Element nodes only
						structure += getPageStructure(child, depth + 1, maxDepth);
					}
				}

				return structure;
			}

			return getPageStructure();
		})()"""

		page = await self.get_agent_current_page()
		structure = await page.evaluate(debug_script)
		return structure

	@time_execution_sync('--get_state')  # This decorator might need to be updated to handle async
	async def get_state(self, cache_clickable_elements_hashes: bool) -> BrowserState:
		"""Get the current state of the browser

		cache_clickable_elements_hashes: bool
			If True, cache the clickable elements hashes for the current state. This is used to calculate which elements are new to the llm (from last message) -> reduces token usage.
		"""
		await self._wait_for_page_and_frames_load()
		session = await self.get_session()
		updated_state = await self._get_updated_state()

		# Find out which elements are new
		# Do this only if url has not changed
		if cache_clickable_elements_hashes:
			# if we are on the same url as the last state, we can use the cached hashes
			if (
				session.cached_state_clickable_elements_hashes
				and session.cached_state_clickable_elements_hashes.url == updated_state.url
			):
				# Pointers, feel free to edit in place
				updated_state_clickable_elements = ClickableElementProcessor.get_clickable_elements(updated_state.element_tree)

				for dom_element in updated_state_clickable_elements:
					dom_element.is_new = (
						ClickableElementProcessor.hash_dom_element(dom_element)
						not in session.cached_state_clickable_elements_hashes.hashes  # see which elements are new from the last state where we cached the hashes
					)
			# in any case, we need to cache the new hashes
			session.cached_state_clickable_elements_hashes = CachedStateClickableElementsHashes(
				url=updated_state.url,
				hashes=ClickableElementProcessor.get_clickable_elements_hashes(updated_state.element_tree),
			)

		session.cached_state = updated_state

		# Save cookies if a file is specified
		if self.config.cookies_file:
			asyncio.create_task(self.save_cookies())

		return session.cached_state

	async def _get_updated_state(self, focus_element: int = -1) -> BrowserState:
		"""Update and return state."""
		session = await self.get_session()

		# Check if current page is still valid, if not switch to another available page
		try:
			page = await self.get_agent_current_page()
			# Test if page is still accessible
			await page.evaluate('1')
		except Exception as e:
			logger.debug(f'👋  Current page is no longer accessible: {str(e)}')
			raise BrowserError('Browser closed: no valid pages available')

		try:
			await self.remove_highlights()
			dom_service = DomService(page)
			content = await dom_service.get_clickable_elements(
				focus_element=focus_element,
				viewport_expansion=self.config.viewport_expansion,
				highlight_elements=self.config.highlight_elements,
			)

			tabs_info = await self.get_tabs_info()

			# Get all cross-origin iframes within the page and open them in new tabs
			# mark the titles of the new tabs so the LLM knows to check them for additional content
			# unfortunately too buggy for now, too many sites use invisible cross-origin iframes for ads, tracking, youtube videos, social media, etc.
			# and it distracts the bot by opening a lot of new tabs
			# iframe_urls = await dom_service.get_cross_origin_iframes()
			# for url in iframe_urls:
			# 	if url in [tab.url for tab in tabs_info]:
			# 		continue  # skip if the iframe if we already have it open in a tab
			# 	new_page_id = tabs_info[-1].page_id + 1
			# 	logger.debug(f'Opening cross-origin iframe in new tab #{new_page_id}: {url}')
			# 	await self.create_new_tab(url)
			# 	tabs_info.append(
			# 		TabInfo(
			# 			page_id=new_page_id,
			# 			url=url,
			# 			title=f'iFrame opened as new tab, treat as if embedded inside page #{self.state.target_id}: {page.url}',
			# 			parent_page_id=self.state.target_id,
			# 		)
			# 	)

			screenshot_b64 = await self.take_screenshot()
			pixels_above, pixels_below = await self.get_scroll_info(page)

			# Find the agent's active tab ID
			agent_current_page_id = 0
			if self.agent_current_page:
				for tab_info in tabs_info:
					if tab_info.url == self.agent_current_page.url:
						agent_current_page_id = tab_info.page_id
						break

			self.current_state = BrowserState(
				element_tree=content.element_tree,
				selector_map=content.selector_map,
				url=page.url,
				title=await page.title(),
				tabs=tabs_info,
				screenshot=screenshot_b64,
				pixels_above=pixels_above,
				pixels_below=pixels_below,
			)

			return self.current_state
		except Exception as e:
			logger.error(f'❌  Failed to update state: {str(e)}')
			# Return last known good state if available
			if hasattr(self, 'current_state'):
				return self.current_state
			raise

	# region - Browser Actions
	@time_execution_async('--take_screenshot')
	async def take_screenshot(self, full_page: bool = False) -> str:
		"""
		Returns a base64 encoded screenshot of the current page.
		"""
		page = await self.get_agent_current_page()

		# We no longer force tabs to the foreground as it disrupts user focus
		# await page.bring_to_front()
		await page.wait_for_load_state()

		screenshot = await page.screenshot(
			full_page=full_page,
			animations='disabled',
			caret='initial',
		)

		screenshot_b64 = base64.b64encode(screenshot).decode('utf-8')

		# await self.remove_highlights()

		return screenshot_b64

	@time_execution_async('--remove_highlights')
	async def remove_highlights(self):
		"""
		Removes all highlight overlays and labels created by the highlightElement function.
		Handles cases where the page might be closed or inaccessible.
		"""
		try:
			page = await self.get_agent_current_page()
			await page.evaluate(
				"""
                try {
                    // Remove the highlight container and all its contents
                    const container = document.getElementById('playwright-highlight-container');
                    if (container) {
                        container.remove();
                    }

                    // Remove highlight attributes from elements
                    const highlightedElements = document.querySelectorAll('[browser-user-highlight-id^="playwright-highlight-"]');
                    highlightedElements.forEach(el => {
                        el.removeAttribute('browser-user-highlight-id');
                    });
                } catch (e) {
                    console.error('Failed to remove highlights:', e);
                }
                """
			)
		except Exception as e:
			logger.debug(f'⚠  Failed to remove highlights (this is usually ok): {str(e)}')
			# Don't raise the error since this is not critical functionality
			pass

	# endregion

	# region - User Actions

	@classmethod
	def _convert_simple_xpath_to_css_selector(cls, xpath: str) -> str:
		"""Converts simple XPath expressions to CSS selectors."""
		if not xpath:
			return ''

		# Remove leading slash if present
		xpath = xpath.lstrip('/')

		# Split into parts
		parts = xpath.split('/')
		css_parts = []

		for part in parts:
			if not part:
				continue

			# Handle custom elements with colons by escaping them
			if ':' in part and '[' not in part:
				base_part = part.replace(':', r'\:')
				css_parts.append(base_part)
				continue

			# Handle index notation [n]
			if '[' in part:
				base_part = part[: part.find('[')]
				# Handle custom elements with colons in the base part
				if ':' in base_part:
					base_part = base_part.replace(':', r'\:')
				index_part = part[part.find('[') :]

				# Handle multiple indices
				indices = [i.strip('[]') for i in index_part.split(']')[:-1]]

				for idx in indices:
					try:
						# Handle numeric indices
						if idx.isdigit():
							index = int(idx) - 1
							base_part += f':nth-of-type({index + 1})'
						# Handle last() function
						elif idx == 'last()':
							base_part += ':last-of-type'
						# Handle position() functions
						elif 'position()' in idx:
							if '>1' in idx:
								base_part += ':nth-of-type(n+2)'
					except ValueError:
						continue

				css_parts.append(base_part)
			else:
				css_parts.append(part)

		base_selector = ' > '.join(css_parts)
		return base_selector

	@classmethod
	@time_execution_sync('--enhanced_css_selector_for_element')
	def _enhanced_css_selector_for_element(cls, element: DOMElementNode, include_dynamic_attributes: bool = True) -> str:
		"""
		Creates a CSS selector for a DOM element, handling various edge cases and special characters.

		Args:
		        element: The DOM element to create a selector for

		Returns:
		        A valid CSS selector string
		"""
		try:
			# Get base selector from XPath
			css_selector = cls._convert_simple_xpath_to_css_selector(element.xpath)

			# Handle class attributes
			if 'class' in element.attributes and element.attributes['class'] and include_dynamic_attributes:
				# Define a regex pattern for valid class names in CSS
				valid_class_name_pattern = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_-]*$')

				# Iterate through the class attribute values
				classes = element.attributes['class'].split()
				for class_name in classes:
					# Skip empty class names
					if not class_name.strip():
						continue

					# Check if the class name is valid
					if valid_class_name_pattern.match(class_name):
						# Append the valid class name to the CSS selector
						css_selector += f'.{class_name}'
					else:
						# Skip invalid class names
						continue

			# Expanded set of safe attributes that are stable and useful for selection
			SAFE_ATTRIBUTES = {
				# Data attributes (if they're stable in your application)
				'id',
				# Standard HTML attributes
				'name',
				'type',
				'placeholder',
				# Accessibility attributes
				'aria-label',
				'aria-labelledby',
				'aria-describedby',
				'role',
				# Common form attributes
				'for',
				'autocomplete',
				'required',
				'readonly',
				# Media attributes
				'alt',
				'title',
				'src',
				# Custom stable attributes (add any application-specific ones)
				'href',
				'target',
			}

			if include_dynamic_attributes:
				dynamic_attributes = {
					'data-id',
					'data-qa',
					'data-cy',
					'data-testid',
				}
				SAFE_ATTRIBUTES.update(dynamic_attributes)

			# Handle other attributes
			for attribute, value in element.attributes.items():
				if attribute == 'class':
					continue

				# Skip invalid attribute names
				if not attribute.strip():
					continue

				if attribute not in SAFE_ATTRIBUTES:
					continue

				# Escape special characters in attribute names
				safe_attribute = attribute.replace(':', r'\:')

				# Handle different value cases
				if value == '':
					css_selector += f'[{safe_attribute}]'
				elif any(char in value for char in '"\'<>`\n\r\t'):
					# Use contains for values with special characters
					# For newline-containing text, only use the part before the newline
					if '\n' in value:
						value = value.split('\n')[0]
					# Regex-substitute *any* whitespace with a single space, then strip.
					collapsed_value = re.sub(r'\s+', ' ', value).strip()
					# Escape embedded double-quotes.
					safe_value = collapsed_value.replace('"', '\\"')
					css_selector += f'[{safe_attribute}*="{safe_value}"]'
				else:
					css_selector += f'[{safe_attribute}="{value}"]'

			return css_selector

		except Exception:
			# Fallback to a more basic selector if something goes wrong
			tag_name = element.tag_name or '*'
			return f"{tag_name}[highlight_index='{element.highlight_index}']"

	@time_execution_async('--is_visible')
	async def _is_visible(self, element: ElementHandle) -> bool:
		"""
		Checks if an element is visible on the page.
		We use our own implementation instead of relying solely on Playwright's is_visible() because
		of edge cases with CSS frameworks like Tailwind. When elements use Tailwind's 'hidden' class,
		the computed style may return display as '' (empty string) instead of 'none', causing Playwright
		to incorrectly consider hidden elements as visible. By additionally checking the bounding box
		dimensions, we catch elements that have zero width/height regardless of how they were hidden.
		"""
		is_hidden = await element.is_hidden()
		bbox = await element.bounding_box()

		return not is_hidden and bbox is not None and bbox['width'] > 0 and bbox['height'] > 0

	@time_execution_async('--get_locate_element')
	async def get_locate_element(self, element: DOMElementNode) -> ElementHandle | None:
		current_frame = await self.get_agent_current_page()

		# Start with the target element and collect all parents
		parents: list[DOMElementNode] = []
		current = element
		while current.parent is not None:
			parent = current.parent
			parents.append(parent)
			current = parent

		# Reverse the parents list to process from top to bottom
		parents.reverse()

		# Process all iframe parents in sequence
		iframes = [item for item in parents if item.tag_name == 'iframe']
		for parent in iframes:
			css_selector = self._enhanced_css_selector_for_element(
				parent,
				include_dynamic_attributes=self.config.include_dynamic_attributes,
			)
			current_frame = current_frame.frame_locator(css_selector)

		css_selector = self._enhanced_css_selector_for_element(
			element, include_dynamic_attributes=self.config.include_dynamic_attributes
		)

		try:
			if isinstance(current_frame, FrameLocator):
				element_handle = await current_frame.locator(css_selector).element_handle()
				return element_handle
			else:
				# Try to scroll into view if hidden
				element_handle = await current_frame.query_selector(css_selector)
				if element_handle:
					is_visible = await self._is_visible(element_handle)
					if is_visible:
						await element_handle.scroll_into_view_if_needed()
					return element_handle
				return None
		except Exception as e:
			logger.error(f'❌  Failed to locate element: {str(e)}')
			return None

	@time_execution_async('--get_locate_element_by_xpath')
	async def get_locate_element_by_xpath(self, xpath: str) -> ElementHandle | None:
		"""
		Locates an element on the page using the provided XPath.
		"""
		current_frame = await self.get_agent_current_page()

		try:
			# Use XPath to locate the element
			element_handle = await current_frame.query_selector(f'xpath={xpath}')
			if element_handle:
				is_visible = await self._is_visible(element_handle)
				if is_visible:
					await element_handle.scroll_into_view_if_needed()
				return element_handle
			return None
		except Exception as e:
			logger.error(f'❌  Failed to locate element by XPath {xpath}: {str(e)}')
			return None

	@time_execution_async('--get_locate_element_by_css_selector')
	async def get_locate_element_by_css_selector(self, css_selector: str) -> ElementHandle | None:
		"""
		Locates an element on the page using the provided CSS selector.
		"""
		current_frame = await self.get_agent_current_page()

		try:
			# Use CSS selector to locate the element
			element_handle = await current_frame.query_selector(css_selector)
			if element_handle:
				is_visible = await self._is_visible(element_handle)
				if is_visible:
					await element_handle.scroll_into_view_if_needed()
				return element_handle
			return None
		except Exception as e:
			logger.error(f'❌  Failed to locate element by CSS selector {css_selector}: {str(e)}')
			return None

	@time_execution_async('--get_locate_element_by_text')
	async def get_locate_element_by_text(
		self, text: str, nth: int | None = 0, element_type: str | None = None
	) -> ElementHandle | None:
		"""
		Locates an element on the page using the provided text.
		If `nth` is provided, it returns the nth matching element (0-based).
		If `element_type` is provided, filters by tag name (e.g., 'button', 'span').
		"""
		current_frame = await self.get_agent_current_page()
		try:
			# handle also specific element type or use any type.
			selector = f'{element_type or "*"}:text("{text}")'
			elements = await current_frame.query_selector_all(selector)
			# considering only visible elements
			elements = [el for el in elements if await self._is_visible(el)]

			if not elements:
				logger.error(f"No visible element with text '{text}' found.")
				return None

			if nth is not None:
				if 0 <= nth < len(elements):
					element_handle = elements[nth]
				else:
					logger.error(f"Visible element with text '{text}' not found at index {nth}.")
					return None
			else:
				element_handle = elements[0]

			is_visible = await self._is_visible(element_handle)
			if is_visible:
				await element_handle.scroll_into_view_if_needed()
			return element_handle
		except Exception as e:
			logger.error(f"❌  Failed to locate element by text '{text}': {str(e)}")
			return None

	@time_execution_async('--input_text_element_node')
	async def _input_text_element_node(self, element_node: DOMElementNode, text: str):
		"""
		Input text into an element with proper error handling and state management.
		Handles different types of input fields and ensures proper element state before input.
		"""
		try:
			# Highlight before typing
			# if element_node.highlight_index is not None:
			# 	await self._update_state(focus_element=element_node.highlight_index)

			element_handle = await self.get_locate_element(element_node)

			if element_handle is None:
				raise BrowserError(f'Element: {repr(element_node)} not found')

			# Ensure element is ready for input
			try:
				await element_handle.wait_for_element_state('stable', timeout=1000)
				is_visible = await self._is_visible(element_handle)
				if is_visible:
					await element_handle.scroll_into_view_if_needed(timeout=1000)
			except Exception:
				pass

			# Get element properties to determine input method
			tag_handle = await element_handle.get_property('tagName')
			tag_name = (await tag_handle.json_value()).lower()
			is_contenteditable = await element_handle.get_property('isContentEditable')
			readonly_handle = await element_handle.get_property('readOnly')
			disabled_handle = await element_handle.get_property('disabled')

			readonly = await readonly_handle.json_value() if readonly_handle else False
			disabled = await disabled_handle.json_value() if disabled_handle else False

			# always click the element first to make sure it's in the focus
			await element_handle.click()
			await asyncio.sleep(0.1)

			try:
				if (await is_contenteditable.json_value() or tag_name == 'input') and not (readonly or disabled):
					await element_handle.evaluate('el => {el.textContent = ""; el.value = "";}')
					await element_handle.type(text, delay=5)
				else:
					await element_handle.fill(text)
			except Exception:
				# last resort fallback, assume it's already focused after we clicked on it,
				# just simulate keypresses on the entire page
				await self.get_agent_current_page().keyboard.type(text)

		except Exception as e:
			logger.debug(f'❌  Failed to input text into element: {repr(element_node)}. Error: {str(e)}')
			raise BrowserError(f'Failed to input text into index {element_node.highlight_index}')

	@time_execution_async('--click_element_node')
	async def _click_element_node(self, element_node: DOMElementNode) -> str | None:
		"""
		Optimized method to click an element using xpath.
		"""
		page = await self.get_agent_current_page()

		try:
			# Highlight before clicking
			# if element_node.highlight_index is not None:
			# 	await self._update_state(focus_element=element_node.highlight_index)

			element_handle = await self.get_locate_element(element_node)

			if element_handle is None:
				raise Exception(f'Element: {repr(element_node)} not found')

			async def perform_click(click_func):
				"""Performs the actual click, handling both download
				and navigation scenarios."""
				if self.config.save_downloads_path:
					try:
						# Try short-timeout expect_download to detect a file download has been been triggered
						async with page.expect_download(timeout=5000) as download_info:
							await click_func()
						download = await download_info.value
						# Determine file path
						suggested_filename = download.suggested_filename
						unique_filename = await self._get_unique_filename(self.config.save_downloads_path, suggested_filename)
						download_path = os.path.join(self.config.save_downloads_path, unique_filename)
						await download.save_as(download_path)
						logger.debug(f'⬇️  Download triggered. Saved file to: {download_path}')
						return download_path
					except TimeoutError:
						# If no download is triggered, treat as normal click
						logger.debug('No download triggered within timeout. Checking navigation...')
						await page.wait_for_load_state()
						await self._check_and_handle_navigation(page)
				else:
					# Standard click logic if no download is expected
					await click_func()
					await page.wait_for_load_state()
					await self._check_and_handle_navigation(page)

			try:
				return await perform_click(lambda: element_handle.click(timeout=1500))
			except URLNotAllowedError as e:
				raise e
			except Exception:
				try:
					return await perform_click(lambda: page.evaluate('(el) => el.click()', element_handle))
				except URLNotAllowedError as e:
					raise e
				except Exception as e:
					raise Exception(f'Failed to click element: {str(e)}')

		except URLNotAllowedError as e:
			raise e
		except Exception as e:
			raise Exception(f'Failed to click element: {repr(element_node)}. Error: {str(e)}')

	@time_execution_async('--get_tabs_info')
	async def get_tabs_info(self) -> list[TabInfo]:
		"""Get information about all tabs"""
		session = await self.get_session()

		tabs_info = []
		for page_id, page in enumerate(session.context.pages):
			try:
				tab_info = TabInfo(page_id=page_id, url=page.url, title=await asyncio.wait_for(page.title(), timeout=1))
			except TimeoutError:
				# page.title() can hang forever on tabs that are crashed/disappeared/about:blank
				# we dont want to try automating those tabs because they will hang the whole script
				logger.debug('⚠  Failed to get tab info for tab #%s: %s (ignoring)', page_id, page.url)
				tab_info = TabInfo(page_id=page_id, url='about:blank', title='ignore this tab and do not use it')
			tabs_info.append(tab_info)

		return tabs_info

	@time_execution_async('--switch_to_tab')
	async def switch_to_tab(self, page_id: int) -> None:
		"""Switch to a specific tab by its page_id"""
		session = await self.get_session()
		pages = session.context.pages

		if page_id >= len(pages):
			raise BrowserError(f'No tab found with page_id: {page_id}')

		page = pages[page_id]

		# Check if the tab's URL is allowed before switching
		if not self._is_url_allowed(page.url):
			raise BrowserError(f'Cannot switch to tab with non-allowed URL: {page.url}')

		# Update target ID if using CDP
		if self.browser.config.cdp_url:
			targets = await self._get_cdp_targets()
			for target in targets:
				if target['url'] == page.url:
					self.state.target_id = target['targetId']
					break

		# Update both tab references - agent wants this tab, and it's now in the foreground
		self.agent_current_page = page
		self.human_current_page = page

		# Bring tab to front and wait for it to load
		await page.bring_to_front()
		await page.wait_for_load_state()

		# Set the viewport size for the tab
		await self.set_viewport_size(page)

	@time_execution_async('--create_new_tab')
	async def create_new_tab(self, url: str | None = None) -> None:
		"""Create a new tab and optionally navigate to a URL"""
		if url and not self._is_url_allowed(url):
			raise BrowserError(f'Cannot create new tab with non-allowed URL: {url}')

		session = await self.get_session()
		new_page = await session.context.new_page()

		# Update both tab references - agent wants this tab, and it's now in the foreground
		self.agent_current_page = new_page
		self.human_current_page = new_page

		await new_page.wait_for_load_state()

		# Set the viewport size for the new tab
		await self.set_viewport_size(new_page)

		if url:
			await new_page.goto(url)
			await self._wait_for_page_and_frames_load(timeout_overwrite=1)

		# Get target ID for new page if using CDP
		if self.browser.config.cdp_url:
			targets = await self._get_cdp_targets()
			for target in targets:
				if target['url'] == new_page.url:
					self.state.target_id = target['targetId']
					break

	# region - Helper methods for easier access to the DOM

	async def get_selector_map(self) -> SelectorMap:
		session = await self.get_session()
		if session.cached_state is None:
			return {}
		return session.cached_state.selector_map

	async def get_element_by_index(self, index: int) -> ElementHandle | None:
		selector_map = await self.get_selector_map()
		element_handle = await self.get_locate_element(selector_map[index])
		return element_handle

	async def get_dom_element_by_index(self, index: int) -> DOMElementNode:
		selector_map = await self.get_selector_map()
		return selector_map[index]

	async def save_cookies(self):
		"""Save current cookies to file"""
		if self.session and self.session.context and self.config.cookies_file:
			try:
				cookies = await self.session.context.cookies()
				logger.debug(f'🍪  Saving {len(cookies)} cookies to {self.config.cookies_file}')

				# Check if the path is a directory and create it if necessary
				dirname = os.path.dirname(self.config.cookies_file)
				if dirname:
					os.makedirs(dirname, exist_ok=True)

				async with await anyio.open_file(self.config.cookies_file, 'w') as f:
					await f.write(json.dumps(cookies))
			except Exception as e:
				logger.warning(f'❌  Failed to save cookies: {str(e)}')

	async def is_file_uploader(self, element_node: DOMElementNode, max_depth: int = 3, current_depth: int = 0) -> bool:
		"""Check if element or its children are file uploaders"""
		if current_depth > max_depth:
			return False

		# Check current element
		is_uploader = False

		if not isinstance(element_node, DOMElementNode):
			return False

		# Check for file input attributes
		if element_node.tag_name == 'input':
			is_uploader = element_node.attributes.get('type') == 'file' or element_node.attributes.get('accept') is not None

		if is_uploader:
			return True

		# Recursively check children
		if element_node.children and current_depth < max_depth:
			for child in element_node.children:
				if isinstance(child, DOMElementNode):
					if await self.is_file_uploader(child, max_depth, current_depth + 1):
						return True

		return False

	async def get_scroll_info(self, page: Page) -> tuple[int, int]:
		"""Get scroll position information for the current page."""
		scroll_y = await page.evaluate('window.scrollY')
		viewport_height = await page.evaluate('window.innerHeight')
		total_height = await page.evaluate('document.documentElement.scrollHeight')
		pixels_above = scroll_y
		pixels_below = total_height - (scroll_y + viewport_height)
		return pixels_above, pixels_below

	async def reset_context(self):
		"""Reset the browser session
		Call this when you don't want to kill the context but just kill the state
		"""
		# close all tabs and clear cached state
		session = await self.get_session()

		pages = session.context.pages
		for page in pages:
			await page.close()

		session.cached_state = None
		self.state.target_id = None

	async def _get_unique_filename(self, directory, filename):
		"""Generate a unique filename by appending (1), (2), etc., if a file already exists."""
		base, ext = os.path.splitext(filename)
		counter = 1
		new_filename = filename
		while os.path.exists(os.path.join(directory, new_filename)):
			new_filename = f'{base} ({counter}){ext}'
			counter += 1
		return new_filename

	async def _get_cdp_targets(self) -> list[dict]:
		"""Get all CDP targets directly using CDP protocol"""
		if not self.browser.config.cdp_url or not self.session:
			return []

		try:
			pages = self.session.context.pages
			if not pages:
				return []

			cdp_session = await pages[0].context.new_cdp_session(pages[0])
			result = await cdp_session.send('Target.getTargets')
			await cdp_session.detach()
			return result.get('targetInfos', [])
		except Exception as e:
			logger.debug(f'Failed to get CDP targets: {e}')
			return []

	async def _resize_window(self, context: PlaywrightBrowserContext) -> None:
		"""Resize the browser window to match the configured size"""
		try:
			if not context.pages:
				return

			page = context.pages[0]
			window_size = {'width': self.config.window_width, 'height': self.config.window_height}

			# First, set the viewport size
			await self.set_viewport_size(page)

			# Then, try to set the actual window size using CDP
			try:
				cdp_session = await context.new_cdp_session(page)

				# Get the window ID
				window_id_result = await cdp_session.send('Browser.getWindowForTarget')

				# Set the window bounds
				await cdp_session.send(
					'Browser.setWindowBounds',
					{
						'windowId': window_id_result['windowId'],
						'bounds': {
							'width': window_size['width'],
							'height': window_size['height'] + BROWSER_NAVBAR_HEIGHT,  # Add height for browser chrome
							'windowState': 'normal',  # Ensure window is not minimized/maximized
						},
					},
				)

				await cdp_session.detach()
				logger.debug(f'Set window size to {window_size["width"]}x{window_size["height"] + BROWSER_NAVBAR_HEIGHT}')
			except Exception as e:
				logger.debug(f'CDP window resize failed: {e}')

				# Fallback to using JavaScript
				try:
					await page.evaluate(
						"""
						(width, height) => {
							window.resizeTo(width, height);
						}
						""",
						window_size['width'],
						window_size['height'] + BROWSER_NAVBAR_HEIGHT,
					)
					logger.debug(
						f'Used JavaScript to set window size to {window_size["width"]}x{window_size["height"] + BROWSER_NAVBAR_HEIGHT}'
					)
				except Exception as e:
					logger.debug(f'JavaScript window resize failed: {e}')

			logger.debug(f'Attempted to resize window to {window_size["width"]}x{window_size["height"]}')
		except Exception as e:
			logger.debug(f'Failed to resize browser window: {e}')
			# Non-critical error, continue execution

	async def wait_for_element(self, selector: str, timeout: float) -> None:
		"""
		Waits for an element matching the given CSS selector to become visible.

		Args:
		    selector (str): The CSS selector of the element.
		    timeout (float): The maximum time to wait for the element to be visible (in milliseconds).

		Raises:
		    TimeoutError: If the element does not become visible within the specified timeout.
		"""
		page = await self.get_agent_current_page()
		await page.wait_for_selector(selector, state='visible', timeout=timeout)
