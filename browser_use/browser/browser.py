"""
Playwright browser on steroids.
"""

import asyncio
import gc
import logging
import subprocess
from dataclasses import dataclass, field
from typing import Literal

import requests
from playwright._impl._api_structures import ProxySettings
from playwright.async_api import Browser as PlaywrightBrowser, Playwright, async_playwright

from browser_use.browser.context import BrowserContext, BrowserContextConfig
from browser_use.utils import time_execution_async

logger = logging.getLogger(__name__)


@dataclass
class BrowserConfig:
	"""
	Configuration for the Browser.

	Args:
		headless: Whether to run browser in headless mode (default: False)
		disable_security: Disable browser security features (default: True)
		extra_browser_args: Extra arguments to pass to the browser (default: [])
		browser_instance_path: Path to Browser executable (default: None)
		wss_url: WebSocket URL for remote browser connection (default: None)
		cdp_url: CDP URL for remote browser connection (default: None)
		proxy: Proxy settings for the browser (default: None)
		new_context_config: Configuration for new browser contexts (default: BrowserContextConfig())
		_force_keep_browser_alive: Force browser to stay alive (default: False)
	"""
	headless: bool = False
	disable_security: bool = True
	extra_browser_args: list[str] = field(default_factory=list)
	browser_instance_path: str | None = None
	wss_url: str | None = None
	cdp_url: str | None = None
	proxy: ProxySettings | None = None
	new_context_config: BrowserContextConfig = field(default_factory=BrowserContextConfig)
	_force_keep_browser_alive: bool = False
	browser_class: Literal['chromium', 'firefox', 'webkit'] = 'chromium'



class Browser:
	"""
	Playwright browser on steroids factory that spawn multiple browser contexts.
	Recommended to use as a singleton to optimize RAM usage.
	"""

	def __init__(self, config: BrowserConfig = BrowserConfig()):
		logger.debug('Initializing new browser')
		self.config = config
		self.playwright: Playwright | None = None
		self.playwright_browser: PlaywrightBrowser | None = None
		self.disable_security_args = self._get_security_args()

	def _get_security_args(self) -> list[str]:
		"""Return security-related arguments based on configuration."""
		if not self.config.disable_security:
			return []

		args = [
			"--disable-web-security",
			"--disable-site-isolation-trials",
			"--disable-features=IsolateOrigins,site-per-process",
		]

		if self.config.browser_class == 'chromium':
			args += ['--disable-features=IsolateOrigins,site-per-process']

		return args

	async def new_context(self, config: BrowserContextConfig = BrowserContextConfig()) -> BrowserContext:
		"""Create a new browser context."""
		return BrowserContext(config=config, browser=self)

	async def get_playwright_browser(self) -> PlaywrightBrowser:
		"""Get or initialize the Playwright browser instance."""
		if self.playwright_browser is None:
			return await self._init()
		return self.playwright_browser

	@time_execution_async("--init (browser)")
	async def _init(self) -> PlaywrightBrowser:
		"""Initialize the browser session."""
		self.playwright = await async_playwright().start()
		self.playwright_browser = await self._setup_browser(self.playwright)
		return self.playwright_browser

	async def _setup_browser(self, playwright: Playwright) -> PlaywrightBrowser:
		"""Sets up and returns a Playwright Browser instance with anti-detection measures."""
		try:
			if self.config.cdp_url:
				return await self._setup_cdp(playwright)
			if self.config.wss_url:
				return await self._setup_wss(playwright)
			if self.config.browser_instance_path:
				return await self._setup_browser_with_instance(playwright)
			return await self._setup_standard_browser(playwright)
		except Exception as e:
			logger.error(f'Failed to initialize Playwright browser: {str(e)}')
			raise

	async def _setup_cdp(self, playwright: Playwright) -> PlaywrightBrowser:
		"""Setup browser connection via Chrome DevTools Protocol(CDP)."""

		if 'firefox' in self.config.browser_instance_path.lower():
			raise ValueError('CDP has been deprecated for firefox, check: https://fxdx.dev/deprecating-cdp-support-in-firefox-embracing-the-future-with-webdriver-bidi/')
		if not self.config.cdp_url:
			raise ValueError('CDP URL is required')
		logger.info(f"Connecting to remote browser via CDP {self.config.cdp_url}")
		browser_class = getattr(playwright, self.config.browser_class)
		return await browser_class.connect_over_cdp(self.config.cdp_url)

	async def _setup_wss(self, playwright: Playwright) -> PlaywrightBrowser:
		"""Setup browser connection via WebSocket."""
		if not self.config.wss_url:
			raise ValueError('WSS URL is required')
		logger.info(f'Connecting to remote browser via WSS {self.config.wss_url}')
		browser_class = getattr(playwright, self.config.browser_class)
		browser = await browser_class.connect(self.config.wss_url)
		return browser

	async def _setup_browser_with_instance(self, playwright: Playwright) -> PlaywrightBrowser:
		"""Setup browser using existing Playwright Browser instance."""
		if not self.config.browser_instance_path:
			raise ValueError('Browser instance path is required')

		endpoint = 'http://localhost:9222'
		try:
			if requests.get(f'{endpoint}/json/version', timeout=2).status_code == 200:
				logger.info('Reusing existing Browser instance')
				browser_class = getattr(playwright, self.config.browser_class)
				browser = await browser_class.connect_over_cdp(
					endpoint_url='http://localhost:9222',
					timeout=20000,  # 20 second timeout for connection
				)
				return browser
		except requests.ConnectionError:
			logger.debug('No existing Browser instance found, starting new one')

		# Start a new Browser instance
		args = [
			self.config.browser_instance_path,
			'--remote-debugging-port=9222',
		]

		if self.config.headless:
			args.append('--headless')

		subprocess.Popen(
			args
			+ self.config.extra_browser_args,
			stdout=subprocess.DEVNULL,
			stderr=subprocess.DEVNULL,
		)
		# Attempt to connect again after starting a new instance
		for _ in range(10):
			try:
				response = requests.get(f'{endpoint}/json/version', timeout=2)
				if response.status_code == 200:
					browser_class = getattr(playwright, self.config.browser_class)
					return browser_class.connect_over_cdp(endpoint, timeout=20000)
			except requests.ConnectionError:
				await asyncio.sleep(1)

		raise RuntimeError('Failed to connect to Browser instance. Close all existing Browser instances and try again.')

	async def _setup_standard_browser(self, playwright: Playwright) -> PlaywrightBrowser:
		"""Sets up and returns a Playwright Browser instance with anti-detection measures."""
		browser_class = getattr(playwright, self.config.browser_class)
		args = {
			'chromium': [
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
			],
			'firefox': [
				'-no-remote',
			],
			'webkit': [
				'--no-startup-window',
			],
		}
		browser = await browser_class.launch(
			headless=self.config.headless,
			args=args[self.config.browser_class] + self.disable_security_args + self.config.extra_browser_args,
			proxy=self.config.proxy,
		)
		return browser

	async def _setup_browser(self, playwright: Playwright) -> PlaywrightBrowser:
		"""Sets up and returns a Playwright Browser instance with anti-detection measures."""
		try:
			if self.config.cdp_url:
				return await self._setup_cdp(playwright)
			if self.config.wss_url:
				return await self._setup_wss(playwright)
			elif self.config.browser_instance_path:
				return await self._setup_browser_with_instance(playwright)
			else:
				return await self._setup_standard_browser(playwright)
		except Exception as e:
			logger.error(f'Failed to initialize Playwright browser: {str(e)}')
			raise

	async def close(self):
		"""Close the browser instance"""
		try:
			if self.config._force_keep_browser_alive:
				return
			if self.playwright_browser:
				await self.playwright_browser.close()
				self.playwright_browser = None
			if self.playwright:
				await self.playwright.stop()
				self.playwright = None
		except Exception as e:
			logger.debug(f'Failed to close browser properly: {e}')
		finally:
			gc.collect()

	def __del__(self) -> None:
		"""Cleanup when object is destroyed."""
		try:
			if self.playwright_browser or self.playwright:
				loop = asyncio.get_running_loop()
				if loop.is_running():
					loop.create_task(self.close())
				else:
					asyncio.run(self.close())
		except Exception as e:
			logger.debug(f'Failed to cleanup browser in destructor: {e}')
