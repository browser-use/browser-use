import logging
from typing import TYPE_CHECKING

from browser_use.typing import AbstractBrowser

if TYPE_CHECKING:
	# these will create circular imports
	from browser_use.browser.browser import BrowserConfig

logger = logging.getLogger(__name__)


class Driver:
	def __init__(self, name: str, config: 'BrowserConfig') -> None:
		self.name = name
		self.config = config
		self.impl: AbstractBrowser | None = None
		logger.info(f'🌎🚗 Created BrowserDriver instance: name={self.name}')

	@property
	def chromium(self) -> AbstractBrowser:
		assert self.config.browser_class == 'chromium', f'Invalid browser class: {self.config.browser_class}'
		assert self.impl is not None, f'Driver {self.name} is not initialized'
		return self.impl

	@property
	def firefox(self) -> AbstractBrowser:
		assert self.config.browser_class == 'firefox', f'Invalid browser class: {self.config.browser_class}'
		assert self.impl is not None, f'Driver {self.name} is not initialized'
		return self.impl

	@property
	def webkit(self) -> AbstractBrowser:
		assert self.config.browser_class == 'webkit', f'Invalid browser class: {self.config.browser_class}'
		assert self.impl is not None, f'Driver {self.name} is not initialized'
		return self.impl

	async def setup(self) -> 'Driver':
		logger.info(f'🌎🚗 BrowserDriver.setup(): name={self.name}')
		if self.name == 'playwright':
			from browser_use.drivers.playwright import PlaywrightBrowser

			if self.config.browser_class == 'chromium':
				self.impl = PlaywrightBrowser('chromium', self.config)
			elif self.config.browser_class == 'firefox':
				self.impl = PlaywrightBrowser('firefox', self.config)
			elif self.config.browser_class == 'webkit':
				self.impl = PlaywrightBrowser('webkit', self.config)
			else:
				raise ValueError(f'Invalid browser name: {self.config.browser_class}')
			await self.impl.setup()
			await self.impl.open()
		else:
			raise NotImplementedError(f"Driver '{self.name}' is not supported.")
		return self

	async def stop(self) -> None:
		logger.info(f'🌎🚗 BrowserDriver.stop(): name={self.name}')
		assert self.impl is not None, f'Driver {self.name} is not initialized'
		await self.impl.close()

	async def __aenter__(self):
		logger.info(f'🌎🚗 BrowserDriver.__aenter__(): name={self.name}')
		await self.setup()
		return self

	async def __aexit__(self, exc_type, exc, tb):
		logger.info(f'🌎🚗 BrowserDriver.__aexit__(): name={self.name}')
		await self.stop()
