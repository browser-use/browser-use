import asyncio
import logging
from collections.abc import Awaitable
from pathlib import Path
from tempfile import gettempdir
from typing import Any, Literal

import httpx
from playwright.async_api import (
	Browser,
	BrowserContext,
	BrowserType,
	ElementHandle,
	Frame,
	Locator,
	Playwright,
	ViewportSize,
	async_playwright,
)
from playwright.async_api import Page as PlaywrightRawPage

from browser_use.browser.browser import BrowserConfig
from browser_use.typing import (
	AbstractBrowser,
	AbstractContext,
	AbstractDownload,
	AbstractElementHandle,
	AbstractFrame,
	AbstractKeyboard,
	AbstractLocator,
	AbstractMouse,
	AbstractTracing,
	Page,
)

logger = logging.getLogger(__name__)


class PlaywrightBrowser(AbstractBrowser):
	def __init__(self, browser_name: str, config: BrowserConfig):
		super().__init__()
		logger.info(f'🛠️  Created BrowserEngine instance: {self.__class__.__name__} browser_name={browser_name}')
		self._browser_name = browser_name
		self._config = config
		self._playwright: Playwright | None = None
		self._browser_type: BrowserType | None = None
		self._browser: Browser | None = None

	async def setup(self):
		"""Setup connector"""
		logger.info(f'🛠️  Initializing BrowserEngine instance: {self.__class__.__name__} browser_name={self._browser_name}')
		self._playwright = await async_playwright().start()
		if self._browser_name == 'chromium':
			self._browser_type = self._playwright.chromium
		elif self._browser_name == 'firefox':
			self._browser_type = self._playwright.firefox
		elif self._browser_name == 'webkit':
			self._browser_type = self._playwright.webkit
		else:
			raise ValueError(f'Invalid browser name: {self._browser_name}')
		return self

	async def open(self) -> 'PlaywrightBrowser':
		"""Open a connection to browser"""
		logger.info(f'🛠️  BrowserEngine.open(): {self.__class__.__name__} browser_name={self._browser_name}')
		assert self._browser_type is not None, 'Browser type is not initialized'
		if self._config.cdp_url:
			self._browser = await setup_remote_cdp_browser(self._browser_type, self._config)
		elif self._config.wss_url:
			self._browser = await setup_remote_wss_browser(self._browser_type, self._config)
		elif self._config.browser_binary_path:
			self._browser = await setup_user_provided_browser(self._browser_type, self._config)
		else:
			raise ValueError('Invalid config: needs one of {cdp_url, wss_url, browser_binary_path}')
		return self

	async def close(self):
		"""Close a connection to browser"""
		logger.info(f'🛠️  BrowserEngine.close(): {self.__class__.__name__} browser_name={self._browser_name}')
		assert self._browser is not None, 'Browser is not initialized'
		assert self._playwright is not None, 'Playwright is not initialized'
		await self._browser.close()
		await self._playwright.stop()

	async def new_context(self, **kwargs):
		"""Create a new browser context"""
		logger.info(f'🛠️  BrowserEngine.new_context(): {self.__class__.__name__} browser_name={self._browser_name}')
		assert self._browser is not None, 'Browser is not initialized'
		ctx = await self._browser.new_context(**kwargs)
		return PlaywrightContext(ctx)

	@property
	def contexts(self):
		"""Get all browser contexts"""
		logger.info(f'🛠️  BrowserEngine.contexts(): {self.__class__.__name__} browser_name={self._browser_name}')
		assert self._browser is not None, 'Browser is not initialized'
		return [PlaywrightContext(ctx) for ctx in self._browser.contexts]

	@property
	def version(self) -> str:
		"""Get the browser version"""
		logger.info(f'🛠️  BrowserEngine.version(): {self.__class__.__name__} browser_name={self._browser_name}')
		assert self._browser is not None, 'Browser is not initialized'
		return self._browser.version


class PlaywrightContext(AbstractContext):
	def __init__(self, context: BrowserContext):
		self._context = context

	async def new_page(self):
		page = await self._context.new_page()
		return PlaywrightPage(page)

	async def close(self):
		await self._context.close()

	@property
	def tracing(self):
		return PlaywrightTracing(self._context.tracing)

	@property
	def pages(self):
		return [PlaywrightPage(page) for page in self._context.pages]

	async def grant_permissions(self, permissions: list[str], origin: str | None = None) -> None:
		await self._context.grant_permissions(permissions, origin=origin)

	async def add_cookies(self, cookies: list[dict]) -> None:
		allowed_keys = {'name', 'value', 'url', 'domain', 'path', 'expires', 'httpOnly', 'secure', 'sameSite'}
		cookies_clean: list = [{k: v for k, v in cookie.items() if k in allowed_keys} for cookie in cookies]
		await self._context.add_cookies(cookies_clean)

	async def add_init_script(self, script: str) -> None:
		await self._context.add_init_script(script)

	def remove_listener(self, event: str, handler) -> None:
		self._context.remove_listener(event, handler)

	def on(self, event: str, handler) -> None:
		self._context.on(event, handler)  # type: ignore

	async def cookies(self) -> list[dict]:
		cookies = await self._context.cookies()
		return [vars(cookie) for cookie in cookies]


class PlaywrightTracing(AbstractTracing):
	def __init__(self, tracing):
		self._tracing = tracing

	async def start(self, **kwargs) -> None:
		await self._tracing.start(**kwargs)

	async def stop(self, **kwargs) -> None:
		await self._tracing.stop(**kwargs)


class PlaywrightFrame(AbstractFrame):
	def __init__(self, frame: Frame):
		self._frame = frame

	@property
	def url(self) -> str:
		return self._frame.url

	async def content(self) -> str:
		return await self._frame.content()

	async def evaluate(self, script: str, *args, **kwargs) -> Any:
		return await self._frame.evaluate(script, *args, **kwargs)

	async def query_selector(self, selector: str) -> 'PlaywrightElementHandle | None':
		handle = await self._frame.query_selector(selector)
		if handle is None:
			return None
		return PlaywrightElementHandle(handle)

	async def query_selector_all(self, selector: str) -> list['PlaywrightElementHandle']:
		handles = await self._frame.query_selector_all(selector)
		return [PlaywrightElementHandle(h) for h in handles]

	def locator(self, selector: str) -> 'PlaywrightLocator':
		return PlaywrightLocator(self._frame.locator(selector))

	def frame_locator(self, selector: str) -> 'PlaywrightLocator':
		return PlaywrightLocator(self._frame.frame_locator(selector).locator(selector))

	async def click(self, *args, **kwargs):
		await self._frame.click(*args, **kwargs)


class PlaywrightKeyboard(AbstractKeyboard):
	def __init__(self, keyboard):
		self._keyboard = keyboard

	async def press(self, keys: str) -> None:
		await self._keyboard.press(keys)

	async def type(self, text: str, delay: float = 0) -> None:
		await self._keyboard.type(text, delay=delay)


class PlaywrightMouse(AbstractMouse):
	def __init__(self, mouse):
		self._mouse = mouse

	async def move(self, x: int, y: int) -> None:
		await self._mouse.move(x, y)

	async def down(self) -> None:
		await self._mouse.down()

	async def up(self) -> None:
		await self._mouse.up()


class PlaywrightDownload(AbstractDownload):
	def __init__(self, download):
		self._download = download

	@property
	def suggested_filename(self) -> str:
		return self._download.suggested_filename

	async def save_as(self, path: str) -> None:
		await self._download.save_as(path)

	@property
	async def value(self):
		return self


class PlaywrightPage(Page):
	def __init__(self, page: PlaywrightRawPage):
		self._page: PlaywrightRawPage = page

	def __eq__(self, other):
		if isinstance(other, PlaywrightPage):
			return self._page.url == other._page.url
		return False

	def __hash__(self):
		return hash(self._page.url)

	async def goto(self, url: str, **kwargs):
		await self._page.goto(url, **kwargs)

	async def click(self, selector: str) -> None:
		await self._page.click(selector)

	async def fill(self, selector: str, text: str) -> None:
		await self._page.fill(selector, text)

	async def get_content(self) -> str:
		return await self._page.content()

	async def screenshot(self, **kwargs) -> bytes:
		return await self._page.screenshot(**kwargs)

	async def close(self):
		await self._page.close()

	async def evaluate(self, script: str, *args, **kwargs):
		return await self._page.evaluate(script, *args, **kwargs)

	async def wait_for_load_state(self, state: Literal['domcontentloaded', 'load', 'networkidle'] | None = 'load', **kwargs):
		await self._page.wait_for_load_state(state, **kwargs)

	async def set_viewport_size(self, viewport_size: ViewportSize) -> None:
		await self._page.set_viewport_size(viewport_size)

	def on(self, event: str, handler) -> None:
		self._page.on(event, handler)  # type: ignore

	def remove_listener(self, event: str, handler) -> None:
		self._page.remove_listener(event, handler)

	@property
	def url(self) -> str:
		return self._page.url

	def is_closed(self) -> bool:
		return self._page.is_closed()

	async def bring_to_front(self) -> None:
		await self._page.bring_to_front()

	async def expose_function(self, name: str, func) -> None:
		await self._page.expose_function(name, func)

	async def go_back(self, **kwargs) -> None:
		await self._page.go_back(**kwargs)

	async def go_forward(self, **kwargs) -> None:
		await self._page.go_forward(**kwargs)

	async def wait_for_selector(self, selector: str, **kwargs) -> None:
		await self._page.wait_for_selector(selector, **kwargs)

	async def content(self) -> str:
		return await self._page.content()

	async def title(self) -> str:
		return await self._page.title()

	@property
	def frames(self) -> list:
		return [PlaywrightFrame(frame) for frame in self._page.frames]

	async def query_selector(self, selector: str) -> 'PlaywrightElementHandle | None':
		handle = await self._page.query_selector(selector)
		if handle is None:
			return None
		return PlaywrightElementHandle(handle)

	async def query_selector_all(self, selector: str) -> list['PlaywrightElementHandle']:
		handles = await self._page.query_selector_all(selector)
		return [PlaywrightElementHandle(h) for h in handles]

	def locator(self, selector: str) -> 'PlaywrightLocator':
		return PlaywrightLocator(self._page.locator(selector))

	def frame_locator(self, selector: str) -> 'PlaywrightLocator':
		return PlaywrightLocator(self._page.frame_locator(selector).locator(selector))

	async def emulate_media(self, **kwargs) -> None:
		await self._page.emulate_media(**kwargs)

	async def pdf(self, **kwargs) -> Any:
		return await self._page.pdf(**kwargs)

	def get_by_text(self, text: str, exact: bool = False) -> 'PlaywrightLocator':
		return PlaywrightLocator(self._page.get_by_text(text, exact=exact))

	@property
	def keyboard(self) -> 'PlaywrightKeyboard':
		return PlaywrightKeyboard(self._page.keyboard)

	@property
	def mouse(self) -> PlaywrightMouse:
		return PlaywrightMouse(self._page.mouse)

	@property
	def viewport_size(self) -> dict | None:
		# Playwright's Page has a viewport_size property, but it may be None
		vs = self._page.viewport_size
		if vs is not None:
			return {'width': vs['width'], 'height': vs['height']}
		return None

	async def reload(self) -> None:
		await self._page.reload()

	async def get_property(self, property_name: str):
		# Playwright's Page does not have get_property; this can be removed or raise NotImplementedError
		raise NotImplementedError('get_property is not available on Playwright Page')

	async def expect_download(self, *args, **kwargs) -> 'AbstractDownload':
		cm = self._page.expect_download(*args, **kwargs)
		download = await cm.__aenter__()
		return PlaywrightDownload(download)

	async def type(self, selector: str, text: str, delay: float = 0) -> None:
		await self._page.type(selector, text, delay=delay)

	async def wait_for_timeout(self, timeout: float) -> None:
		await self._page.wait_for_timeout(timeout)


class PlaywrightElementHandle(AbstractElementHandle):
	def __init__(self, element_handle: ElementHandle):
		self._element_handle = element_handle

	async def is_visible(self) -> bool:
		return await self._element_handle.is_visible()

	async def is_hidden(self) -> bool:
		return await self._element_handle.is_hidden()

	async def bounding_box(self) -> dict | None:
		bbox = await self._element_handle.bounding_box()
		return dict(bbox) if bbox else None

	async def scroll_into_view_if_needed(self, timeout: int | float | None = None) -> None:
		kwargs = {}
		if timeout is not None:
			kwargs['timeout'] = timeout
		await self._element_handle.scroll_into_view_if_needed(**kwargs)

	async def element_handle(self) -> 'PlaywrightElementHandle':
		return self

	async def wait_for_element_state(
		self,
		state: Literal['disabled', 'editable', 'enabled', 'hidden', 'stable', 'visible'],
		timeout: int | float | None = None,
	) -> None:
		await self._element_handle.wait_for_element_state(state, timeout=timeout)

	async def query_selector(self, selector: str) -> 'PlaywrightElementHandle | None':
		handle = await self._element_handle.query_selector(selector)
		if handle is None:
			return None
		return PlaywrightElementHandle(handle)

	async def query_selector_all(self, selector: str) -> list['PlaywrightElementHandle']:
		handles = await self._element_handle.query_selector_all(selector)
		return [PlaywrightElementHandle(h) for h in handles]

	def on(self, event: str, handler) -> None:
		self._element_handle.on(event, handler)

	def remove_listener(self, event: str, handler) -> None:
		self._element_handle.remove_listener(event, handler)

	async def click(self, *args, **kwargs):
		await self._element_handle.click(*args, **kwargs)

	async def get_property(self, property_name: str):
		return await self._element_handle.get_property(property_name)

	async def evaluate(self, script: str, *args, **kwargs):
		return await self._element_handle.evaluate(script, *args, **kwargs)

	async def type(self, text: str, delay: float = 0) -> None:
		await self._element_handle.type(text, delay=delay)

	async def fill(self, text: str, timeout: float | None = None) -> None:
		kwargs = {}
		if timeout is not None:
			kwargs['timeout'] = timeout
		await self._element_handle.fill(text, **kwargs)

	async def clear(self, timeout: float | None = None) -> None:
		kwargs = {}
		if timeout is not None:
			kwargs['timeout'] = timeout
		await self._element_handle.fill('', **kwargs)


class PlaywrightLocator(AbstractLocator):
	def __init__(self, locator: Locator):
		self._locator = locator

	def filter(self, **kwargs) -> 'PlaywrightLocator':
		return PlaywrightLocator(self._locator.filter(**kwargs))

	async def evaluate_all(self, expression: str) -> Any:
		return await self._locator.evaluate_all(expression)

	async def count(self) -> int:
		return await self._locator.count()

	@property
	def first(self) -> Awaitable['PlaywrightElementHandle | None']:
		async def _first():
			handle = await self._locator.first.element_handle()
			return PlaywrightElementHandle(handle) if handle else None

		return _first()

	def nth(self, index: int) -> 'PlaywrightLocator':
		return PlaywrightLocator(self._locator.nth(index))

	async def select_option(self, **kwargs) -> Any:
		return await self._locator.select_option(**kwargs)

	async def element_handle(self) -> 'PlaywrightElementHandle | None':
		handle = await self._locator.element_handle()
		return PlaywrightElementHandle(handle) if handle else None

	def locator(self, selector: str) -> 'PlaywrightLocator':
		return PlaywrightLocator(self._locator.locator(selector))

	def frame_locator(self, selector: str) -> 'PlaywrightLocator':
		return PlaywrightLocator(self._locator.frame_locator(selector).locator(selector))

	async def click(self, *args, **kwargs):
		await self._locator.click(*args, **kwargs)

	async def evaluate(self, script: str, *args, **kwargs):
		return await self._locator.evaluate(script, *args, **kwargs)

	async def fill(self, text: str, timeout: float | None = None) -> None:
		kwargs = {}
		if timeout is not None:
			kwargs['timeout'] = timeout
		await self._locator.fill(text, **kwargs)


async def setup_remote_cdp_browser(browser_type: 'BrowserType', config: BrowserConfig) -> 'Browser':
	if 'firefox' in (config.browser_binary_path or '').lower():
		raise ValueError(
			'CDP has been deprecated for firefox, check: https://fxdx.dev/deprecating-cdp-support-in-firefox-embracing-the-future-with-webdriver-bidi/'
		)
	if not config.cdp_url:
		raise ValueError('CDP URL is required')
	logger.info(f'🔌  Connecting to remote browser via CDP {config.cdp_url}')
	browser = await browser_type.connect_over_cdp(config.cdp_url)
	return browser


async def setup_remote_wss_browser(browser_type: 'BrowserType', config: BrowserConfig) -> 'Browser':
	if not config.wss_url:
		raise ValueError('WSS URL is required')
	logger.info(f'🔌  Connecting to remote browser via WSS {config.wss_url}')
	browser = await browser_type.connect(ws_endpoint=config.wss_url)
	return browser


async def setup_user_provided_browser(browser_type: 'BrowserType', config: BrowserConfig) -> 'Browser':
	if not config.browser_binary_path:
		raise ValueError('A browser_binary_path is required')
	try:
		async with httpx.AsyncClient() as client:
			response = await client.get(f'http://localhost:{config.chrome_remote_debugging_port}/json/version', timeout=2)
			if response.status_code == 200:
				logger.info(
					f'🔌  Reusing existing browser found running on http://localhost:{config.chrome_remote_debugging_port}'
				)
			browser = await browser_type.connect_over_cdp(
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
				response = await client.get(f'http://localhost:{config.chrome_remote_debugging_port}/json/version', timeout=2)
				if response.status_code == 200:
					break
		except httpx.RequestError:
			pass
		await asyncio.sleep(1)
	try:
		browser = await browser_type.connect_over_cdp(
			endpoint_url=f'http://localhost:{config.chrome_remote_debugging_port}',
			timeout=20000,
		)
		return browser
	except Exception as e:
		logger.error(f'❌  Failed to start a new Chrome instance: {str(e)}')
		raise RuntimeError(
			'To start chrome in Debug mode, you need to close all existing Chrome instances and try again otherwise we can not connect to the instance.'
		)
