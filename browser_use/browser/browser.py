"""
Playwright browser on steroids.
"""

import asyncio
import logging
from typing import Union
from dataclasses import dataclass, field

from playwright.async_api import Browser as PlaywrightBrowser, BrowserContext as PlaywrightBrowserContext

from playwright.async_api import (
	Playwright,
	async_playwright,
)

from browser_use.browser.context import BrowserContext, BrowserContextConfig

logger = logging.getLogger(__name__)


@dataclass
class BrowserConfig:
	"""
	Configuration for the Browser.

	Default values:
		headless: True
			Whether to run browser in headless mode

		disable_security: False
			Disable browser security features

		extra_chromium_args: []
			Extra arguments to pass to the browser

		wss_url: None
			Connect to a browser instance via WebSocket
	"""

	headless: bool = True
	disable_security: bool = False
	extra_chromium_args: list[str] = field(default_factory=list)
	wss_url: str | None = None

	new_context_config: BrowserContextConfig = field(default_factory=BrowserContextConfig)


# @singleton: TODO - think about id singleton makes sense here
# @dev By default this is a singleton, but you can create multiple instances if you need to.
class Browser:
	"""
	Playwright browser on steroids.

	This is persistant browser factory that can spawn multiple browser contexts.
	It is recommended to use only one instance of Browser per your application (RAM usage will grow otherwise).
	"""

	def __init__(
		self,
		config: BrowserConfig = BrowserConfig(),
	):
		logger.debug('Initializing new browser')
		self.config = config
		self.playwright: Playwright | None = None
		self.playwright_browser: PlaywrightBrowser | None = None

	async def new_context(
		self, config: BrowserContextConfig = BrowserContextConfig()
	) -> BrowserContext:
		"""Create a browser context"""
		return BrowserContext(config=config, browser=self)

	async def get_playwright_browser(self) -> PlaywrightBrowser:
		"""Get a browser context"""
		if self.playwright_browser is None:
			return await self._init()

		return self.playwright_browser

	async def _init(self):
		"""Initialize the browser session"""
		playwright = await async_playwright().start()
		browser = await self._setup_browser(playwright)

		self.playwright = playwright
		self.playwright_browser = browser

		return self.playwright_browser

	async def _setup_browser(self, playwright: Playwright) -> Union[PlaywrightBrowser, PlaywrightBrowserContext]:
		"""Sets up and returns a Playwright Browser instance with anti-detection measures."""
		if self.config.wss_url:
			browser = await playwright.chromium.connect(self.config.wss_url)
			return browser

		else:
			try:
				disable_security_args = []
				if self.config.disable_security:
					disable_security_args = [
						'--disable-web-security',
						'--disable-site-isolation-trials',
						'--disable-features=IsolateOrigins,site-per-process',
					]

				if self.config.new_context_config.user_data_dir:
					browser = await playwright.chromium.launch_persistent_context(
						user_data_dir=self.config.new_context_config.user_data_dir,
						headless=self.config.headless,
						viewport=self.config.new_context_config.browser_window_size,
						user_agent=(
							'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
							'(KHTML, like Gecko) Chrome/85.0.4183.102 Safari/537.36'
						),
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
							# '--no-startup-window',  # Prevents initial focus
							'--window-position=0,0',
						],
					)
				else:
					browser = await playwright.chromium.launch(
						headless=self.config.headless,
						args=[
							'--no-sandbox',
							'--disable-blink-features=AutomationControlled',
							'--disable-infobars',
							'--disable-background-timer-throttling',
							'--disable-popup-blocking',
							'--disable-backgrounding-occluded-windows',
							'--disable-renderer-backgrounding',
							'--disable-window-activation',
							'--disable-focus-on-load',
							'--no-first-run',
							'--no-default-browser-check',
							'--no-startup-window',
							'--window-position=0,0',
						]
						+ disable_security_args
						+ self.config.extra_chromium_args,
					)

				return browser
			except Exception as e:
				logger.error(f'Failed to initialize Playwright browser: {str(e)}')
				raise

	async def close(self):
		"""Close the browser instance"""
		if self.playwright_browser:
			await self.playwright_browser.close()
		if self.playwright:
			await self.playwright.stop()

	def __del__(self):
		"""Async cleanup when object is destroyed"""
		try:
			loop = asyncio.get_running_loop()
			if loop.is_running():
				loop.create_task(self.close())
			else:
				asyncio.run(self.close())
		except RuntimeError:
			asyncio.run(self.close())
