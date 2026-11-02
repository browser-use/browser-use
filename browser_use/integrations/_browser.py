from __future__ import annotations

import asyncio
import base64
import json
import math
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel

from browser_use import BrowserUse as PiBrowser


class SessionInfo(BaseModel):
	session_id: str


class TargetInfo(BaseModel):
	target_id: str
	url: str
	title: str


class Sender:
	def __init__(self, session: BrowserConnection, method: str = ''):
		self.session = session
		self.method = method

	def __getattr__(self, name: str) -> Sender:
		value = Sender(self.session, f'{self.method}.{name}'.lstrip('.'))
		setattr(self, name, value)
		return value

	async def __call__(self, params: dict[str, Any] | None = None, *, session_id: str | None = None) -> Any:
		return await self.session.command(self.method, params, session_id)


class BrowserConnection:
	def __init__(self, browser: PiBrowser | dict[str, Any] | None = None, *, use_cloud: bool = False, controller: str = 'custom'):
		if browser is not None and not isinstance(browser, (PiBrowser, dict)):
			raise TypeError(
				'Use a Pi BrowserUse session or browser configuration; old BrowserSession objects need the old package version.'
			)
		if browser is not None and use_cloud:
			raise ValueError('Pass a browser or use_cloud=True, not both.')
		self.client = browser if isinstance(browser, PiBrowser) else None
		self.options = browser if isinstance(browser, dict) else None
		self.controller = controller
		self.owned = self.client is None
		self.send = Sender(self)
		self.cdp_client = self
		self.agent_focus_target_id: str | None = None
		self._targets: list[TargetInfo] = []
		self._sessions: dict[str, SessionInfo] = {}
		self._lock = asyncio.Lock()
		self._observer = ''

	@property
	def is_cdp_connected(self) -> bool:
		return self.client is not None

	async def start(self) -> None:
		if self.client is None:
			options: dict[str, Any] = {'controller': self.controller, 'entrypoint': 'adapter'}
			if self.options is not None:
				options['browser'] = self.options
			self.client = await PiBrowser.create(**options)
		await self.refresh()

	async def value(self, expression: str) -> Any:
		if self.client is None:
			raise RuntimeError('Start the browser before using its tools.')
		async with self._lock:
			return await self.client.execute_json(expression)

	async def command(self, method: str, params: dict[str, Any] | None = None, session_id: str | None = None) -> Any:
		return await self.value(
			f'browser.send({json.dumps(method)}, {json.dumps(params or {})}, {json.dumps(session_id) if session_id else "undefined"})'
		)

	async def refresh(self) -> list[TargetInfo]:
		result = await self.command('Target.getTargets')
		self._targets = [
			TargetInfo(target_id=t['targetId'], url=t.get('url', ''), title=t.get('title', ''))
			for t in result['targetInfos']
			if t['type'] == 'page'
		]
		ids = {t.target_id for t in self._targets}
		if self.agent_focus_target_id not in ids:
			self.agent_focus_target_id = self._targets[0].target_id if self._targets else None
		return self._targets

	def get_page_targets(self) -> list[TargetInfo]:
		return self._targets.copy()

	async def get_or_create_cdp_session(self, target: str, *, focus: bool = False) -> SessionInfo:
		if target not in self._sessions:
			result = await self.command('Target.attachToTarget', {'targetId': target, 'flatten': True})
			self._sessions[target] = SessionInfo(session_id=result['sessionId'])
			await self.command('Page.enable', session_id=result['sessionId'])
			await self.command('Runtime.enable', session_id=result['sessionId'])
		if focus:
			self.agent_focus_target_id = target
		return self._sessions[target]

	async def new_page(self, url: str = 'about:blank') -> Page:
		target = await self.value(f'(await tabs.open({json.dumps(url)})).targetId')
		self.agent_focus_target_id = target
		session = await self.get_or_create_cdp_session(target)
		await self.refresh()
		return Page(self, target, session.session_id)

	async def close_page(self, page: Page) -> None:
		await self.command('Target.closeTarget', {'targetId': page._target_id})
		self._sessions.pop(page._target_id, None)
		await self.refresh()

	async def navigate_to(self, url: str) -> None:
		target = self.agent_focus_target_id
		if target is None:
			await self.new_page(url)
		else:
			session = await self.get_or_create_cdp_session(target)
			await Page(self, target, session.session_id).goto(url)
		await self.refresh()

	async def reconnect(self) -> None:
		await self.value('(async () => { await reconnect(); return null; })()')
		self._sessions.clear()
		self._observer = ''
		await self.refresh()

	async def observe(self, methods: list[str]) -> None:
		if not self._observer:
			self._observer = '__browserUseAdapter_' + uuid4().hex
			await self.value(
				r"""((key) => {
                const state = {queue: []};
                state.unsubscribe = browser.addEventObserver((method, params, session) => {
                    if (!/^(Runtime\.|Network\.|Log\.|Browser\.download|Target\.targetCrashed)/.test(method)) return;
                    if (state.queue.length === 1000) state.queue.shift();
                    state.queue.push({method, params, session: session ?? null});
                });
                global[key] = state;
                return null;
            })("""
				+ json.dumps(self._observer)
				+ ')'
			)
		for target in await self.refresh():
			session = await self.get_or_create_cdp_session(target.target_id)
			for method in methods:
				await self.command(method, session_id=session.session_id)

	async def events(self) -> list[dict[str, Any]]:
		if not self._observer:
			return []
		return await self.value(f'global[{json.dumps(self._observer)}].queue.splice(0)')

	async def stop_observer(self) -> None:
		if self._observer and self.client:
			await self.value(
				'((key) => { global[key]?.unsubscribe(); delete global[key]; return null; })(' + json.dumps(self._observer) + ')'
			)
			self._observer = ''

	async def release(self) -> None:
		await self.stop_observer()
		for target, session in list(self._sessions.items()):
			await self.command('Target.detachFromTarget', {'sessionId': session.session_id})
			self._sessions.pop(target, None)

	async def close(self) -> None:
		results = list(await asyncio.gather(self.release(), return_exceptions=True))
		if self.owned:
			results.extend(await asyncio.gather(self.kill(), return_exceptions=True))
		for result in results:
			if isinstance(result, BaseException):
				raise result

	async def kill(self) -> None:
		if self.client and self.owned:
			await self.client.close()
			self.client = None


class Page:
	def __init__(self, session: BrowserConnection, target: str, session_id: str):
		self._session = session
		self._target_id = target
		self._session_id = session_id
		self._mouse = Mouse(self)

	@property
	async def session_id(self) -> str:
		return self._session_id

	@property
	async def mouse(self) -> Mouse:
		return self._mouse

	async def cdp(self, method: str, params: dict[str, Any] | None = None) -> Any:
		return await self._session.command(method, params, self._session_id)

	async def evaluate(self, function: str, *args: Any) -> str:
		result = await self.cdp(
			'Runtime.evaluate',
			{
				'expression': f'({function})(...{json.dumps(args)})',
				'returnByValue': True,
				'awaitPromise': True,
				'userGesture': True,
			},
		)
		value = result_value(result)
		return value if isinstance(value, str) else json.dumps(value)

	async def goto(self, url: str) -> None:
		result = await self.cdp('Page.navigate', {'url': url})
		if result.get('errorText'):
			raise RuntimeError(result['errorText'])
		await self.wait_loaded()

	async def wait_loaded(self) -> None:
		await self.cdp(
			'Runtime.evaluate',
			{
				'expression': "new Promise(resolve => { if (document.readyState !== 'loading') resolve(); else document.addEventListener('DOMContentLoaded', resolve, {once:true}); })",
				'awaitPromise': True,
				'timeout': 15000,
			},
		)

	async def get_url(self) -> str:
		return await self.evaluate('() => location.href')

	async def get_title(self) -> str:
		return await self.evaluate('() => document.title')

	async def get_target_info(self) -> dict[str, Any]:
		return (await self._session.command('Target.getTargetInfo', {'targetId': self._target_id}))['targetInfo']

	async def screenshot(self) -> str:
		viewport = (await self.cdp('Page.getLayoutMetrics'))['cssVisualViewport']
		return (
			await self.cdp(
				'Page.captureScreenshot',
				{
					'format': 'png',
					'captureBeyondViewport': False,
					'clip': {
						'x': viewport['pageX'],
						'y': viewport['pageY'],
						'width': viewport['clientWidth'],
						'height': viewport['clientHeight'],
						'scale': 1,
					},
				},
			)
		)['data']

	async def get_element(self, backend: int) -> Element:
		return Element(self, backend)

	async def go_back(self) -> None:
		await self._history(-1)

	async def go_forward(self) -> None:
		await self._history(1)

	async def _history(self, offset: int) -> None:
		history = await self.cdp('Page.getNavigationHistory')
		index = history['currentIndex'] + offset
		if 0 <= index < len(history['entries']):
			await self.cdp('Page.navigateToHistoryEntry', {'entryId': history['entries'][index]['id']})
			await self.wait_loaded()

	async def reload(self) -> None:
		await self.cdp('Page.reload')
		await self.wait_loaded()

	async def press(self, chord: str) -> None:
		await self.hold_key(chord, 0)

	async def hold_key(self, chord: str, duration: float) -> None:
		if not math.isfinite(duration) or duration < 0:
			raise ValueError('Key duration must be finite and non-negative.')
		aliases = {
			'ctrl': 'Control',
			'control': 'Control',
			'alt': 'Alt',
			'option': 'Alt',
			'cmd': 'Meta',
			'command': 'Meta',
			'meta': 'Meta',
			'shift': 'Shift',
			'enter': 'Enter',
			'return': 'Enter',
			'tab': 'Tab',
			'escape': 'Escape',
			'esc': 'Escape',
			'space': ' ',
			'backspace': 'Backspace',
			'delete': 'Delete',
			'arrowup': 'ArrowUp',
			'arrowdown': 'ArrowDown',
			'arrowleft': 'ArrowLeft',
			'arrowright': 'ArrowRight',
		}
		keys = [aliases.get(key.lower(), key) for key in chord.split('+')]
		modifiers = sum(bit for key, bit in [('Alt', 1), ('Control', 2), ('Meta', 4), ('Shift', 8)] if key in keys)
		codes = {
			'Enter': 13,
			'Tab': 9,
			'Escape': 27,
			'Backspace': 8,
			'Delete': 46,
			'ArrowLeft': 37,
			'ArrowUp': 38,
			'ArrowRight': 39,
			'ArrowDown': 40,
			' ': 32,
		}
		pressed: list[dict[str, Any]] = []
		try:
			for key in keys:
				params: dict[str, Any] = {'key': key, 'modifiers': modifiers}
				if len(key) == 1:
					params.update(code='Space' if key == ' ' else f'Key{key.upper()}', windowsVirtualKeyCode=ord(key.upper()))
					if modifiers & 7 == 0:
						params['text'] = key
				elif key in codes:
					params.update(code=key, windowsVirtualKeyCode=codes[key])
					if key == 'Enter':
						params['text'] = '\r'
				await self.cdp('Input.dispatchKeyEvent', {'type': 'keyDown', **params})
				pressed.append(params)
			if duration:
				await asyncio.sleep(duration)
		finally:
			for params in reversed(pressed):
				await self.cdp(
					'Input.dispatchKeyEvent', {'type': 'keyUp', **{key: value for key, value in params.items() if key != 'text'}}
				)


def result_value(result: dict[str, Any]) -> Any:
	if result.get('exceptionDetails'):
		detail = result['exceptionDetails']
		raise RuntimeError(detail.get('exception', {}).get('description', detail.get('text', 'JavaScript failed.')))
	return result.get('result', {}).get('value')


def _read_upload(path: Path) -> bytes:
	with path.open('rb') as source:
		return source.read(10_000_001)


class Element:
	def __init__(self, page: Page, backend: int):
		self.page = page
		self.backend = backend

	async def evaluate(self, function: str, *args: Any) -> str:
		resolved = await self.page.cdp('DOM.resolveNode', {'backendNodeId': self.backend})
		object_id = resolved['object']['objectId']
		parsed = re.fullmatch(r'\s*(async\s+)?\(([^)]*)\)\s*=>\s*(.+)', function, re.DOTALL)
		if not parsed:
			raise ValueError('Element evaluation requires an arrow function.')
		prefix, parameters, body = parsed.groups()
		declaration = f'{prefix or ""}function({parameters}) ' + (
			body if body.strip().startswith('{') else '{ return ' + body + '; }'
		)
		try:
			result = await self.page.cdp(
				'Runtime.callFunctionOn',
				{
					'objectId': object_id,
					'functionDeclaration': declaration,
					'arguments': [{'value': arg} for arg in args],
					'returnByValue': True,
					'awaitPromise': True,
					'userGesture': True,
				},
			)
			value = result_value(result)
			return value if isinstance(value, str) else json.dumps(value)
		finally:
			await self.page.cdp('Runtime.releaseObject', {'objectId': object_id})

	async def get_attribute(self, name: str) -> str | None:
		value = await self.evaluate('(name) => this.getAttribute(name)', name)
		return None if value == 'null' else value

	async def scroll_into_view(self) -> None:
		await self.page.cdp('DOM.scrollIntoViewIfNeeded', {'backendNodeId': self.backend})

	async def point(self) -> tuple[float, float]:
		await self.scroll_into_view()
		quads = (await self.page.cdp('DOM.getContentQuads', {'backendNodeId': self.backend})).get('quads', [])
		if not quads:
			raise RuntimeError('Element has no visible target.')
		quad = quads[0]
		return sum(quad[::2]) / 4, sum(quad[1::2]) / 4

	async def click(self) -> None:
		await self.page._mouse.click(*(await self.point()))

	async def hover(self) -> None:
		await self.page._mouse.move(*(await self.point()))

	async def fill(self, text: str) -> None:
		await self.evaluate(
			"""(text) => {
            if (!this.isConnected || this.disabled || this.readOnly) throw Error('Input is unavailable');
            if (this.isContentEditable) { this.focus(); this.textContent = text; }
            else {
                if (!['INPUT', 'TEXTAREA'].includes(this.tagName)) throw Error('Target is not a text input');
                const proto = this.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
                Object.getOwnPropertyDescriptor(proto, 'value').set.call(this, text);
            }
            this.dispatchEvent(new Event('input', {bubbles:true}));
            this.dispatchEvent(new Event('change', {bubbles:true}));
        }""",
			text,
		)

	async def select_option(self, values: str | list[str]) -> None:
		await self.evaluate(
			"""(values) => {
            if (this.tagName !== 'SELECT' || this.disabled) throw Error('Target is not an enabled select');
            if (!this.multiple && values.length > 1) throw Error('Select accepts one value');
            const options = [...this.options];
            const selected = values.map(value => {
                const option = options.find(o => o.value === value || o.label.trim() === value);
                if (!option || option.disabled || option.parentElement.disabled) throw Error('Option is unavailable');
                return option;
            });
            for (const option of options) option.selected = selected.includes(option);
            this.dispatchEvent(new Event('input', {bubbles:true}));
            this.dispatchEvent(new Event('change', {bubbles:true}));
        }""",
			[values] if isinstance(values, str) else values,
		)

	async def check(self) -> None:
		if await self.evaluate('() => this.checked') != 'true':
			await self.click()
		if await self.evaluate('() => this.checked') != 'true':
			raise RuntimeError('Input did not retain its checked state.')

	async def set_input_files(self, paths: list[str]) -> None:
		files = []
		total = 0
		for raw in paths:
			path = Path(raw)
			content = await asyncio.to_thread(_read_upload, path)
			total += len(content)
			if total > 10_000_000:
				raise ValueError('Uploads exceed the 10 MB transfer limit.')
			files.append({'name': path.name, 'data': base64.b64encode(content).decode()})
		await self.evaluate(
			"""(files) => {
            if (!this.isConnected || this.type !== 'file' || this.disabled) throw Error('Upload input is unavailable');
            if (!this.multiple && files.length > 1) throw Error('Upload input accepts one file');
            const transfer = new DataTransfer();
            for (const file of files) transfer.items.add(new File([Uint8Array.from(atob(file.data), c => c.charCodeAt(0))], file.name));
            this.files = transfer.files;
            this.dispatchEvent(new Event('input', {bubbles:true}));
            this.dispatchEvent(new Event('change', {bubbles:true}));
        }""",
			files,
		)


class Mouse:
	def __init__(self, page: Page):
		self.page = page
		self.x = 0.0
		self.y = 0.0
		self.buttons = 0

	async def event(
		self, kind: str, *, button: str = 'none', click_count: int = 0, modifiers: Sequence[str] | None = None, **extra: Any
	) -> None:
		bits = sum(bit for name, bit in [('Alt', 1), ('Control', 2), ('Meta', 4), ('Shift', 8)] if name in (modifiers or []))
		await self.page.cdp(
			'Input.dispatchMouseEvent',
			{
				'type': kind,
				'x': self.x,
				'y': self.y,
				'button': button,
				'buttons': self.buttons,
				'clickCount': click_count,
				'modifiers': bits,
				**extra,
			},
		)

	async def move(self, x: float, y: float, *, modifiers: Sequence[str] | None = None) -> None:
		if not math.isfinite(x) or not math.isfinite(y):
			raise ValueError('Pointer coordinates must be finite.')
		self.x, self.y = x, y
		await self.event('mouseMoved', modifiers=modifiers)

	async def down(self, *, button: str = 'left', click_count: int = 1, modifiers: Sequence[str] | None = None) -> None:
		self.buttons |= {'left': 1, 'right': 2, 'middle': 4}[button]
		await self.event('mousePressed', button=button, click_count=click_count, modifiers=modifiers)

	async def up(self, *, button: str = 'left', click_count: int = 1, modifiers: Sequence[str] | None = None) -> None:
		self.buttons &= ~{'left': 1, 'right': 2, 'middle': 4}[button]
		await self.event('mouseReleased', button=button, click_count=click_count, modifiers=modifiers)

	async def click(
		self, x: float, y: float, *, button: str = 'left', click_count: int = 1, modifiers: Sequence[str] | None = None
	) -> None:
		await self.move(x, y, modifiers=modifiers)
		try:
			await self.down(button=button, click_count=click_count, modifiers=modifiers)
		finally:
			await self.up(button=button, click_count=click_count, modifiers=modifiers)

	async def scroll(self, x: float = 0, y: float = 0, delta_x: float = 0, delta_y: float = 0) -> None:
		self.x, self.y = x, y
		await self.event('mouseWheel', deltaX=delta_x, deltaY=delta_y)
