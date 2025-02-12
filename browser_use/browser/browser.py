"""
Playwright browser on steroids.
"""

import asyncio
import gc
import logging
from dataclasses import dataclass, field

from playwright._impl._api_structures import ProxySettings
from playwright.async_api import Browser as PlaywrightBrowser
from playwright.async_api import (
	Playwright,
	async_playwright,
)

from browser_use.browser.context import BrowserContext, BrowserContextConfig

logger = logging.getLogger(__name__)


@dataclass
class BrowserConfig:
	r"""
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

		cdp_url: None
			Connect to a browser instance via CDP

		chrome_instance_path: None
			Path to a Chrome instance to use to connect to your normal browser
			e.g. '/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome'
	"""

	headless: bool = False
	disable_security: bool = True
	extra_chromium_args: list[str] = field(default_factory=list)
	chrome_instance_path: str | None = None
	wss_url: str | None = None
	cdp_url: str | None = None

	proxy: ProxySettings | None = field(default=None)
	new_context_config: BrowserContextConfig = field(default_factory=BrowserContextConfig)

	_force_keep_browser_alive: bool = False


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

		self.disable_security_args = []
		if self.config.disable_security:
			self.disable_security_args = [
				'--disable-web-security',
				'--disable-site-isolation-trials',
				'--disable-features=IsolateOrigins,site-per-process',
			]

	async def new_context(self, config: BrowserContextConfig = BrowserContextConfig()) -> BrowserContext:
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

	async def _setup_cdp(self, playwright: Playwright) -> PlaywrightBrowser:
		"""Sets up and returns a Playwright Browser instance with anti-detection measures."""
		if not self.config.cdp_url:
			raise ValueError('CDP URL is required')
		logger.info(f'Connecting to remote browser via CDP {self.config.cdp_url}')
		browser = await playwright.chromium.connect_over_cdp(self.config.cdp_url)
		return browser

	async def _setup_wss(self, playwright: Playwright) -> PlaywrightBrowser:
		"""Sets up and returns a Playwright Browser instance with anti-detection measures."""
		if not self.config.wss_url:
			raise ValueError('WSS URL is required')
		logger.info(f'Connecting to remote browser via WSS {self.config.wss_url}')
		browser = await playwright.chromium.connect(self.config.wss_url)
		return browser

	async def _setup_browser_with_instance(self, playwright: Playwright) -> PlaywrightBrowser:
		"""Sets up and returns a Playwright Browser instance with anti-detection measures."""
		if not self.config.chrome_instance_path:
			raise ValueError('Chrome instance path is required')
		import subprocess

		import requests

		try:
			# Check if browser is already running
			response = requests.get('http://localhost:9222/json/version', timeout=2)
			if response.status_code == 200:
				logger.info('Reusing existing Chrome instance')
				browser = await playwright.chromium.connect_over_cdp(
					endpoint_url='http://localhost:9222',
					timeout=20000,  # 20 second timeout for connection
				)
				return browser
		except requests.ConnectionError:
			logger.debug('No existing Chrome instance found, starting a new one')

		# Start a new Chrome instance
		subprocess.Popen(
			[
				self.config.chrome_instance_path,
				'--remote-debugging-port=9222',
			]
			+ self.config.extra_chromium_args,
			stdout=subprocess.DEVNULL,
			stderr=subprocess.DEVNULL,
		)

		# Attempt to connect again after starting a new instance
		for _ in range(10):
			try:
				response = requests.get('http://localhost:9222/json/version', timeout=2)
				if response.status_code == 200:
					break
			except requests.ConnectionError:
				pass
			await asyncio.sleep(1)

		# Attempt to connect again after starting a new instance
		try:
			browser = await playwright.chromium.connect_over_cdp(
				endpoint_url='http://localhost:9222',
				timeout=20000,  # 20 second timeout for connection
			)
			return browser
		except Exception as e:
			logger.error(f'Failed to start a new Chrome instance.: {str(e)}')
			raise RuntimeError(
				' To start chrome in Debug mode, you need to close all existing Chrome instances and try again otherwise we can not connect to the instance.'
			)

	async def _setup_standard_browser(self, playwright: Playwright) -> PlaywrightBrowser:
		"""Sets up and returns a Playwright Browser instance with anti-detection measures."""
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
				# '--window-size=1280,1000',
			]
			+ self.disable_security_args
			+ self.config.extra_chromium_args,
			proxy=self.config.proxy,
		)
		# convert to Browser
		return browser

	async def _setup_browser(self, playwright: Playwright) -> PlaywrightBrowser:
		"""Sets up and returns a Playwright Browser instance with anti-detection measures."""
		try:
			if self.config.cdp_url:
				return await self._setup_cdp(playwright)
			if self.config.wss_url:
				return await self._setup_wss(playwright)
			elif self.config.chrome_instance_path:
				return await self._setup_browser_with_instance(playwright)
			else:
				return await self._setup_standard_browser(playwright)
		except Exception as e:
			logger.error(f'Failed to initialize Playwright browser: {str(e)}')
			raise

	async def close(self):
		"""Close the browser instance"""
		try:
			if not self.config._force_keep_browser_alive:
				if self.playwright_browser:
					await self.playwright_browser.close()
					del self.playwright_browser
				if self.playwright:
					await self.playwright.stop()
					del self.playwright

		except Exception as e:
			logger.debug(f'Failed to close browser properly: {e}')
		finally:
			self.playwright_browser = None
			self.playwright = None

			gc.collect()

	def __del__(self):
		"""Async cleanup when object is destroyed"""
		try:
			if self.playwright_browser or self.playwright:
				loop = asyncio.get_running_loop()
				if loop.is_running():
					loop.create_task(self.close())
				else:
					asyncio.run(self.close())
		except Exception as e:
			logger.debug(f'Failed to cleanup browser in destructor: {e}')
