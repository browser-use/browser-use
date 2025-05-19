"""
Browser on steroids.
"""

import asyncio
import gc
import logging
import os
from typing import Literal

from dotenv import load_dotenv
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from browser_use.driver import Driver, AbstractBrowser
from browser_use.driver import setup_browser

load_dotenv()

from browser_use.browser.chrome import CHROME_DEBUG_PORT
from browser_use.browser.context import BrowserContext, BrowserContextConfig
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

		chrome_remote_debugging_port: 9222
			Chrome remote debugging port to use to when browser_binary_path is supplied.
			This allows running multiple chrome browsers with same browser_binary_path but running on different ports.
			Also, makes it possible to launch new user provided chrome browser without closing already opened chrome instances,
			by providing non-default chrome debugging port.

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
	browser_binary_path: str | None = Field(
		default=None, validation_alias=AliasChoices('browser_instance_path', 'chrome_instance_path')
	)
	chrome_remote_debugging_port: int | None = CHROME_DEBUG_PORT
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
	Browser on steroids.

	This is persistent browser factory that can spawn multiple browser contexts.
	It is recommended to use only one instance of Browser per your application (RAM usage will grow otherwise).
	"""

	def __init__(
		self,
		config: BrowserConfig | None = None,
	):
		logger.debug('🌎  Initializing new browser')
		self.config = config or BrowserConfig()
		self.driver: Driver | None = None
		self.browser_impl: AbstractBrowser | None = None

	async def new_context(self, config: BrowserContextConfig | None = None) -> BrowserContext:
		"""Create a browser context"""
		browser_config = self.config.model_dump() if self.config else {}
		context_config = config.model_dump() if config else {}
		merged_config = {**browser_config, **context_config}
		return BrowserContext(config=BrowserContextConfig(**merged_config), browser=self)

	async def get_playwright_browser(self) -> AbstractBrowser:
		"""Get a browser context"""
		if self.browser_impl is None:
			return await self._init()

		return self.browser_impl

	@time_execution_async('--init (browser)')
	async def _init(self):
		"""Initialize the browser session"""
		driver = Driver("playwright")
		self.driver = driver

		browser = await setup_browser(driver, self.config)
		self.browser_impl = browser

		return self.browser_impl

	async def close(self):
		"""Close the browser instance"""
		if self.config.keep_alive:
			return

		try:
			if self.browser_impl:
				await self.browser_impl.close()
				del self.browser_impl
			if self.driver:
				await self.driver.stop()
				del self.driver

		except Exception as e:
			if 'OpenAI error' not in str(e):
				logger.debug(f'Failed to close browser properly: {e}')

		finally:
			self.browser_impl = None
			self.driver = None
			gc.collect()

	def __del__(self):
		"""Async cleanup when object is destroyed"""
		try:
			if self.browser_impl or self.driver:
				loop = asyncio.get_running_loop()
				if loop.is_running():
					loop.create_task(self.close())
				else:
					asyncio.run(self.close())
		except Exception as e:
			logger.debug(f'Failed to cleanup browser in destructor: {e}')
