from __future__ import annotations

import asyncio
import logging
import random
import string
import time
import uuid
from collections.abc import Awaitable
from typing import Any, Literal

import socketio

from browser_use.browser.browser import BrowserProfile
from browser_use.browser.generic import (
	Download,
	ElementHandle,
	Frame,
	GenericBrowser,
	GenericBrowserContext,
	Keyboard,
	Locator,
	Mouse,
	Page,
	Tracing,
)

logger = logging.getLogger(__name__)

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
	# these will create circular imports
	from browser_use.browser.browser import BrowserProfile

logger = logging.getLogger(__name__)


# Generate a unique Python client ID
def generate_python_client_id():
	timestamp = int(time.time() * 1000)
	random_suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=9))
	return f'python_{timestamp}_{random_suffix}'


# Helper for request/response pattern over socket.io
class SocketRequestManager:
	def __init__(self, sio: socketio.AsyncClient, browser_client_id: str):
		self.sio = sio
		self._browser_client_id = browser_client_id
		self._futures = {}
		self.sio.on('response', self._on_response)

	def set_target_browser_client(self, browser_client_id: str):
		"""Set the target browser client for routing requests."""
		self._browser_client_id = browser_client_id

	async def emit(self, event: str, data: dict) -> Any:
		req_id = str(uuid.uuid4())
		fut = asyncio.get_event_loop().create_future()
		self._futures[req_id] = fut

		# Add browser client routing information if available
		emit_data = {**data, 'req_id': req_id}
		if self._browser_client_id:
			emit_data['target_browser_client_id'] = self._browser_client_id
			# Route through browser_command event for proper routing
			await self.sio.emit(
				'browser_command', {'browser_client_id': self._browser_client_id, 'command': event, 'data': emit_data}
			)
		else:
			# Direct emission for backwards compatibility
			await self.sio.emit(event, emit_data)

		return await fut

	def _on_response(self, data):
		if data.get('browser_client_id') != self._browser_client_id:
			return
		logger.debug(f'Received response: {data}')
		req_id = data.get('req_id')
		if req_id and req_id in self._futures:
			fut = self._futures.pop(req_id)
			fut.set_result(data.get('result'))


class SocketBrowser(GenericBrowser):
	def __init__(
		self,
		profile: BrowserProfile,
		client_id: str,
		client_url: str,
	):
		super().__init__()
		self.profile = profile
		self.client_id = client_id
		self.client_url = client_url
		self._python_client_id = generate_python_client_id()
		self._sio = socketio.AsyncClient(logger=True, engineio_logger=True)
		self._req = SocketRequestManager(self._sio, self.client_id)
		self._contexts = []
		self._version = None

	async def launch(self, **kwargs):
		raise NotImplementedError('SocketBrowser does not support launch')

	async def launch_persistent_context(self, **kwargs):
		raise NotImplementedError('SocketBrowser does not support launch_persistent_context')

	async def connect_over_cdp(self, **kwargs):
		raise NotImplementedError('SocketBrowser does not support connect_over_cdp')

	async def connect(self, **kwargs):
		raise NotImplementedError('SocketBrowser does not support connect')

	async def new_browser_cdp_session(self, **kwargs):
		raise NotImplementedError('SocketBrowser does not support new_browser_cdp_session')

	async def new_context(self, **kwargs):
		raise NotImplementedError('SocketBrowser does not support new_context')

	async def start_tracing(self, **kwargs):
		raise NotImplementedError('SocketBrowser does not support start_tracing')

	async def stop_tracing(self, **kwargs):
		raise NotImplementedError('SocketBrowser does not support stop_tracing')

	async def connect_over_wss(self, **kwargs):
		raise NotImplementedError('SocketBrowser does not support connect_over_wss')

	@property
	def browser(self):
		return self

	async def setup(self):
		url = self.client_url
		if not url:
			raise ValueError('SocketBrowser requires client_url for socket.io endpoint')
		logger.info(f'Connecting to {url} as Python client: {self._python_client_id}')

		try:
			# Try connecting with auth data as a parameter
			auth_data = {'clientType': 'python', 'clientId': self._python_client_id}
			await self._sio.connect(url, transports=['websocket'], auth=auth_data)
		except TypeError:
			# Fallback: connect without auth and send auth data separately
			await self._sio.connect(url, transports=['websocket'])
			await self._sio.emit('client_auth', {'clientType': 'python', 'clientId': self._python_client_id})

		self._version = await self._req.emit('get_version', {})
		logger.info(f'Browser version: {self._version}')
		return self

	async def open(self) -> SocketBrowser:
		# No-op for socket.io, connection is established in setup
		return self

	async def close(self):
		await self._sio.disconnect()

	async def new_session(self, **kwargs):
		response = await self._req.emit('new_context', kwargs)
		pages = [SocketPage(self._req, page['id']) for page in response['pages']]
		ctx = SocketContext(self._req, response['contextId'], pages)
		self._contexts.append(ctx)
		return ctx

	async def is_connected(self) -> bool:
		raise NotImplementedError('SocketBrowser does not support is_connected')

	@property
	def contexts(self):
		return self._contexts

	@property
	def version(self) -> str:
		return self._version or ''

	@property
	def python_client_id(self) -> str:
		return self._python_client_id

	def set_target_browser_client(self, browser_client_id: str):
		"""Set the target browser client for routing requests."""
		self._req.set_target_browser_client(browser_client_id)


class SocketContext(GenericBrowserContext):
	def __init__(self, req: SocketRequestManager, ctx_id: str, pages: list):
		self._req = req
		self._ctx_id = ctx_id
		self._pages = pages

	async def new_cdp_session(self, **kwargs):
		raise NotImplementedError('SocketContext does not support new_cdp_session')

	@property
	def browser(self):
		return None  # Not implemented for socket

	async def expose_binding(self, name: str, binding: Any) -> None:
		raise NotImplementedError('SocketContext does not support expose_binding')

	async def storage_state(self, **kwargs) -> dict:
		raise NotImplementedError('SocketContext does not support storage_state')

	async def clear_permissions(self) -> None:
		raise NotImplementedError('SocketContext does not support clear_permissions')

	async def set_default_navigation_timeout(self, timeout: float) -> None:
		raise NotImplementedError('SocketContext does not support set_default_navigation_timeout')

	async def set_default_timeout(self, timeout: float) -> None:
		raise NotImplementedError('SocketContext does not support set_default_timeout')

	async def new_page(self):
		page_id = await self._req.emit('new_page', {'context_id': self._ctx_id})
		page = SocketPage(self._req, page_id)
		self._pages.append(page)
		return page

	async def close(self):
		await self._req.emit('close_context', {'context_id': self._ctx_id})

	@property
	def tracing(self):
		return SocketTracing(self._req, self._ctx_id)

	@property
	def pages(self):
		return self._pages

	async def grant_permissions(self, permissions: list[str], origin: str | None = None) -> None:
		await self._req.emit('grant_permissions', {'context_id': self._ctx_id, 'permissions': permissions, 'origin': origin})

	async def add_cookies(self, cookies: list[dict]) -> None:
		await self._req.emit('add_cookies', {'context_id': self._ctx_id, 'cookies': cookies})

	async def add_init_script(self, script: str) -> None:
		await self._req.emit('add_init_script', {'context_id': self._ctx_id, 'script': script})

	def remove_listener(self, event: str, handler) -> None:
		pass  # Not implemented for socket

	def on(self, event: str, handler) -> None:
		pass  # Not implemented for socket

	async def cookies(self) -> list[dict]:
		return await self._req.emit('get_cookies', {'context_id': self._ctx_id})

	async def set_extra_http_headers(self, headers: dict) -> None:
		await self._req.emit('set_extra_http_headers', {'context_id': self._ctx_id, 'headers': headers})

	async def set_geolocation(self, latitude: float, longitude: float, accuracy: float | None = None) -> None:
		await self._req.emit(
			'set_geolocation', {'context_id': self._ctx_id, 'latitude': latitude, 'longitude': longitude, 'accuracy': accuracy}
		)


class SocketTracing(Tracing):
	def __init__(self, req: SocketRequestManager, ctx_id: str):
		self._req = req
		self._ctx_id = ctx_id

	async def start(self, **kwargs) -> None:
		await self._req.emit('tracing_start', {'context_id': self._ctx_id, **kwargs})

	async def stop(self, **kwargs) -> None:
		await self._req.emit('tracing_stop', {'context_id': self._ctx_id, **kwargs})


class SocketFrame(Frame):
	def __init__(self, req: SocketRequestManager, frame_id: str, page_id: str):
		self._req = req
		self._frame_id = frame_id
		self._page_id = page_id

	@property
	def url(self) -> str:
		return self._frame_id  # Or fetch via req if needed

	async def content(self) -> str:
		return await self._req.emit('frame_content', {'frame_id': self._frame_id, 'page_id': self._page_id})

	async def evaluate(self, script: str, *args, **kwargs) -> Any:
		return await self._req.emit(
			'frame_evaluate', {'frame_id': self._frame_id, 'script': script, 'args': args, 'kwargs': kwargs}
		)

	async def query_selector(self, selector: str) -> SocketElementHandle | None:
		el_id = await self._req.emit('frame_query_selector', {'frame_id': self._frame_id, 'selector': selector})
		if not el_id:
			return None
		return SocketElementHandle(self._req, el_id, self._page_id)

	async def query_selector_all(self, selector: str) -> list[SocketElementHandle]:
		el_ids = await self._req.emit('frame_query_selector_all', {'frame_id': self._frame_id, 'selector': selector})
		return [SocketElementHandle(self._req, eid, self._page_id) for eid in el_ids]

	def locator(self, selector: str) -> SocketLocator:
		return SocketLocator(self._req, self._frame_id, selector, exact=False, page_id=self._page_id)

	def frame_locator(self, selector: str) -> SocketLocator:
		return SocketLocator(self._req, self._frame_id, selector, exact=False, page_id=self._page_id)

	async def click(self, *args, **kwargs):
		await self._req.emit('frame_click', {'frame_id': self._frame_id, 'args': args, 'kwargs': kwargs})

	async def wait_for_load_state(self, state: Literal['domcontentloaded', 'load', 'networkidle'] | None = 'load', **kwargs):
		await self._req.emit('frame_wait_for_load_state', {'frame_id': self._frame_id, 'state': state, 'kwargs': kwargs})


class SocketKeyboard(Keyboard):
	def __init__(self, req: SocketRequestManager, page_id: str):
		self._req = req
		self._page_id = page_id

	async def press(self, keys: str) -> None:
		await self._req.emit('keyboard_press', {'page_id': self._page_id, 'keys': keys})

	async def type(self, text: str, delay: float = 0) -> None:
		await self._req.emit('keyboard_type', {'page_id': self._page_id, 'text': text, 'delay': delay})


class SocketMouse(Mouse):
	def __init__(self, req: SocketRequestManager, page_id: str):
		self._req = req
		self._page_id = page_id

	async def move(self, x: int, y: int) -> None:
		await self._req.emit('mouse_move', {'page_id': self._page_id, 'x': x, 'y': y})

	async def down(self) -> None:
		await self._req.emit('mouse_down', {'page_id': self._page_id})

	async def up(self) -> None:
		await self._req.emit('mouse_up', {'page_id': self._page_id})

	async def click(self, x: int, y: int, **kwargs) -> None:
		await self._req.emit('mouse_click', {'page_id': self._page_id, 'x': x, 'y': y, 'kwargs': kwargs})


class SocketDownload(Download):
	def __init__(self, req: SocketRequestManager, download_id: str):
		self._req = req
		self._download_id = download_id

	@property
	def suggested_filename(self) -> str:
		return self._download_id  # Or fetch via req if needed

	async def save_as(self, path: str) -> None:
		await self._req.emit('download_save_as', {'download_id': self._download_id, 'path': path})

	@property
	async def value(self):
		return self


class SocketPage(Page):
	def __init__(self, req: SocketRequestManager, page_id: str):
		self._req = req
		self._page_id = page_id

	@property
	def context(self):
		return None  # Not implemented for socket

	@property
	def accessibility(self):
		return None  # Not implemented for socket

	async def goto(self, url: str, **kwargs):
		await self._req.emit('page_goto', {'page_id': self._page_id, 'url': url, 'kwargs': kwargs})

	async def click(self, selector: str) -> None:
		await self._req.emit('page_click', {'page_id': self._page_id, 'selector': selector})

	async def fill(self, selector: str, text: str) -> None:
		await self._req.emit('page_fill', {'page_id': self._page_id, 'selector': selector, 'text': text})

	async def get_content(self) -> str:
		return await self._req.emit('page_content', {'page_id': self._page_id})

	async def screenshot(self, **kwargs) -> bytes:
		result = await self._req.emit('page_screenshot', {'page_id': self._page_id, 'kwargs': kwargs})
		if isinstance(result, str) and result.startswith('data:image/'):
			import base64
			import re

			match = re.match(r'data:image/[^;]+;base64,(.*)', result)
			if match:
				return base64.b64decode(match.group(1))
			else:
				raise ValueError('Unexpected screenshot data URL format')
		elif isinstance(result, (bytes, bytearray)):
			return result
		else:
			raise ValueError('Unexpected screenshot result type')

	async def close(self):
		await self._req.emit('page_close', {'page_id': self._page_id})

	async def evaluate(self, script: str, *args, **kwargs):
		result = await self._req.emit(
			'page_evaluate', {'page_id': self._page_id, 'script': script, 'args': args, 'kwargs': kwargs}
		)
		logger.debug(f'Evaluate result: {result}')
		return result

	async def wait_for_load_state(self, state: Literal['domcontentloaded', 'load', 'networkidle'] | None = 'load', **kwargs):
		await self._req.emit('page_wait_for_load_state', {'page_id': self._page_id, 'state': state, 'kwargs': kwargs})

	async def set_viewport_size(self, viewport_size: dict) -> None:
		await self._req.emit('page_set_viewport_size', {'page_id': self._page_id, 'viewport_size': viewport_size})

	def on(self, event: str, handler) -> None:
		pass  # Not implemented for socket

	def remove_listener(self, event: str, handler) -> None:
		pass  # Not implemented for socket

	@property
	def url(self) -> str:
		return self._page_id  # Or fetch via req if needed

	def is_closed(self) -> bool:
		return False  # Could fetch via req if needed

	async def bring_to_front(self) -> None:
		await self._req.emit('page_bring_to_front', {'page_id': self._page_id})

	async def expose_function(self, name: str, func) -> None:
		# Not supported over socket
		pass

	async def go_back(self, **kwargs) -> None:
		await self._req.emit('page_go_back', {'page_id': self._page_id, 'kwargs': kwargs})

	async def go_forward(self, **kwargs) -> None:
		await self._req.emit('page_go_forward', {'page_id': self._page_id, 'kwargs': kwargs})

	async def wait_for_selector(self, selector: str, **kwargs) -> None:
		await self._req.emit('page_wait_for_selector', {'page_id': self._page_id, 'selector': selector, 'kwargs': kwargs})

	async def content(self) -> str:
		return await self._req.emit('page_content', {'page_id': self._page_id})

	async def title(self) -> str:
		return await self._req.emit('page_title', {'page_id': self._page_id})

	@property
	async def frames(self) -> list:
		frame_ids = await self._req.emit('page_frames', {'page_id': self._page_id})
		return [SocketFrame(self._req, fid, self._page_id) for fid in frame_ids]

	async def query_selector(self, selector: str) -> SocketElementHandle | None:
		el_id = await self._req.emit('page_query_selector', {'page_id': self._page_id, 'selector': selector})
		if not el_id:
			return None
		return SocketElementHandle(self._req, el_id, self._page_id)

	async def query_selector_all(self, selector: str) -> list[SocketElementHandle]:
		el_ids = await self._req.emit('page_query_selector_all', {'page_id': self._page_id, 'selector': selector})
		return [SocketElementHandle(self._req, eid, self._page_id) for eid in el_ids]

	def locator(self, selector: str) -> SocketLocator:
		return SocketLocator(self._req, self._page_id, selector, exact=False, page_id=self._page_id)

	def frame_locator(self, selector: str) -> SocketLocator:
		return SocketLocator(self._req, self._page_id, selector, exact=False, page_id=self._page_id)

	async def emulate_media(self, **kwargs) -> None:
		await self._req.emit('page_emulate_media', {'page_id': self._page_id, 'kwargs': kwargs})

	async def pdf(self, **kwargs) -> Any:
		return await self._req.emit('page_pdf', {'page_id': self._page_id, 'kwargs': kwargs})

	def get_by_text(self, text: str, exact: bool = False) -> SocketLocator:
		return SocketLocator(self._req, self._page_id, f'text={text}', exact=exact, page_id=self._page_id)

	@property
	def keyboard(self) -> SocketKeyboard:
		return SocketKeyboard(self._req, self._page_id)

	@property
	def mouse(self) -> SocketMouse:
		return SocketMouse(self._req, self._page_id)

	@property
	def viewport_size(self) -> dict | None:
		return None  # Could fetch via req if needed

	async def reload(self) -> None:
		await self._req.emit('page_reload', {'page_id': self._page_id})

	async def get_property(self, property_name: str):
		return await self._req.emit('page_get_property', {'page_id': self._page_id, 'property_name': property_name})

	async def expect_download(self, *args, **kwargs) -> Download:
		download_id = await self._req.emit('page_expect_download', {'page_id': self._page_id, 'args': args, 'kwargs': kwargs})
		return SocketDownload(self._req, download_id)

	async def type(self, selector: str, text: str, delay: float = 0) -> None:
		await self._req.emit('page_type', {'page_id': self._page_id, 'selector': selector, 'text': text, 'delay': delay})

	async def wait_for_timeout(self, timeout: float) -> None:
		await self._req.emit('page_wait_for_timeout', {'page_id': self._page_id, 'timeout': timeout})


class SocketElementHandle(ElementHandle):
	def __init__(self, req: SocketRequestManager, el_id: str, page_id: str):
		self._req = req
		self._el_id = el_id
		self._page_id = page_id

	async def is_visible(self) -> bool:
		return await self._req.emit(
			'element_is_visible',
			{
				'element_id': self._el_id,
				'page_id': self._page_id,
			},
		)

	async def is_hidden(self) -> bool:
		return await self._req.emit(
			'element_is_hidden',
			{
				'element_id': self._el_id,
				'page_id': self._page_id,
			},
		)

	async def bounding_box(self) -> dict | None:
		return await self._req.emit(
			'element_bounding_box',
			{
				'element_id': self._el_id,
				'page_id': self._page_id,
			},
		)

	async def scroll_into_view_if_needed(self, timeout: int | float | None = None) -> None:
		await self._req.emit(
			'element_scroll_into_view_if_needed', {'element_id': self._el_id, 'page_id': self._page_id, 'timeout': timeout}
		)

	async def element_handle(self) -> SocketElementHandle:
		return self

	async def wait_for_element_state(
		self, state: Literal['disabled', 'editable', 'enabled', 'hidden', 'stable', 'visible'], timeout: int | float | None = None
	) -> None:
		await self._req.emit(
			'element_wait_for_element_state',
			{'element_id': self._el_id, 'page_id': self._page_id, 'state': state, 'timeout': timeout},
		)

	async def query_selector(self, selector: str) -> SocketElementHandle | None:
		el_id = await self._req.emit(
			'element_query_selector', {'element_id': self._el_id, 'page_id': self._page_id, 'selector': selector}
		)
		if not el_id:
			return None
		return SocketElementHandle(self._req, el_id, self._page_id)

	async def query_selector_all(self, selector: str) -> list[SocketElementHandle]:
		el_ids = await self._req.emit(
			'element_query_selector_all', {'element_id': self._el_id, 'page_id': self._page_id, 'selector': selector}
		)
		return [SocketElementHandle(self._req, eid, self._page_id) for eid in el_ids]

	def on(self, event: str, handler) -> None:
		pass  # Not implemented for socket

	def remove_listener(self, event: str, handler) -> None:
		pass  # Not implemented for socket

	async def click(self, *args, **kwargs):
		await self._req.emit(
			'element_click', {'element_id': self._el_id, 'page_id': self._page_id, 'args': args, 'kwargs': kwargs}
		)

	async def get_property(self, property_name: str):
		return await self._req.emit(
			'element_get_property', {'element_id': self._el_id, 'page_id': self._page_id, 'property_name': property_name}
		)

	async def evaluate(self, script: str, *args, **kwargs):
		result = await self._req.emit(
			'element_evaluate',
			{'element_id': self._el_id, 'page_id': self._page_id, 'script': script, 'args': args, 'kwargs': kwargs},
		)
		logger.debug(f'Evaluate result: {result}')
		return result

	async def type(self, text: str, delay: float = 0) -> None:
		await self._req.emit('element_type', {'element_id': self._el_id, 'page_id': self._page_id, 'text': text, 'delay': delay})

	async def fill(self, text: str, timeout: float | None = None) -> None:
		await self._req.emit(
			'element_fill', {'element_id': self._el_id, 'page_id': self._page_id, 'text': text, 'timeout': timeout}
		)

	async def clear(self, timeout: float | None = None) -> None:
		await self._req.emit('element_clear', {'element_id': self._el_id, 'page_id': self._page_id, 'timeout': timeout})


class SocketLocator(Locator):
	def __init__(self, req: SocketRequestManager, parent_id: str, selector: str, exact: bool = False, page_id: str | None = None):
		self._req = req
		self._parent_id = parent_id
		self._selector = selector
		self._exact = exact
		self._page_id = page_id

	async def is_visible(self) -> bool:
		return await self._req.emit(
			'locator_is_visible', {'parent_id': self._parent_id, 'selector': self._selector, 'exact': self._exact}
		)

	async def is_hidden(self) -> bool:
		return await self._req.emit(
			'locator_is_hidden', {'parent_id': self._parent_id, 'selector': self._selector, 'exact': self._exact}
		)

	async def is_enabled(self) -> bool:
		return await self._req.emit(
			'locator_is_enabled', {'parent_id': self._parent_id, 'selector': self._selector, 'exact': self._exact}
		)

	async def is_disabled(self) -> bool:
		return await self._req.emit(
			'locator_is_disabled', {'parent_id': self._parent_id, 'selector': self._selector, 'exact': self._exact}
		)

	async def bounding_box(self) -> dict | None:
		return await self._req.emit(
			'locator_bounding_box', {'parent_id': self._parent_id, 'selector': self._selector, 'exact': self._exact}
		)

	async def scroll_into_view_if_needed(self, timeout: float | None = None) -> None:
		await self._req.emit(
			'locator_scroll_into_view_if_needed',
			{'parent_id': self._parent_id, 'selector': self._selector, 'exact': self._exact, 'timeout': timeout},
		)

	def filter(self, **kwargs) -> SocketLocator:
		return SocketLocator(self._req, self._parent_id, self._selector, exact=self._exact, page_id=self._page_id)

	@property
	def first(self) -> Awaitable[SocketElementHandle | None]:
		async def _first():
			el_id = await self._req.emit(
				'locator_first', {'parent_id': self._parent_id, 'selector': self._selector, 'exact': self._exact}
			)
			if not el_id or not self._page_id:
				return None
			return SocketElementHandle(self._req, el_id, self._page_id)

		return _first()

	async def element_handle(self) -> SocketElementHandle | None:
		el_id = await self._req.emit(
			'locator_element_handle', {'parent_id': self._parent_id, 'selector': self._selector, 'exact': self._exact}
		)
		if not el_id or not self._page_id:
			return None
		return SocketElementHandle(self._req, el_id, self._page_id)

	def locator(self, selector: str) -> SocketLocator:
		return SocketLocator(self._req, self._parent_id, selector, exact=self._exact, page_id=self._page_id)

	def frame_locator(self, selector: str) -> SocketLocator:
		return SocketLocator(self._req, self._parent_id, selector, exact=self._exact, page_id=self._page_id)

	async def click(self, *args, **kwargs):
		await self._req.emit(
			'locator_click',
			{'parent_id': self._parent_id, 'selector': self._selector, 'exact': self._exact, 'args': args, 'kwargs': kwargs},
		)

	async def evaluate(self, script: str, *args, **kwargs):
		result = await self._req.emit(
			'locator_evaluate',
			{
				'parent_id': self._parent_id,
				'selector': self._selector,
				'exact': self._exact,
				'script': script,
				'args': args,
				'kwargs': kwargs,
			},
		)
		logger.debug(f'Evaluate result: {result}')
		return result

	async def fill(self, text: str, timeout: float | None = None) -> None:
		await self._req.emit(
			'locator_fill',
			{'parent_id': self._parent_id, 'selector': self._selector, 'exact': self._exact, 'text': text, 'timeout': timeout},
		)

	async def evaluate_all(self, expression: str) -> Any:
		return await self._req.emit(
			'locator_evaluate_all',
			{'parent_id': self._parent_id, 'selector': self._selector, 'expression': expression, 'exact': self._exact},
		)

	async def count(self) -> int:
		return await self._req.emit(
			'locator_count', {'parent_id': self._parent_id, 'selector': self._selector, 'exact': self._exact}
		)

	def nth(self, index: int) -> SocketLocator:
		return SocketLocator(self._req, self._parent_id, self._selector, exact=self._exact, page_id=self._page_id)

	async def select_option(self, **kwargs) -> Any:
		return await self._req.emit(
			'locator_select_option', {'parent_id': self._parent_id, 'selector': self._selector, 'exact': self._exact, **kwargs}
		)


class async_driver_socket:
	def __init__(self, profile: BrowserProfile, client_id: str, client_url: str) -> None:
		self.profile = profile
		self.client_id = client_id
		self.client_url = client_url
		self.impl: GenericBrowser | None = None
		self.name = f'socket_driver_{client_id}'
		logger.info('🌎🚗 Created SocketDriver instance')

	@property
	def chromium(self) -> GenericBrowser:
		assert self.impl is not None, 'SocketDriver is not initialized'
		return self.impl

	@property
	def firefox(self) -> GenericBrowser:
		assert self.impl is not None, 'SocketDriver is not initialized'
		return self.impl

	@property
	def webkit(self) -> GenericBrowser:
		assert self.impl is not None, 'SocketDriver is not initialized'
		return self.impl

	async def setup(self) -> async_driver_socket:
		logger.info('🌎🚗 SocketDriver.setup()')
		self.impl = SocketBrowser(self.profile, self.client_id, self.client_url)
		await self.impl.setup()
		await self.impl.open()
		return self

	async def stop(self) -> None:
		logger.info(f'🌎🚗 SocketDriver.stop(): name={self.name}')
		assert self.impl is not None, 'SocketDriver is not initialized'
		await self.impl.close()

	async def __aenter__(self):
		logger.info(f'🌎🚗 SocketDriver.__aenter__(): name={self.name}')
		await self.setup()
		return self

	async def __aexit__(self, exc_type, exc, tb):
		logger.info(f'🌎🚗 SocketDriver.__aexit__(): name={self.name}')
		await self.stop()
