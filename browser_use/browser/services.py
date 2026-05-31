from __future__ import annotations

import asyncio
import json
import mimetypes
import os
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from cdp_use.cdp.input.commands import DispatchKeyEventParameters
from cdp_use.cdp.target import TargetID
from pydantic import BaseModel, ConfigDict

from browser_use.actor.utils import get_key_info
from browser_use.browser.events import (
	ClickElementEvent,
	FileDownloadedEvent,
	TypeTextEvent,
)
from browser_use.browser.session import BrowserSession
from browser_use.browser.views import BrowserError, BrowserStateSummary, TabInfo


class BrowserService(BaseModel):
	"""Base class for explicit browser services."""

	model_config = ConfigDict(arbitrary_types_allowed=True)

	browser_session: BrowserSession


class BrowserStateService(BrowserService):
	"""Fresh browser state capture."""

	async def get_state(
		self,
		*,
		include_screenshot: bool = True,
		cached: bool = False,
		include_recent_events: bool = False,
	) -> BrowserStateSummary:
		return await self.browser_session.get_browser_state_summary(
			include_screenshot=include_screenshot,
			cached=cached,
			include_recent_events=include_recent_events,
		)

	async def get_text(self) -> str:
		return await self.browser_session.get_state_as_text()


class NavigationService(BrowserService):
	"""Page navigation operations."""

	async def navigate(self, url: str, *, new_tab: bool = False, verify_not_empty: bool = True) -> None:
		self._ensure_url_allowed(url)
		target_id = await self._target_for_navigation(new_tab=new_tab)
		await self.browser_session._navigate_and_wait(url, target_id)
		await self.browser_session._close_extension_options_pages()
		if verify_not_empty and not new_tab:
			await self._ensure_page_not_empty(url)

	async def go_back(self) -> str | None:
		cdp_session = await self.browser_session.get_or_create_cdp_session(target_id=None, focus=True)
		history = await cdp_session.cdp_client.send.Page.getNavigationHistory(session_id=cdp_session.session_id)
		current_index = history['currentIndex']
		entries = history['entries']
		if current_index <= 0:
			return None

		previous_entry = entries[current_index - 1]
		await cdp_session.cdp_client.send.Page.navigateToHistoryEntry(
			params={'entryId': previous_entry['id']},
			session_id=cdp_session.session_id,
		)
		await asyncio.sleep(0.5)
		return str(previous_entry.get('url', ''))

	async def current_url(self) -> str:
		return await self.browser_session.get_current_page_url()

	async def current_title(self) -> str:
		return await self.browser_session.get_current_page_title()

	async def _target_for_navigation(self, *, new_tab: bool) -> TargetID:
		if self.browser_session.agent_focus_target_id is None:
			cdp_session = await self.browser_session.get_or_create_cdp_session(target_id=None, focus=True)
			return cdp_session.target_id

		if not new_tab:
			return self.browser_session.agent_focus_target_id

		target_id = await self.browser_session._cdp_create_new_page('about:blank')
		await self.browser_session.get_or_create_cdp_session(target_id=target_id, focus=True)
		return target_id

	def _ensure_url_allowed(self, url: str) -> None:
		security_watchdog = getattr(self.browser_session, '_security_watchdog', None)
		if security_watchdog is not None and not security_watchdog._is_url_allowed(url):
			raise ValueError(f'Navigation to {url} blocked by security policy')

	async def _ensure_page_not_empty(self, url: str) -> None:
		state = await self.browser_session.get_browser_state_summary(include_screenshot=False)
		url_is_http = state.url.lower().startswith(('http://', 'https://'))
		if not url_is_http or not _page_appears_empty(state):
			return

		self.browser_session.logger.warning(f'⚠️ Empty DOM detected after navigation to {url}, waiting 3s and rechecking...')
		await asyncio.sleep(3.0)
		state = await self.browser_session.get_browser_state_summary(include_screenshot=False)
		if not state.url.lower().startswith(('http://', 'https://')) or not _page_appears_empty(state):
			return

		self.browser_session.logger.warning(f'⚠️ Still empty after 3s, attempting page reload for {url}...')
		target_id = self.browser_session.agent_focus_target_id
		if target_id is None:
			cdp_session = await self.browser_session.get_or_create_cdp_session(target_id=None, focus=True)
			target_id = cdp_session.target_id
		await self.browser_session._navigate_and_wait(url, target_id)
		await asyncio.sleep(5.0)
		state = await self.browser_session.get_browser_state_summary(include_screenshot=False)
		if state.url.lower().startswith(('http://', 'https://')) and state.dom_state._root is None:
			raise RuntimeError(
				f'Page loaded but returned empty content for {url}. '
				f'The page may require JavaScript that failed to render, use anti-bot measures, '
				f'or have a connection issue (e.g. tunnel/proxy error). Try a different URL or approach.'
			)


class TabService(BrowserService):
	"""Tab listing and focus operations."""

	async def list_tabs(self) -> list[TabInfo]:
		return await self.browser_session.get_tabs()

	async def switch(self, target_id: TargetID | None = None) -> TargetID:
		if target_id is None:
			if self.browser_session.agent_focus_target_id is None:
				cdp_session = await self.browser_session.get_or_create_cdp_session(target_id=None, focus=True)
				return cdp_session.target_id
			return self.browser_session.agent_focus_target_id

		await self.browser_session.cdp_client.send.Target.activateTarget(params={'targetId': target_id})
		await self.browser_session.get_or_create_cdp_session(target_id=target_id, focus=True)
		return target_id

	async def close(self, target_id: TargetID) -> None:
		await self.browser_session._cdp_close_page(target_id)


class ClickService(BrowserService):
	"""Element and coordinate clicking.

	The current implementation intentionally delegates to the existing action
	handlers. This gives the new runtime one explicit call site that can later
	move the click heuristics out of the watchdog.
	"""

	async def click_index(self, index: int, *, button: Literal['left', 'right', 'middle'] = 'left') -> dict[str, Any] | None:
		node = await self.browser_session.get_element_by_index(index)
		if node is None:
			raise ValueError(f'No element found for index {index}')
		default_action_watchdog = getattr(self.browser_session, '_default_action_watchdog', None)
		if default_action_watchdog is not None:
			return await default_action_watchdog.on_ClickElementEvent(ClickElementEvent(node=node, button=button))

		event = self.browser_session.event_bus.dispatch(ClickElementEvent(node=node, button=button))
		await event
		return await event.event_result(raise_if_any=True, raise_if_none=False)

	async def click_coordinates(
		self,
		coordinate_x: int,
		coordinate_y: int,
		*,
		button: Literal['left', 'right', 'middle'] = 'left',
		force: bool = False,
	) -> dict[str, Any] | None:
		if not self.browser_session.agent_focus_target_id:
			raise BrowserError('Cannot click coordinates because no browser target is focused.')

		if not force:
			element_node = await self.browser_session.get_dom_element_at_coordinates(coordinate_x, coordinate_y)
			if element_node is not None:
				if self.browser_session.is_file_input(element_node):
					return {'validation_error': 'Cannot click a file input by coordinates. Use upload_file instead.'}
				if element_node.tag_name.lower() == 'select':
					return {'validation_error': 'Cannot click a <select> by coordinates. Use dropdown tools instead.'}

		cdp_session = await self.browser_session.get_or_create_cdp_session(target_id=None, focus=True)
		await cdp_session.cdp_client.send.Input.dispatchMouseEvent(
			params={'type': 'mouseMoved', 'x': coordinate_x, 'y': coordinate_y}, session_id=cdp_session.session_id
		)
		await asyncio.sleep(0.05)
		await cdp_session.cdp_client.send.Input.dispatchMouseEvent(
			params={
				'type': 'mousePressed',
				'x': coordinate_x,
				'y': coordinate_y,
				'button': button,
				'clickCount': 1,
			},
			session_id=cdp_session.session_id,
		)
		await asyncio.sleep(0.05)
		await cdp_session.cdp_client.send.Input.dispatchMouseEvent(
			params={
				'type': 'mouseReleased',
				'x': coordinate_x,
				'y': coordinate_y,
				'button': button,
				'clickCount': 1,
			},
			session_id=cdp_session.session_id,
		)
		return {'click_x': coordinate_x, 'click_y': coordinate_y}


class TypeService(BrowserService):
	"""Text entry operations."""

	async def type_index(
		self,
		index: int,
		text: str,
		*,
		clear: bool = True,
		is_sensitive: bool = False,
		sensitive_key_name: str | None = None,
	) -> dict[str, Any] | None:
		node = await self.browser_session.get_element_by_index(index)
		if node is None:
			raise ValueError(f'No element found for index {index}')
		default_action_watchdog = getattr(self.browser_session, '_default_action_watchdog', None)
		if default_action_watchdog is not None:
			return await default_action_watchdog.on_TypeTextEvent(
				TypeTextEvent(
					node=node,
					text=text,
					clear=clear,
					is_sensitive=is_sensitive,
					sensitive_key_name=sensitive_key_name,
				)
			)

		event = self.browser_session.event_bus.dispatch(
			TypeTextEvent(
				node=node,
				text=text,
				clear=clear,
				is_sensitive=is_sensitive,
				sensitive_key_name=sensitive_key_name,
			)
		)
		await event
		return await event.event_result(raise_if_any=True, raise_if_none=False)


class ScrollService(BrowserService):
	"""Scrolling operations."""

	async def viewport_height(self, *, fallback: int = 1000) -> int:
		try:
			cdp_session = await self.browser_session.get_or_create_cdp_session(target_id=None, focus=True)
			metrics = await cdp_session.cdp_client.send.Page.getLayoutMetrics(session_id=cdp_session.session_id)
			css_viewport = metrics.get('cssVisualViewport', {})
			css_layout_viewport = metrics.get('cssLayoutViewport', {})
			return int(css_viewport.get('clientHeight') or css_layout_viewport.get('clientHeight', fallback))
		except Exception as exc:
			self.browser_session.logger.debug(f'Failed to get viewport height, using fallback {fallback}px: {exc}')
			return fallback

	async def scroll_pages(self, pages: float, *, direction: Literal['up', 'down'] = 'down') -> dict[str, Any]:
		viewport_height = await self.viewport_height()
		completed_scrolls = 0.0
		total_pixels = 0

		if pages >= 1.0:
			num_full_pages = int(pages)
			remaining_fraction = pages - num_full_pages
			for _ in range(num_full_pages):
				await self.scroll_page(viewport_height, direction=direction)
				completed_scrolls += 1
				total_pixels += viewport_height
				await asyncio.sleep(0.15)
			if remaining_fraction > 0:
				pixels = int(remaining_fraction * viewport_height)
				await self.scroll_page(pixels, direction=direction)
				completed_scrolls += remaining_fraction
				total_pixels += pixels
		else:
			pixels = int(pages * viewport_height)
			await self.scroll_page(pixels, direction=direction)
			completed_scrolls = pages
			total_pixels = pixels

		return {
			'direction': direction,
			'pages': pages,
			'completed_pages': completed_scrolls,
			'viewport_height': viewport_height,
			'pixels': total_pixels,
		}

	async def scroll_page(self, amount: int, *, direction: Literal['up', 'down', 'left', 'right'] = 'down') -> None:
		delta_x = 0
		delta_y = 0
		if direction == 'down':
			delta_y = amount
		elif direction == 'up':
			delta_y = -amount
		elif direction == 'right':
			delta_x = amount
		elif direction == 'left':
			delta_x = -amount

		cdp_session = await self.browser_session.get_or_create_cdp_session(target_id=None, focus=True)
		await cdp_session.cdp_client.send.Runtime.evaluate(
			params={'expression': f'window.scrollBy({delta_x}, {delta_y})', 'returnByValue': True},
			session_id=cdp_session.session_id,
		)


class KeyboardService(BrowserService):
	"""Keyboard input operations."""

	async def send_keys(self, keys: str) -> None:
		cdp_session = await self.browser_session.get_or_create_cdp_session(focus=True)
		normalized_keys = self._normalize_keys(keys)

		if '+' in normalized_keys:
			parts = normalized_keys.split('+')
			modifiers = parts[:-1]
			main_key = parts[-1]

			modifier_value = 0
			modifier_map = {'Alt': 1, 'Control': 2, 'Meta': 4, 'Shift': 8}
			for mod in modifiers:
				modifier_value |= modifier_map.get(mod, 0)

			for mod in modifiers:
				await self._dispatch_key_event(cdp_session, 'keyDown', mod)

			await self._dispatch_key_event(cdp_session, 'keyDown', main_key, modifier_value)
			await self._dispatch_key_event(cdp_session, 'keyUp', main_key, modifier_value)

			for mod in reversed(modifiers):
				await self._dispatch_key_event(cdp_session, 'keyUp', mod)
		elif normalized_keys in self._special_keys():
			await self._dispatch_key_event(cdp_session, 'keyDown', normalized_keys)
			if normalized_keys == 'Enter':
				await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
					params={'type': 'char', 'text': '\r', 'key': 'Enter'},
					session_id=cdp_session.session_id,
				)
			await self._dispatch_key_event(cdp_session, 'keyUp', normalized_keys)
		else:
			for char in normalized_keys:
				if char in ('\n', '\r'):
					await self._dispatch_enter_text(cdp_session)
					continue

				modifiers, vk_code, base_key = self._get_char_modifiers_and_vk(char)
				key_code = self._get_key_code_for_char(base_key)

				await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
					params={
						'type': 'keyDown',
						'key': base_key,
						'code': key_code,
						'modifiers': modifiers,
						'windowsVirtualKeyCode': vk_code,
					},
					session_id=cdp_session.session_id,
				)
				await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
					params={'type': 'char', 'text': char, 'key': char},
					session_id=cdp_session.session_id,
				)
				await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
					params={
						'type': 'keyUp',
						'key': base_key,
						'code': key_code,
						'modifiers': modifiers,
						'windowsVirtualKeyCode': vk_code,
					},
					session_id=cdp_session.session_id,
				)
				await asyncio.sleep(0.010)

		self.browser_session.logger.info(f'⌨️ Sent keys: {keys}')
		if 'enter' in keys.lower() or 'return' in keys.lower():
			await asyncio.sleep(0.1)

	def _normalize_keys(self, keys: str) -> str:
		key_aliases = {
			'ctrl': 'Control',
			'control': 'Control',
			'alt': 'Alt',
			'option': 'Alt',
			'meta': 'Meta',
			'cmd': 'Meta',
			'command': 'Meta',
			'shift': 'Shift',
			'enter': 'Enter',
			'return': 'Enter',
			'tab': 'Tab',
			'delete': 'Delete',
			'backspace': 'Backspace',
			'escape': 'Escape',
			'esc': 'Escape',
			'space': ' ',
			'up': 'ArrowUp',
			'down': 'ArrowDown',
			'left': 'ArrowLeft',
			'right': 'ArrowRight',
			'pageup': 'PageUp',
			'pagedown': 'PageDown',
			'home': 'Home',
			'end': 'End',
		}
		if '+' in keys:
			return '+'.join(key_aliases.get(part.strip().lower(), part) for part in keys.split('+'))
		return key_aliases.get(keys.strip().lower(), keys)

	def _special_keys(self) -> set[str]:
		return {
			'Enter',
			'Tab',
			'Delete',
			'Backspace',
			'Escape',
			'ArrowUp',
			'ArrowDown',
			'ArrowLeft',
			'ArrowRight',
			'PageUp',
			'PageDown',
			'Home',
			'End',
			'Control',
			'Alt',
			'Meta',
			'Shift',
			'F1',
			'F2',
			'F3',
			'F4',
			'F5',
			'F6',
			'F7',
			'F8',
			'F9',
			'F10',
			'F11',
			'F12',
		}

	async def _dispatch_key_event(self, cdp_session, event_type: str, key: str, modifiers: int = 0) -> None:
		code, vk_code = get_key_info(key)
		params: DispatchKeyEventParameters = {
			'type': event_type,
			'key': key,
			'code': code,
		}
		if modifiers:
			params['modifiers'] = modifiers
		if vk_code is not None:
			params['windowsVirtualKeyCode'] = vk_code
		await cdp_session.cdp_client.send.Input.dispatchKeyEvent(params=params, session_id=cdp_session.session_id)

	async def _dispatch_enter_text(self, cdp_session) -> None:
		for params in (
			{'type': 'rawKeyDown', 'windowsVirtualKeyCode': 13, 'unmodifiedText': '\r', 'text': '\r'},
			{'type': 'char', 'windowsVirtualKeyCode': 13, 'unmodifiedText': '\r', 'text': '\r'},
			{'type': 'keyUp', 'windowsVirtualKeyCode': 13, 'unmodifiedText': '\r', 'text': '\r'},
		):
			await cdp_session.cdp_client.send.Input.dispatchKeyEvent(params=params, session_id=cdp_session.session_id)

	def _get_char_modifiers_and_vk(self, char: str) -> tuple[int, int, str]:
		shift_chars = {
			'!': ('1', 49),
			'@': ('2', 50),
			'#': ('3', 51),
			'$': ('4', 52),
			'%': ('5', 53),
			'^': ('6', 54),
			'&': ('7', 55),
			'*': ('8', 56),
			'(': ('9', 57),
			')': ('0', 48),
			'_': ('-', 189),
			'+': ('=', 187),
			'{': ('[', 219),
			'}': (']', 221),
			'|': ('\\', 220),
			':': (';', 186),
			'"': ("'", 222),
			'<': (',', 188),
			'>': ('.', 190),
			'?': ('/', 191),
			'~': ('`', 192),
		}
		if char in shift_chars:
			base_key, vk_code = shift_chars[char]
			return (8, vk_code, base_key)

		def _vk_from(c: str) -> int:
			up = c.upper()
			return ord(up) if len(up) == 1 else ord(c)

		if char.isupper():
			return (8, ord(char), char.lower()[:1] or char)
		if char.islower():
			return (0, _vk_from(char), char)
		if char.isdigit():
			return (0, ord(char), char)

		no_shift_chars = {
			' ': 32,
			'-': 189,
			'=': 187,
			'[': 219,
			']': 221,
			'\\': 220,
			';': 186,
			"'": 222,
			',': 188,
			'.': 190,
			'/': 191,
			'`': 192,
		}
		if char in no_shift_chars:
			return (0, no_shift_chars[char], char)
		return (0, _vk_from(char) if char.isalpha() else ord(char), char)

	def _get_key_code_for_char(self, char: str) -> str:
		key_codes = {
			' ': 'Space',
			'.': 'Period',
			',': 'Comma',
			'-': 'Minus',
			'_': 'Minus',
			'@': 'Digit2',
			'!': 'Digit1',
			'?': 'Slash',
			':': 'Semicolon',
			';': 'Semicolon',
			'(': 'Digit9',
			')': 'Digit0',
			'[': 'BracketLeft',
			']': 'BracketRight',
			'{': 'BracketLeft',
			'}': 'BracketRight',
			'/': 'Slash',
			'\\': 'Backslash',
			'=': 'Equal',
			'+': 'Equal',
			'*': 'Digit8',
			'&': 'Digit7',
			'%': 'Digit5',
			'$': 'Digit4',
			'#': 'Digit3',
			'^': 'Digit6',
			'~': 'Backquote',
			'`': 'Backquote',
			"'": 'Quote',
			'"': 'Quote',
		}
		if char.isdigit():
			return f'Digit{char}'
		if char.isalpha():
			return f'Key{char.upper()}'
		if char in key_codes:
			return key_codes[char]
		return f'Key{char.upper()}'


def _page_appears_empty(state: BrowserStateSummary) -> bool:
	return state.dom_state._root is None or not state.dom_state.llm_representation().strip()


def _download_filename(url: str, *, content_type: str | None, suggested_filename: str | None) -> str:
	if suggested_filename:
		return _sanitize_download_filename(suggested_filename)

	parsed = urlparse(url)
	filename = _sanitize_download_filename(os.path.basename(parsed.path))
	if filename != 'download' and '.' in filename:
		return filename
	if content_type and 'pdf' in content_type:
		return 'document.pdf'
	return filename


def _sanitize_download_filename(name: str | None) -> str:
	if not name:
		return 'download'
	name = name.replace('\x00', '')
	name = name.replace('\\', '/')
	name = os.path.basename(name.rsplit('/', 1)[-1])
	if name in ('', '.', '..'):
		return 'download'
	return name


def _unique_download_destination(downloads_dir: Path, filename: str) -> Path:
	destination = downloads_dir / filename
	if not destination.exists():
		return destination

	base = destination.stem
	ext = destination.suffix
	counter = 1
	while True:
		candidate = downloads_dir / f'{base} ({counter}){ext}'
		if not candidate.exists():
			return candidate
		counter += 1


def _is_path_contained(path: str | Path, directory: str | Path) -> bool:
	real_path = os.path.realpath(str(path))
	real_dir = os.path.realpath(str(directory))
	return real_path == real_dir or real_path.startswith(real_dir + os.sep)


class DownloadService(BrowserService):
	"""Downloaded file access."""

	def list_downloads(self) -> list[str]:
		return self.browser_session.downloaded_files

	async def download_url(
		self,
		url: str,
		*,
		target_id: TargetID | None = None,
		content_type: str | None = None,
		suggested_filename: str | None = None,
		timeout_s: float = 15.0,
	) -> dict[str, Any] | None:
		"""Download a URL through the browser context and track it without the event bus."""

		downloads_path = self.browser_session.browser_profile.downloads_path
		if not downloads_path:
			self.browser_session.logger.warning('[DownloadService] No downloads path configured')
			return None

		downloads_dir = Path(downloads_path).expanduser().resolve()
		downloads_dir.mkdir(parents=True, exist_ok=True)
		filename = _download_filename(url, content_type=content_type, suggested_filename=suggested_filename)
		destination = _unique_download_destination(downloads_dir, filename)
		if not _is_path_contained(destination, downloads_dir):
			self.browser_session.logger.error(
				f'[DownloadService] Refusing to write download outside downloads_dir: {destination}'
			)
			return None

		if target_id is None:
			if self.browser_session.agent_focus_target_id is None:
				cdp_session = await self.browser_session.get_or_create_cdp_session(target_id=None, focus=True)
			else:
				cdp_session = await self.browser_session.get_or_create_cdp_session(
					target_id=self.browser_session.agent_focus_target_id, focus=False
				)
		else:
			cdp_session = await self.browser_session.get_or_create_cdp_session(target_id=target_id, focus=False)

		result = await asyncio.wait_for(
			cdp_session.cdp_client.send.Runtime.evaluate(
				params={
					'expression': f"""
(async () => {{
	const response = await fetch({json.dumps(url)}, {{ cache: 'force-cache' }});
	if (!response.ok) {{
		throw new Error(`HTTP error! status: ${{response.status}}`);
	}}
	const blob = await response.blob();
	const arrayBuffer = await blob.arrayBuffer();
	const uint8Array = new Uint8Array(arrayBuffer);
	return {{ data: Array.from(uint8Array), responseSize: uint8Array.length }};
}})()
""",
					'awaitPromise': True,
					'returnByValue': True,
				},
				session_id=cdp_session.session_id,
			),
			timeout=timeout_s,
		)
		download_result = result.get('result', {}).get('value') or {}
		data = download_result.get('data') or []
		if not data:
			self.browser_session.logger.warning(f'[DownloadService] No data received when downloading from {url}')
			return None

		payload = bytes(data)
		await asyncio.to_thread(destination.write_bytes, payload)
		file_size = destination.stat().st_size
		resolved_content_type = content_type or mimetypes.guess_type(destination.name)[0]
		file_ext = destination.suffix.lower().lstrip('.') or None
		event = FileDownloadedEvent(
			url=url,
			path=str(destination),
			file_name=destination.name,
			file_size=file_size,
			file_type=file_ext,
			mime_type=resolved_content_type,
			auto_download=True,
		)
		await self.browser_session.on_FileDownloadedEvent(event)
		return {
			'url': url,
			'path': str(destination),
			'file_name': destination.name,
			'file_size': file_size,
			'file_type': file_ext,
			'mime_type': resolved_content_type,
		}


class DialogService(BrowserService):
	"""Dialog state captured by popup handling."""

	def closed_messages(self) -> list[str]:
		return list(self.browser_session._closed_popup_messages)

	def clear_closed_messages(self) -> None:
		self.browser_session._closed_popup_messages.clear()


class NetworkService(BrowserService):
	"""Network configuration helpers."""

	async def set_extra_headers(self, headers: dict[str, str], *, target_id: TargetID | None = None) -> None:
		await self.browser_session.set_extra_headers(headers, target_id=target_id)


class StorageStateService(BrowserService):
	"""Storage state import/export helpers."""

	async def export(self, output_path: str | None = None) -> dict[str, Any]:
		return await self.browser_session.export_storage_state(output_path=output_path)


class LifecycleService(BrowserService):
	"""Browser lifecycle operations."""

	async def start(self) -> None:
		await self.browser_session.start()

	async def stop(self) -> None:
		await self.browser_session.stop()

	async def kill(self) -> None:
		await self.browser_session.kill()


class ActionService(BaseModel):
	"""Grouped browser action services."""

	model_config = ConfigDict(arbitrary_types_allowed=True)

	click: ClickService
	type: TypeService
	scroll: ScrollService
	keyboard: KeyboardService
	navigation: NavigationService
	tabs: TabService

	@classmethod
	def from_session(cls, browser_session: BrowserSession) -> ActionService:
		return cls(
			click=ClickService(browser_session=browser_session),
			type=TypeService(browser_session=browser_session),
			scroll=ScrollService(browser_session=browser_session),
			keyboard=KeyboardService(browser_session=browser_session),
			navigation=NavigationService(browser_session=browser_session),
			tabs=TabService(browser_session=browser_session),
		)


class BrowserServiceBundle(BaseModel):
	"""Explicit service bundle for browser runtime operations."""

	model_config = ConfigDict(arbitrary_types_allowed=True)

	state: BrowserStateService
	actions: ActionService
	navigation: NavigationService
	tabs: TabService
	downloads: DownloadService
	dialogs: DialogService
	network: NetworkService
	storage: StorageStateService
	lifecycle: LifecycleService

	@classmethod
	def from_session(cls, browser_session: BrowserSession) -> BrowserServiceBundle:
		navigation = NavigationService(browser_session=browser_session)
		tabs = TabService(browser_session=browser_session)
		return cls(
			state=BrowserStateService(browser_session=browser_session),
			actions=ActionService.from_session(browser_session),
			navigation=navigation,
			tabs=tabs,
			downloads=DownloadService(browser_session=browser_session),
			dialogs=DialogService(browser_session=browser_session),
			network=NetworkService(browser_session=browser_session),
			storage=StorageStateService(browser_session=browser_session),
			lifecycle=LifecycleService(browser_session=browser_session),
		)
