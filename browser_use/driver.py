from abc import ABC, abstractmethod
from typing import Any, Awaitable
from browser_use.playwright import PlaywrightBrowser
import httpx
import asyncio
import logging
from pathlib import Path
from tempfile import gettempdir

logger = logging.getLogger(__name__)

# --- Mixins for shared APIs ---
class EventEmitterMixin(ABC):
	@abstractmethod
	def on(self, event: str, handler) -> None: ...

	@abstractmethod
	def remove_listener(self, event: str, handler) -> None: ...

class QueryableMixin(ABC):
	@abstractmethod
	async def query_selector(self, selector: str) -> 'ElementHandle | None': ...
	
	@abstractmethod
	async def query_selector_all(self, selector: str) -> list['ElementHandle']: ...

	@abstractmethod
	def locator(self, selector: str) -> 'AbstractLocator': ...

	@abstractmethod
	def frame_locator(self, selector: str) -> 'FrameLocator': ...
	
	@abstractmethod
	async def evaluate(self, script: str, *args, **kwargs) -> Any: ...

	@abstractmethod
	async def click(self, *args, **kwargs) -> Any: ...

	@abstractmethod
	async def get_property(self, property_name: str) -> Any: ...

class TypableMixin(ABC):
	@abstractmethod
	async def type(self, text: str, delay: float = 0) -> None: ...
	
	@abstractmethod
	async def fill(self, text: str, timeout: float | None = None) -> None: ...

# --- Main Abstract Classes ---
class Driver:
	
	def __init__(self, name: str) -> None:
		self.name: str = name
		self.impl = None
		
	@property
	def chromium(self) -> 'AbstractBrowser':
		if self.name == "playwright" and self.impl is None:
			return getattr(self.impl, "chromium") # type: ignore
		raise ValueError("Chromium is not initialized")
	
	@property
	def firefox(self) -> 'AbstractBrowser':
		if self.name == "playwright" and self.impl is None:
			return getattr(self.impl, "firefox") # type: ignore
		raise ValueError("Firefox is not initialized")
	
	@property
	def webkit(self) -> 'AbstractBrowser':
		if self.name == "playwright" and self.impl is None:
			return getattr(self.impl, "webkit") # type: ignore
		raise ValueError("WebKit is not initialized")
		
	async def connect(self, browser: str, cdp_url: str) -> 'AbstractBrowser':
		if self.name == "playwright":
			browser_type = getattr(self.impl, browser)
			browser_instance = await browser_type.connect_over_cdp(cdp_url)
			return PlaywrightBrowser(browser_instance)
		raise NotImplementedError(f"Driver '{self.name}' is not supported.")
	
	async def start(self) -> 'Driver':
		if self.name == "playwright":
			from playwright.async_api import async_playwright
			self.impl = await async_playwright().start()
			return self
		else:
			raise NotImplementedError(f"Driver '{self.name}' is not supported.")

	async def stop(self) -> None:
		if self.name == "playwright":
			pass  # No stop method for async_playwright singleton
		else:
			raise NotImplementedError(f"Driver '{self.name}' is not supported.")

	async def __aenter__(self):
		return self

	async def __aexit__(self, exc_type, exc, tb):
		await self.stop()

class AbstractBrowser(ABC):
	@abstractmethod
	async def new_context(self, **kwargs) -> "AbstractContext":
		pass
	
	@abstractmethod
	async def launch(self, **kwargs) -> "AbstractBrowser":
		pass

	@abstractmethod
	async def close(self) -> None:
		pass

	@property
	@abstractmethod
	def contexts(self) -> list["AbstractContext"]:
		pass

	@classmethod
	@abstractmethod
	async def connect_over_cdp(cls, cdp_url: str, timeout: int = 30000) -> 'AbstractBrowser':
		pass

	@property
	@abstractmethod
	def version(self) -> str:
		pass

class AbstractContext(EventEmitterMixin, ABC):
	@abstractmethod
	async def new_page(self) -> "Page":
		pass

	@abstractmethod
	async def close(self) -> None:
		pass

	@property
	@abstractmethod
	def pages(self) -> list["Page"]:
		pass

	@abstractmethod
	async def grant_permissions(self, permissions: list[str], origin: str | None = None) -> None:
		pass

	@property
	@abstractmethod
	def tracing(self) -> "AbstractTracing":
		pass

	@abstractmethod
	async def add_cookies(self, cookies: list[dict]) -> None:
		pass

	@abstractmethod
	async def add_init_script(self, script: str) -> None:
		pass

	@abstractmethod
	async def cookies(self) -> list[dict]:
		pass

class AbstractFrame(QueryableMixin, ABC):
	@property
	@abstractmethod
	def url(self) -> str:
		pass

	@abstractmethod
	async def content(self) -> str:
		pass

class Page(EventEmitterMixin, QueryableMixin, TypableMixin, ABC):
	@abstractmethod
	async def goto(self, url: str, **kwargs) -> None:
		pass

	@abstractmethod
	async def click(self, selector: str) -> None:
		pass

	@abstractmethod
	async def fill(self, selector: str, text: str) -> None:
		pass

	@abstractmethod
	async def get_content(self) -> str:
		pass

	@abstractmethod
	async def screenshot(self, **kwargs) -> bytes:
		pass

	@abstractmethod
	async def close(self) -> None:
		pass

	@abstractmethod
	async def wait_for_load_state(self, state: str = 'load', **kwargs) -> None:
		pass

	@property
	@abstractmethod
	def url(self) -> str:
		pass

	@abstractmethod
	async def set_viewport_size(self, viewport_size: dict) -> None:
		pass

	@abstractmethod
	def is_closed(self) -> bool:
		pass

	@abstractmethod
	async def bring_to_front(self) -> None:
		pass

	@abstractmethod
	async def expose_function(self, name: str, func) -> None:
		pass

	@abstractmethod
	async def go_back(self, **kwargs) -> None:
		pass

	@abstractmethod
	async def go_forward(self, **kwargs) -> None:
		pass

	@abstractmethod
	async def wait_for_selector(self, selector: str, **kwargs) -> None:
		pass

	@abstractmethod
	async def content(self) -> str:
		pass

	@abstractmethod
	async def title(self) -> str:
		pass

	@property
	@abstractmethod
	def frames(self) -> list[AbstractFrame]:
		pass

	@abstractmethod
	async def emulate_media(self, **kwargs) -> None:
		pass

	@abstractmethod
	async def pdf(self, **kwargs) -> Any:
		pass

	@property
	@abstractmethod
	def keyboard(self) -> 'AbstractKeyboard':
		pass

	@abstractmethod
	def get_by_text(self, text: str, exact: bool = False) -> 'AbstractLocator':
		pass

	@property
	@abstractmethod
	def mouse(self) -> 'AbstractMouse':
		pass

	@abstractmethod
	async def viewport_size(self) -> dict:
		pass

	@abstractmethod
	async def reload(self) -> None:
		pass

	@abstractmethod
	async def expect_download(self, *args, **kwargs) -> 'AbstractDownload':
		pass

	@abstractmethod
	async def wait_for_timeout(self, timeout: float) -> None:
		pass

class ElementHandle(QueryableMixin, EventEmitterMixin, TypableMixin, ABC):
	@abstractmethod
	async def is_visible(self) -> bool:
		pass

	@abstractmethod
	async def is_hidden(self) -> bool:
		pass

	@abstractmethod
	async def bounding_box(self) -> dict | None:
		pass

	@abstractmethod
	async def scroll_into_view_if_needed(self, timeout: int | float | None = None) -> None:
		pass

	@abstractmethod
	async def element_handle(self) -> 'ElementHandle':
		pass

	@abstractmethod
	async def wait_for_element_state(self, state: str, timeout: int | float | None = None) -> None:
		pass

	@abstractmethod
	async def clear(self, timeout: float | None = None) -> None:
		pass

class AbstractTracing(ABC):
	@abstractmethod
	async def start(self, **kwargs) -> None:
		pass

	@abstractmethod
	async def stop(self, **kwargs) -> None:
		pass

class AbstractLocator(QueryableMixin, ABC):
	@abstractmethod
	def filter(self, **kwargs) -> 'AbstractLocator':
		pass

	@abstractmethod
	async def evaluate_all(self, expression: str) -> Any:
		pass

	@abstractmethod
	async def count(self) -> int:
		pass

	@property
	@abstractmethod
	def first(self) -> 'Awaitable[ElementHandle]':
		"""Returns an awaitable that resolves to the first element handle (must be awaited)."""
		pass

	@abstractmethod
	def nth(self, index: int) -> 'AbstractLocator':
		pass

	@abstractmethod
	async def select_option(self, **kwargs) -> Any:
		pass
	
	@abstractmethod
	async def element_handle(self) -> 'ElementHandle':
		pass

class FrameLocator(AbstractLocator):
	@abstractmethod
	async def frame(self) -> 'AbstractFrame':
		pass

class AbstractKeyboard(ABC):
	@abstractmethod
	async def press(self, keys: str) -> None:
		pass

	@abstractmethod
	async def type(self, text: str, delay: float = 0) -> None:
		pass

class AbstractMouse(ABC):
	@abstractmethod
	async def move(self, x: int, y: int) -> None:
		pass

	@abstractmethod
	async def down(self) -> None:
		pass

	@abstractmethod
	async def up(self) -> None:
		pass

class AbstractDownload(ABC):
	@property
	@abstractmethod
	def suggested_filename(self) -> str:
		pass

	@abstractmethod
	async def save_as(self, path: str) -> None:
		pass

	@property
	@abstractmethod
	async def value(self):
		pass

async def setup_builtin_browser(driver: 'Driver', config) -> 'AbstractBrowser':
	# This is a simplified version; you can expand as needed
	browser_class = getattr(driver, config.browser_class)
	browser = await browser_class.launch(headless=config.headless)
	return browser

async def setup_browser(driver: 'Driver', config) -> 'AbstractBrowser':
	if config.cdp_url:
		if 'firefox' in (config.browser_binary_path or '').lower():
			raise ValueError(
				'CDP has been deprecated for firefox, check: https://fxdx.dev/deprecating-cdp-support-in-firefox-embracing-the-future-with-webdriver-bidi/'
			)
		if not config.cdp_url:
			raise ValueError('CDP URL is required')
		logger.info(f'🔌  Connecting to remote browser via CDP {config.cdp_url}')
		browser_class = getattr(driver, config.browser_class)
		browser = await browser_class.connect_over_cdp(config.cdp_url)
		return browser
	if config.wss_url:
		if not config.wss_url:
			raise ValueError('WSS URL is required')
		logger.info(f'🔌  Connecting to remote browser via WSS {config.wss_url}')
		browser_class = getattr(driver, config.browser_class)
		browser = await browser_class.connect(config.wss_url)
		return browser
	if config.browser_binary_path:
		if not config.browser_binary_path:
			raise ValueError('A browser_binary_path is required')
		assert config.browser_class == 'chromium', (
			'browser_binary_path only supports chromium browsers (make sure browser_class=chromium)'
		)
		try:
			async with httpx.AsyncClient() as client:
				response = await client.get(
					f'http://localhost:{config.chrome_remote_debugging_port}/json/version', timeout=2
				)
				if response.status_code == 200:
					logger.info(
						f'🔌  Reusing existing browser found running on http://localhost:{config.chrome_remote_debugging_port}'
					)
					browser_class = getattr(driver, config.browser_class)
					browser = await browser_class.connect_over_cdp(
						endpoint_url=f'http://localhost:{config.chrome_remote_debugging_port}',
						timeout=20000,
					)
					return browser
		except httpx.RequestError:
			logger.debug('🌎  No existing Chrome instance found, starting a new one')
		provided_user_data_dir = [arg for arg in config.extra_browser_args if '--user-data-dir=' in arg]
		if provided_user_data_dir:
			user_data_dir = Path(provided_user_data_dir[0].split('=')[-1])
		else:
			fallback_user_data_dir = Path(gettempdir()) / 'browseruse' / 'profiles' / 'default'
			try:
				user_data_dir = Path('~/.config') / 'browseruse' / 'profiles' / 'default'
				user_data_dir = user_data_dir.expanduser()
				user_data_dir.mkdir(parents=True, exist_ok=True)
			except Exception as e:
				logger.error(f'❌  Failed to create ~/.config/browseruse directory: {type(e).__name__}: {e}')
				user_data_dir = fallback_user_data_dir
				user_data_dir.mkdir(parents=True, exist_ok=True)
		logger.info(f'🌐  Storing Browser Profile user data dir in: {user_data_dir}')
		try:
			(user_data_dir / 'Default' / 'SingletonLock').unlink()
			config.extra_browser_args.append('--no-first-run')
		except (FileNotFoundError, PermissionError, OSError):
			pass
		chrome_launch_args = [
			*{
				f'--remote-debugging-port={config.chrome_remote_debugging_port}',
				*([f'--user-data-dir={user_data_dir.resolve()}'] if not provided_user_data_dir else []),
				*config.extra_browser_args,
			},
		]
		chrome_sub_process = await asyncio.create_subprocess_exec(
			config.browser_binary_path,
			*chrome_launch_args,
			stdout=asyncio.subprocess.DEVNULL,
			stderr=asyncio.subprocess.DEVNULL,
			shell=False,
		)
		# Optionally store the process handle if needed
		for _ in range(10):
			try:
				async with httpx.AsyncClient() as client:
					response = await client.get(
						f'http://localhost:{config.chrome_remote_debugging_port}/json/version', timeout=2
					)
					if response.status_code == 200:
						break
			except httpx.RequestError:
				pass
			await asyncio.sleep(1)
		try:
			browser_class = getattr(driver, config.browser_class)
			browser = await browser_class.connect_over_cdp(
				endpoint_url=f'http://localhost:{config.chrome_remote_debugging_port}',
				timeout=20000,
			)
			return browser
		except Exception as e:
			logger.error(f'❌  Failed to start a new Chrome instance: {str(e)}')
			raise RuntimeError(
				'To start chrome in Debug mode, you need to close all existing Chrome instances and try again otherwise we can not connect to the instance.'
			)
	return await setup_builtin_browser(driver, config)