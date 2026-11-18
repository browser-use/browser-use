"""Run OpenAI browser tools through Browser Use Actor methods."""

from __future__ import annotations

import asyncio
import base64
import json
from collections import deque
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from cdp_use import CDPClient
from PIL import Image
from pydantic import BaseModel

from browser_use.actor.page import Page
from browser_use.browser._cdp_timeout import TimeoutWrappedCDPClient
from browser_use.browser.session import BrowserSession
from openai.lib import browser as api

_STATE_TIMEOUT_S = 15.0
_DIAGNOSTIC_TIMEOUT_S = 5.0
_OBSERVATION_TIMEOUT_S = 20.0


def _bounded_text(text: str) -> str:
	if len(text) <= 10000:
		return text
	notice = '\n[Output truncated; request a smaller section or return fewer script results.]'
	return text[: 10000 - len(notice)] + notice


class Reference(BaseModel):
	tab: str
	backend: int


class FileGrant(BaseModel):
	"""Bind one approved transfer to its original browser document."""

	operation: str
	tab: str
	document: int
	path: Path
	target: int | None = None
	url: str | None = None
	content: bytes = b''


class BrowserUse:
	"""Own a browser session or borrow an already connected session."""

	def __init__(self, browser: BrowserSession | None = None, *, use_cloud: bool = False):
		if browser is not None and use_cloud:
			raise ValueError('Pass a browser or use_cloud=True, not both.')
		self.browser = browser if browser is not None else BrowserSession(use_cloud=use_cloud)
		self._owns_browser = browser is None
		self._closed = False
		self._refs: dict[str, Reference] = {}
		self._next_ref = 0
		self._active: str | None = None
		self._crashed_targets: set[str] = set()
		self._scopes: dict[str, Reference] = {}
		self._grants: dict[str, FileGrant] = {}
		self._diagnostic_client: CDPClient | None = None
		self._diagnostic_sessions: dict[str, str] = {}
		self._diagnostics: dict[str, dict[str, deque[str]]] = {}

	async def __aenter__(self) -> BrowserUse:
		if self._closed:
			raise RuntimeError('The driver is closed.')
		try:
			if self._owns_browser:
				await self.browser.start()
			elif not self.browser.is_cdp_connected:
				raise RuntimeError('Start the borrowed browser before entering the driver.')
			return self
		except BaseException:
			await self.close()
			raise

	async def __aexit__(self, *_: Any) -> None:
		await self.close()

	async def close(self) -> None:
		"""Close only the browser that this driver created."""
		if not self._closed:
			if self._diagnostic_client:
				await self._diagnostic_client.stop()
				self._diagnostic_client = None
			self._grants.clear()
			self._scopes.clear()
			if self._owns_browser:
				try:
					cloud = self.browser._cloud_browser_client
					if cloud.current_session_id:
						stopped = await cloud.stop_browser()
						if stopped.status != 'stopped':
							raise api.BrowserError('Cloud did not confirm browser cleanup.')
				finally:
					await self.browser.kill()
			self._refs.clear()
			self._closed = True

	def _target_crashed(self, event: Any, session_id: str | None = None) -> None:
		self._crashed_targets.add(event['targetId'])

	async def state(self) -> api.BrowserState:
		"""Report current browser tabs without retaining stale tab state."""
		if self._closed:
			raise api.BrowserError('The driver is closed.')
		for attempt in range(2):
			try:
				async with asyncio.timeout(_STATE_TIMEOUT_S):
					result = await self.browser.cdp_client.send.Target.getTargets()
				break
			except Exception as exc:
				if attempt:
					raise api.BrowserError('Browser state is unavailable after reconnecting.') from exc
				try:
					async with asyncio.timeout(_STATE_TIMEOUT_S):
						# Suppress automatic reconnect when this reconnect closes the old socket.
						stopping = self.browser._intentional_stop
						self.browser._intentional_stop = True
						try:
							await self.browser.reconnect()
						finally:
							self.browser._intentional_stop = stopping
				except Exception as reconnect_error:
					raise api.BrowserError('Browser reconnection failed.') from reconnect_error
		tabs = [t for t in result['targetInfos'] if t['type'] == 'page']
		ids = {t['targetId'] for t in tabs}
		if self._active not in ids:
			focus = self.browser.agent_focus_target_id
			self._active = focus if focus in ids else next(iter(ids), None)
		self._refs = {name: ref for name, ref in self._refs.items() if ref.tab in ids}
		return {
			'tabs': [
				{
					'id': t['targetId'],
					'url': t['url'] or 'about:blank',
					'title': t['title'],
					'active': t['targetId'] == self._active,
				}
				for t in tabs
			]
		}

	async def _page(self, tab_id: str | None) -> Page:
		state = await self.state()
		target = tab_id or self._active
		if target is None or target not in {tab['id'] for tab in state['tabs']}:
			raise api.BrowserError('Unknown tab.')
		if target in self._crashed_targets:
			raise api.BrowserError('The page crashed; open the page in a new tab.')
		try:
			async with asyncio.timeout(_STATE_TIMEOUT_S):
				session = await self.browser.get_or_create_cdp_session(target, focus=True)
		except Exception as exc:
			raise api.BrowserError('The page is unavailable; select another tab or open it again.') from exc
		self._active = target
		try:
			await self._start_diagnostics(target)
		except api.BrowserError:
			pass
		return Page(self.browser, target, session.session_id)

	async def _element(self, page: Page, target: str):
		ref = self._refs.get(target)
		if ref is None or ref.tab != page._target_id:
			raise api.BrowserError('Stale element reference; read the page again.')
		try:
			await self.browser.cdp_client.send.DOM.getDocument({'depth': 0}, session_id=await page.session_id)
			element = await page.get_element(ref.backend)
			connected = await element.evaluate('() => this.isConnected')
			if connected.casefold() != 'true':
				raise ValueError('Detached element')
			return element
		except Exception as exc:
			self._refs.pop(target, None)
			raise api.BrowserError('Stale element reference; read the page again.') from exc

	async def navigate(self, args: api.NavigateInput) -> None:
		"""Invalidate element references before navigating the selected tab."""
		page = await self._page(args['tab_id'])
		self._refs = {name: ref for name, ref in self._refs.items() if ref.tab != page._target_id}
		await page.goto(args['url'])

	async def read_page(self, args: api.ReadPageInput) -> str:
		"""Read the accessibility tree and issue tab-bound element references."""
		return await self._read_page(args)

	async def _read_page(self, args: api.ReadPageInput, query: str | None = None) -> str:
		attempt = 0
		while True:
			try:
				async with asyncio.timeout(_OBSERVATION_TIMEOUT_S):
					return await self._read_page_once(args, query)
			except Exception as exc:
				if attempt:
					raise api.BrowserError('Page reading failed; select another tab or try again.') from exc
				attempt += 1

	async def _read_page_once(self, args: api.ReadPageInput, query: str | None = None) -> str:
		terms = query.casefold().split() if query else []
		page = await self._page(args['tab_id'])
		await self.browser.cdp_client.send.DOM.getDocument({'depth': 0}, session_id=await page.session_id)
		refs = {ref.backend: name for name, ref in self._refs.items() if ref.tab == page._target_id}
		result = await self.browser.cdp_client.send.Accessibility.getFullAXTree(session_id=await page.session_id)
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
			'tab',
			'option',
			'listbox',
			'switch',
		}
		identity = json.loads(await page.evaluate('() => ({title: document.title, url: location.href})'))
		lines = [f'Title: {identity["title"][:2000]}', f'URL: {identity["url"][:2000]}']
		nodes = {node['nodeId']: node for node in result['nodes']}
		children = {child for node in result['nodes'] for child in node.get('childIds', [])}
		pending = [(node, 0) for node in reversed(result['nodes']) if node['nodeId'] not in children]
		seen: set[str] = set()
		length = sum(len(line) + 1 for line in lines)
		notice = '\n[Page truncated; use read_page_scoped, find, or interactive reads for specific content.]'
		while pending:
			node, depth = pending.pop()
			if node['nodeId'] in seen:
				continue
			seen.add(node['nodeId'])
			visible = not node.get('ignored') and node.get('role', {}).get('value') != 'InlineTextBox'
			pending.extend(
				(nodes[child], min(depth + int(visible), 30)) for child in reversed(node.get('childIds', [])) if child in nodes
			)
			role = node.get('role', {}).get('value', '')
			if node.get('ignored') or role == 'InlineTextBox':
				continue
			if args['filter'] == 'interactive' and role not in interactive:
				continue
			name = node.get('name', {}).get('value', '')
			prefix = ''
			backend = node.get('backendDOMNodeId')
			if backend and role in interactive:
				ref = refs.get(backend)
				if ref is None:
					self._next_ref += 1
					ref = f'ref_{self._next_ref}'
					self._refs[ref] = Reference(tab=page._target_id, backend=backend)
					refs[backend] = ref
				prefix = f'[{ref}] '
			states = [
				f'{prop["name"]}={json.dumps(prop["value"].get("value"))}'
				for prop in node.get('properties', [])
				if prop['name']
				in {'checked', 'selected', 'expanded', 'disabled', 'required', 'level', 'hasPopup', 'multiselectable'}
				and 'value' in prop.get('value', {})
			]
			value = node.get('value', {}).get('value')
			if value is not None:
				states.append(f'value={json.dumps(value, ensure_ascii=False)}')
			suffix = ' ' + ' '.join(states) if states else ''
			line = f'{"  " * depth}{prefix}{role} {json.dumps(name, ensure_ascii=False)}{suffix}'
			if not all(term in line.casefold() for term in terms):
				continue
			remaining = 10000 - len(notice) - length
			if len(line) + 1 > remaining:
				return '\n'.join(lines) + notice
			lines.append(line)
			length += len(line) + 1
		return '\n'.join(lines)

	async def find(self, args: api.FindInput) -> str:
		"""Find current interactive elements by visible label text."""
		return await self._read_page({'tab_id': args['tab_id'], 'filter': 'interactive'}, query=args['query'])

	async def get_page_text(self, args: api.TabInput) -> str:
		"""Read the selected page without returning form values."""
		page = await self._page(args['tab_id'])
		return _bounded_text(await page.evaluate("() => document.body?.innerText || ''"))

	async def click(self, args: api.ClickInput) -> None:
		"""Click an element from the latest page read."""
		page = await self._page(args['tab_id'])
		await (await self._element(page, args['target'])).click()

	async def hover(self, args: api.ClickInput) -> None:
		"""Move the pointer over a referenced element."""
		page = await self._page(args['tab_id'])
		await (await self._element(page, args['target'])).hover()

	async def scroll_to(self, args: api.ClickInput) -> None:
		"""Scroll a referenced element into view."""
		page = await self._page(args['tab_id'])
		await (await self._element(page, args['target'])).scroll_into_view()

	async def type(self, args: api.TypeInput) -> None:
		"""Fill a referenced element or type at the current focus."""
		page = await self._page(args['tab_id'])
		if args['target'] is not None:
			await (await self._element(page, args['target'])).fill(args['text'])
		else:
			await self.browser.cdp_client.send.Input.insertText({'text': args['text']}, session_id=await page.session_id)

	async def key(self, args: api.KeyInput) -> None:
		"""Press a key combination in the selected tab."""
		page = await self._page(args['tab_id'])
		await page.press('+'.join(args['keys']))

	async def select_option(self, args: api.SelectOptionInput) -> None:
		"""Select values in a referenced native select element."""
		page = await self._page(args['tab_id'])
		await (await self._element(page, args['target'])).select_option(args['values'])

	async def scroll(self, args: api.ScrollInput) -> None:
		"""Scroll by the requested number of pixels."""
		page = await self._page(args['tab_id'])
		amount = args['amount'] * (-1 if args['direction'] in {'up', 'left'} else 1)
		horizontal = args['direction'] in {'left', 'right'}
		await (await page.mouse).scroll(delta_x=amount if horizontal else 0, delta_y=0 if horizontal else amount)

	async def wait_for(self, args: api.WaitForInput) -> None:
		"""Wait for visible text within the requested deadline."""
		page = await self._page(args['tab_id'])
		result = await page.evaluate(
			"""(text, timeout) => new Promise(resolve => {
                let timer;
                const observer = new MutationObserver(check);
                function finish(found) { observer.disconnect(); clearTimeout(timer); resolve(found); }
                function check() { if (document.body?.innerText.includes(text)) finish(true); }
                observer.observe(document, {subtree: true, childList: true, characterData: true, attributes: true});
                timer = setTimeout(() => finish(false), timeout);
                check();
            })""",
			args['text'],
			args['timeout_ms'],
		)
		if result.casefold() != 'true':
			raise api.BrowserError('Visible text did not appear before the deadline.')

	async def screenshot(self, args: api.TabInput) -> dict[str, str]:
		"""Capture the selected viewport as a native image input."""
		attempt = 0
		while True:
			try:
				async with asyncio.timeout(_OBSERVATION_TIMEOUT_S):
					page = await self._page(args['tab_id'])
					metrics = await self.browser.cdp_client.send.Page.getLayoutMetrics(session_id=await page.session_id)
					viewport = metrics['cssVisualViewport']
					size = (round(viewport['clientWidth']), round(viewport['clientHeight']))
					data = await page.screenshot()
					with Image.open(BytesIO(base64.b64decode(data))) as image:
						image.load()
						if image.size != size:
							output = BytesIO()
							image.resize(size, Image.Resampling.LANCZOS).save(output, format='PNG')
							data = base64.b64encode(output.getvalue()).decode()
					return {'type': 'input_image', 'image_url': 'data:image/png;base64,' + data, 'detail': 'original'}
			except Exception as exc:
				if attempt:
					raise api.BrowserError('Screenshot capture failed; select another tab or try again.') from exc
				attempt += 1

	async def zoom(self, args: api.ZoomInput) -> dict[str, str]:
		"""Crop a screenshot without changing the pointer coordinate origin."""
		result = await self.screenshot({'tab_id': args['tab_id']})
		with Image.open(BytesIO(base64.b64decode(result['image_url'].split(',', 1)[1]))) as image:
			left, top, right, bottom = args['region']
			if left < 0 or top < 0 or right > image.width or bottom > image.height or right <= left or bottom <= top:
				raise api.BrowserError('Crop exceeds the screenshot bounds.')
			output = BytesIO()
			image.crop((left, top, right, bottom)).save(output, format='PNG')
		result['image_url'] = 'data:image/png;base64,' + base64.b64encode(output.getvalue()).decode()
		return result

	async def new_tab(self, args: api.NewTabInput) -> None:
		"""Open a tab and select it for subsequent actions."""
		page = await self.browser.new_page(args['url'])
		self._active = page._target_id

	async def switch_tab(self, args: api.TabInput) -> None:
		"""Activate an existing tab."""
		page = await self._page(args['tab_id'])
		await self.browser.cdp_client.send.Target.activateTarget({'targetId': page._target_id})

	async def close_tab(self, args: api.TabInput) -> None:
		"""Close only the selected tab."""
		page = await self._page(args['tab_id'])
		await self.browser.close_page(page)
		for _ in range(500):
			if not any(tab['id'] == page._target_id for tab in (await self.state())['tabs']):
				return
			await asyncio.sleep(0.02)
		raise api.BrowserError('Tab closure is pending; read the tab list before retrying.')

	async def _bounds(self, page: Page, points: list[tuple[int, int]]) -> None:
		metrics = await self.browser.cdp_client.send.Page.getLayoutMetrics(session_id=await page.session_id)
		viewport = metrics['cssVisualViewport']
		if any(x < 0 or y < 0 or x >= viewport['clientWidth'] or y >= viewport['clientHeight'] for x, y in points):
			raise api.BrowserError('Pointer coordinates exceed the viewport.')

	async def click_at(self, args: api.ClickAtInput, *, cancelled=None) -> None:
		"""Click full-viewport coordinates with the requested modifiers."""
		page = await self._page(args['tab_id'])
		await self._bounds(page, [(args['x'], args['y'])])
		if cancelled and cancelled():
			raise asyncio.CancelledError()
		await (await page.mouse).click(
			args['x'], args['y'], button=args['button'], click_count=args['click_count'], modifiers=args['keys']
		)

	async def hover_at(self, args: api.HoverAtInput) -> None:
		"""Move the pointer to full-viewport coordinates."""
		page = await self._page(args['tab_id'])
		await self._bounds(page, [(args['x'], args['y'])])
		await (await page.mouse).move(args['x'], args['y'])

	async def drag_path(self, args: api.DragPathInput, *, cancelled=None) -> None:
		"""Drag through a path and release the pointer after failure."""
		page = await self._page(args['tab_id'])
		points = [(point['x'], point['y']) for point in args['path']]
		await self._bounds(page, points)
		mouse = await page.mouse
		await mouse.move(*points[0], modifiers=args['keys'])
		try:
			if cancelled and cancelled():
				raise asyncio.CancelledError()
			await mouse.down(modifiers=args['keys'])
			for x, y in points[1:]:
				if cancelled and cancelled():
					raise asyncio.CancelledError()
				await mouse.move(x, y, modifiers=args['keys'])
		finally:
			await mouse.up(modifiers=args['keys'])

	async def hold_keys(self, args: api.HoldKeysInput, *, cancelled=None) -> None:
		"""Hold a key combination for the requested duration."""
		page = await self._page(args['tab_id'])
		if cancelled and cancelled():
			raise asyncio.CancelledError()
		await page.hold_key('+'.join(args['keys']), args['duration_ms'] / 1000)

	async def set_checked(self, args: api.SetCheckedInput) -> None:
		"""Set a native checkbox without toggling an already matching state."""
		page = await self._page(args['tab_id'])
		element = await self._element(page, args['target'])
		kind = await element.get_attribute('type')
		if kind not in {'checkbox', 'radio'}:
			raise api.BrowserError('The target is not a native checkbox or radio button.')
		if kind == 'radio' and not args['checked']:
			raise api.BrowserError('Clear a radio button by selecting another option.')
		current = await element.evaluate('() => this.checked')
		if (current.casefold() == 'true') != args['checked']:
			await element.click()

	async def run_script(self, args: api.RunScriptInput) -> str:
		"""Run an explicitly enabled page script within the caller deadline."""
		page = await self._page(args['tab_id'])
		async with asyncio.timeout(args['timeout_ms'] / 1000):
			result = await self.browser.cdp_client.send.Runtime.evaluate(
				{'expression': args['source'], 'returnByValue': True, 'awaitPromise': True},
				session_id=await page.session_id,
			)
			if result.get('exceptionDetails'):
				raise api.BrowserError('Page script failed.')
			value = result.get('result', {}).get('value')
			return _bounded_text(value if isinstance(value, str) else json.dumps(value))

	async def _start_diagnostics(self, target: str) -> None:
		if target in self._diagnostic_sessions:
			return
		try:
			async with asyncio.timeout(_DIAGNOSTIC_TIMEOUT_S):
				if self._diagnostic_client is None:
					self._diagnostic_client = TimeoutWrappedCDPClient(
						self.browser.cdp_client.url,
						additional_headers=self.browser.cdp_client.additional_headers,
						cdp_request_timeout_s=_DIAGNOSTIC_TIMEOUT_S,
					)
					await self._diagnostic_client.start()
					self._diagnostic_client.register.Target.targetCrashed(self._target_crashed)
					await self._diagnostic_client.send.Target.setDiscoverTargets({'discover': True})
					self._diagnostic_client.register.Runtime.consoleAPICalled(self._console_event)
					self._diagnostic_client.register.Network.responseReceived(self._network_event)
				attached = await self._diagnostic_client.send.Target.attachToTarget({'targetId': target, 'flatten': True})
				session = attached['sessionId']
				self._diagnostics[session] = {'console': deque(maxlen=100), 'network': deque(maxlen=100)}
				await self._diagnostic_client.send.Runtime.enable(session_id=session)
				await self._diagnostic_client.send.Network.enable(session_id=session)
				self._diagnostic_sessions[target] = session
		except BaseException as exc:
			client, self._diagnostic_client = self._diagnostic_client, None
			self._diagnostic_sessions.clear()
			self._diagnostics.clear()
			if client is not None:
				try:
					async with asyncio.timeout(_DIAGNOSTIC_TIMEOUT_S):
						await client.stop()
				except Exception:
					pass
			if not isinstance(exc, Exception):
				raise
			raise api.BrowserError('Page diagnostics are unavailable.') from exc

	def _console_event(self, event: Any, session_id: str | None) -> None:
		if session_id in self._diagnostics:
			values = [str(arg.get('value', arg.get('type', '')))[:512] for arg in event.get('args', [])[:10]]
			self._diagnostics[session_id]['console'].append(event['type'] + ': ' + ' '.join(values))

	def _network_event(self, event: Any, session_id: str | None) -> None:
		if session_id in self._diagnostics:
			response = event['response']
			url = urlsplit(response['url'])
			self._diagnostics[session_id]['network'].append(
				f'{response["status"]} {url.scheme}://{url.hostname or ""}{url.path}'[:1024]
			)

	async def read_diagnostics(self, args: api.ReadDiagnosticsInput) -> api.BrowserReadV1:
		"""Return bounded diagnostics without network headers or request bodies."""
		page = await self._page(args['tab_id'])
		if page._target_id not in self._diagnostic_sessions:
			raise api.BrowserError('Page diagnostics are unavailable; try again after the page responds.')
		records = self._diagnostics[self._diagnostic_sessions[page._target_id]][args['source']]
		return {
			'version': 1,
			'text': '\n'.join(list(records)[-args['limit'] :]),
			'elements': [],
			'omitted': ['report_limit'] if len(records) > args['limit'] else [],
		}

	async def read_page_scoped(self, args: api.ReadPageScopedInput) -> api.BrowserScopedReadV1:
		"""Discover semantic regions or read their current accessibility subtree."""
		page = await self._page(args['tab_id'])
		result = await self.browser.cdp_client.send.Accessibility.getFullAXTree(session_id=await page.session_id)
		nodes = {node['nodeId']: node for node in result['nodes']}
		root = args['root']
		if root is None:
			self._scopes = {key: ref for key, ref in self._scopes.items() if ref.tab != page._target_id}
			scopes = []
			for node in nodes.values():
				role = node.get('role', {}).get('value')
				if role in {'RootWebArea', 'main', 'navigation', 'region', 'complementary', 'contentinfo', 'banner'} and node.get(
					'backendDOMNodeId'
				):
					key = 'scope_' + uuid4().hex
					self._scopes[key] = Reference(tab=page._target_id, backend=int(node.get('backendDOMNodeId') or 0))
					scopes.append(
						{
							'ref': key,
							'label': str(node.get('name', {}).get('value') or role)
							.encode('utf-8')[:256]
							.decode('utf-8', errors='ignore'),
						}
					)
					if len(json.dumps(scopes)) > 9800 or len(scopes) > 100:
						scopes.pop()
						return {'version': 1, 'text': '', 'elements': [], 'omitted': ['report_limit'], 'scopes': scopes}
			return {'version': 1, 'text': '', 'elements': [], 'omitted': [], 'scopes': scopes}
		ref = self._scopes.get(root)
		if ref is None or ref.tab != page._target_id:
			raise api.BrowserError('Unknown or stale read scope.')
		node = next((n for n in nodes.values() if n.get('backendDOMNodeId') == ref.backend), None)
		if node is None:
			raise api.BrowserError('Unknown or stale read scope.')
		queue = [(node, 0)]
		lines, elements = [], []
		visited = 0
		truncated = False
		while queue and len(lines) < 200 and visited < 2000:
			node, depth = queue.pop(0)
			visited += 1
			role = node.get('role', {}).get('value', '')
			name = str(node.get('name', {}).get('value', ''))
			prefix = ''
			previous_elements = len(elements)
			previous_lines = len(lines)
			if not node.get('ignored') and role != 'InlineTextBox':
				if role in {'button', 'textbox', 'combobox', 'checkbox', 'radio', 'slider', 'listbox', 'link'} and node.get(
					'backendDOMNodeId'
				):
					self._next_ref += 1
					key = f'ref_{self._next_ref}'
					self._refs[key] = Reference(tab=page._target_id, backend=int(node.get('backendDOMNodeId') or 0))
					prefix = f'[{key}] '
					if role != 'link':
						label = (name.strip() or f'Unnamed {role}').encode('utf-8')[:256].decode('utf-8', errors='ignore')
						elements.append({'ref': key, 'role': role, 'label': label})
				if args['filter'] == 'all' or role in {
					'button',
					'textbox',
					'combobox',
					'checkbox',
					'radio',
					'slider',
					'listbox',
					'link',
				}:
					lines.append(f'{prefix}{role} {name[:500]}')
			if (
				len(
					json.dumps(
						{'version': 1, 'text': '\n'.join(lines), 'elements': elements, 'omitted': ['report_limit'], 'scopes': []}
					)
				)
				> 10000
			):
				del lines[previous_lines:]
				del elements[previous_elements:]
				truncated = True
				break
			if depth < args['depth']:
				queue.extend((nodes[key], depth + 1) for key in node.get('childIds', []) if key in nodes)
		return {
			'version': 1,
			'text': '\n'.join(lines),
			'elements': elements,
			'omitted': ['report_limit'] if queue or truncated else [],
			'scopes': [],
		}

	async def grant_upload(self, path: str | Path, *, target: str, tab_id: str | None = None) -> str:
		"""Approve one file snapshot for a specific input and document."""
		page = await self._page(tab_id)
		element = await self._element(page, target)
		if await element.get_attribute('type') != 'file':
			raise api.BrowserError('Upload target must be a file input.')
		path = Path(path).resolve()
		with path.open('rb') as source:
			content = source.read(10_000_001)
		if len(content) > 10_000_000:
			raise api.BrowserError('File exceeds the 10 MB transfer limit.')
		document = await self.browser.cdp_client.send.DOM.getDocument(session_id=await page.session_id)
		key = uuid4().hex
		self._grants[key] = FileGrant(
			operation='upload',
			tab=page._target_id,
			document=document['root']['backendNodeId'],
			path=path,
			target=self._refs[target].backend,
			content=content,
		)
		return key

	async def grant_download(self, url: str, path: str | Path, *, tab_id: str | None = None) -> str:
		"""Approve one browser fetch into a new application-side file."""
		if urlsplit(url).scheme not in {'http', 'https', 'blob'}:
			raise api.BrowserError('Download requires an HTTP, HTTPS, or blob URL.')
		page = await self._page(tab_id)
		document = await self.browser.cdp_client.send.DOM.getDocument(session_id=await page.session_id)
		path = Path(path).resolve()
		if path.exists():
			raise api.BrowserError('Download destination already exists.')
		key = uuid4().hex
		self._grants[key] = FileGrant(
			operation='download', tab=page._target_id, document=document['root']['backendNodeId'], path=path, url=url
		)
		return key

	async def _consume_grant(self, key: str, operation: str) -> tuple[FileGrant, Page]:
		grant = self._grants.pop(key, None)
		if grant is None or grant.operation != operation:
			raise api.BrowserError('Unknown, consumed, or mismatched file grant.')
		page = await self._page(grant.tab)
		document = await self.browser.cdp_client.send.DOM.getDocument(session_id=await page.session_id)
		if document['root']['backendNodeId'] != grant.document:
			raise api.BrowserError('File grant belongs to an earlier document.')
		return grant, page

	async def upload_file(self, args: api.BrowserFileInput) -> api.BrowserFileOutcome:
		"""Transfer approved bytes into the remote browser file input."""
		grant, page = await self._consume_grant(args['grant_id'], 'upload')
		if grant.target is None:
			raise api.BrowserError('Upload grant has no target.')
		element = await page.get_element(grant.target)
		await element.evaluate(
			"""(encoded, name) => {
            if (!this.isConnected || this.type !== 'file') throw new Error('Invalid upload target');
            const bytes = Uint8Array.from(atob(encoded), c => c.charCodeAt(0));
            const transfer = new DataTransfer();
            transfer.items.add(new File([bytes], name));
            this.files = transfer.files;
            this.dispatchEvent(new Event('input', {bubbles: true}));
            this.dispatchEvent(new Event('change', {bubbles: true}));
        }""",
			base64.b64encode(grant.content).decode(),
			grant.path.name,
		)
		return {'version': 1, 'status': 'completed', 'effect': 'completed', 'cleanup': 'completed'}

	async def download_file(self, args: api.BrowserFileInput) -> api.BrowserFileOutcome:
		"""Fetch approved bytes through the browser and create the destination."""
		grant, page = await self._consume_grant(args['grant_id'], 'download')
		encoded = await page.evaluate(
			"""(url) => (async () => {
            const response = await fetch(url, {redirect: 'error', signal: AbortSignal.timeout(30000)});
            if (!response.ok) throw new Error('Download request failed');
            const reader = response.body.getReader();
            const chunks = [];
            let size = 0;
            try {
                while (true) {
                    const {done, value} = await reader.read();
                    if (done) break;
                    size += value.length;
                    if (size > 10000000) throw new Error('Download exceeds 10 MB');
                    chunks.push(value);
                }
            } finally { await reader.cancel(); }
            let binary = '';
            for (const chunk of chunks) {
                for (let i = 0; i < chunk.length; i += 8192)
                    binary += String.fromCharCode(...chunk.subarray(i, i + 8192));
            }
            return btoa(binary);
        })()""",
			grant.url,
		)
		content = base64.b64decode(encoded, validate=True)
		with grant.path.open('xb') as destination:
			destination.write(content)
		return {'version': 1, 'status': 'completed', 'effect': 'completed', 'cleanup': 'completed'}
