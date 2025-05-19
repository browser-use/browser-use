from typing import Any, Awaitable, cast

from .driver import AbstractBrowser, AbstractContext, Page, AbstractTracing, AbstractFrame, AbstractLocator, AbstractKeyboard, ElementHandle, AbstractMouse, AbstractDownload

from playwright.async_api import Browser, BrowserContext

class PlaywrightBrowser(AbstractBrowser):
    def __init__(self, browser: Browser):
        self._browser = browser
        self.chromium = getattr(browser, 'chromium', None)
        self.firefox = getattr(browser, 'firefox', None)
        self.webkit = getattr(browser, 'webkit', None)

    @classmethod
    async def connect_over_cdp(cls, cdp_url: str, timeout: int = 30000) -> 'PlaywrightBrowser':
        from playwright.async_api import async_playwright
        pw = await async_playwright().start()
        browser = await pw.chromium.connect_over_cdp(cdp_url, timeout=timeout)
        return cls(browser)

    async def launch(self, **kwargs):
        raise NotImplementedError("launch is not implemented for PlaywrightBrowser")

    async def new_context(self, viewport=(1280, 800)):
        ctx = await self._browser.new_context(viewport={'width': viewport[0], 'height': viewport[1]})
        return PlaywrightContext(ctx)

    async def close(self):
        await self._browser.close()

    @property
    def contexts(self):
        return [PlaywrightContext(ctx) for ctx in self._browser.contexts]

    @property
    def version(self) -> str:
        return self._browser.version if hasattr(self._browser, 'version') else ""


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
        allowed_keys = {"name", "value", "url", "domain", "path", "expires", "httpOnly", "secure", "sameSite"}
        cookies_clean = [
            {k: v for k, v in cookie.items() if k in allowed_keys}
            for cookie in cookies
        ]
        await self._context.add_cookies(cast(list, cookies_clean))

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
    def __init__(self, frame):
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

    def frame_locator(self, selector: str) -> 'PlaywrightFrameLocator':
        return PlaywrightFrameLocator(self._frame.frame_locator(selector))

    async def click(self, *args, **kwargs):
        await self._frame.click(*args, **kwargs)

    async def get_property(self, property_name: str):
        return await self._frame.get_property(property_name)


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
    def __init__(self, page):
        self._page = page

    async def goto(self, url: str, **kwargs):
        await self._page.goto(url, **kwargs)

    async def click(self, *args, **kwargs):
        await self._page.click(*args, **kwargs)

    async def fill(self, text: str) -> None:
        await self._page.fill(text)

    async def get_content(self) -> str:
        return await self._page.content()

    async def screenshot(self, **kwargs) -> bytes:
        return await self._page.screenshot(**kwargs)

    async def close(self):
        await self._page.close()

    async def evaluate(self, script: str, *args, **kwargs):
        return await self._page.evaluate(script, *args, **kwargs)

    async def wait_for_load_state(self, state: str = 'load', **kwargs):
        await self._page.wait_for_load_state(state, **kwargs)

    async def set_viewport_size(self, viewport_size: dict) -> None:
        await self._page.set_viewport_size(viewport_size)

    def on(self, event: str, handler) -> None:
        self._page.on(event, handler)

    def remove_listener(self, event: str, handler) -> None:
        self._page.remove_listener(event, handler)

    @property
    def url(self) -> str:
        return self._page.url

    @property
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

    def frame_locator(self, selector: str) -> 'PlaywrightFrameLocator':
        return PlaywrightFrameLocator(self._page.frame_locator(selector))

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

    async def viewport_size(self) -> dict:
        return await self._page.viewport_size()

    async def reload(self) -> None:
        await self._page.reload()

    async def get_property(self, property_name: str):
        return await self._page.get_property(property_name)

    async def expect_download(self, *args, **kwargs) -> 'AbstractDownload':
        cm = self._page.expect_download(*args, **kwargs)
        download = await cm.__aenter__()
        return PlaywrightDownload(download)

    async def type(self, text: str, delay: float = 0) -> None:
        await self._page.type(text, delay=delay)

    async def wait_for_timeout(self, timeout: float) -> None:
        await self._page.wait_for_timeout(timeout)


class PlaywrightElementHandle(ElementHandle):
    def __init__(self, element_handle):
        self._element_handle = element_handle

    async def is_visible(self) -> bool:
        return await self._element_handle.is_visible()

    async def is_hidden(self) -> bool:
        return await self._element_handle.is_hidden()

    async def bounding_box(self) -> dict | None:
        return await self._element_handle.bounding_box()

    async def scroll_into_view_if_needed(self) -> None:
        await self._element_handle.scroll_into_view_if_needed()

    async def element_handle(self) -> 'PlaywrightElementHandle':
        return self

    async def wait_for_element_state(self, state: str, timeout: int | float | None = None) -> None:
        await self._element_handle.wait_for_element_state(state, timeout=timeout)

    async def query_selector(self, selector: str) -> 'PlaywrightElementHandle | None':
        handle = await self._element_handle.query_selector(selector)
        if handle is None:
            return None
        return PlaywrightElementHandle(handle)

    async def query_selector_all(self, selector: str) -> list['PlaywrightElementHandle']:
        handles = await self._element_handle.query_selector_all(selector)
        return [PlaywrightElementHandle(h) for h in handles]

    def locator(self, selector: str) -> 'PlaywrightLocator':
        return PlaywrightLocator(self._element_handle.locator(selector))

    def frame_locator(self, selector: str) -> 'PlaywrightFrameLocator':
        return PlaywrightFrameLocator(self._element_handle.frame_locator(selector))

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
    def __init__(self, locator):
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

    async def query_selector(self, selector: str) -> 'PlaywrightElementHandle | None':
        handle = await self._locator.query_selector(selector)
        if handle is None:
            return None
        return PlaywrightElementHandle(handle)

    async def query_selector_all(self, selector: str) -> list['PlaywrightElementHandle']:
        handles = await self._locator.query_selector_all(selector)
        return [PlaywrightElementHandle(h) for h in handles]

    def locator(self, selector: str) -> 'PlaywrightLocator':
        return PlaywrightLocator(self._locator.locator(selector))

    def frame_locator(self, selector: str) -> 'PlaywrightFrameLocator':
        return PlaywrightFrameLocator(self._locator.frame_locator(selector))

    async def click(self, *args, **kwargs):
        await self._locator.click(*args, **kwargs)

    async def get_property(self, property_name: str):
        return await self._locator.get_property(property_name)

    async def evaluate(self, script: str, *args, **kwargs):
        return await self._locator.evaluate(script, *args, **kwargs)

    async def fill(self, text: str, timeout: float | None = None) -> None:
        kwargs = {}
        if timeout is not None:
            kwargs['timeout'] = timeout
        await self._locator.fill(text, **kwargs)


class PlaywrightFrameLocator(PlaywrightLocator):
    def __init__(self, frame_locator):
        self._frame_locator = frame_locator
        super().__init__(frame_locator)

    async def frame(self) -> 'PlaywrightFrame':
        frame = await self._frame_locator.frame()
        return PlaywrightFrame(frame)

    async def click(self, *args, **kwargs):
        raise NotImplementedError("click is not supported on FrameLocator")

    async def get_property(self, property_name: str):
        raise NotImplementedError("get_property is not supported on FrameLocator")

    async def evaluate(self, script: str, *args, **kwargs):
        raise NotImplementedError("evaluate is not supported on FrameLocator")
