"""
Playwright browser on steroids.
"""

import asyncio
import gc
import logging
import os
import socket
import subprocess
from typing import Literal

import psutil
import requests
from dotenv import load_dotenv
from playwright.async_api import Browser as PlaywrightBrowser
from playwright.async_api import (
	Playwright,
	async_playwright,
)
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

load_dotenv()

from browser_use.browser.chrome import (
	CHROME_ARGS,
	CHROME_DETERMINISTIC_RENDERING_ARGS,
	CHROME_DISABLE_SECURITY_ARGS,
	CHROME_DOCKER_ARGS,
	CHROME_HEADLESS_ARGS,
)
from browser_use.browser.context import BrowserContext, BrowserContextConfig
from browser_use.browser.utils.screen_resolution import get_screen_resolution, get_window_adjustments
from browser_use.utils import time_execution_async

logger = logging.getLogger(__name__)

IN_DOCKER = os.environ.get('IN_DOCKER', 'false').lower()[0] in 'ty1'


class ProxySettings(BaseModel):
	"""the same as playwright.sync_api.ProxySettings, but now as a Pydantic BaseModel so pydantic can validate it"""

	server: str
	bypass: str | None = None
	username: str | None = None
	password: str | None = None

	model_config = ConfigDict(populate_by_name=True, from_attributes=True)

	# Support dict-like behavior for compatibility with Playwright's ProxySettings
	def __getitem__(self, key):
		return getattr(self, key)

	def get(self, key, default=None):
		return getattr(self, key, default)


class BrowserConfig(BaseModel):
	r"""
	Configuration for the Browser.

	Default values:
		headless: False
			Whether to run browser in headless mode (not recommended)

		disable_security: False
			Disable browser security features (required for cross-origin iframe support)

		extra_browser_args: []
			Extra arguments to pass to the browser

		wss_url: None
			Connect to a browser instance via WebSocket

		cdp_url: None
			Connect to a browser instance via CDP

		browser_binary_path: None
			Path to a Browser instance to use to connect to your normal browser
			e.g. '/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome'

		keep_alive: False
			Keep the browser alive after the agent has finished running

		deterministic_rendering: False
			Enable deterministic rendering (makes GPU/font rendering consistent across different OS's and docker)
	"""

	model_config = ConfigDict(
		arbitrary_types_allowed=True,
		extra='ignore',
		populate_by_name=True,
		from_attributes=True,
		validate_assignment=True,
		revalidate_instances='subclass-instances',
	)

	wss_url: str | None = None
	cdp_url: str | None = None

	browser_class: Literal['chromium', 'firefox', 'webkit'] = 'chromium'
	browser_binary_path: str | None = Field(default=None, alias=AliasChoices('browser_instance_path', 'chrome_instance_path'))
	extra_browser_args: list[str] = Field(default_factory=list)

	headless: bool = False
	disable_security: bool = False  # disable_security=True is dangerous as any malicious URL visited could embed an iframe for the user's bank, and use their cookies to steal money
	deterministic_rendering: bool = False
	keep_alive: bool = Field(default=False, alias='_force_keep_browser_alive')  # used to be called _force_keep_browser_alive

	proxy: ProxySettings | None = None
	new_context_config: BrowserContextConfig = Field(default_factory=BrowserContextConfig)


# @singleton: TODO - think about id singleton makes sense here
# @dev By default this is a singleton, but you can create multiple instances if you need to.
class Browser:
	"""
	Playwright browser on steroids.

	This is persistent browser factory that can spawn multiple browser contexts.
	It is recommended to use only one instance of Browser per your application (RAM usage will grow otherwise).
	"""

	def __init__(
		self,
		config: BrowserConfig | None = None,
	):
		logger.debug('🌎  Initializing new browser')
		self.config = config or BrowserConfig()
		self.playwright: Playwright | None = None
		self.playwright_browser: PlaywrightBrowser | None = None

	async def new_context(self, config: BrowserContextConfig | None = None) -> BrowserContext:
		"""Create a browser context"""
		return BrowserContext(config=config or self.config, browser=self)

	async def get_playwright_browser(self) -> PlaywrightBrowser:
		"""Get a browser context"""
		if self.playwright_browser is None:
			return await self._init()

		return self.playwright_browser

	@time_execution_async('--init (browser)')
	async def _init(self):
		"""Initialize the browser session"""
		playwright = await async_playwright().start()
		browser = await self._setup_browser(playwright)

		self.playwright = playwright
		self.playwright_browser = browser

		return self.playwright_browser

	async def _setup_remote_cdp_browser(self, playwright: Playwright) -> PlaywrightBrowser:
		"""Sets up and returns a Playwright Browser instance with anti-detection measures. Firefox has no longer CDP support."""
		if 'firefox' in (self.config.browser_binary_path or '').lower():
			raise ValueError(
				'CDP has been deprecated for firefox, check: https://fxdx.dev/deprecating-cdp-support-in-firefox-embracing-the-future-with-webdriver-bidi/'
			)
		if not self.config.cdp_url:
			raise ValueError('CDP URL is required')
		logger.info(f'🔌  Connecting to remote browser via CDP {self.config.cdp_url}')
		browser_class = getattr(playwright, self.config.browser_class)
		browser = await browser_class.connect_over_cdp(self.config.cdp_url)
		return browser

	async def _setup_remote_wss_browser(self, playwright: Playwright) -> PlaywrightBrowser:
		"""Sets up and returns a Playwright Browser instance with anti-detection measures."""
		if not self.config.wss_url:
			raise ValueError('WSS URL is required')
		logger.info(f'🔌  Connecting to remote browser via WSS {self.config.wss_url}')
		browser_class = getattr(playwright, self.config.browser_class)
		browser = await browser_class.connect(self.config.wss_url)
		return browser

	async def _setup_user_provided_browser(self, playwright: Playwright) -> PlaywrightBrowser:
		"""Sets up and returns a Playwright Browser instance with anti-detection measures."""
		if not self.config.browser_binary_path:
			raise ValueError('A browser_binary_path is required')

		assert self.config.browser_class == 'chromium', (
			'browser_binary_path only supports chromium browsers (make sure browser_class=chromium)'
		)

		try:
			# Check if browser is already running
			response = requests.get('http://localhost:9222/json/version', timeout=2)
			if response.status_code == 200:
				logger.info('🔌  Reusing existing browser found running on http://localhost:9222')
				browser_class = getattr(playwright, self.config.browser_class)
				browser = await browser_class.connect_over_cdp(
					endpoint_url='http://localhost:9222',
					timeout=20000,  # 20 second timeout for connection
				)
				return browser
		except requests.ConnectionError:
			logger.debug('🌎  No existing Chrome instance found, starting a new one')

		# Start a new Chrome instance
		chrome_launch_cmd = [
			self.config.browser_binary_path,
			*{  # remove duplicates (usually preserves the order, but not guaranteed)
				*CHROME_ARGS,
				*(CHROME_DOCKER_ARGS if IN_DOCKER else []),
				*(CHROME_HEADLESS_ARGS if self.config.headless else []),
				*(CHROME_DISABLE_SECURITY_ARGS if self.config.disable_security else []),
				*(CHROME_DETERMINISTIC_RENDERING_ARGS if self.config.deterministic_rendering else []),
				*self.config.extra_browser_args,
			},
		]
		self._chrome_subprocess = psutil.Process(
			subprocess.Popen(
				chrome_launch_cmd,
				stdout=subprocess.DEVNULL,
				stderr=subprocess.DEVNULL,
				shell=False,
			).pid
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
			browser_class = getattr(playwright, self.config.browser_class)
			browser = await browser_class.connect_over_cdp(
				endpoint_url='http://localhost:9222',
				timeout=20000,  # 20 second timeout for connection
			)
			return browser
		except Exception as e:
			logger.error(f'❌  Failed to start a new Chrome instance: {str(e)}')
			raise RuntimeError(
				'To start chrome in Debug mode, you need to close all existing Chrome instances and try again otherwise we can not connect to the instance.'
			)

	async def _setup_builtin_browser(self, playwright: Playwright) -> PlaywrightBrowser:
		"""Sets up and returns a Playwright Browser instance with anti-detection measures."""
		assert self.config.browser_binary_path is None, 'browser_binary_path should be None if trying to use the builtin browsers'

		if self.config.headless:
			screen_size = {'width': 1920, 'height': 1080}
			offset_x, offset_y = 0, 0
		else:
			screen_size = get_screen_resolution()
			offset_x, offset_y = get_window_adjustments()

		chrome_args = {
			*CHROME_ARGS,
			*(CHROME_DOCKER_ARGS if IN_DOCKER else []),
			*(CHROME_HEADLESS_ARGS if self.config.headless else []),
			*(CHROME_DISABLE_SECURITY_ARGS if self.config.disable_security else []),
			*(CHROME_DETERMINISTIC_RENDERING_ARGS if self.config.deterministic_rendering else []),
			f'--window-position={offset_x},{offset_y}',
			f'--window-size={screen_size["width"]},{screen_size["height"]}',
			*self.config.extra_browser_args,
		}

		# check if port 9222 is already taken, if so remove the remote-debugging-port arg to prevent conflicts
		with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
			if s.connect_ex(('localhost', 9222)) == 0:
				chrome_args.remove('--remote-debugging-port=9222')

		browser_class = getattr(playwright, self.config.browser_class)
		args = {
			'chromium': list(chrome_args),
			'firefox': [
				*{
					'-no-remote',
					*self.config.extra_browser_args,
				}
			],
			'webkit': [
				*{
					'--no-startup-window',
					*self.config.extra_browser_args,
				}
			],
		}

		browser = await browser_class.launch(
			headless=self.config.headless,
			args=args[self.config.browser_class],
			proxy=self.config.proxy.model_dump() if self.config.proxy else None,
			handle_sigterm=False,
			handle_sigint=False,
		)
		return browser

	async def _setup_browser(self, playwright: Playwright) -> PlaywrightBrowser:
		"""Sets up and returns a Playwright Browser instance with anti-detection measures."""
		try:
			if self.config.cdp_url:
				return await self._setup_remote_cdp_browser(playwright)
			if self.config.wss_url:
				return await self._setup_remote_wss_browser(playwright)

			if self.config.headless:
				logger.warning('⚠️ Headless mode is not recommended. Many sites will detect and block all headless browsers.')

			if self.config.browser_binary_path:
				return await self._setup_user_provided_browser(playwright)
			else:
				return await self._setup_builtin_browser(playwright)
		except Exception as e:
			logger.error(f'Failed to initialize Playwright browser: {e}')
			raise

	async def close(self):
		"""Close the browser instance"""
		if self.config.keep_alive:
			return

		try:
			if self.playwright_browser:
				await self.playwright_browser.close()
				del self.playwright_browser
			if self.playwright:
				await self.playwright.stop()
				del self.playwright
			if chrome_proc := getattr(self, '_chrome_subprocess', None):
				try:
					# always kill all children processes, otherwise chrome leaves a bunch of zombie processes
					for proc in chrome_proc.children(recursive=True):
						proc.kill()
					chrome_proc.kill()
				except Exception as e:
					logger.debug(f'Failed to terminate chrome subprocess: {e}')

			# Then cleanup httpx clients
			await self.cleanup_httpx_clients()
		except Exception as e:
			logger.debug(f'Failed to close browser properly: {e}')

		finally:
			self.playwright_browser = None
			self.playwright = None
			self._chrome_subprocess = None
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

	async def cleanup_httpx_clients(self):
		"""Cleanup all httpx clients"""
		import gc

		import httpx

		# Force garbage collection to make sure all clients are in memory
		gc.collect()

		# Get all httpx clients
		clients = [obj for obj in gc.get_objects() if isinstance(obj, httpx.AsyncClient)]

		# Close all clients
		for client in clients:
			if not client.is_closed:
				try:
					await client.aclose()
				except Exception as e:
					logger.debug(f'Error closing httpx client: {e}')
