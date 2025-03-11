"""
Playwright browser on steroids.
"""

import asyncio
import gc
import logging
from dataclasses import dataclass, field
import os
from pathlib import Path
import tempfile
import json
import shutil
import requests
from zipfile import ZipFile

from playwright._impl._api_structures import ProxySettings
from playwright.async_api import Browser as PlaywrightBrowser
from playwright.async_api import (
	Playwright,
	async_playwright,
)

from browser_use.browser.context import BrowserContext, BrowserContextConfig
from browser_use.utils import time_execution_async

logger = logging.getLogger(__name__)


@dataclass
class BrowserConfig:
	r"""
	Configuration for the Browser.

	Default values:
		headless: True
			Whether to run browser in headless mode

		disable_security: True
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

		enable_adblock: False
			Whether to automatically download and enable uBlock Lite extension.
			Will download from GitHub releases on first use and store in system's
			~/.cache directory.
	"""

	headless: bool = False
	disable_security: bool = True
	extra_chromium_args: list[str] = field(default_factory=list)
	chrome_instance_path: str | None = None
	wss_url: str | None = None
	cdp_url: str | None = None
	enable_adblock: bool = False

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

	UBLOCK_RELEASE_URL = "https://api.github.com/repos/uBlockOrigin/uBOL-home/releases/latest"

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

	@property
	def _ublock_cache_dir(self) -> Path:
		"""Get the cache directory for uBlock extension"""
		cache_dir = Path.home() / ".cache" / "browser-use" / "extensions" / "ublock-lite"
		cache_dir.mkdir(parents=True, exist_ok=True)
		return cache_dir

	@property
	def _user_data_dir(self) -> Path:
		"""Get the user data directory for persistent context"""
		data_dir = Path.home() / ".cache" / "browser-use" / "user-data"
		data_dir.mkdir(parents=True, exist_ok=True)
		return data_dir

	async def _get_ublock_path(self) -> Path:
		"""
		Download and extract uBlock Lite if not already present.
		Returns path to the extension directory.
		"""
		# If extension already exists and has manifest.json, use it
		if self._ublock_cache_dir.exists() and (self._ublock_cache_dir / "manifest.json").exists():
			logger.debug("Using cached uBlock Lite extension")
			return self._ublock_cache_dir
		
		# Download if not present
		logger.info("Downloading uBlock Lite extension...")
		try:
			# Get latest release info
			response = requests.get(self.UBLOCK_RELEASE_URL)
			response.raise_for_status()
			release_data = response.json()
			
			# Find the chromium zip asset
			zip_asset = next(
				asset for asset in release_data["assets"] 
				if asset["name"].endswith(".chromium.mv3.zip")
			)
			
			# Create a temporary directory for extraction
			with tempfile.TemporaryDirectory() as temp_dir:
				# Download zip file
				zip_path = os.path.join(temp_dir, "extension.zip")
				response = requests.get(zip_asset["browser_download_url"])
				response.raise_for_status()
				
				# Save zip file
				with open(zip_path, "wb") as f:
					f.write(response.content)
				
				# Extract to cache directory
				with ZipFile(zip_path) as zip_file:
					zip_file.extractall(str(self._ublock_cache_dir))
				
				logger.info("Successfully installed uBlock Lite")
		
		except Exception as e:
			logger.error(f"Failed to download uBlock Lite: {e}")
			raise RuntimeError("Failed to download uBlock Lite extension") from e
		
		return self._ublock_cache_dir

	async def new_context(self, config: BrowserContextConfig = BrowserContextConfig()) -> BrowserContext:
		"""Create a browser context"""
		return BrowserContext(config=config, browser=self)

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
