"""Run OpenAI browser tools through Browser Use Actor methods."""

from __future__ import annotations

import asyncio
import base64
import json
from io import BytesIO
from typing import Any

from PIL import Image
from pydantic import BaseModel

from browser_use.actor.page import Page
from browser_use.browser.session import BrowserSession
from openai.lib import browser as api


class Reference(BaseModel):
	tab: str
	backend: int


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

	async def state(self) -> api.BrowserState:
		"""Report current browser tabs without retaining stale tab state."""
		if self._closed:
			raise api.BrowserError('The driver is closed.')
		result = await self.browser.cdp_client.send.Target.getTargets()
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
		session = await self.browser.get_or_create_cdp_session(target, focus=True)
		self._active = target
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
		page = await self._page(args['tab_id'])
		await self.browser.cdp_client.send.DOM.getDocument({'depth': 0}, session_id=await page.session_id)
		self._refs = {name: ref for name, ref in self._refs.items() if ref.tab != page._target_id}
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
		lines = []
		for node in result['nodes']:
			role = node.get('role', {}).get('value', '')
			if node.get('ignored') or role == 'InlineTextBox':
				continue
			if args['filter'] == 'interactive' and role not in interactive:
				continue
			name = node.get('name', {}).get('value', '')
			prefix = ''
			backend = node.get('backendDOMNodeId')
			if backend and role in interactive:
				self._next_ref += 1
				ref = f'ref_{self._next_ref}'
				self._refs[ref] = Reference(tab=page._target_id, backend=backend)
				prefix = f'[{ref}] '
			lines.append(f'{prefix}{role} {json.dumps(name, ensure_ascii=False)}')
		return '\n'.join(lines)

	async def find(self, args: api.FindInput) -> str:
		"""Find current interactive elements by visible label text."""
		text = await self.read_page({'tab_id': args['tab_id'], 'filter': 'interactive'})
		terms = args['query'].casefold().split()
		return '\n'.join(line for line in text.splitlines() if all(term in line.casefold() for term in terms))

	async def get_page_text(self, args: api.TabInput) -> str:
		"""Read the selected page without returning form values."""
		page = await self._page(args['tab_id'])
		return await page.evaluate("() => document.body?.innerText || ''")

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
		page = await self._page(args['tab_id'])
		metrics = await self.browser.cdp_client.send.Page.getLayoutMetrics(session_id=await page.session_id)
		viewport = metrics['cssVisualViewport']
		size = (round(viewport['clientWidth']), round(viewport['clientHeight']))
		data = await page.screenshot()
		with Image.open(BytesIO(base64.b64decode(data))) as image:
			if image.size != size:
				output = BytesIO()
				image.resize(size, Image.Resampling.LANCZOS).save(output, format='PNG')
				data = base64.b64encode(output.getvalue()).decode()
		return {'type': 'input_image', 'image_url': 'data:image/png;base64,' + data, 'detail': 'original'}

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
			return value if isinstance(value, str) else json.dumps(value)
