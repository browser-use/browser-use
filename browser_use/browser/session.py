from __future__ import annotations

import json
import logging
import os
from functools import wraps
from pathlib import Path
from typing import Any, Self

import psutil
from playwright.async_api import Browser as PlaywrightBrowser
from playwright.async_api import BrowserContext as PlaywrightBrowserContext
from playwright.async_api import Page, Playwright, async_playwright
from pydantic import BaseModel, ConfigDict, Field, InstanceOf, model_validator

from browser_use.browser.types import BrowserProfile

# Check if running in Docker
IN_DOCKER = os.environ.get('IN_DOCKER', 'false').lower()[0] in 'ty1'

logger = logging.getLogger('browser_use.browser.session')


def truncate_url(s: str, max_len: int | None = None) -> str:
	"""Truncate/pretty-print a URL with a maximum length, removing the protocol and www. prefix"""
	s = s.replace('https://', '').replace('http://', '').replace('www.', '')
	if max_len is not None and len(s) > max_len:
		return s[:max_len] + '…'
	return s


def require_initialization(func):
	"""decorator for BrowserSession methods to require the BrowserSession be already active"""

	@wraps(func)
	def wrapper(self, *args, **kwargs):
		if not self.initialized:
			raise RuntimeError('BrowserSession(...).start() must be called first to launch or connect to the browser')
		return func(self, *args, **kwargs)

	return wrapper


DEFAULT_BROWSER_PROFILE = BrowserProfile()


class BrowserSession(BaseModel):
	"""
	Represents an active browser session with a running browser process somewhere.

	Chromium flags should be passed via extra_launch_args.
	Extra Playwright launch options (e.g., handle_sigterm, handle_sigint) can be passed as kwargs to BrowserSession and will be forwarded to the launch() call.
	"""

	model_config = ConfigDict(
		extra='allow', validate_assignment=False, revalidate_instances='always', frozen=False, arbitrary_types_allowed=True
	)
	# this class accepts arbitrary extra **kwargs in init because of the extra='allow' pydantic option
	# they are saved on the model, then applied to self.browser_profile via .apply_session_overrides_to_profile()

	# template profile for the BrowserSession, will be copied at init/validation time, and overrides applied to the copy
	browser_profile: InstanceOf[BrowserProfile] = Field(
		default=DEFAULT_BROWSER_PROFILE, description='BrowserProfile() instance containing config for the BrowserSession'
	)

	# runtime state: connection and process handles
	wss_url: str | None = Field(
		default=None,
		description='WSS URL of the node.js playwright browser server to connect to, outputted by (await chromium.launchServer()).wsEndpoint()',
	)
	cdp_url: str | None = Field(
		default=None,
		description='CDP URL of the browser to connect to, e.g. http://localhost:9222 or ws://127.0.0.1:9222/devtools/browser/387adf4c-243f-4051-a181-46798f4a46f4',
	)
	chrome_process: psutil.Process | None = Field(
		default=None, description='psutil Process object for the running chrome process to connect to (optional)'
	)
	playwright: Playwright | None = Field(
		default=None, description='Playwright library object returned by (playwright or patchright).async_playwright().start()'
	)
	browser: InstanceOf[PlaywrightBrowser] | None = Field(default=None, description='playwright Browser object to use (optional)')
	browser_context: InstanceOf[PlaywrightBrowserContext] | None = Field(
		default=None, description='playwright BrowserContext object to use (optional)'
	)
	initialized: bool = Field(
		default=False, description='Skip BrowserSession launch/connection setup entirely if True (not recommended)'
	)

	# runtime state: internally tracked attrs updated by BrowserSession class methods
	agent_current_page: InstanceOf[Page] | None = Field(default=None, description='Foreground Page that the agent is focused on')
	human_current_page: InstanceOf[Page] | None = Field(default=None, description='Foreground Page that the human is focused on')

	def __getattr__(self, key: str) -> Any:
		# fall back to getting attributes from BrowserProfile when not found on BrowserSession
		return getattr(self.browser_profile, key)

	@model_validator(mode='after')
	def apply_session_overrides_to_profile(self) -> Self:
		session_own_fields = type(self).model_fields.keys()
		overrides = self.model_dump(exclude=session_own_fields)
		self.browser_profile = self.browser_profile.model_copy(update=overrides)
		return self

	async def start(self) -> Self:
		# unlock the user data dir for first-run initialization
		assert isinstance(self.browser_profile, BrowserProfile)
		self.browser_profile.prepare_user_data_dir()
		self.browser_profile.detect_display_configuration()

		# setup playwright, Browser, and BrowserContext objects
		await self.setup_playwright()
		await self.setup_browser_connection()
		await self.setup_browser_context()
		assert self.browser_context

		# resize the existing pages and set up foreground tab detection
		await self.setup_viewport_sizing()
		await self.setup_foreground_tab_detection()

		self.initialized = True

		return self

	async def stop(self) -> None:
		if not self.browser_profile.keep_alive:
			logger.info('🛑 Shutting down browser...')
			await self.browser_context.close()
			await self.browser.close()

			# kill the chrome subprocess if we were the ones that started it
			if self.chrome_process:
				self.chrome_process.terminate()

	async def __aenter__(self) -> BrowserSession:
		await self.start()
		return self

	async def __aexit__(self, exc_type, exc_val, exc_tb):
		await self.stop()

	async def setup_playwright(self) -> None:
		"""Override to customize the set up of the playwright or patchright library object"""
		self.playwright = self.playwright or await async_playwright().start()
		return self.playwright

	async def setup_browser_connection(self) -> None:
		"""Override to customize the set up of the connection to an existing browser"""

		# if process is provided, calcuclate its CDP URL by looking for --remote-debugging-port=... in the launch args
		if self.chrome_process:
			assert isinstance(self.chrome_process, psutil.Process) and self.chrome_process.is_running(), (
				'Chrome process is not running'
			)
			args = self.chrome_process.cmdline()
			debug_port = next((arg for arg in args if arg.startswith('--remote-debugging-port=')), '').split('=')[-1].strip()
			assert debug_port, (
				f'Could not connect because could not find --remote-debugging-port=... in chrome launch args: pid={self.chrome_process.pid} {self.chrome_process.cmdline()}'
			)
			# we could automatically relaunch the browser process with that arg added here, but they may have tabs open they dont want to lose
			self.cdp_url = self.cdp_url or f'http://localhost:{debug_port}/'
			logger.info(f'🌎 Connecting to existing chromium process: pid={self.chrome_process.pid} on {self.cdp_url}')

		if self.wss_url:
			logger.info(f'🌎 Connecting to remote chromium playwright node.js server over WSS: {self.wss_url}')
			self.browser = self.browser or await self.playwright.chromium.connect(
				self.wss_url,
				**self.browser_profile.kwargs_for_connect().model_dump(),
			)
			# dont default to closing the browser when the BrowserSession is over if we connect by WSS
			if self.browser_profile.keep_alive is None:
				self.browser_profile.keep_alive = True
		elif self.cdp_url:
			logger.info(f'🌎 Connecting to remote chromium browser over CDP: {self.cdp_url}')
			self.browser = self.browser or await self.playwright.chromium.connect_over_cdp(
				self.cdp_url,
				**self.browser_profile.kwargs_for_connect().model_dump(),
			)
			# dont default to closing the browser when the BrowserSession is over if we connect by CDP
			if self.browser_profile.keep_alive is None:
				self.browser_profile.keep_alive = True

		# self.browser may still be None at this point if we have no config implying we should connect to an existing browser
		# self.setup_browser_context() will be called next and if it finds self.browser is None, it will
		# launch a new browser+context all in one go using launch_persistent_context()

		return self.browser

	async def setup_browser_context(self) -> None:
		# if we have a browser_context but no browser, use the browser from the context
		if self.browser_context:
			logger.info(f'🌎 Using existing user-provided browser_context and browser: {self.browser_context}')
			self.browser = self.browser or self.browser_context.browser
			# dont default to closing the browser when the BrowserSession is over if we are passed an external browser
			if self.browser_profile.keep_alive is None:
				self.browser_profile.keep_alive = True

		current_process = psutil.Process(os.getpid())
		child_pids_before_launch = {child.pid for child in current_process.children(recursive=True)}

		# if we have a browser object but no browser_context, use the first context discovered or make a new one
		if self.browser and not self.browser_context:
			if self.browser.contexts:
				self.browser_context = self.browser.contexts[0]
				logger.info(f'🌎 Using first browser_context available in user-provided browser: {self.browser_context}')
			else:
				self.browser_context = await self.browser.new_context(
					**self.browser_profile.kwargs_for_new_context().model_dump()
				)
				storage_info = (
					f' + loaded storage_state={len(self.browser_profile.storage_state.cookies) if self.browser_profile.storage_state else 0} cookies'
					if self.browser_profile.storage_state
					else ''
				)
				logger.info(f'🌎 Created new empty browser_context in existing browser{storage_info}: {self.browser_context}')

		# if we still have no browser_context by now, launch a new local one using launch_persistent_context()
		if not self.browser_context:
			logger.info(f'🌎 Launching local playwright chromium context with user_data_dir={self.browser_profile.user_data_dir}')
			self.browser_context = await self.playwright.chromium.launch_persistent_context(
				**self.browser_profile.kwargs_for_launch_persistent_context().model_dump()
			)
			self.browser = self.browser_context.browser
			# ^ this is unfortunately = None ^ playwright does not give us a browser object when we use launch_persistent_context()

		# Detect any new child chrome processes that we might have launched above
		child_pids_after_launch = {child.pid for child in current_process.children(recursive=True)}
		new_child_pids = child_pids_after_launch - child_pids_before_launch
		new_child_procs = [psutil.Process(pid) for pid in new_child_pids]
		new_chrome_procs = [proc for proc in new_child_procs if 'Helper' not in proc.name() and proc.status() == 'running']
		if new_chrome_procs and not self.chrome_process:
			self.chrome_process = new_chrome_procs[0]
			logger.debug(f' ↳ Spawned chrome subprocess: pid={self.chrome_process.pid} {" ".join(self.chrome_process.cmdline())}')
			# default to closing the browser ourselves when the BrowserSession is over if we launched it ourselves
			if self.browser_profile.keep_alive is None:
				self.browser_profile.keep_alive = False

		if self.browser:
			assert self.browser.is_connected(), 'Browser is not connected, did the browser process crash or get killed?'
		assert self.browser_context, f'BrowserContext {self.browser_context} is not set up'

		return self.browser_context

	async def setup_foreground_tab_detection(self) -> None:
		# Uses a combination of:
		# - visibilitychange events
		# - window focus/blur events
		# - pointermove events

		# This multi-method approach provides more reliable detection across browsers.

		# TODO: pester the playwright team to add a new event that fires when a headful tab is focused.
		# OR implement a browser-use chrome extension that acts as a bridge to the chrome.tabs API.

		#         - https://github.com/microsoft/playwright/issues/1290
		#         - https://github.com/microsoft/playwright/issues/2286
		#         - https://github.com/microsoft/playwright/issues/3570
		#         - https://github.com/microsoft/playwright/issues/13989

		# set up / detect foreground page
		pages = self.browser_context.pages
		foreground_page = None
		if pages:
			foreground_page = pages[0]
			logger.debug(f'👁️ Found {len(pages)} existing pages in browser, agent will start with: {foreground_page.url}')
		else:
			foreground_page = await self.browser_context.new_page()
			pages = [foreground_page]
			logger.debug('📄 Opened new page in empty fresh browser context...')

		self.agent_current_page = self.agent_current_page or foreground_page
		self.human_current_page = self.human_current_page or foreground_page

		def _BrowserUseonTabVisibilityChange(source):
			new_page = source['page']

			# Update human foreground tab state
			old_foreground = self.human_current_page
			self.human_current_page = new_page

			# Log before and after for debugging
			if old_foreground.url != new_page.url:
				logger.info(
					f'👁️ Foregound tab changed by human from {truncate_url(old_foreground.url, 22) if old_foreground else "about:blank"} '
					f'➡️ {truncate_url(new_page.url, 22)} '
					f'(agent will stay on {truncate_url(self.agent_current_page.url, 22)})'
				)
			return new_page.url

		await self.browser_context.expose_binding('_BrowserUseonTabVisibilityChange', _BrowserUseonTabVisibilityChange)
		update_tab_focus_script = """
			// --- Method 1: visibilitychange event (unfortunately *all* tabs are always marked visible by playwright, usually does not fire) ---
			document.addEventListener('visibilitychange', async () => {
				if (document.visibilityState === 'visible') {
					await window._BrowserUseonTabVisibilityChange({ source: 'visibilitychange', url: document.location.href });
					console.log('BrowserUse Foreground tab change event fired', document.location.href);
				}
			});
			
			// --- Method 2: focus/blur events, most reliable method for headful browsers ---
			window.addEventListener('focus', async () => {
				await window._BrowserUseonTabVisibilityChange({ source: 'focus', url: document.location.href });
				console.log('BrowserUse Foreground tab change event fired', document.location.href);
			});
			
			// --- Method 3: pointermove events (may be fired by agent if we implement AI hover movements) ---
			// Use a throttled handler to avoid excessive calls
			// let lastMove = 0;
			// window.addEventListener('pointermove', async () => {
			// 	const now = Date.now();
			// 	if (now - lastMove > 1000) {  // Throttle to once per second
			// 		lastMove = now;
			// 		await window._BrowserUseonTabVisibilityChange({ source: 'pointermove', url: document.location.href });
			//      console.log('BrowserUse Foreground tab change event fired', document.location.href);
			// 	}
			// });
		"""
		await self.browser_context.add_init_script(update_tab_focus_script)

		# set the user agent to the one we want
		# Set up visibility listeners for all existing tabs
		for page in self.browser_context.pages:
			if not page.url.startswith('chrome-extension://') and not page.url.startswith('chrome://') and not page.is_closed():
				await page.evaluate(update_tab_focus_script)
				# logger.debug(f'👁️ Added visibility listener to existing tab: {page.url}')

	async def setup_viewport_sizing(self) -> None:
		"""Resize any existing page viewports to match the configured size"""

		if not self.browser_context.pages:
			return

		# First, set the viewport size on any existing pages
		use_viewport = (not self.browser_profile.no_viewport) and self.viewport
		if use_viewport:
			logger.debug(
				'👁️ Resizing existing pages '
				f'headless={self.browser_profile.headless}'
				f'use_viewport={use_viewport} '
				f'screen={self.browser_profile.screen["width"] if self.browser_profile.screen else "0"}x{self.browser_profile.screen["height"] if self.browser_profile.screen else "0"} '
				f'window={self.browser_profile.window_size["width"] if self.browser_profile.window_size else "0"}x{self.browser_profile.window_size["height"] if self.browser_profile.window_size else "0"} '
				f'viewport={self.browser_profile.viewport["width"] if self.browser_profile.viewport else "0"}x{self.browser_profile.viewport["height"] if self.browser_profile.viewport else "0"} '
			)
			for page in self.browser_context.pages:
				await page.set_viewport_size(self.browser_profile.viewport)

	# --- Tab management ---
	@property
	def tabs(self) -> list[Page]:
		if not self.browser_context:
			return []
		return list(self.browser_context.pages)

	@require_initialization
	async def new_tab(self, url: str | None = None) -> Page:
		page = await self.browser_context.new_page()
		if url:
			await page.goto(url)
		self.agent_current_page = page
		self.human_current_page = page
		return page

	@require_initialization
	async def switch_tab(self, tab_index: int) -> Page:
		pages = self.tabs
		if not pages or tab_index >= len(pages):
			raise IndexError('Tab index out of range')
		page = pages[tab_index]
		self.agent_current_page = page
		self.human_current_page = page
		return page

	@require_initialization
	async def wait_for_element(self, selector: str, timeout: int = 10000) -> None:
		await self.agent_current_page.wait_for_selector(selector, timeout=timeout)

	@require_initialization
	async def get_current_page(self) -> Page | None:
		"""Get the current page. Used by controller/agent."""
		return self.agent_current_page

	@require_initialization
	async def go_back(self) -> None:
		"""Navigate back. Used by controller/agent."""
		if self.agent_current_page:
			await self.agent_current_page.go_back()

	@require_initialization
	async def get_selector_map(self) -> dict[int, Any]:
		"""Get selector map for the current page."""
		if not self.agent_current_page:
			return {}

		from browser_use.dom.service import DomService

		dom_service = DomService(self.agent_current_page)
		dom_state = await dom_service.get_clickable_elements(
			highlight_elements=self.browser_profile.highlight_elements, viewport_expansion=self.browser_profile.viewport_expansion
		)
		return dom_state.selector_map

	@require_initialization
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

	@require_initialization
	async def get_dom_element_by_index(self, index: int) -> Any | None:
		"""Get DOM element by index."""
		selector_map = await self.get_selector_map()
		return selector_map.get(index)

	@require_initialization
	async def is_file_uploader(self, element: Any) -> bool:
		"""Check if element is a file uploader."""
		if not self.agent_current_page or not element:
			return False

		# Check if the element is an input with type=file
		if element.tag_name.lower() == 'input' and element.attributes.get('type') == 'file':
			return True

		# Or if it has an ancestor that's an input with type=file
		xpath = element.xpath
		try:
			file_inputs = await self.agent_current_page.query_selector_all('input[type="file"]')
			for file_input in file_inputs:
				if await file_input.is_visible():
					return True
		except Exception as e:
			logging.warning(f'Error checking if element is file uploader: {e}')

		return False

	@require_initialization
	async def _click_element_node(self, element: Any) -> str | None:
		"""
		Click on a DOM element node.
		Returns download path if a download was triggered, None otherwise.
		"""
		if not self.agent_current_page or not element:
			return None

		if not hasattr(element, 'xpath') or not element.xpath:
			logging.warning('Element has no xpath')
			return None

		try:
			# Use the xpath to find the element
			element_handle = await self.agent_current_page.query_selector_all(f'xpath={element.xpath}')
			if not element_handle or len(element_handle) == 0:
				logging.warning(f'Element not found with xpath: {element.xpath}')
				return None

			# Click the element
			await element_handle[0].scroll_into_view_if_needed()
			await element_handle[0].click()

			# Check if a download was triggered
			# This would require tracking downloads and returning the path
			# For now, we'll return None as a placeholder
			return None
		except Exception as e:
			logging.warning(f'Error clicking element: {e}')
			return None

	@require_initialization
	async def _input_text_element_node(self, element: Any, text: str) -> None:
		"""Input text into an element node."""
		if not self.agent_current_page or not element:
			return

		if not hasattr(element, 'xpath') or not element.xpath:
			logging.warning('Element has no xpath')
			return

		try:
			# Use the xpath to find the element
			element_handle = await self.agent_current_page.query_selector_all(f'xpath={element.xpath}')
			if not element_handle or len(element_handle) == 0:
				logging.warning(f'Element not found with xpath: {element.xpath}')
				return

			# Clear existing text (if any) and input new text
			await element_handle[0].click()
			await element_handle[0].fill(text)
		except Exception as e:
			logging.warning(f'Error inputting text to element: {e}')
			return

	@require_initialization
	async def close_tab(self, tab_index: int | None = None) -> None:
		pages = self.tabs
		if not pages:
			return
		if tab_index is None:
			page = self.agent_current_page or pages[0]
		else:
			page = pages[tab_index]
		await page.close()
		# Update current page refs
		remaining = self.tabs
		if remaining:
			self.agent_current_page = remaining[0]
			self.human_current_page = remaining[0]
		else:
			self.agent_current_page = None
			self.human_current_page = None

	# --- Page navigation ---
	@require_initialization
	async def navigate(self, url: str) -> None:
		if not self.agent_current_page:
			await self.new_tab(url)
		else:
			await self.agent_current_page.goto(url)

	@require_initialization
	async def refresh(self) -> None:
		if self.agent_current_page:
			await self.agent_current_page.reload()

	# --- State and info ---
	@require_initialization
	async def get_state(self) -> dict[str, Any]:
		"""Return a dict with basic session state info (for compatibility)."""
		return {
			'current_url': self.agent_current_page.url if self.agent_current_page else None,
			'tabs': [p.url for p in self.tabs],
			'downloads_dir': str(self.browser_profile.downloads_dir),
			'uploads_dir': str(self.browser_profile.uploads_dir) if self.browser_profile.uploads_dir else None,
		}

	@require_initialization
	async def take_screenshot(self, full_page: bool = False) -> bytes | None:
		if self.agent_current_page:
			return await self.agent_current_page.screenshot(full_page=full_page)
		return None

	@require_initialization
	async def execute_javascript(self, script: str) -> Any:
		if self.agent_current_page:
			return await self.agent_current_page.evaluate(script)
		return None

	async def get_cookies(self) -> list[dict[str, Any]]:
		if self.browser_context:
			return await self.browser_context.cookies()
		return []

	async def save_cookies(self, path: Path | None = None) -> None:
		"""
		Save cookies to the specified path or the default cookies_file in the downloads_dir.
		"""
		if self.browser_context:
			cookies = await self.browser_context.cookies()
			out_path = path or self.browser_profile.cookies_file
			if out_path:
				# If out_path is not absolute, resolve relative to downloads_dir
				out_path = Path(out_path)
				if not out_path.is_absolute():
					out_path = Path(self.browser_profile.downloads_dir) / out_path
				out_path.parent.mkdir(parents=True, exist_ok=True)
				out_path.write_text(json.dumps(cookies, indent=4))  # TODO: replace with anyio asyncio write

	# --- Compatibility properties for old API ---
	@property
	def browser_pages(self) -> list[Page]:
		return self.tabs

	@property
	def browser_extension_pages(self) -> list[Page]:
		if not self.browser_context:
			return []
		return [p for p in self.browser_context.pages if p.url.startswith('chrome-extension://')]

	@property
	def saved_downloads(self) -> list[Path]:
		"""
		Return a list of files in the downloads_dir.
		"""
		return list(Path(self.browser_profile.downloads_dir).glob('*'))
