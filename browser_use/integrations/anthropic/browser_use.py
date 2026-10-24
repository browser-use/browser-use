from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import re
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from io import BytesIO
from typing import Any, cast
from urllib.parse import urlsplit

from PIL import Image

from anthropic.tools import ToolError
from anthropic.tools.browser import (
	BetaAsyncAbstractBrowserToolset20260801,
	BetaBrowserNavigateResult,
	BetaBrowserState,
	BetaScreenshotResult,
	TabMissingError,
)
from anthropic.types.beta import BetaBrowserStateTabEntryParam, BetaBrowserToolsetConfigsParam
from browser_use import BrowserUse as PiBrowser
from browser_use.integrations._browser import BrowserConnection, Page

from .tab_state import (
	PinnedTabSnapshot,
	consume_pinned_tabs,
	converged_active_tab,
	pin_tabs,
)


@dataclass(frozen=True)
class Reference:
	tab: str
	document: str
	backend: int


class BrowserUse(BetaAsyncAbstractBrowserToolset20260801):
	def __init__(
		self,
		browser: PiBrowser | dict[str, Any] | None = None,
		*,
		use_cloud: bool = False,
		document_resolver: Callable[[str], str] | None = None,
		max_log_entries: int = 1000,
		**options: Any,
	):
		configs = options.pop('configs', None)
		if configs is None:
			configs = {}
		else:
			configs = {name: dict(config) for name, config in configs.items()}
		file_upload_config = configs.setdefault('file_upload', {})
		file_upload_config.setdefault('enabled', False)
		super().__init__(configs=cast(BetaBrowserToolsetConfigsParam, configs), **options)
		if browser is not None and use_cloud:
			raise ValueError('Pass a Pi session or use_cloud=True, not both.')
		self.browser = BrowserConnection(browser, use_cloud=use_cloud, controller='anthropic_toolset')
		self._manages_browser = self.browser.owned
		self._document_resolver = document_resolver
		self._released = False
		self._pages: dict[str, Page] = {}
		self._refs: dict[str, Reference] = {}
		self._ref_names: dict[Reference, str] = {}
		self._next_ref = 1
		self._documents: dict[str, str] = {}
		self._next_document = 1
		self._reported_tabs: set[str] = set()
		self._last_tabs: list[dict] = []
		self._observer_sessions: dict[str, str] = {}
		self._session_tabs: dict[str, str] = {}
		self._attached_at: dict[str, float] = {}
		self._console = defaultdict(lambda: deque(maxlen=max_log_entries))
		self._network = defaultdict(lambda: deque(maxlen=max_log_entries))
		self._requests: dict[tuple[str, str], dict] = {}
		self._statuses: dict[str, int] = {}
		self._changes: list[Any] = []
		self._pending_tabs_snapshot: PinnedTabSnapshot | None = None
		self._downloads: dict[str, str] = {}
		self.completed_download_paths: list[str] = []

		self._held: dict[str, tuple[float, float, int]] = {}

	async def __aenter__(self):
		await super().__aenter__()
		try:
			await self.browser.start()
			await self._ensure_observer()
			self._reported_tabs = {t['tab_id'] for t in self._tabs()}
			return self
		except BaseException:
			await self.close()
			raise

	async def close(self):
		await super().close()
		if self._released:
			return

		operations: list[Callable[[], Awaitable[None]]] = [lambda tab=tab: self._release_mouse(tab) for tab in self._held]
		operations.append(self.browser.close)
		errors = []
		for operation in operations:
			result = await asyncio.gather(operation(), return_exceptions=True)
			errors.extend(value for value in result if isinstance(value, BaseException))
		self._refs.clear()
		self._ref_names.clear()
		self._released = not errors
		if errors:
			raise errors[0]

	def _tabs(self):
		targets = (self.browser.get_page_targets() if self.browser.is_cdp_connected else [])[:100]
		active = self.browser.agent_focus_target_id
		if targets and active not in {target.target_id for target in targets}:
			active = targets[0].target_id
		self._last_tabs = [
			{'tab_id': target.target_id, 'url': target.url, 'title': target.title or '', 'active': target.target_id == active}
			for target in targets
		]
		return self._last_tabs.copy()

	async def _browser_state(self, context):
		await self.browser.refresh()
		await self._pump_events()

		tabs = consume_pinned_tabs(self._pending_tabs_snapshot, context)
		self._pending_tabs_snapshot = None
		if tabs is None:
			tabs = self._tabs()
		changes = self._changes[:]
		self._changes.clear()
		changes.extend({'type': 'tab_opened', 'tab_id': t['tab_id']} for t in tabs if t['tab_id'] not in self._reported_tabs)
		self._reported_tabs = {t['tab_id'] for t in tabs}
		for tab in set(self._pages) - self._reported_tabs:
			self._pages.pop(tab, None)
			self._held.pop(tab, None)
			self._invalidate_refs(tab)
			self._console.pop(tab, None)
			self._network.pop(tab, None)
			sid = self._observer_sessions.pop(tab, None)
			if sid:
				self._session_tabs.pop(sid, None)
		return BetaBrowserState(tabs=cast(list[BetaBrowserStateTabEntryParam], tabs), state_changes=changes)

	async def _ensure_observer(self):
		await self.browser.observe(['Runtime.enable', 'Network.enable', 'Log.enable'])
		for tab in self._tabs():
			await self._observe_tab(tab['tab_id'])
		await self._pump_events()

	async def _observe_tab(self, tab):
		session = await self.browser.get_or_create_cdp_session(tab)
		self._observer_sessions[tab] = session.session_id
		self._session_tabs[session.session_id] = tab
		self._attached_at.setdefault(tab, 0)

	async def _pump_events(self):
		handlers = {
			'Runtime.consoleAPICalled': self._on_console,
			'Runtime.exceptionThrown': self._on_exception,
			'Log.entryAdded': self._on_log,
			'Network.requestWillBeSent': self._on_request,
			'Network.responseReceived': self._on_response,
			'Network.loadingFinished': self._on_finished,
			'Network.loadingFailed': self._on_failed,
		}
		for event in await self.browser.events():
			handler = handlers.get(event['method'])
			if handler:
				handler(event['params'], event['session'])
			data = event['params']
			if event['method'] == 'Browser.downloadWillBegin':
				self._downloads[data['guid']] = data['url']
				self._changes.append({'type': 'download_started', 'download_id': data['guid'], 'url': data['url']})
			elif event['method'] == 'Browser.downloadProgress' and data['guid'] in self._downloads:
				if data['state'] in {'completed', 'canceled'}:
					url = self._downloads.pop(data['guid'])
					change = {
						'type': 'download_completed' if data['state'] == 'completed' else 'download_failed',
						'download_id': data['guid'],
						'url': url,
					}
					if data['state'] == 'completed':
						change['size_bytes'] = int(data['receivedBytes'])
					else:
						change['error'] = 'Download cancelled'
					self._changes.append(change)

	def _on_console(self, event, session_id=None):
		tab = self._session_tabs.get(session_id or '')
		if tab and event.get('timestamp', float('inf')) >= self._attached_at.get(tab, 0):
			values = [
				a.get(
					'value',
					a.get('description', a.get('unserializableValue', a.get('type', ''))),
				)
				for a in event.get('args', [])
			]
			line = f'{event.get("type", "log")}: ' + ' '.join(
				v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str) for v in values
			)
			self._console[tab].append(line[:8192])

	def _on_exception(self, event, session_id=None):
		tab = self._session_tabs.get(session_id or '')
		if tab:
			detail = event.get('exceptionDetails', {})
			self._console[tab].append('error: ' + detail.get('exception', {}).get('description', detail.get('text', 'Exception')))

	def _on_log(self, event, session_id=None):
		tab = self._session_tabs.get(session_id or '')
		if tab:
			entry = event.get('entry', {})
			self._console[tab].append(f'{entry.get("level", "log")}: {entry.get("text", "")}')

	def _on_request(self, event, session_id=None):
		tab = self._session_tabs.get(session_id or '')
		if not tab:
			return
		key = (session_id or '', event['requestId'])
		if 'redirectResponse' in event and key in self._requests:
			old = self._requests.pop(key)
			old.update(
				status=event['redirectResponse'].get('status'),
				mime=event['redirectResponse'].get('mimeType'),
			)
			self._record_request(tab, old, event.get('timestamp'))
		request = event.get('request', {})
		self._requests[key] = {
			'method': request.get('method', ''),
			'url': request.get('url', ''),
			'start': event.get('timestamp'),
			'type': event.get('type'),
		}
		if len(self._requests) > 4000:
			self._requests.pop(next(iter(self._requests)))

	def _on_response(self, event, session_id=None):
		key = (session_id or '', event['requestId'])
		request = self._requests.get(key)
		response = event.get('response', {})
		if request is not None:
			request.update(status=response.get('status'), mime=response.get('mimeType'))
		tab = self._session_tabs.get(session_id or '')
		if tab and event.get('type') == 'Document':
			self._statuses[tab] = int(response.get('status', 0))

	def _record_request(self, tab, request, end=None, error=None):
		row = {k: v for k, v in request.items() if k not in {'start', 'type'}}
		if end is not None and request.get('start') is not None:
			row['duration_ms'] = round((end - request['start']) * 1000, 1)
		if error:
			row['error'] = error
		self._network[tab].append(json.dumps(row, ensure_ascii=False))

	def _on_finished(self, event, session_id=None):
		tab = self._session_tabs.get(session_id or '')
		request = self._requests.pop((session_id or '', event['requestId']), None)
		if tab and request:
			self._record_request(tab, request, event.get('timestamp'))

	def _on_failed(self, event, session_id=None):
		tab = self._session_tabs.get(session_id or '')
		request = self._requests.pop((session_id or '', event['requestId']), None)
		if tab and request:
			self._record_request(tab, request, event.get('timestamp'), event.get('errorText', 'Failed'))

	async def _page(self, tab_id=None):
		await self.browser.refresh()
		tabs = self._tabs()
		tab = tab_id or next((t['tab_id'] for t in tabs if t['active']), None)
		if tab is None or not any(t['tab_id'] == tab for t in tabs):
			raise TabMissingError()
		session = await self.browser.get_or_create_cdp_session(tab, focus=True)
		page = self._pages.get(tab)
		if page is None or await page.session_id != session.session_id:
			page = Page(self.browser, tab, session.session_id)
			self._pages[tab] = page
		await self._ensure_observer()
		await self._observe_tab(tab)
		return page

	@property
	def _cdp(self):
		return self.browser.cdp_client

	async def _eval(self, page, expression):
		result = await self._cdp.send.Runtime.evaluate(
			params={
				'expression': expression,
				'returnByValue': True,
				'awaitPromise': True,
			},
			session_id=await page.session_id,
		)
		self._raise_js(result)
		remote = result.get('result', {})
		return remote.get('value', remote.get('unserializableValue'))

	@staticmethod
	def _raise_js(result):
		if result.get('exceptionDetails'):
			detail = result['exceptionDetails']
			raise ToolError(detail.get('exception', {}).get('description', detail.get('text', 'JavaScript failed')))

	def _invalidate_refs(self, tab):
		for name, reference in list(self._refs.items()):
			if reference.tab == tab:
				self._refs.pop(name, None)
				self._ref_names.pop(reference, None)
		self._documents.pop(tab, None)

	async def _document(self, page):
		session_id = await page.session_id
		await self._cdp.send.DOM.getDocument(params={'depth': 0}, session_id=session_id)
		tab = page._target_id
		if tab not in self._documents:
			self._documents[tab] = f'{tab}:{self._next_document}'
			self._next_document += 1
		return self._documents[tab]

	def _reference(self, page, document: str, backend: int):
		reference = Reference(page._target_id, document, backend)
		if reference not in self._ref_names:
			name = f'ref_{self._next_ref}'
			self._next_ref += 1
			self._refs[name] = reference
			self._ref_names[reference] = name
		return self._ref_names[reference]

	async def _resolve(self, page, name):
		document = await self._document(page)
		reference = self._refs.get(name)
		if not reference or reference.tab != page._target_id or reference.document != document:
			raise ToolError(f'{name} is stale or belongs to another tab. Call read_page or find again.')
		object_id = None
		try:
			resolved = await self._cdp.send.DOM.resolveNode(
				params={'backendNodeId': reference.backend},
				session_id=await page.session_id,
			)
			object_id = resolved['object']['objectId']
			check = await self._call_node(page, object_id, 'function() { return this.isConnected; }')
			if check is not True:
				raise ValueError('Detached element')
			return reference.backend, object_id
		except Exception as exc:
			if object_id:
				await self._release_object(page, object_id)
			self._refs.pop(name, None)
			self._ref_names.pop(reference, None)
			raise ToolError(f'{name} is stale. Call read_page or find again.') from exc

	async def _call_node(self, page, object_id, function, *args):
		result = await self._cdp.send.Runtime.callFunctionOn(
			params={
				'objectId': object_id,
				'functionDeclaration': function,
				'arguments': [{'value': value} for value in args],
				'returnByValue': True,
				'awaitPromise': True,
			},
			session_id=await page.session_id,
		)
		self._raise_js(result)
		return result.get('result', {}).get('value')

	async def _release_object(self, page, object_id):
		with contextlib.suppress(Exception):
			await self._cdp.send.Runtime.releaseObject(params={'objectId': object_id}, session_id=await page.session_id)

	async def _point(self, page, target):
		if target.type == 'coordinate':
			x, y = target.x, target.y
		else:
			_, object_id = await self._resolve(page, target.ref)
			try:
				point = await self._call_node(
					page,
					object_id,
					"""function() {
                    const e = this.nodeType === 1 ? this : this.parentElement;
                    if (!e || !e.isConnected) throw Error('Detached element');
                    e.scrollIntoView({block:'center', inline:'center', behavior:'instant'});
                    const r = e.getBoundingClientRect();
                    if (!r.width || !r.height || getComputedStyle(e).visibility === 'hidden')
                        throw Error('Element has no visible click target');
                    let x=r.left+r.width/2, y=r.top+r.height/2, w=e.ownerDocument.defaultView;
                    while (w !== w.top) {
                        const f=w.frameElement;
                        if (!f) throw Error('Cross-origin frame coordinates unavailable');
                        const b=f.getBoundingClientRect(); x+=b.left+f.clientLeft; y+=b.top+f.clientTop; w=w.parent;
                    }
                    return {x,y};
                }""",
				)
				x, y = point['x'], point['y']
			finally:
				await self._release_object(page, object_id)
		metrics = await self._cdp.send.Page.getLayoutMetrics(session_id=await page.session_id)
		viewport = metrics['cssVisualViewport']
		if not (0 <= x < viewport['clientWidth'] and 0 <= y < viewport['clientHeight']):
			raise ToolError('Target lies outside the current viewport. Use scroll_to or a fresh screenshot.')
		return x, y

	@staticmethod
	def _modifiers(text):
		bits = 0
		aliases = {
			'alt': 1,
			'option': 1,
			'ctrl': 2,
			'control': 2,
			'cmd': 4,
			'command': 4,
			'meta': 4,
			'shift': 8,
		}
		for key in text.lower().split('+') if text else []:
			if key.strip() not in aliases:
				raise ToolError(f'Unsupported modifier {key}')
			bits |= aliases[key.strip()]
		return bits

	async def _mouse(self, page, kind, x, y, *, button='none', count=0, modifiers=0, buttons=None):
		mouse = await page.mouse
		names = [name for name, bit in [('Alt', 1), ('Control', 2), ('Meta', 4), ('Shift', 8)] if modifiers & bit]
		if kind == 'mouseMoved':
			await mouse.move(x, y, modifiers=names)
		elif kind == 'mousePressed':
			await mouse.move(x, y, modifiers=names)
			old = self._held.get(page._target_id, (0, 0, 0))[2]
			bit = {'left': 1, 'right': 2, 'middle': 4, 'none': 0}[button]
			self._held[page._target_id] = (x, y, old | bit)
			await mouse.down(button=button, click_count=count, modifiers=names)
		elif kind == 'mouseReleased':
			await mouse.move(x, y, modifiers=names)
			await mouse.up(button=button, click_count=count, modifiers=names)
		else:
			raise ValueError(f'Unknown mouse event: {kind}')
		old = self._held.get(page._target_id, (0, 0, 0))[2]
		bit = {'left': 1, 'right': 2, 'middle': 4, 'none': 0}[button]
		mask = old | bit if kind == 'mousePressed' else old & ~bit if kind == 'mouseReleased' else old
		self._held[page._target_id] = (x, y, mask)

	async def _release_mouse(self, tab):
		page = self._pages.get(tab)
		if page is None:
			return
		x, y, mask = self._held.get(tab, (0, 0, 0))
		for button, bit in [('left', 1), ('right', 2), ('middle', 4)]:
			if mask & bit:
				await self._mouse(page, 'mouseReleased', x, y, button=button, count=1)

	async def _click(self, input, button, count=1):
		page = await self._page(input.tab_id)
		x, y = await self._point(page, input.target)
		modifiers = self._modifiers(input.modifiers)
		if self._held.get(page._target_id, (0, 0, 0))[2]:
			raise ToolError('Release held mouse buttons before starting a click.')
		await self._mouse(page, 'mouseMoved', x, y, modifiers=modifiers)
		try:
			for n in range(1, count + 1):
				await self._mouse(
					page,
					'mousePressed',
					x,
					y,
					button=button,
					count=n,
					modifiers=modifiers,
				)
				await self._mouse(
					page,
					'mouseReleased',
					x,
					y,
					button=button,
					count=n,
					modifiers=modifiers,
				)
		finally:
			await self._release_mouse(page._target_id)

	async def navigate(self, context, input):
		page = await self._page(input.tab_id)
		await self._release_mouse(page._target_id)
		self._statuses.pop(page._target_id, None)
		if input.url in {'back', 'forward', 'reload'}:
			await {
				'back': page.go_back,
				'forward': page.go_forward,
				'reload': page.reload,
			}[input.url]()

		else:
			url = input.url if urlsplit(input.url).scheme else 'https://' + input.url
			await self.browser.navigate_to(url)
		self._invalidate_refs(page._target_id)
		return BetaBrowserNavigateResult(
			url=await page.get_url(),
			title=await page.get_title(),
			status=self._statuses.get(page._target_id),
		)

	async def _screenshot(self, page):
		metrics = await self._cdp.send.Page.getLayoutMetrics(session_id=await page.session_id)
		v = metrics['cssVisualViewport']
		result = await self._cdp.send.Page.captureScreenshot(
			params={
				'format': 'png',
				'captureBeyondViewport': False,
				'clip': {
					'x': v['pageX'],
					'y': v['pageY'],
					'width': v['clientWidth'],
					'height': v['clientHeight'],
					'scale': 1,
				},
			},
			session_id=await page.session_id,
		)
		with Image.open(BytesIO(base64.b64decode(result['data']))) as source:
			size = (round(v['clientWidth']), round(v['clientHeight']))
			return source.resize(size) if source.size != size else source.copy()

	@staticmethod
	def _image(image):
		max_edge = 2000
		if max(image.size) > max_edge:
			scale = max_edge / max(image.size)
			image = image.resize(
				(round(image.width * scale), round(image.height * scale)),
				Image.Resampling.LANCZOS,
			)
		out = BytesIO()
		image.save(out, format='PNG')
		return BetaScreenshotResult(data=base64.b64encode(out.getvalue()).decode())

	async def screenshot(self, context, input):
		return self._image(await self._screenshot(await self._page(input.tab_id)))

	async def zoom(self, context, input):
		image = await self._screenshot(await self._page(input.tab_id))
		x0, y0, x1, y1 = input.region
		if not (0 <= x0 < x1 <= image.width and 0 <= y0 < y1 <= image.height):
			raise ToolError('Zoom region must lie inside the full viewport screenshot.')
		cropped = image.crop((x0, y0, x1, y1))
		factor = min(2, 2000 / max(cropped.size))
		return self._image(cropped.resize((round(cropped.width * factor), round(cropped.height * factor))))

	async def left_click(self, context, input):
		await self._click(input, 'left')

	async def right_click(self, context, input):
		await self._click(input, 'right')

	async def middle_click(self, context, input):
		await self._click(input, 'middle')

	async def double_click(self, context, input):
		await self._click(input, 'left', 2)

	async def triple_click(self, context, input):
		await self._click(input, 'left', 3)

	async def hover(self, context, input):
		page = await self._page(input.tab_id)
		x, y = await self._point(page, input.target)
		await self._mouse(page, 'mouseMoved', x, y)

	async def mouse_move(self, context, input):
		page = await self._page(input.tab_id)
		x, y = await self._point(page, input.target)
		await self._mouse(page, 'mouseMoved', x, y)

	async def left_mouse_down(self, context, input):
		page = await self._page(input.tab_id)
		if self._held.get(page._target_id, (0, 0, 0))[2] & 1:
			raise ToolError('Left mouse button is already held.')
		x, y = await self._point(page, input.target)
		await self._mouse(page, 'mouseMoved', x, y)
		await self._mouse(page, 'mousePressed', x, y, button='left', count=1)

	async def left_mouse_up(self, context, input):
		page = await self._page(input.tab_id)
		try:
			x, y = await self._point(page, input.target)
			await self._mouse(page, 'mouseReleased', x, y, button='left', count=1)
		finally:
			await self._release_mouse(page._target_id)

	async def left_click_drag(self, context, input):
		page = await self._page(input.tab_id)
		if self._held.get(page._target_id, (0, 0, 0))[2]:
			raise ToolError('Release held mouse buttons before starting a drag.')

		x0, y0 = await self._point(page, input.from_)
		x1, y1 = await self._point(page, input.target)
		await self._mouse(page, 'mouseMoved', x0, y0)
		try:
			await self._mouse(page, 'mousePressed', x0, y0, button='left', count=1)
			for step in range(1, 11):
				await self._mouse(
					page,
					'mouseMoved',
					x0 + (x1 - x0) * step / 10,
					y0 + (y1 - y0) * step / 10,
				)
				await asyncio.sleep(0.015)
		finally:
			await self._release_mouse(page._target_id)

	async def scroll(self, context, input):
		page = await self._page(input.tab_id)
		x, y = await self._point(page, input.target)
		amount = (input.scroll_amount if input.scroll_amount is not None else 3) * 100
		dx = amount if input.scroll_direction == 'right' else -amount if input.scroll_direction == 'left' else 0
		dy = amount if input.scroll_direction == 'down' else -amount if input.scroll_direction == 'up' else 0
		await (await page.mouse).scroll(x, y, dx, dy)
		await asyncio.sleep(0.1)

	async def scroll_to(self, context, input):
		page = await self._page(input.tab_id)
		backend, object_id = await self._resolve(page, input.target.ref)
		try:
			await (await page.get_element(backend)).scroll_into_view()
		finally:
			await self._release_object(page, object_id)

	async def type(self, context, input):
		page = await self._page(input.tab_id)
		await self._cdp.send.Input.insertText(params={'text': input.text}, session_id=await page.session_id)

	async def key(self, context, input):
		page = await self._page(input.tab_id)
		for _ in range(input.repeat if input.repeat is not None else 1):
			for chord in input.text.split():
				await page.press(chord)

	async def hold_key(self, context, input):
		page = await self._page(input.tab_id)
		aliases = {
			'ctrl': 'Control',
			'control': 'Control',
			'cmd': 'Meta',
			'command': 'Meta',
			'meta': 'Meta',
			'shift': 'Shift',
			'alt': 'Alt',
			'option': 'Alt',
			'return': 'Enter',
			'enter': 'Enter',
			'esc': 'Escape',
			'escape': 'Escape',
			'space': ' ',
			'backspace': 'Backspace',
			'tab': 'Tab',
			'delete': 'Delete',
			'up': 'ArrowUp',
			'down': 'ArrowDown',
			'left': 'ArrowLeft',
			'right': 'ArrowRight',
		}
		if ' ' in input.text.strip():
			raise ToolError('hold_key accepts one key or chord, not a sequence.')
		chord = '+'.join(aliases.get(part.lower(), part) for part in input.text.split('+'))
		parts = chord.split('+')
		if len(parts[-1]) == 1 and 'Shift' in parts[:-1] and not {'Control', 'Alt', 'Meta'}.intersection(parts[:-1]):
			parts[-1] = parts[-1].upper()
			chord = '+'.join(parts)
		await page.hold_key(chord, input.duration)

	async def form_input(self, context, input):
		page = await self._page(input.tab_id)
		backend, object_id = await self._resolve(page, input.target.ref)
		try:
			kind = await self._call_node(
				page,
				object_id,
				"""function(){return {
                tag:this.tagName,type:this.type,disabled:this.disabled,readOnly:this.readOnly,editable:this.isContentEditable
            };}""",
			)
			if kind.get('disabled') or kind.get('readOnly'):
				raise ToolError('Form element is disabled or read-only.')
			if (
				kind.get('tag') in {'INPUT', 'TEXTAREA'}
				and kind.get('type')
				not in {
					'checkbox',
					'radio',
					'file',
					'button',
					'submit',
					'reset',
					'image',
					'hidden',
				}
			) or kind.get('editable'):
				value = (
					str(input.value).lower()
					if isinstance(input.value, bool)
					else str(int(input.value))
					if isinstance(input.value, float) and input.value.is_integer()
					else str(input.value)
				)
				await (await page.get_element(backend)).fill(value)
				actual = await self._call_node(
					page,
					object_id,
					'function(){return this.isContentEditable ? this.textContent : this.value;}',
				)
				if actual != value:
					raise ToolError('The page did not retain the requested form value.')
				return
			element = await page.get_element(backend)
			if kind.get('tag') == 'SELECT':
				await element.select_option(str(input.value))
				return
			if kind.get('tag') == 'INPUT' and kind.get('type') in {'checkbox', 'radio'}:
				if not isinstance(input.value, bool):
					raise ToolError('Checkbox/radio requires boolean')
				if kind['type'] == 'radio' and not input.value:
					raise ToolError('Choose another radio option to clear a selected radio')
				if input.value:
					await element.check()
				elif await self._call_node(page, object_id, 'function(){return this.checked;}'):
					await element.click()
				if await self._call_node(page, object_id, 'function(){return this.checked;}') != input.value:
					raise ToolError('Page refused checked state')
				return
			raise ToolError('Reference is not a supported form element')
		finally:
			await self._release_object(page, object_id)

	async def _tree(self, page):
		document = await self._document(page)
		sid = await page.session_id
		tree, snapshot, metrics = await asyncio.gather(
			self._cdp.send.Accessibility.getFullAXTree(session_id=sid),
			self._cdp.send.DOMSnapshot.captureSnapshot(params={'computedStyles': []}, session_id=sid),
			self._cdp.send.Page.getLayoutMetrics(session_id=sid),
		)
		nodes = tree['nodes']

		frames = await self._cdp.send.Page.getFrameTree(session_id=sid)

		def descendants(frame):
			for child in frame.get('childFrames', []):
				yield child['frame']['id']
				yield from descendants(child)

		for frame in descendants(frames['frameTree']):
			try:
				child_tree = await self._cdp.send.Accessibility.getFullAXTree(params={'frameId': frame}, session_id=sid)
				nodes.extend(child_tree['nodes'])
			except Exception as exc:
				raise ToolError('Frame accessibility data is unavailable.') from exc
		boxes = {}
		for doc in snapshot['documents']:
			dom = doc['nodes']
			layout = doc['layout']
			for index, bounds in zip(layout['nodeIndex'], layout['bounds']):
				boxes[dom['backendNodeId'][index]] = (
					bounds,
					doc.get('scrollOffsetX', 0),
					doc.get('scrollOffsetY', 0),
				)
		return document, nodes, boxes, metrics['cssVisualViewport']

	@staticmethod
	def _describe(node):
		role = node.get('role', {}).get('value', '')
		name = str(node.get('name', {}).get('value', ''))
		value = node.get('value', {}).get('value')
		props = [
			f'{p["name"]}={p["value"].get("value")}'
			for p in node.get('properties', [])
			if p['name']
			in {
				'checked',
				'selected',
				'expanded',
				'disabled',
				'required',
				'level',
				'hasPopup',
				'multiselectable',
			}
		]
		return ' '.join(
			x
			for x in [
				role,
				json.dumps(name, ensure_ascii=False) if name else '',
				f'value={json.dumps(value, ensure_ascii=False)}' if value is not None else '',
				*props,
			]
			if x
		)

	@staticmethod
	def _visible(node, boxes, viewport, all_elements=False):
		backend = node.get('backendDOMNodeId')
		if backend not in boxes:
			return False
		bounds, sx, sy = boxes[backend]
		x, y, width, height = bounds
		if width <= 0 or height <= 0:
			return False
		return all_elements or (
			x + width > sx and y + height > sy and x < sx + viewport['clientWidth'] and y < sy + viewport['clientHeight']
		)

	async def read_page(self, context, input):
		page = await self._page(input.tab_id)
		root_backend = None
		if input.ref:
			root_backend, object_id = await self._resolve(page, input.ref)
			await self._release_object(page, object_id)
		document, nodes, boxes, viewport = await self._tree(page)
		by_id = {n['nodeId']: n for n in nodes}
		roots = [n for n in nodes if n.get('parentId') not in by_id]
		if root_backend is not None:
			roots = [n for n in nodes if n.get('backendDOMNodeId') == root_backend]
			if not roots:
				raise ToolError('Referenced element is not in the accessibility tree.')
		depth_limit = input.depth if input.depth is not None else 15
		lines = []
		seen = set()
		interactive = {
			'button',
			'link',
			'textbox',
			'searchbox',
			'combobox',
			'checkbox',
			'radio',
			'slider',
			'spinbutton',
			'menuitem',
			'menuitemcheckbox',
			'menuitemradio',
			'tab',
			'option',
			'listbox',
			'switch',
			'treeitem',
			'Date',
			'DateTime',
		}

		def visit(node, depth):
			if node['nodeId'] in seen or depth > depth_limit:
				return
			seen.add(node['nodeId'])
			role = node.get('role', {}).get('value', '')
			show = not node.get('ignored') and self._visible(node, boxes, viewport, input.filter == 'all')
			if input.filter == 'interactive' and role not in interactive:
				show = False
			if show:
				backend = node.get('backendDOMNodeId')
				prefix = (
					''
					if not backend or role in {'StaticText', 'InlineTextBox'}
					else f'[{self._reference(page, document, backend)}] '
				)
				lines.append('  ' * depth + prefix + self._describe(node))
			for child in node.get('childIds', []):
				if child in by_id:
					visit(by_id[child], depth + (0 if node.get('ignored') else 1))

		for root in roots:
			visit(root, 0)
		text = '\n'.join(lines) or '(No matching accessible elements.)'
		if len(text) > 50000:
			text = text[:49900] + '\n[Truncated: narrow with ref or smaller depth.]'
		return text

	async def find(self, context, input):
		page = await self._page(input.tab_id)
		document, nodes, boxes, viewport = await self._tree(page)
		stop = {
			'the',
			'a',
			'an',
			'to',
			'of',
			'for',
			'with',
			'please',
			'find',
			'element',
			'on',
			'this',
			'page',
		}
		terms = set(re.findall(r'\w+', input.query.lower())) - stop
		synonyms = {
			'bar': {'textbox', 'searchbox', 'input'},
			'field': {'textbox', 'searchbox', 'combobox', 'input'},
			'input': {'textbox', 'searchbox', 'combobox'},
			'dropdown': {'combobox', 'listbox'},
			'search': {'searchbox'},
			'box': {'textbox', 'checkbox', 'searchbox'},
		}
		if not terms:
			raise ToolError('Use a meaningful element description.')
		matches = []
		for node in nodes:
			if node.get('ignored') or node.get('role', {}).get('value') in {
				'StaticText',
				'InlineTextBox',
			}:
				continue
			backend = node.get('backendDOMNodeId')
			if not backend or not self._visible(node, boxes, viewport, True):
				continue
			haystack = self._describe(node).lower()
			words = set(re.findall(r'\w+', haystack))
			score = sum(
				2 if term in words else 1 if term in haystack or synonyms.get(term, set()) & words else 0 for term in terms
			)
			if score and score >= len(terms):
				matches.append((score, node))
		matches.sort(key=lambda pair: pair[0], reverse=True)
		return (
			'\n'.join(f'[{self._reference(page, document, n["backendDOMNodeId"])}] {self._describe(n)}' for _, n in matches[:20])
			or 'No matching elements. Try visible label text or read_page.'
		)

	async def get_page_text(self, context, input):
		page = await self._page(input.tab_id)
		return await self._eval(
			page,
			"(document.querySelector('article,main') || document.body)?.innerText || ''",
		)

	async def wait(self, context, input):
		await self._page(input.tab_id)
		await asyncio.sleep(input.duration)

	async def file_upload(self, context, input):
		page = await self._page(input.tab_id)
		backend, object_id = await self._resolve(page, input.target.ref)
		try:
			valid = await self._call_node(
				page,
				object_id,
				"function(){return this.tagName==='INPUT'&&this.type==='file'&&!this.disabled;}",
			)
			if not valid:
				raise ToolError('Upload target must be an enabled file input.')
			paths = list(input.paths or [])
			if input.document_ids:
				if self._document_resolver is None:
					raise ToolError('Document IDs require a document_resolver for browser-host files.')
				if paths:
					raise ToolError('Upload local paths and staged remote document IDs in separate calls.')
				paths = [self._document_resolver(doc) for doc in input.document_ids]
				await self._cdp.send.DOM.setFileInputFiles(
					params={'files': paths, 'backendNodeId': backend}, session_id=await page.session_id
				)
				return
			if not paths:
				raise ToolError('No upload paths were resolved.')
			multiple = await self._call_node(page, object_id, 'function(){return this.multiple;}')
			if len(paths) > 1 and not multiple:
				raise ToolError('This file input accepts only one file.')
			await (await page.get_element(backend)).set_input_files(paths)
		finally:
			await self._release_object(page, object_id)

	async def read_console(self, context, input):
		page = await self._page(input.tab_id)
		lines = self._console[page._target_id]
		text = '\n'.join(str(line).replace('\n', '\\n') for line in lines)
		lines.clear()
		return text[:50000] + ('\n[Console output truncated.]' if len(text) > 50000 else '')

	async def read_network(self, context, input):
		page = await self._page(input.tab_id)
		lines = self._network[page._target_id]
		text = '\n'.join(lines)
		lines.clear()
		return text[:50000] + ('\n[Network output truncated.]' if len(text) > 50000 else '')

	async def javascript_exec(self, context, input):
		result = await self._eval(await self._page(input.tab_id), input.text)
		if isinstance(result, str):
			return result
		return json.dumps(result, ensure_ascii=False, default=str)

	async def new_tab(self, context, input):
		await self.browser.refresh()
		if len(self._tabs()) >= 100:
			raise ToolError('At most 100 tabs are supported.')
		page = await self.browser.new_page()
		return await self._select_tab(context, page._target_id)

	async def list_tabs(self, context, input):
		await self.browser.refresh()
		tabs = self._tabs()
		self._pending_tabs_snapshot = pin_tabs(context, tabs)
		return tabs

	async def _select_tab(self, context, target):
		await self.browser.command('Target.activateTarget', {'targetId': target})
		self.browser.agent_focus_target_id = target
		await self.browser.refresh()
		converged = converged_active_tab(context, self._tabs(), target, target)
		if converged is None:
			raise ToolError('Tab state did not confirm the selected tab.')
		selected, self._pending_tabs_snapshot = converged
		return selected

	async def switch_tab(self, context, input):
		await self._page(input.tab_id)
		return await self._select_tab(context, input.tab_id)

	async def close_tab(self, context, input):
		page = await self._page(input.tab_id)
		await self._release_mouse(page._target_id)
		await self.browser.close_page(page)
