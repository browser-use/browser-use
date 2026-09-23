# pyright: reportMissingImports=false, reportArgumentType=false, reportCallIssue=false, reportOptionalSubscript=false, reportOptionalMemberAccess=false, reportTypedDictNotRequiredAccess=false

"""Anthropic browser tools adapter for Browser Use.

One BrowserSession is exclusively controlled by this toolset. The SDK owns action
validation, permissions, serialized calls, and rendering; this module only executes
browser operations. The caller owns a borrowed session unless owns_browser=True.

References are CDP backend nodes scoped to a tab and document. find performs
bounded lexical/role matching over accessibility names, without another model.
Optional upload and JavaScript tools retain the SDK's opt-in confirmation gates.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import re
import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO
from typing import Any
from urllib.parse import urlsplit

try:
	from anthropic.tools.browser import (
		BetaAsyncAbstractBrowserToolset20260801,
		BetaBrowserNavigateResult,
		BetaBrowserScreenshotResult,
		BrowserState,
		TabMissingError,
		ToolError,
	)
except ImportError as exc:
	raise ImportError(
		'BrowserUseToolset requires an Anthropic SDK with the browser toolset helpers '
		'(anthropic 1.6.0 or newer). The regular Browser Use Anthropic dependency '
		'is kept separate for compatibility with ChatAnthropic.'
	) from exc
from cdp_use import CDPClient
from PIL import Image

from browser_use.actor.page import Page
from browser_use.browser.events import (
	DownloadProgressEvent,
	DownloadStartedEvent,
	FileDownloadedEvent,
	SwitchTabEvent,
)
from browser_use.browser.session import BrowserSession


@dataclass(frozen=True)
class Reference:
	tab: str
	document: int
	backend: int


class BrowserUseToolset(BetaAsyncAbstractBrowserToolset20260801):
	"""Run Anthropic's browser tools against a Browser Use session.

	The adapter implements the complete 31-member toolspec, including
	accessibility references, form controls, held-pointer actions, tab
	lifecycle, console/network inspection, and the opt-in upload and JavaScript
	members. It never creates a second agent or makes an extra model call.

	document_resolver maps already policy-approved document IDs to browser-host
	paths; local paths still pass the SDK FilePolicy. Remote browser uploads require
	pre-staging on that browser host, not just a file on the Python client machine.
	"""

	def __init__(
		self,
		browser: BrowserSession,
		*,
		owns_browser: bool = False,
		document_resolver: Callable[[str], str] | None = None,
		max_log_entries: int = 1000,
		**options: Any,
	):
		super().__init__(**options)
		self.browser = browser
		self._owns_browser = owns_browser
		self._document_resolver = document_resolver
		self._released = False
		self._closing = False
		self._pages: dict[str, Page] = {}
		self._refs: dict[str, Reference] = {}
		self._ref_names: dict[Reference, str] = {}
		self._next_ref = 1
		self._documents: dict[str, int] = {}
		self._reported_tabs: set[str] = set()
		self._last_tabs: list[dict] = []
		self._observer: CDPClient | None = None
		self._observer_sessions: dict[str, str] = {}
		self._session_tabs: dict[str, str] = {}
		self._attached_at: dict[str, float] = {}
		self._console = defaultdict(lambda: deque(maxlen=max_log_entries))
		self._network = defaultdict(lambda: deque(maxlen=max_log_entries))
		self._requests: dict[tuple[str, str], dict] = {}
		self._statuses: dict[str, int] = {}
		self._changes: list[Any] = []
		self._downloads: dict[str, str] = {}
		self._seen_download_events: set[str] = set(browser.event_bus.event_history)
		self._held: dict[str, tuple[float, float, int]] = {}
		self._background: set[asyncio.Task] = set()
		self._observer_lock = asyncio.Lock()

	async def __aenter__(self):
		await super().__aenter__()
		try:
			if self._owns_browser:
				await self.browser.start()
			elif not self.browser.is_cdp_connected:
				raise RuntimeError('Start the borrowed BrowserSession before entering the driver.')
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
		# Stop accepting observer work, but leave owned cleanup retryable on failure.
		self._closing = True
		errors = []
		for tab in list(self._held):
			try:
				await self._release_mouse(tab)
			except Exception as exc:
				errors.append(exc)
		for task in list(self._background):
			task.cancel()
		if self._background:
			await asyncio.gather(*self._background, return_exceptions=True)
		if self._observer:
			try:
				await self._observer.stop()
				self._observer = None
			except BaseException as exc:
				errors.append(exc)
		self._refs.clear()
		self._ref_names.clear()
		if self._owns_browser:
			try:
				await self.browser.kill()
			except BaseException as exc:
				errors.append(exc)
		self._released = not errors
		if errors:
			raise errors[0]

	def _tabs(self):
		try:
			targets = (self.browser.get_page_targets() if self.browser.is_cdp_connected else [])[:100]
			active = self.browser.agent_focus_target_id
			if targets and active not in {t.target_id for t in targets}:
				active = targets[0].target_id
			self._last_tabs = [
				dict(
					tab_id=t.target_id,
					url=t.url,
					title=t.title or '',
					active=t.target_id == active,
				)
				for t in targets
			]
		except Exception:
			pass  # State reporting must still work after a CDP action fails.
		return self._last_tabs.copy()

	async def _browser_state(self, context):
		tabs = self._tabs()
		self._collect_downloads()
		changes = self._changes[:]
		self._changes.clear()
		changes.extend(dict(type='tab_opened', tab_id=t['tab_id']) for t in tabs if t['tab_id'] not in self._reported_tabs)
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
		return BrowserState(tabs=tabs, state_changes=changes)

	def _spawn(self, coro):
		task = asyncio.create_task(coro)
		self._background.add(task)

		def done(finished):
			self._background.discard(finished)
			if not finished.cancelled():
				finished.exception()  # observed; action path retries attach if required

		task.add_done_callback(done)

	async def _ensure_observer(self):
		if self._observer or self._released or self._closing:
			return
		async with self._observer_lock:
			if self._observer or self._closing:
				return
			root = self.browser.cdp_client
			observer = CDPClient(root.url, additional_headers=getattr(root, 'additional_headers', None))
			await observer.start()
			self._observer = observer
			# A dedicated observer avoids replacing BrowserSession's single-listener CDP handlers.
			observer.register.Runtime.consoleAPICalled(self._on_console)
			observer.register.Runtime.exceptionThrown(self._on_exception)
			observer.register.Log.entryAdded(self._on_log)
			observer.register.Network.requestWillBeSent(self._on_request)
			observer.register.Network.responseReceived(self._on_response)
			observer.register.Network.loadingFinished(self._on_finished)
			observer.register.Network.loadingFailed(self._on_failed)
			observer.register.Target.targetCreated(self._on_target)
			await observer.send.Target.setDiscoverTargets(params={'discover': True})
		for tab in self._tabs():
			await self._observe_tab(tab['tab_id'])

	def _on_target(self, event, session_id=None):
		info = event.get('targetInfo', {})
		if info.get('type') == 'page' and not self._released and not self._closing:
			self._spawn(self._observe_tab(info['targetId']))

	async def _observe_tab(self, tab):
		# Concurrent target-created + first action are possible; serialize attaches.
		async with self._observer_lock:
			if not self._observer or self._released or self._closing or tab in self._observer_sessions:
				return
			result = await self._observer.send.Target.attachToTarget(params={'targetId': tab, 'flatten': True})
			sid = result['sessionId']
			self._observer_sessions[tab] = sid
			self._session_tabs[sid] = tab
			self._attached_at[tab] = time.time() * 1000
			await asyncio.gather(
				self._observer.send.Runtime.enable(session_id=sid),
				self._observer.send.Network.enable(session_id=sid),
				self._observer.send.Log.enable(session_id=sid),
			)

	def _on_console(self, event, session_id=None):
		tab = self._session_tabs.get(session_id)
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
		tab = self._session_tabs.get(session_id)
		if tab:
			detail = event.get('exceptionDetails', {})
			self._console[tab].append('error: ' + detail.get('exception', {}).get('description', detail.get('text', 'Exception')))

	def _on_log(self, event, session_id=None):
		tab = self._session_tabs.get(session_id)
		if tab:
			entry = event.get('entry', {})
			self._console[tab].append(f'{entry.get("level", "log")}: {entry.get("text", "")}')

	def _on_request(self, event, session_id=None):
		tab = self._session_tabs.get(session_id)
		if not tab:
			return
		key = (session_id, event['requestId'])
		if 'redirectResponse' in event and key in self._requests:
			old = self._requests.pop(key)
			old.update(
				status=event['redirectResponse'].get('status'),
				mime=event['redirectResponse'].get('mimeType'),
			)
			self._record_request(tab, old, event.get('timestamp'))
		request = event.get('request', {})
		self._requests[key] = dict(
			method=request.get('method', ''),
			url=request.get('url', ''),
			start=event.get('timestamp'),
			type=event.get('type'),
		)
		if len(self._requests) > 4000:
			self._requests.pop(next(iter(self._requests)))

	def _on_response(self, event, session_id=None):
		key = (session_id, event['requestId'])
		request = self._requests.get(key)
		response = event.get('response', {})
		if request is not None:
			request.update(status=response.get('status'), mime=response.get('mimeType'))
		tab = self._session_tabs.get(session_id)
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
		tab = self._session_tabs.get(session_id)
		request = self._requests.pop((session_id, event['requestId']), None)
		if tab and request:
			self._record_request(tab, request, event.get('timestamp'))

	def _on_failed(self, event, session_id=None):
		tab = self._session_tabs.get(session_id)
		request = self._requests.pop((session_id, event['requestId']), None)
		if tab and request:
			self._record_request(tab, request, event.get('timestamp'), event.get('errorText', 'Failed'))

	def _collect_downloads(self):
		# Reuse the normal download watchdog instead of changing browser-wide policy
		# or competing for its CDP event handlers on a second connection.
		history = self.browser.event_bus.event_history
		for event_id, event in list(history.items()):
			if event_id in self._seen_download_events:
				continue
			self._seen_download_events.add(event_id)
			if isinstance(event, DownloadStartedEvent):
				self._downloads[event.guid] = event.url
				self._changes.append(dict(type='download_started', download_id=event.guid, url=event.url))
			elif isinstance(event, DownloadProgressEvent) and event.state == 'canceled':
				url = self._downloads.pop(event.guid, None)
				if url:
					self._changes.append(
						dict(
							type='download_failed',
							download_id=event.guid,
							url=url,
							error='Download cancelled',
						)
					)
			elif isinstance(event, FileDownloadedEvent):
				self._changes.append(
					dict(
						type='download_completed',
						download_id=event.guid or str(event_id),
						url=event.url,
						path=event.path,
						size_bytes=event.file_size,
					)
				)
				self._downloads.pop(event.guid, None)
		self._seen_download_events.intersection_update(history)

	async def _page(self, tab_id=None):
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
		result = await self._cdp.send.DOM.getDocument(params={'depth': 0}, session_id=await page.session_id)
		document = result['root']['backendNodeId']
		tab = page._target_id
		if self._documents.get(tab) != document:
			self._invalidate_refs(tab)
			self._documents[tab] = document
		return document

	def _reference(self, page, document, backend):
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
			await asyncio.sleep(0.15)
			for _ in range(100):
				try:
					if await self._eval(page, 'document.readyState') in {
						'interactive',
						'complete',
					}:
						break
				except Exception:
					pass
				await asyncio.sleep(0.05)
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
				'clip': dict(
					x=v['pageX'],
					y=v['pageY'],
					width=v['clientWidth'],
					height=v['clientHeight'],
					scale=1,
				),
			},
			session_id=await page.session_id,
		)
		with Image.open(BytesIO(base64.b64decode(result['data']))) as source:
			size = (round(v['clientWidth']), round(v['clientHeight']))
			return source.resize(size) if source.size != size else source.copy()

	@staticmethod
	def _image(image):
		out = BytesIO()
		image.save(out, format='PNG')
		return BetaBrowserScreenshotResult(data=base64.b64encode(out.getvalue()).decode())

	async def screenshot(self, context, input):
		return self._image(await self._screenshot(await self._page(input.tab_id)))

	async def zoom(self, context, input):
		image = await self._screenshot(await self._page(input.tab_id))
		x0, y0, x1, y1 = input.region
		if not (0 <= x0 < x1 <= image.width and 0 <= y0 < y1 <= image.height):
			raise ToolError('Zoom region must lie inside the full viewport screenshot.')
		cropped = image.crop((x0, y0, x1, y1))
		factor = min(2, 2048 / max(cropped.size))
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
		await self.hover(context, input)

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
		# The SDK deliberately requires coordinate targets for both drag endpoints.
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
			await self._call_node(
				page,
				object_id,
				"""function(value) {
                const e=this, w=e.ownerDocument.defaultView;
                if (e.disabled || e.readOnly) throw Error('Form element is disabled or read-only');
                if (e.tagName==='INPUT' && (e.type==='checkbox'||e.type==='radio')) {
                    if (typeof value !== 'boolean') throw Error('Checkbox/radio requires boolean');
                    if (e.type==='radio' && !value) throw Error('Choose another radio option to clear a selected radio');
                    if (e.checked !== value) e.click();
                    if (e.checked !== value) throw Error('Page refused checked state');
                    return;
                }
                if (e.tagName==='SELECT') {
                    const option=Array.from(e.options).find(o=>o.value===String(value)) ||
                                 Array.from(e.options).find(o=>o.textContent.trim()===String(value));
                    if (!option || option.disabled) throw Error('Enabled select option not found');
                    Object.getOwnPropertyDescriptor(w.HTMLSelectElement.prototype,'value').set.call(e,option.value);
                } else if (e.tagName==='INPUT'||e.tagName==='TEXTAREA') {
                    if (['file','button','submit','reset','image','hidden'].includes(e.type))
                        throw Error('Input does not accept form values');
                    const proto=e.tagName==='INPUT'?w.HTMLInputElement.prototype:w.HTMLTextAreaElement.prototype;
                    Object.getOwnPropertyDescriptor(proto,'value').set.call(e,String(value));
                    if (e.value !== String(value)) throw Error('Browser rejected or normalized the supplied value');
                } else if (e.isContentEditable) {
                    e.textContent=String(value);
                } else throw Error('Reference is not a supported form element');
                e.dispatchEvent(new w.Event('input',{bubbles:true}));
                e.dispatchEvent(new w.Event('change',{bubbles:true}));
            }""",
				input.value,
			)
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
		# Same-process iframe trees are not included in getFullAXTree's default main-frame tree.
		frames = await self._cdp.send.Page.getFrameTree(session_id=sid)

		def descendants(frame):
			for child in frame.get('childFrames', []):
				yield child['frame']['id']
				yield from descendants(child)

		for frame in descendants(frames['frameTree']):
			try:
				child_tree = await self._cdp.send.Accessibility.getFullAXTree(params={'frameId': frame}, session_id=sid)
				nodes.extend(child_tree['nodes'])
			except Exception:
				pass  # Remote iframe content is still usable via viewport actions; see capability notes.
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
					raise ToolError('Document IDs require an application document_resolver to stage files on the browser host.')
				paths.extend(self._document_resolver(doc) for doc in input.document_ids)
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
		if len(self._tabs()) >= 100:
			raise ToolError('At most 100 tabs are supported.')
		page = await self.browser.new_page()
		info = await page.get_target_info()
		await self.browser.get_or_create_cdp_session(info['targetId'], focus=True)
		await self._page(info['targetId'])
		return next(t for t in self._tabs() if t['tab_id'] == info['targetId'])

	async def list_tabs(self, context, input):
		return self._tabs()

	async def switch_tab(self, context, input):
		await self._page(input.tab_id)
		event = self.browser.event_bus.dispatch(SwitchTabEvent(target_id=input.tab_id))
		await event
		await event.event_result(raise_if_any=True)
		return next(t for t in self._tabs() if t['tab_id'] == input.tab_id)

	async def close_tab(self, context, input):
		page = await self._page(input.tab_id)
		await self._release_mouse(page._target_id)
		await self.browser.close_page(page)
		for _ in range(100):
			if not any(t['tab_id'] == input.tab_id for t in self._tabs()):
				return
			await asyncio.sleep(0.02)
		raise ToolError('Close was sent but tab state has not caught up; call list_tabs before retrying.')
