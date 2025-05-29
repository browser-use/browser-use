from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Literal

from patchright.async_api import Playwright as _Patchright
from playwright.async_api import Browser as _Browser
from playwright.async_api import BrowserContext as _BrowserContext
from playwright.async_api import BrowserType as _BrowserType
from playwright.async_api import ElementHandle as _ElementHandle
from playwright.async_api import Frame as _Frame
from playwright.async_api import Locator as _Locator
from playwright.async_api import Page as _Page
from playwright.async_api import Playwright as _Playwright
from playwright.async_api import async_playwright

from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession
from browser_use.typing import (
	Browser,
	Download,
	Driver,
	ElementHandle,
	Frame,
	Keyboard,
	Locator,
	Mouse,
	Page,
	Tracing,
	ViewportSize,
)

logger = logging.getLogger(__name__)


class PlaywrightDriver(Driver):
	def __init__(self, profile: BrowserProfile, backend=async_playwright) -> None:
		super().__init__(profile)
		self.backend = backend

	async def init_impl(self) -> None:
		self.impl = PlaywrightBrowser(self.profile, backend=self.backend)
		await self.impl.setup()


class PlaywrightBrowser(Browser):
	def __init__(self, profile: BrowserProfile, backend) -> None:
		super().__init__()
		logger.info(f'🛠️  Created BrowserEngine: {self.__class__.__name__}')
		self._profile = profile
		self._backend = backend
		self._playwright: _Playwright | _Patchright | None = None
		self._browser_type: _BrowserType | None = None
		self._browser: _Browser | None = None

	async def setup(self) -> Browser:
		"""Setup connector"""
		logger.info(f'🛠️  Initializing BrowserEngine: {self.__class__.__name__} channel={self._profile.channel}')
		self._playwright = await self._backend().start()  # type: ignore
		assert isinstance(self._playwright, (_Playwright, _Patchright)), 'Playwright object is not initialized'
		if self._profile.channel == 'chromium':
			self._browser_type = self._playwright.chromium  # type: ignore
		elif self._profile.channel == 'firefox':
			self._browser_type = self._playwright.firefox  # type: ignore
		elif self._profile.channel == 'webkit':
			self._browser_type = self._playwright.webkit  # type: ignore
		else:
			raise ValueError(f'Invalid browser name: {self._profile.channel}')
		assert self._browser_type is not None, 'Browser type is not initialized'
		return self

	async def open(self, **kwargs: Any) -> Browser:
		"""Open a connection to browser"""
		assert self._browser_type is not None, 'Browser type is not initialized'
		if "endpoint_url" in kwargs:
			self._browser = await self._browser_type.connect_over_cdp(**kwargs)
		elif "ws_endpoint" in kwargs:
			self._browser = await self._browser_type.connect(**kwargs)
		else:
			self._browser = await self._browser_type.launch(**kwargs)
		assert self._browser is not None, 'Browser is not initialized'
		logger.info(f'🛠️  BrowserEngine.open(): {self.__class__.__name__} channel={self._profile.channel}')
		return self

	async def close(self) -> None:
		"""Close a connection to browser"""
		logger.info(f'🛠️  BrowserEngine.close(): {self.__class__.__name__} channel={self._profile.channel}')
		if self._browser:
			await self._browser.close()
		if self._playwright:
			await self._playwright.stop()

	async def new_session(self, **kwargs: Any) -> BrowserSession:
		"""Create a new browser session"""
		logger.info(f'🛠️  BrowserEngine.new_context(): {self.__class__.__name__} channel={self._profile.channel}')
		assert self._browser is not None, 'Browser is not initialized'
		ctx: _BrowserContext = await self._browser.new_context(**kwargs)
		return PlaywrightSession(self._profile, ctx)

	def is_connected(self) -> bool:
		assert self._browser is not None, 'Browser is not initialized'
		return self._browser.is_connected()

	@property
	def sessions(self) -> list[BrowserSession]:
		"""Get all browser contexts"""
		logger.info(f'🛠️  BrowserEngine.contexts(): {self.__class__.__name__} channel={self._profile.channel}')
		assert self._browser is not None, 'Browser is not initialized'
		return [PlaywrightSession(self._profile, ctx) for ctx in self._browser.contexts]

	@property
	def version(self) -> str:
		"""Get the browser version"""
		logger.info(f'🛠️  BrowserEngine.version(): {self.__class__.__name__} channel={self._profile.channel}')
		assert self._browser is not None, 'Browser is not initialized'
		return self._browser.version


class PlaywrightSession(BrowserSession):
	def __init__(self, profile: BrowserProfile, ctx: _BrowserContext | None = None) -> None:
		super().__init__(browser_profile=profile)
		self.browser_context: _BrowserContext | None = ctx  # To store playwright context object

	@property
	def browser(self) -> Browser:
		assert isinstance(self.driver, PlaywrightDriver), 'Driver is not a PlaywrightDriver'
		return PlaywrightBrowser(self.browser_profile, self.driver.backend)

	async def new_page(self) -> Page:
		assert self.browser_context is not None, 'Context is not initialized'
		page = await self.browser_context.new_page()
		return PlaywrightPage(page)

	async def close(self) -> None:
		assert self.browser_context is not None, 'Context is not initialized'
		return await self.browser_context.close()

	@property
	def tracing(self) -> Tracing:
		assert self.browser_context is not None, 'Context is not initialized'
		return PlaywrightTracing(self.browser_context.tracing)

	@property
	def pages(self) -> list[Page]:
		assert self.browser_context is not None, 'Context is not initialized'
		return [PlaywrightPage(page) for page in self.browser_context.pages]

	async def grant_permissions(self, permissions: list[str], origin: str | None = None) -> None:
		assert self.browser_context is not None, 'Context is not initialized'
		await self.browser_context.grant_permissions(permissions, origin=origin)

	async def add_cookies(self, cookies: list[dict[str, Any]]) -> None:
		assert self.browser_context is not None, 'Context is not initialized'
		await self.browser_context.add_cookies(cookies)  # type: ignore

	async def add_init_script(self, script: str) -> None:
		assert self.browser_context is not None, 'Context is not initialized'
		await self.browser_context.add_init_script(script)

	def remove_listener(self, event: str, handler: Any) -> None:
		assert self.browser_context is not None, 'Context is not initialized'
		self.browser_context.remove_listener(event, handler)

	def on(self, event: str, handler: Any) -> None:
		self.browser_context.on(event, handler)  # type: ignore

	async def cookies(self) -> list[dict[str, Any]]:
		assert self.browser_context is not None, 'Context is not initialized'
		cookies = await self.browser_context.cookies()
		return [vars(cookie) for cookie in cookies]


class PlaywrightTracing(Tracing):
	def __init__(self, tracing: Any):
		self._tracing = tracing

	async def start(self, **kwargs: Any) -> None:
		await self._tracing.start(**kwargs)

	async def stop(self, **kwargs: Any) -> None:
		await self._tracing.stop(**kwargs)


class PlaywrightFrame(Frame):
	def __init__(self, frame: _Frame):
		self._frame = frame

	@property
	def url(self) -> str:
		return self._frame.url

	async def content(self) -> str:
		return await self._frame.content()

	async def evaluate(self, script: str, *args: Any, **kwargs: Any) -> Any:
		return await self._frame.evaluate(script, *args, **kwargs)

	async def query_selector(self, selector: str) -> ElementHandle | None:
		handle = await self._frame.query_selector(selector)
		if handle is None:
			return None
		return PlaywrightElementHandle(handle)

	async def query_selector_all(self, selector: str) -> list[ElementHandle]:
		handles = await self._frame.query_selector_all(selector)
		return [PlaywrightElementHandle(h) for h in handles]

	def locator(self, selector: str) -> Locator:
		return PlaywrightLocator(self._frame.locator(selector))

	async def click(self, *args: Any, **kwargs: Any) -> Any:
		await self._frame.click(*args, **kwargs)


class PlaywrightKeyboard(Keyboard):
	def __init__(self, keyboard: Any):
		self._keyboard = keyboard

	async def press(self, keys: str) -> None:
		await self._keyboard.press(keys)

	async def type(self, text: str, delay: float = 0) -> None:
		await self._keyboard.type(text, delay=delay)


class PlaywrightMouse(Mouse):
	def __init__(self, mouse: Any):
		self._mouse = mouse

	async def move(self, x: int, y: int) -> None:
		await self._mouse.move(x, y)

	async def down(self) -> None:
		await self._mouse.down()

	async def up(self) -> None:
		await self._mouse.up()


class PlaywrightDownload(Download):
	def __init__(self, download: Any):
		self._download = download

	@property
	def suggested_filename(self) -> str:
		return self._download.suggested_filename

	async def save_as(self, path: str) -> None:
		await self._download.save_as(path)

	@property
	async def value(self) -> None:
		return None


class PlaywrightPage(Page):
	def __init__(self, page: _Page):
		self._page: _Page = page

	async def goto(self, url: str, **kwargs: Any) -> None:
		await self._page.goto(url, **kwargs)

	async def click(self, selector: str) -> None:
		await self._page.click(selector)

	async def fill(self, selector: str, text: str) -> None:
		await self._page.fill(selector, text)

	async def get_content(self) -> str:
		return await self._page.content()

	async def screenshot(self, **kwargs: Any) -> bytes:
		return await self._page.screenshot(**kwargs)

	async def close(self) -> None:
		await self._page.close()

	async def wait_for_load_state(
		self, state: Literal['domcontentloaded', 'load', 'networkidle'] | None = 'load', **kwargs: Any
	) -> None:
		await self._page.wait_for_load_state(state, **kwargs)

	@property
	def context(self) -> _BrowserContext:
		return self._page.context

	@property
	def url(self) -> str:
		return self._page.url

	async def set_viewport_size(self, viewport: ViewportSize) -> None:
		await self._page.set_viewport_size(**viewport.model_dump())

	def is_closed(self) -> bool:
		return self._page.is_closed()

	async def bring_to_front(self) -> None:
		await self._page.bring_to_front()

	async def expose_function(self, name: str, func: Callable[..., Any]) -> None:
		await self._page.expose_function(name, func)  # type: ignore

	async def go_back(self, **kwargs: Any) -> None:
		await self._page.go_back(**kwargs)

	async def go_forward(self, **kwargs: Any) -> None:
		await self._page.go_forward(**kwargs)

	async def wait_for_selector(self, selector: str, **kwargs: Any) -> None:
		await self._page.wait_for_selector(selector, **kwargs)

	async def content(self) -> str:
		return await self._page.content()

	async def title(self) -> str:
		return await self._page.title()

	@property
	def frames(self) -> list[Frame]:
		return [PlaywrightFrame(frame) for frame in self._page.frames]

	async def emulate_media(self, **kwargs: Any) -> None:
		await self._page.emulate_media(**kwargs)

	async def pdf(self, **kwargs: Any) -> Any:
		return await self._page.pdf(**kwargs)

	@property
	def keyboard(self) -> Keyboard:
		return PlaywrightKeyboard(self._page.keyboard)

	def get_by_text(self, text: str, exact: bool = False) -> Locator:
		return PlaywrightLocator(self._page.get_by_text(text, exact=exact))

	@property
	def mouse(self) -> Mouse:
		return PlaywrightMouse(self._page.mouse)

	async def viewport_size(self) -> ViewportSize:
		vs = self._page.viewport_size
		return ViewportSize(width=vs['width'], height=vs['height']) if vs else ViewportSize(width=0, height=0)

	async def reload(self) -> None:
		await self._page.reload()

	async def expect_download(self, *args: Any, **kwargs: Any) -> Download:
		cm = self._page.expect_download(*args, **kwargs)
		download = await cm.__aenter__()
		return PlaywrightDownload(download)

	async def wait_for_timeout(self, timeout: float) -> None:
		await self._page.wait_for_timeout(timeout)

	async def type(self, selector: str, text: str, delay: float = 0) -> None:
		await self._page.type(selector, text, delay=delay)

	def locator(self, selector: str) -> Locator:
		return PlaywrightLocator(self._page.locator(selector))

	async def query_selector(self, selector: str) -> ElementHandle | None:
		handle = await self._page.query_selector(selector)
		if handle is None:
			return None
		return PlaywrightElementHandle(handle)

	async def query_selector_all(self, selector: str) -> list[ElementHandle]:
		handles = await self._page.query_selector_all(selector)
		return [PlaywrightElementHandle(h) for h in handles]

	async def evaluate(self, script: str, *args: Any, **kwargs: Any) -> Any:
		return await self._page.evaluate(script, *args, **kwargs)

	def on(self, event: str, handler: Any) -> None:
		self._page.on(event, handler)  # type: ignore

	def remove_listener(self, event: str, handler: Any) -> None:
		self._page.remove_listener(event, handler)  # type: ignore


class PlaywrightElementHandle(ElementHandle):
	def __init__(self, element_handle: _ElementHandle):
		self._element_handle = element_handle

	async def is_visible(self) -> bool:
		return await self._element_handle.is_visible()

	async def is_hidden(self) -> bool:
		return await self._element_handle.is_hidden()

	async def bounding_box(self) -> dict[str, Any] | None:
		bbox = await self._element_handle.bounding_box()
		return dict(bbox) if bbox else None

	async def scroll_into_view_if_needed(self, timeout: int | float | None = None) -> None:
		kwargs: dict[str, Any] = {}
		if timeout is not None:
			kwargs['timeout'] = timeout
		await self._element_handle.scroll_into_view_if_needed(**kwargs)

	async def element_handle(self) -> ElementHandle:
		return self

	async def wait_for_element_state(
		self,
		state: Literal['disabled', 'editable', 'enabled', 'hidden', 'stable', 'visible'],
		timeout: int | float | None = None,
	) -> None:
		await self._element_handle.wait_for_element_state(state, timeout=timeout)

	async def query_selector(self, selector: str) -> ElementHandle | None:
		handle = await self._element_handle.query_selector(selector)
		if handle is None:
			return None
		return PlaywrightElementHandle(handle)

	async def query_selector_all(self, selector: str) -> list[ElementHandle]:
		handles = await self._element_handle.query_selector_all(selector)
		return [PlaywrightElementHandle(h) for h in handles]

	def on(self, event: str, handler: Any) -> None:
		self._element_handle.on(event, handler)

	def remove_listener(self, event: str, handler: Any) -> None:
		self._element_handle.remove_listener(event, handler)

	async def click(self, *args: Any, **kwargs: Any) -> Any:
		await self._element_handle.click(*args, **kwargs)

	async def get_property(self, property_name: str) -> Any:
		return await self._element_handle.get_property(property_name)

	async def evaluate(self, script: str, *args: Any, **kwargs: Any) -> Any:
		return await self._element_handle.evaluate(script, *args, **kwargs)

	async def type(self, text: str, delay: float = 0) -> None:
		await self._element_handle.type(text, delay=delay)

	async def fill(self, text: str, timeout: float | None = None) -> None:
		kwargs: dict[str, Any] = {}
		if timeout is not None:
			kwargs['timeout'] = timeout
		await self._element_handle.fill(text, **kwargs)

	async def clear(self, timeout: float | None = None) -> None:
		kwargs: dict[str, Any] = {}
		if timeout is not None:
			kwargs['timeout'] = timeout
		await self._element_handle.fill('', **kwargs)


class PlaywrightLocator(Locator):
	def __init__(self, locator: _Locator):
		self._locator = locator

	def filter(self, **kwargs: Any) -> Locator:
		return PlaywrightLocator(self._locator.filter(**kwargs))

	async def evaluate_all(self, expression: str) -> Any:
		return await self._locator.evaluate_all(expression)

	async def count(self) -> int:
		return await self._locator.count()

	@property
	def first(self) -> Locator:
		return PlaywrightLocator(self._locator.first)

	def nth(self, index: int) -> Locator:
		return PlaywrightLocator(self._locator.nth(index))

	async def select_option(self, **kwargs: Any) -> Any:
		return await self._locator.select_option(**kwargs)

	async def element_handle(self) -> ElementHandle | None:
		handle = await self._locator.element_handle()
		return PlaywrightElementHandle(handle) if handle else None

	def locator(self, selector: str) -> Locator:
		return PlaywrightLocator(self._locator.locator(selector))

	async def click(self, *args: Any, **kwargs: Any) -> Any:
		try:
			handle = await self._locator.element_handle()
			await handle.click(*args, **kwargs)
		except Exception:
			logger.error(f'Error clicking on element: {self._locator}')
			raise

	async def evaluate(self, script: str, *args: Any, **kwargs: Any) -> Any:
		try:
			handle = await self._locator.element_handle()
			return await handle.evaluate(script, *args, **kwargs)
		except Exception:
			logger.error(f'Error evaluating element: {self._locator}')
			raise

	async def fill(self, text: str, timeout: float | None = None) -> None:
		kwargs: dict[str, Any] = {}
		if timeout is not None:
			kwargs['timeout'] = timeout
		await self._locator.fill(text, **kwargs)
