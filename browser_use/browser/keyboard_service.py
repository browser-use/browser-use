from __future__ import annotations

import asyncio

from cdp_use.cdp.input.commands import DispatchKeyEventParameters

from browser_use.actor.utils import get_key_info
from browser_use.browser.service_base import BrowserService


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
