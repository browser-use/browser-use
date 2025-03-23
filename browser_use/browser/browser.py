"""
Playwright browser on steroids.
"""

import asyncio
import gc
import logging
import os
import tempfile
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

from playwright._impl._api_structures import ProxySettings
from playwright.async_api import Browser as PlaywrightBrowser
from playwright.async_api import (
	Playwright,
	async_playwright,
)

from browser_use.browser.context import BrowserContext, BrowserContextConfig
from browser_use.utils import time_execution_async
from browser_use.cache.views import CacheSettings, CacheStrategy
from browser_use.agent.views import AgentSettings
from langchain_core.language_models.chat_models import BaseChatModel
from browser_use.controller.service import Controller
if TYPE_CHECKING:
	from browser_use.agent.service import Agent
from browser_use.cache.views import CacheSettings

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
            
		anti_fingerprint: False
			Apply anti-fingerprinting patches to avoid bot detection
	"""

	headless: bool = True
	disable_security: bool = True
	extra_chromium_args: list[str] = field(default_factory=list)
	chrome_instance_path: Optional[str] = None
	wss_url: Optional[str] = None
	cdp_url: Optional[str] = None
	proxy: Optional[ProxySettings] = None
	anti_fingerprint: bool = False

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
		self._anti_fingerprint_scripts = []
		if self.config.anti_fingerprint:
			self._load_anti_fingerprint_scripts()

	def _load_anti_fingerprint_scripts(self):
		"""Load anti-fingerprinting scripts"""
		# Basic anti-fingerprinting scripts
		self._anti_fingerprint_scripts = [
			# Override navigator properties
			"""
			() => {
				const originalGetProperty = Object.getOwnPropertyDescriptor(Object.prototype, '__proto__').get;
				
				// Override navigator properties
				const navigatorProps = {
					webdriver: false,
					plugins: { length: 3 },
					languages: ['en-US', 'en'],
					platform: 'Win32',
					hardwareConcurrency: 8,
					deviceMemory: 8,
					userAgent: navigator.userAgent.replace('Headless', '')
				};
				
				for (const [key, value] of Object.entries(navigatorProps)) {
					if (Object.getOwnPropertyDescriptor(Navigator.prototype, key)) {
						Object.defineProperty(Navigator.prototype, key, {
							get: function() { return value; }
						});
					}
				}
				
				// Override screen properties
				const screenProps = {
					width: 1920,
					height: 1080,
					availWidth: 1920,
					availHeight: 1040,
					colorDepth: 24,
					pixelDepth: 24
				};
				
				for (const [key, value] of Object.entries(screenProps)) {
					if (Object.getOwnPropertyDescriptor(Screen.prototype, key)) {
						Object.defineProperty(Screen.prototype, key, {
							get: function() { return value; }
						});
					}
				}
				
				// Mock plugins
				const mockPlugins = [
					{
						name: 'Chrome PDF Plugin',
						filename: 'internal-pdf-viewer',
						description: 'Portable Document Format',
						length: 1
					},
					{
						name: 'Chrome PDF Viewer',
						filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai',
						description: '',
						length: 1
					},
					{
						name: 'Native Client',
						filename: 'internal-nacl-plugin',
						description: '',
						length: 2
					}
				];
				
				// Create a mock plugins array
				const mockPluginsArray = Object.create(PluginArray.prototype);
				mockPluginsArray.length = mockPlugins.length;
				
				mockPlugins.forEach((plugin, i) => {
					const mockPlugin = Object.create(Plugin.prototype);
					for (const [key, value] of Object.entries(plugin)) {
						mockPlugin[key] = value;
					}
					mockPluginsArray[i] = mockPlugin;
					mockPluginsArray[plugin.name] = mockPlugin;
				});
				
				// Override navigator.plugins
				Object.defineProperty(Navigator.prototype, 'plugins', {
					get: function() { return mockPluginsArray; }
				});
				
				// Override navigator.mimeTypes
				const mockMimeTypes = [
					{
						type: 'application/pdf',
						suffixes: 'pdf',
						description: 'Portable Document Format',
						__pluginName: 'Chrome PDF Plugin'
					},
					{
						type: 'application/x-google-chrome-pdf',
						suffixes: 'pdf',
						description: 'Portable Document Format',
						__pluginName: 'Chrome PDF Viewer'
					},
					{
						type: 'application/x-nacl',
						suffixes: '',
						description: 'Native Client Executable',
						__pluginName: 'Native Client'
					},
					{
						type: 'application/x-pnacl',
						suffixes: '',
						description: 'Portable Native Client Executable',
						__pluginName: 'Native Client'
					}
				];
				
				const mockMimeTypesArray = Object.create(MimeTypeArray.prototype);
				mockMimeTypesArray.length = mockMimeTypes.length;
				
				mockMimeTypes.forEach((mimeType, i) => {
					const mockMimeType = Object.create(MimeType.prototype);
					for (const [key, value] of Object.entries(mimeType)) {
						if (key !== '__pluginName') {
							mockMimeType[key] = value;
						}
					}
					
					// Set plugin reference
					mockMimeType.enabledPlugin = mockPluginsArray[mimeType.__pluginName];
					
					mockMimeTypesArray[i] = mockMimeType;
					mockMimeTypesArray[mimeType.type] = mockMimeType;
				});
				
				Object.defineProperty(Navigator.prototype, 'mimeTypes', {
					get: function() { return mockMimeTypesArray; }
				});
				
				// Override WebGL fingerprinting
				const getParameter = WebGLRenderingContext.prototype.getParameter;
				WebGLRenderingContext.prototype.getParameter = function(parameter) {
					// UNMASKED_VENDOR_WEBGL
					if (parameter === 37445) {
						return 'Google Inc. (Intel)';
					}
					// UNMASKED_RENDERER_WEBGL
					if (parameter === 37446) {
						return 'ANGLE (Intel, Intel(R) UHD Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)';
					}
					return getParameter.apply(this, arguments);
				};
			}
			""",
			
			# Add noise to canvas fingerprinting
			"""
			() => {
				// Add subtle noise to canvas operations
				const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
				const originalGetImageData = CanvasRenderingContext2D.prototype.getImageData;
				
				// Helper to add subtle noise
				const addNoise = (data) => {
					const noise = 1; // Very subtle noise
					for (let i = 0; i < data.length; i += 4) {
						// Only modify a small percentage of pixels
						if (Math.random() < 0.05) {
							data[i] = Math.max(0, Math.min(255, data[i] + (Math.random() * noise * 2 - noise)));
							data[i+1] = Math.max(0, Math.min(255, data[i+1] + (Math.random() * noise * 2 - noise)));
							data[i+2] = Math.max(0, Math.min(255, data[i+2] + (Math.random() * noise * 2 - noise)));
						}
					}
					return data;
				};
				
				// Override toDataURL
				HTMLCanvasElement.prototype.toDataURL = function() {
					// Only add noise to small canvases (likely used for fingerprinting)
					if (this.width <= 300 && this.height <= 150) {
						const context = this.getContext('2d');
						if (context) {
							const imageData = context.getImageData(0, 0, this.width, this.height);
							const data = imageData.data;
							addNoise(data);
							context.putImageData(imageData, 0, 0);
						}
					}
					return originalToDataURL.apply(this, arguments);
				};
				
				// Override getImageData
				CanvasRenderingContext2D.prototype.getImageData = function() {
					const imageData = originalGetImageData.apply(this, arguments);
					
					// Only add noise to small canvases (likely used for fingerprinting)
					if (this.canvas.width <= 300 && this.canvas.height <= 150) {
						addNoise(imageData.data);
					}
					
					return imageData;
				};
			}
			""",
			
			# Add noise to audio fingerprinting
			"""
			() => {
				// Override AudioBuffer methods to add subtle noise
				if (typeof AudioBuffer !== 'undefined') {
					const originalGetChannelData = AudioBuffer.prototype.getChannelData;
					if (originalGetChannelData) {
						AudioBuffer.prototype.getChannelData = function(channel) {
							const array = originalGetChannelData.call(this, channel);
							
							// Add very subtle noise to the audio data
							// Only modify a small percentage of samples
							const length = array.length;
							const noise = 0.0001; // Very subtle noise
							
							// Only process short audio buffers (likely used for fingerprinting)
							if (length < 1000) {
								for (let i = 0; i < length; i++) {
									if (Math.random() < 0.05) {
										array[i] += (Math.random() * noise * 2 - noise);
									}
								}
							}
							
							return array;
						};
					}
					
					// Override copyFromChannel if it exists
					const originalCopyFromChannel = AudioBuffer.prototype.copyFromChannel;
					if (originalCopyFromChannel) {
						AudioBuffer.prototype.copyFromChannel = function(destination, channelNumber, startInChannel) {
							originalCopyFromChannel.apply(this, arguments);
							
							// Add subtle noise to the destination array
							const noise = 0.0001;
							for (let i = 0; i < destination.length; i++) {
								if (Math.random() < 0.05) {
									destination[i] += (Math.random() * noise * 2 - noise);
								}
							}
						};
					}
				}
				
				// Override AnalyserNode methods
				if (typeof AnalyserNode !== 'undefined') {
					const originalGetFloatFrequencyData = AnalyserNode.prototype.getFloatFrequencyData;
					if (originalGetFloatFrequencyData) {
						AnalyserNode.prototype.getFloatFrequencyData = function(array) {
							originalGetFloatFrequencyData.call(this, array);
							
							// Add subtle noise to the frequency data
							const noise = 0.1;
							for (let i = 0; i < array.length; i++) {
								if (Math.random() < 0.05) {
									array[i] += (Math.random() * noise * 2 - noise);
								}
							}
						};
					}
					
					const originalGetByteFrequencyData = AnalyserNode.prototype.getByteFrequencyData;
					if (originalGetByteFrequencyData) {
						AnalyserNode.prototype.getByteFrequencyData = function(array) {
							originalGetByteFrequencyData.call(this, array);
							
							// Add subtle noise to the frequency data
							const noise = 1;
							for (let i = 0; i < array.length; i++) {
								if (Math.random() < 0.05) {
									array[i] = Math.max(0, Math.min(255, array[i] + (Math.random() * noise * 2 - noise)));
								}
							}
						};
					}
				}
			}
			"""
		]

	async def new_context(self, config: BrowserContextConfig = BrowserContextConfig()) -> BrowserContext:
		"""Create a browser context"""
		context = BrowserContext(config=config, browser=self)
		
		# Initialize anti-fingerprinting if enabled
		if self.config.anti_fingerprint and not hasattr(self, '_anti_fingerprint_scripts'):
			self._load_anti_fingerprint_scripts()
		
		return context

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
		args = [
				self.config.chrome_instance_path,
				'--remote-debugging-port=9222',
			]
		if self.config.headless:
			args.append('--headless')
		subprocess.Popen(
			args
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
		"""Setup a standard browser instance"""
		args = []

		if self.config.disable_security:
			args.extend(
				[
					'--no-sandbox',
					'--disable-web-security',
					'--disable-features=IsolateOrigins,site-per-process',
				]
			)

		args.extend(self.config.extra_chromium_args)

		browser = await playwright.chromium.launch(
			headless=self.config.headless,
			args=args,
			proxy=self.config.proxy,
		)

		# Apply anti-fingerprinting patches if enabled
		if self.config.anti_fingerprint:
			if not hasattr(self, '_anti_fingerprint_scripts'):
				self._load_anti_fingerprint_scripts()
			
		return browser

	async def _apply_anti_fingerprint_patches(self, context):
		"""Apply anti-fingerprinting patches to a playwright context"""
		try:
			# Load scripts if not already loaded
			if not hasattr(self, '_anti_fingerprint_scripts'):
				self._load_anti_fingerprint_scripts()
			
			# Get the first page or create one if none exists
			pages = context.pages
			if len(pages) == 0:
				page = await context.new_page()
			else:
				page = pages[0]
			
			# Apply each script
			for script in self._anti_fingerprint_scripts:
				await page.evaluate(script)
			
			logger.info("Anti-fingerprinting patches applied successfully")
		except Exception as e:
			logger.error(f"Failed to apply anti-fingerprinting patches: {e}")

	async def _apply_anti_fingerprint_patches_to_all_pages(self, context):
		"""Apply anti-fingerprinting patches to all pages in a context"""
		if not hasattr(self, '_anti_fingerprint_scripts'):
			self._load_anti_fingerprint_scripts()
		
		for page in context.pages:
			try:
				for script in self._anti_fingerprint_scripts:
					await page.evaluate(script)
			except Exception as e:
				logger.error(f"Failed to apply anti-fingerprinting patches to page: {e}")
		
		# Add event listener for new pages
		async def on_page(page):
			try:
				for script in self._anti_fingerprint_scripts:
					await page.evaluate(script)
				logger.debug("Applied anti-fingerprinting patches to new page")
			except Exception as e:
				logger.error(f"Failed to apply anti-fingerprinting patches to new page: {e}")
		
		context.on("page", on_page)
		logger.info("Anti-fingerprinting patches applied to all pages")

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

	async def create_agent_with_cache(
		self,
		task: str,
		llm: BaseChatModel,
		controller: Controller,
		agent_settings: AgentSettings = AgentSettings(),
		context_config: BrowserContextConfig = BrowserContextConfig(),
		cache_settings: CacheSettings = CacheSettings(),
	) -> "Agent":
		"""Create an agent with caching enabled"""
		# Create a browser context
		context = await self.new_context(config=context_config)
		
		# Create an agent with caching enabled
		from browser_use.agent.service import Agent  # Import inside the method to avoid circular import
		agent = Agent(
			task=task,
			llm=llm,
			browser_context=context,
			controller=controller,
			settings=agent_settings,
			cache_settings=cache_settings,
		)
		
		return agent
