from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel

if TYPE_CHECKING:
	# these will create circular imports
	from browser_use.browser import BrowserProfile, BrowserSession

logger = logging.getLogger(__name__)


class ViewportSize(BaseModel):
	"""Represents a viewport size"""

	width: int
	height: int


class ClientCertificate(BaseModel):
	"""Represents a client certificate for authentication"""

	cert: str
	key: str


class Geolocation(BaseModel):
	"""Represents geographical location coordinates"""

	latitude: float
	longitude: float
	accuracy: float | None = None


class HttpCredentials(BaseModel):
	"""Represents HTTP authentication credentials"""

	username: str
	password: str


class ProxySettings(BaseModel):
	"""Represents proxy server settings"""

	server: str
	bypass: str | None = None
	username: str | None = None
	password: str | None = None


class StorageState(BaseModel):
	"""Represents browser storage state"""

	cookies: list[dict[str, Any]] = []
	origins: list[dict[str, Any]] = []


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
	async def evaluate(self, script: str, *args: Any, **kwargs: Any) -> Any: ...

	@abstractmethod
	async def click(self, *args: Any, **kwargs: Any) -> Any: ...


class Browser(ABC):
	@abstractmethod
	async def new_session(self, **kwargs: Any) -> BrowserSession:
		pass

	@abstractmethod
	def is_connected(self) -> bool:
		pass

	@abstractmethod
	async def open(self, **kwargs: Any) -> Browser:
		pass

	@abstractmethod
	async def close(self) -> None:
		pass

	@property
	@abstractmethod
	def sessions(self) -> list[BrowserSession]:
		pass

	@property
	@abstractmethod
	def version(self) -> str:
		pass


class BrowserContext(ABC):
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
	def browser(self) -> Browser:
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


class Page(EventEmitterMixin, QueryableMixin, LocatorMixin, ABC):
	@property
	@abstractmethod
	def context(self) -> BrowserContext:
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

	@abstractmethod
	async def set_viewport_size(self, viewport: ViewportSize) -> None:
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

	@abstractmethod
	async def viewport_size(self) -> ViewportSize:
		pass

	@abstractmethod
	async def reload(self) -> None:
		pass

	@abstractmethod
	async def expect_download(self, *args: Any, **kwargs: Any) -> Download:
		pass

	@abstractmethod
	async def wait_for_timeout(self, timeout: float) -> None:
		pass


class ElementHandle(QueryableMixin, EventEmitterMixin, PropertyMixin, ABC):
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

	@abstractmethod
	async def element_handle(self) -> ElementHandle:
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
	async def value(self):
		pass


class Driver(ABC):
	def __init__(self, profile: BrowserProfile) -> None:
		self.profile = profile
		self.impl: Browser | None = None
		logger.info(f'🌎🚗 Created BrowserDriver instance: name={self.__class__.__name__}, profile={self.profile}')

	@property
	def chromium(self) -> Browser:
		assert self.profile.channel == 'chromium', f'Invalid browser class: {self.profile.channel}'
		assert self.impl is not None, f'Driver {self.__class__.__name__} is not initialized'
		return self.impl

	@property
	def firefox(self) -> Browser:
		assert self.profile.channel == 'firefox', f'Invalid browser class: {self.profile.channel}'
		assert self.impl is not None, f'Driver {self.__class__.__name__} is not initialized'
		return self.impl

	@property
	def webkit(self) -> Browser:
		assert self.profile.channel == 'webkit', f'Invalid browser class: {self.profile.channel}'
		assert self.impl is not None, f'Driver {self.__class__.__name__} is not initialized'
		return self.impl

	@abstractmethod
	async def init_impl(self) -> None: ...

	"""
	Initialize the driver implementation.
	
	"""

	async def setup(self) -> Driver:
		logger.info(f'🌎🚗 BrowserDriver.setup(): name={self.__class__.__name__}')

		await self.init_impl()
		assert self.impl is not None, f'Driver {self.__class__.__name__} is not initialized'
		await self.impl.open()
		return self

	async def stop(self) -> None:
		logger.info(f'\U0001f30e\U0001f697 BrowserDriver.stop(): name={self.__class__.__name__}')
		assert self.impl is not None, f'Driver {self.__class__.__name__} is not initialized'
		await self.impl.close()

	async def __aenter__(self):
		logger.info(f'🌎🚗 BrowserDriver.__aenter__(): name={self.__class__.__name__}')
		await self.setup()
		return self

	async def __aexit__(self, exc_type: Any, exc: Any, tb: Any):
		logger.info(f'🌎🚗 BrowserDriver.__aexit__(): name={self.__class__.__name__}')
		await self.stop()
