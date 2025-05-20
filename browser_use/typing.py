from abc import ABC, abstractmethod
from collections.abc import Awaitable
from typing import Any


class EventEmitterMixin(ABC):
	@abstractmethod
	def on(self, event: str, handler) -> None: ...

	@abstractmethod
	def remove_listener(self, event: str, handler) -> None: ...


class PropertyMixin(ABC):
	@abstractmethod
	async def get_property(self, property_name: str) -> Any: ...


class LocatorMixin(ABC):
	@abstractmethod
	def locator(self, selector: str) -> 'AbstractLocator': ...

	@abstractmethod
	def frame_locator(self, selector: str) -> 'AbstractLocator': ...


class QueryableMixin(ABC):
	@abstractmethod
	async def query_selector(self, selector: str) -> 'AbstractElementHandle | None': ...

	@abstractmethod
	async def query_selector_all(self, selector: str) -> list['AbstractElementHandle']: ...

	@abstractmethod
	async def evaluate(self, script: str, *args, **kwargs) -> Any: ...

	@abstractmethod
	async def click(self, *args, **kwargs) -> Any: ...


class TypableMixin(ABC):
	@abstractmethod
	async def type(self, text: str, delay: float = 0) -> None: ...


class AbstractBrowser(ABC):
	@abstractmethod
	async def new_context(self, **kwargs) -> 'AbstractContext':
		pass

	@abstractmethod
	async def open(self, **kwargs) -> 'AbstractBrowser':
		pass

	@abstractmethod
	async def close(self) -> None:
		pass

	@property
	@abstractmethod
	def contexts(self) -> list['AbstractContext']:
		pass

	@property
	@abstractmethod
	def version(self) -> str:
		pass


class AbstractContext(EventEmitterMixin, ABC):
	@abstractmethod
	async def new_page(self) -> 'AbstractPage':
		pass

	@abstractmethod
	async def close(self) -> None:
		pass

	@property
	@abstractmethod
	def pages(self) -> list['AbstractPage']:
		pass

	@abstractmethod
	async def grant_permissions(self, permissions: list[str], origin: str | None = None) -> None:
		pass

	@property
	@abstractmethod
	def tracing(self) -> 'AbstractTracing':
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


class AbstractFrame(QueryableMixin, LocatorMixin, ABC):
	@property
	@abstractmethod
	def url(self) -> str:
		pass

	@abstractmethod
	async def content(self) -> str:
		pass


class AbstractPage(EventEmitterMixin, QueryableMixin, PropertyMixin, LocatorMixin, TypableMixin, ABC):
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


class AbstractElementHandle(QueryableMixin, EventEmitterMixin, PropertyMixin, TypableMixin, ABC):
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
	async def element_handle(self) -> 'AbstractElementHandle':
		pass

	@abstractmethod
	async def wait_for_element_state(self, state: str, timeout: int | float | None = None) -> None:
		pass

	@abstractmethod
	async def clear(self, timeout: float | None = None) -> None:
		pass

	@abstractmethod
	async def fill(self, text: str, timeout: float | None = None) -> None: ...


class AbstractTracing(ABC):
	@abstractmethod
	async def start(self, **kwargs) -> None:
		pass

	@abstractmethod
	async def stop(self, **kwargs) -> None:
		pass


class AbstractLocator(LocatorMixin, ABC):
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
	def first(self) -> 'Awaitable[AbstractElementHandle]':
		"""Returns an awaitable that resolves to the first element handle (must be awaited)."""
		pass

	@abstractmethod
	def nth(self, index: int) -> 'AbstractLocator':
		pass

	@abstractmethod
	async def select_option(self, **kwargs) -> Any:
		pass

	@abstractmethod
	async def element_handle(self) -> 'AbstractElementHandle':
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


Page = AbstractPage
ElementHandle = AbstractElementHandle
