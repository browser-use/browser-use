"""
Playwright browser on steroids.
"""

import asyncio
import base64
import logging
import time
from dataclasses import dataclass

from playwright.async_api import Browser as PlaywrightBrowser
from playwright.async_api import BrowserContext, ElementHandle, Page, Playwright, async_playwright

from browser_use.browser.views import BrowserError, BrowserState, TabInfo
from browser_use.dom.service import DomService
from browser_use.dom.views import SelectorMap
from browser_use.utils import time_execution_sync

logger = logging.getLogger(__name__)


@dataclass
class BrowserSession:
	playwright: Playwright
	browser: PlaywrightBrowser
	context: BrowserContext
	current_page: Page
	cached_state: BrowserState
	# current_page_id: str
	# opened_tabs: dict[str, TabInfo] = field(default_factory=dict)


class Browser:
	MINIMUM_WAIT_TIME = 0.5
	MAXIMUM_WAIT_TIME = 5

	def __init__(self, headless: bool = False, keep_open: bool = False):
		self.headless = headless
		self.keep_open = keep_open

		# Initialize these as None - they'll be set up when needed
		self.session: BrowserSession | None = None

	async def _initialize_session(self):
		"""Initialize the browser session"""
		playwright = await async_playwright().start()
		browser = await self._setup_browser(playwright)
		context = await self._create_context(browser)
		page = await context.new_page()

		# Instead of calling _update_state(), create an empty initial state
		initial_state = BrowserState(
			items=[],
			selector_map={},
			url=page.url,
			title=await page.title(),
			screenshot=None,
			tabs=[],
		)

		self.session = BrowserSession(
			playwright=playwright,
			browser=browser,
			context=context,
			current_page=page,
			cached_state=initial_state,
		)

		return self.session

	async def get_session(self) -> BrowserSession:
		"""Lazy initialization of the browser and related components"""
		if self.session is None:
			return await self._initialize_session()
		return self.session

	async def get_current_page(self) -> Page:
		"""Get the current page"""
		session = await self.get_session()
		return session.current_page

	async def _setup_browser(self, playwright: Playwright) -> PlaywrightBrowser:
		"""Sets up and returns a Playwright Browser instance with anti-detection measures."""
		try:
			browser = await playwright.chromium.launch(
				headless=self.headless,
				ignore_default_args=['--enable-automation'],  # Helps with anti-detection
				args=[
					'--no-sandbox',
					'--disable-blink-features=AutomationControlled',
					'--disable-extensions',
					'--disable-infobars',
					'--disable-background-timer-throttling',
					'--disable-popup-blocking',
					'--disable-backgrounding-occluded-windows',
					'--disable-renderer-backgrounding',
					'--disable-window-activation',
					'--disable-focus-on-load',  # Prevents focus on navigation
					'--no-first-run',
					'--no-default-browser-check',
					'--no-startup-window',  # Prevents initial focus
					'--window-position=0,0',
				],
			)

			return browser
		except Exception as e:
			logger.error(f'Failed to initialize Playwright browser: {str(e)}')
			raise

	async def _create_context(self, browser: PlaywrightBrowser):
		"""Creates a new browser context with anti-detection measures."""
		context = await browser.new_context(
			viewport={'width': 1280, 'height': 1024},
			user_agent=(
				'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
				'(KHTML, like Gecko) Chrome/85.0.4183.102 Safari/537.36'
			),
			java_script_enabled=True,
		)

		# Expose anti-detection scripts
		await context.add_init_script(
			"""
			// Webdriver property
			Object.defineProperty(navigator, 'webdriver', {
				get: () => undefined
			});

			// Languages
			Object.defineProperty(navigator, 'languages', {
				get: () => ['en-US', 'en']
			});

			// Plugins
			Object.defineProperty(navigator, 'plugins', {
				get: () => [1, 2, 3, 4, 5]
			});

			// Chrome runtime
			window.chrome = { runtime: {} };

			// Permissions
			const originalQuery = window.navigator.permissions.query;
			window.navigator.permissions.query = (parameters) => (
				parameters.name === 'notifications' ?
					Promise.resolve({ state: Notification.permission }) :
					originalQuery(parameters)
			);
			"""
		)

		return context

	async def wait_for_page_load(self, timeout_overwrite: float | None = None):
		"""
		Ensures page is fully loaded before continuing.
		Waits for either document.readyState to be complete or minimum WAIT_TIME, whichever is longer.
		"""
		page = await self.get_current_page()

		# Start timing
		start_time = time.time()

		# Wait for page load
		try:
			await page.wait_for_load_state('load', timeout=5000)
		except Exception:
			pass

		# Calculate remaining time to meet minimum WAIT_TIME
		elapsed = time.time() - start_time
		remaining = max((timeout_overwrite or self.MINIMUM_WAIT_TIME) - elapsed, 0)

		logger.debug(
			f'--Page loaded in {elapsed:.2f} seconds, waiting for additional {remaining:.2f} seconds'
		)

		# Sleep remaining time if needed
		if remaining > 0:
			await asyncio.sleep(remaining)

	async def close(self, force: bool = False):
		"""Close the browser instance"""
		if force and not self.keep_open:
			session = await self.get_session()
			await session.browser.close()
			await session.playwright.stop()
		else:
			# Note: input() is blocking - consider an async alternative if needed
			# input('Press Enter to close Browser...')
			self.keep_open = False
			await self.close(force=True)

	def __del__(self):
		"""Async cleanup when object is destroyed"""
		if self.session is not None:
			asyncio.run(self.close(force=True))

	async def navigate_to(self, url: str):
		"""Navigate to a URL"""
		page = await self.get_current_page()
		await page.goto(url)
		await self.wait_for_page_load()

	async def refresh_page(self):
		"""Refresh the current page"""
		page = await self.get_current_page()
		await page.reload()
		await self.wait_for_page_load()

	async def go_back(self):
		"""Navigate back in history"""
		page = await self.get_current_page()
		await page.go_back()
		await self.wait_for_page_load()

	async def go_forward(self):
		"""Navigate forward in history"""
		page = await self.get_current_page()
		await page.go_forward()
		await self.wait_for_page_load()

	async def close_current_tab(self):
		"""Close the current tab"""
		session = await self.get_session()
		page = session.current_page
		await page.close()

		# Switch to the first available tab if any exist
		if session.context.pages:
			await self.switch_to_tab(0)

		# otherwise the browser will be closed

	async def get_page_html(self) -> str:
		"""Get the current page HTML content"""
		page = await self.get_current_page()
		return await page.content()

	async def execute_javascript(self, script: str):
		"""Execute JavaScript code on the page"""
		page = await self.get_current_page()
		return await page.evaluate(script)

	@time_execution_sync('--get_state')  # This decorator might need to be updated to handle async
	async def get_state(self, use_vision: bool = False) -> BrowserState:
		"""Get the current state of the browser"""
		session = await self.get_session()
		session.cached_state = await self._update_state(use_vision=use_vision)
		return session.cached_state

	async def _update_state(self, use_vision: bool = False) -> BrowserState:
		"""Update and return state."""
		page = await self.get_current_page()
		dom_service = DomService(page)
		content = await dom_service.get_clickable_elements()  # Assuming this is async

		screenshot_b64 = None
		if use_vision:
			screenshot_b64 = await self.take_screenshot(selector_map=content.selector_map)

		self.current_state = BrowserState(
			items=content.items,
			selector_map=content.selector_map,
			url=page.url,
			title=await page.title(),
			tabs=await self.get_tabs_info(),
			screenshot=screenshot_b64,
		)

		return self.current_state

	# region - Browser Actions

	async def take_screenshot(
		self, selector_map: SelectorMap | None, full_page: bool = False
	) -> str:
		"""
		Returns a base64 encoded screenshot of the current page.
		"""
		page = await self.get_current_page()

		if selector_map:
			await self.highlight_selector_map_elements(selector_map)

		screenshot = await page.screenshot(
			full_page=full_page,
			animations='disabled',
		)

		screenshot_b64 = base64.b64encode(screenshot).decode('utf-8')

		if selector_map:
			await self.remove_highlights()

		return screenshot_b64

	async def highlight_selector_map_elements(self, selector_map: SelectorMap):
		page = await self.get_current_page()
		await self.remove_highlights()

		script = """
		const highlights = {
		"""

		# Build the highlights object with all selectors and indices
		for index, selector in selector_map.items():
			# Adjusting the JavaScript code to accept variables
			script += f'"{index}": "{selector}",\n'

		script += """
		};
		
		for (const [index, selector] of Object.entries(highlights)) {
			const el = document.evaluate(selector, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
			if (!el) continue;  // Skip if element not found
			el.style.outline = "2px solid red";
			el.setAttribute('browser-user-highlight-id', 'playwright-highlight');
			
			const label = document.createElement("div");
			label.className = 'playwright-highlight-label';
			label.style.position = "fixed";
			label.style.background = "red";
			label.style.color = "white";
			label.style.padding = "2px 6px";
			label.style.borderRadius = "10px";
			label.style.fontSize = "12px";
			label.style.zIndex = "9999999";
			label.textContent = index;
			const rect = el.getBoundingClientRect();
			label.style.top = (rect.top - 20) + "px";
			label.style.left = rect.left + "px";
			document.body.appendChild(label);
		}
		"""

		await page.evaluate(script)

	async def remove_highlights(self):
		"""
		Removes all highlight outlines and labels created by highlight_selector_map_elements

		"""
		page = await self.get_current_page()
		await page.evaluate(
			"""
			// Remove all highlight outlines
			const highlightedElements = document.querySelectorAll('[browser-user-highlight-id="playwright-highlight"]');
			highlightedElements.forEach(el => {
				el.style.outline = '';
				el.removeAttribute('browser-user-highlight-id');
			});
			

			// Remove all labels
			const labels = document.querySelectorAll('.playwright-highlight-label');
			labels.forEach(label => label.remove());
			"""
		)

	# endregion

	# region - User Actions

	async def _input_text_by_xpath(self, xpath: str, text: str):
		page = await self.get_current_page()

		try:
			element = await page.wait_for_selector(f'xpath={xpath}', timeout=5000, state='visible')

			if element is None:
				raise Exception(f'Element with xpath: {xpath} not found')

			await element.scroll_into_view_if_needed(timeout=2500)
			await element.fill('')
			await element.type(text)
			await self.wait_for_page_load()

		except Exception as e:
			raise Exception(
				f'Failed to input text into element with xpath: {xpath}. Error: {str(e)}'
			)

	async def _click_element_by_xpath(self, xpath: str):
		"""
		Optimized method to click an element using xpath.
		"""
		page = await self.get_current_page()

		try:
			element = await page.wait_for_selector(f'xpath={xpath}', timeout=5000, state='visible')

			if element is None:
				raise Exception(f'Element with xpath: {xpath} not found')

			# await element.scroll_into_view_if_needed()

			try:
				await element.click(timeout=2500)
				await self.wait_for_page_load()
				return
			except Exception:
				pass

			try:
				await page.evaluate('(el) => el.click()', element)
				await self.wait_for_page_load()
				return
			except Exception as e:
				raise Exception(f'Failed to click element: {str(e)}')

		except Exception as e:
			raise Exception(f'Failed to click element with xpath: {xpath}. Error: {str(e)}')

	async def get_tabs_info(self) -> list[TabInfo]:
		"""Get information about all tabs"""
		session = await self.get_session()

		tabs_info = []
		for page_id, page in enumerate(session.context.pages):
			tab_info = TabInfo(page_id=page_id, url=page.url, title=await page.title())
			tabs_info.append(tab_info)

		return tabs_info

	async def switch_to_tab(self, page_id: int) -> None:
		"""Switch to a specific tab by its page_id

		@You can also use negative indices to switch to tabs from the end (Pure pythonic way)
		"""
		session = await self.get_session()
		pages = session.context.pages

		if page_id >= len(pages):
			raise BrowserError(f'No tab found with page_id: {page_id}')

		page = pages[page_id]
		session.current_page = page

		await page.bring_to_front()
		await self.wait_for_page_load()

	async def create_new_tab(self, url: str | None = None) -> None:
		"""Create a new tab and optionally navigate to a URL"""
		session = await self.get_session()
		new_page = await session.context.new_page()
		session.current_page = new_page

		await self.wait_for_page_load()

		page = await self.get_current_page()

		if url:
			await page.goto(url)
			await self.wait_for_page_load(timeout_overwrite=1)

	# endregion

	# region - Helper methods for easier access to the DOM
	async def get_selector_map(self) -> SelectorMap:
		session = await self.get_session()
		return session.cached_state.selector_map

	async def get_xpath(self, index: int) -> str:
		selector_map = await self.get_selector_map()
		return selector_map[index]

	async def get_element_by_index(self, index: int) -> ElementHandle | None:
		page = await self.get_current_page()
		return await page.wait_for_selector(
			await self.get_xpath(index), timeout=2500, state='visible'
		)

	# endregion
