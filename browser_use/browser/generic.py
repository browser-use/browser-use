from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, AsyncContextManager, Literal

if TYPE_CHECKING:
	# these will create circular imports
	from browser_use.browser import BrowserProfile
	from browser_use.browser.types import Geolocation, StorageState, ViewportSize

logger = logging.getLogger(__name__)


class EventEmitterMixin(ABC):
	@abstractmethod
	def on(self, event: str, handler: Any) -> None: ...

	@abstractmethod
	def remove_listener(self, event: str, handler: Any) -> None: ...


class PropertyMixin(ABC):
	@abstractmethod
	async def get_property(self, property_name: str) -> Any: ...


class LocatorMixin(ABC):
	@abstractmethod
	def locator(self, selector: str) -> Locator: ...


class QueryableMixin(ABC):
	@abstractmethod
	async def query_selector(self, selector: str) -> ElementHandle | None: ...

	@abstractmethod
	async def query_selector_all(self, selector: str) -> list[ElementHandle]: ...

	@abstractmethod
	async def evaluate(self, expression: str, arg: Any | None = None, *, isolated_context: bool | None = True) -> Any: ...

	@abstractmethod
	async def click(self, *args: Any, **kwargs: Any) -> Any: ...


class GenericBrowser(ABC):
	@abstractmethod
	async def launch(self, **kwargs: Any) -> GenericBrowser:
		pass

	@abstractmethod
	async def launch_persistent_context(self, **kwargs: Any) -> GenericBrowserContext:
		pass

	@abstractmethod
	async def connect(self, url: str, **kwargs: Any) -> GenericBrowser:
		pass

	@abstractmethod
	async def connect_over_cdp(self, cdp_url: str, **kwargs: Any) -> GenericBrowser:
		pass

	@abstractmethod
	async def connect_over_wss(self, wss_url: str, **kwargs: Any) -> GenericBrowser:
		pass

	@abstractmethod
	async def new_context(self, **kwargs: Any) -> GenericBrowserContext:
		pass

	@abstractmethod
	def is_connected(self) -> bool:
		pass

	@abstractmethod
	async def open(self, **kwargs: Any) -> GenericBrowser:
		pass

	@abstractmethod
	async def close(self) -> None:
		pass

	@property
	@abstractmethod
	def contexts(self) -> list[GenericBrowserContext]:
		pass

	@property
	@abstractmethod
	def version(self) -> str:
		pass


class GenericBrowserContext(ABC):
	@abstractmethod
	async def new_cdp_session(self, page: Page | Frame) -> CDPSession:
		pass

	@abstractmethod
	async def new_page(self) -> Page:
		pass

	@abstractmethod
	async def close(self) -> None:
		pass

	@property
	@abstractmethod
	def pages(self) -> list[Page]:
		pass

	@property
	@abstractmethod
	def browser(self) -> GenericBrowser:
		pass

	@property
	@abstractmethod
	def tracing(self) -> Tracing:
		pass

	@abstractmethod
	async def expose_binding(self, name: str, func: Any) -> None:
		pass

	@abstractmethod
	async def add_init_script(self, script: str) -> None:
		pass

	@abstractmethod
	async def cookies(self) -> list[dict[str, Any]]:
		pass

	@abstractmethod
	async def storage_state(self) -> StorageState:
		pass

	@abstractmethod
	async def add_cookies(self, cookies: list[dict[str, Any]]) -> None:
		pass

	@abstractmethod
	async def grant_permissions(self, permissions: list[str]) -> None:
		pass

	@abstractmethod
	async def set_default_timeout(self, timeout: float) -> None:
		pass

	@abstractmethod
	async def set_default_navigation_timeout(self, timeout: float) -> None:
		pass

	@abstractmethod
	async def set_extra_http_headers(self, headers: dict[str, str]) -> None:
		pass

	@abstractmethod
	async def set_geolocation(self, geolocation: Geolocation) -> None:
		pass


class Frame(QueryableMixin, LocatorMixin, ABC):
	@property
	@abstractmethod
	def url(self) -> str:
		pass

	@abstractmethod
	async def content(self) -> str:
		pass

	@abstractmethod
	async def wait_for_load_state(self, timeout: int) -> None:
		pass


class Page(EventEmitterMixin, QueryableMixin, LocatorMixin, ABC):
	@property
	@abstractmethod
	def context(self) -> GenericBrowserContext:
		pass

	@abstractmethod
	async def goto(self, url: str, **kwargs: Any) -> None:
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
	async def screenshot(self, **kwargs: Any) -> bytes:
		pass

	@abstractmethod
	async def close(self) -> None:
		pass

	@abstractmethod
	async def wait_for_load_state(
		self, state: Literal['domcontentloaded', 'load', 'networkidle'] | None = 'load', **kwargs: Any
	) -> None:
		pass

	@property
	@abstractmethod
	def url(self) -> str:
		pass

	@property
	@abstractmethod
	def accessibility(self) -> Accessibility:
		pass

	@abstractmethod
	async def set_viewport_size(self, viewport_size: ViewportSize) -> None:
		pass

	@abstractmethod
	def is_closed(self) -> bool:
		pass

	@abstractmethod
	async def bring_to_front(self) -> None:
		pass

	@abstractmethod
	async def expose_function(self, name: str, func: Any) -> None:
		pass

	@abstractmethod
	async def go_back(self, **kwargs: Any) -> None:
		pass

	@abstractmethod
	async def go_forward(self, **kwargs: Any) -> None:
		pass

	@abstractmethod
	async def wait_for_selector(self, selector: str, **kwargs: Any) -> None:
		pass

	@abstractmethod
	async def content(self) -> str:
		pass

	@abstractmethod
	async def title(self) -> str:
		pass

	@property
	@abstractmethod
	def frames(self) -> list[Frame]:
		pass

	@abstractmethod
	async def emulate_media(self, **kwargs: Any) -> None:
		pass

	@abstractmethod
	async def pdf(self, **kwargs: Any) -> Any:
		pass

	@property
	@abstractmethod
	def keyboard(self) -> Keyboard:
		pass

	@abstractmethod
	async def type(self, selector: str, text: str, delay: float = 0) -> None: ...

	@abstractmethod
	def get_by_text(self, text: str, exact: bool = False) -> Locator:
		pass

	@property
	@abstractmethod
	def mouse(self) -> Mouse:
		pass

	@property
	@abstractmethod
	def viewport_size(self) -> ViewportSize | None:
		pass

	@abstractmethod
	async def reload(self, **kwargs: Any) -> None:
		pass

	@abstractmethod
	def expect_download(self, timeout: float = 30000) -> AsyncContextManager[Download]:
		"""Waits for a download to be triggered.

		Args:
			timeout: Maximum time to wait for in milliseconds. Defaults to 30000.

		Returns:
			AsyncContextManager that yields a Download object when entered.
		"""
		pass

	@abstractmethod
	async def wait_for_timeout(self, timeout: float) -> None:
		pass

	@abstractmethod
	def frame_locator(self, selector: str) -> FrameLocator:
		"""Returns a FrameLocator object for the specified selector."""
		pass


class Accessibility(ABC):
	@abstractmethod
	async def snapshot(self, interesting_only: bool = True) -> dict[str, Any]:
		pass


class ElementHandle(QueryableMixin, EventEmitterMixin, PropertyMixin, ABC):
	@abstractmethod
	async def bounding_box(self) -> dict[str, Any] | None:
		pass

	@abstractmethod
	async def is_hidden(self) -> bool:
		"""Returns whether the element is hidden."""
		pass

	@abstractmethod
	async def type(self, text: str, delay: float = 0) -> None: ...

	@abstractmethod
	async def wait_for_element_state(
		self,
		state: Literal['disabled', 'editable', 'enabled', 'hidden', 'stable', 'visible'],
		timeout: int | float | None = None,
	) -> None:
		pass

	@abstractmethod
	async def clear(self, timeout: float | None = None) -> None:
		pass

	@abstractmethod
	async def fill(self, text: str, timeout: float | None = None) -> None: ...

	@abstractmethod
	async def scroll_into_view_if_needed(self, timeout: float | None = None) -> None:
		"""Scrolls element into view if needed."""
		pass


class Tracing(ABC):
	@abstractmethod
	async def start(self, **kwargs: Any) -> None:
		pass

	@abstractmethod
	async def stop(self, **kwargs: Any) -> None:
		pass


class Locator(LocatorMixin, ABC):
	@abstractmethod
	def filter(self, **kwargs: Any) -> Locator:
		pass

	@abstractmethod
	async def evaluate_all(self, expression: str) -> Any:
		pass

	@abstractmethod
	async def count(self) -> int:
		pass

	@property
	@abstractmethod
	def first(self) -> Locator:
		pass

	@abstractmethod
	def nth(self, index: int) -> Locator:
		pass

	@abstractmethod
	async def select_option(self, **kwargs: Any) -> Any:
		pass

	@abstractmethod
	async def element_handle(self) -> ElementHandle | None:
		pass

	@abstractmethod
	async def is_visible(self) -> bool:
		pass

	@abstractmethod
	async def is_hidden(self) -> bool:
		pass

	@abstractmethod
	async def bounding_box(self) -> dict[str, Any] | None:
		pass

	@abstractmethod
	async def scroll_into_view_if_needed(self, timeout: int | float | None = None) -> None:
		pass


class Keyboard(ABC):
	@abstractmethod
	async def press(self, keys: str) -> None:
		pass

	@abstractmethod
	async def type(self, text: str, delay: float = 0) -> None:
		pass


class Mouse(ABC):
	@abstractmethod
	async def move(self, x: int, y: int) -> None:
		pass

	@abstractmethod
	async def down(self) -> None:
		pass

	@abstractmethod
	async def up(self) -> None:
		pass

	@abstractmethod
	async def click(self, x: int, y: int) -> None:
		"""Clicks at the specified coordinates."""
		pass


class Download(ABC):
	@property
	@abstractmethod
	def suggested_filename(self) -> str:
		pass

	@abstractmethod
	async def save_as(self, path: str) -> None:
		pass

	@property
	@abstractmethod
	async def value(self) -> Download:
		pass


class FrameLocator(ABC):
	@abstractmethod
	def locator(self, selector: str) -> Locator:
		pass

	@abstractmethod
	async def first(self) -> Locator:
		pass

	@abstractmethod
	def nth(self, index: int) -> Locator:
		pass

	@abstractmethod
	def frame_locator(self, selector: str) -> FrameLocator:
		pass

	@abstractmethod
	async def element_handle(self) -> ElementHandle | None:
		pass

	@abstractmethod
	async def count(self) -> int:
		pass

	@abstractmethod
	async def is_visible(self) -> bool:
		pass

	@abstractmethod
	async def is_hidden(self) -> bool:
		pass

	@abstractmethod
	async def click(self, *args: Any, **kwargs: Any) -> Any:
		pass

	@abstractmethod
	async def fill(self, text: str, timeout: float | None = None) -> None:
		pass

	@abstractmethod
	async def evaluate(self, script: str, *args: Any, **kwargs: Any) -> Any:
		pass

	@abstractmethod
	async def evaluate_all(self, expression: str) -> Any:
		pass

	@abstractmethod
	async def select_option(self, **kwargs: Any) -> Any:
		pass

	@abstractmethod
	async def scroll_into_view_if_needed(self, timeout: int | float | None = None) -> None:
		pass

	@abstractmethod
	async def bounding_box(self) -> dict[str, Any] | None:
		pass

	@abstractmethod
	async def wait_for_element_state(
		self,
		state: Literal['disabled', 'editable', 'enabled', 'hidden', 'stable', 'visible'],
		timeout: int | float | None = None,
	) -> None:
		pass


class Driver(ABC):

	@abstractmethod
	async def configure(self, **kwargs: Any) -> None: ...

	@abstractmethod
	async def stop(self) -> None: ...
	
	@property
	@abstractmethod
	def chromium(self) -> GenericBrowser: ...

	@property
	@abstractmethod
	def firefox(self) -> GenericBrowser: ...

	@property
	@abstractmethod
	def webkit(self) -> GenericBrowser: ...


class CDPSession(ABC):
	@abstractmethod
	async def send(self, method: str, params: dict[str, Any] | None = None) -> Any:
		pass

	@abstractmethod
	async def detach(self) -> None:
		pass


class Error(Exception):
	def __init__(self, message: str) -> None:
		self._message = message
		self._name: str | None = None
		self._stack: str | None = None
		super().__init__(message)

	@property
	def message(self) -> str:
		return self._message

	@property
	def name(self) -> str | None:
		return self._name

	@property
	def stack(self) -> str | None:
		return self._stack


class TargetClosedError(Error):
	def __init__(self, message: str | None = None) -> None:
		super().__init__(message or 'Target page, context or browser has been closed')
