"""Utility functions for actor operations."""


class Utils:
	"""Utility functions for actor operations."""

	@staticmethod
	def get_key_info(key: str) -> tuple[str, int | None]:
		"""Get the code and windowsVirtualKeyCode for a key.

		Args:
			key: Key name (e.g., 'Enter', 'ArrowUp', 'a', 'A')

		Returns:
			Tuple of (code, windowsVirtualKeyCode)

		Reference: Windows Virtual Key Codes
		https://docs.microsoft.com/en-us/windows/win32/inputdev/virtual-key-codes
		"""
		# Complete mapping of key names to (code, virtualKeyCode)
		# Based on standard Windows Virtual Key Codes
		key_map = {
			# Navigation keys
			'Backspace': ('Backspace', 8),
			'Tab': ('Tab', 9),
			'Enter': ('Enter', 13),
			'Escape': ('Escape', 27),
			'Space': ('Space', 32),
			' ': ('Space', 32),
			'PageUp': ('PageUp', 33),
			'PageDown': ('PageDown', 34),
			'End': ('End', 35),
			'Home': ('Home', 36),
			'ArrowLeft': ('ArrowLeft', 37),
			'ArrowUp': ('ArrowUp', 38),
			'ArrowRight': ('ArrowRight', 39),
			'ArrowDown': ('ArrowDown', 40),
			'Insert': ('Insert', 45),
			'Delete': ('Delete', 46),
			# Modifier keys
			'Shift': ('ShiftLeft', 16),
			'ShiftLeft': ('ShiftLeft', 16),
			'ShiftRight': ('ShiftRight', 16),
			'Control': ('ControlLeft', 17),
			'ControlLeft': ('ControlLeft', 17),
			'ControlRight': ('ControlRight', 17),
			'Alt': ('AltLeft', 18),
			'AltLeft': ('AltLeft', 18),
			'AltRight': ('AltRight', 18),
			'Meta': ('MetaLeft', 91),
			'MetaLeft': ('MetaLeft', 91),
			'MetaRight': ('MetaRight', 92),
			# Function keys F1-F24
			'F1': ('F1', 112),
			'F2': ('F2', 113),
			'F3': ('F3', 114),
			'F4': ('F4', 115),
			'F5': ('F5', 116),
			'F6': ('F6', 117),
			'F7': ('F7', 118),
			'F8': ('F8', 119),
			'F9': ('F9', 120),
			'F10': ('F10', 121),
			'F11': ('F11', 122),
			'F12': ('F12', 123),
			'F13': ('F13', 124),
			'F14': ('F14', 125),
			'F15': ('F15', 126),
			'F16': ('F16', 127),
			'F17': ('F17', 128),
			'F18': ('F18', 129),
			'F19': ('F19', 130),
			'F20': ('F20', 131),
			'F21': ('F21', 132),
			'F22': ('F22', 133),
			'F23': ('F23', 134),
			'F24': ('F24', 135),
			# Numpad keys
			'NumLock': ('NumLock', 144),
			'Numpad0': ('Numpad0', 96),
			'Numpad1': ('Numpad1', 97),
			'Numpad2': ('Numpad2', 98),
			'Numpad3': ('Numpad3', 99),
			'Numpad4': ('Numpad4', 100),
			'Numpad5': ('Numpad5', 101),
			'Numpad6': ('Numpad6', 102),
			'Numpad7': ('Numpad7', 103),
			'Numpad8': ('Numpad8', 104),
			'Numpad9': ('Numpad9', 105),
			'NumpadMultiply': ('NumpadMultiply', 106),
			'NumpadAdd': ('NumpadAdd', 107),
			'NumpadSubtract': ('NumpadSubtract', 109),
			'NumpadDecimal': ('NumpadDecimal', 110),
			'NumpadDivide': ('NumpadDivide', 111),
			# Lock keys
			'CapsLock': ('CapsLock', 20),
			'ScrollLock': ('ScrollLock', 145),
			# OEM/Punctuation keys (US keyboard layout)
			'Semicolon': ('Semicolon', 186),
			';': ('Semicolon', 186),
			'Equal': ('Equal', 187),
			'=': ('Equal', 187),
			'Comma': ('Comma', 188),
			',': ('Comma', 188),
			'Minus': ('Minus', 189),
			'-': ('Minus', 189),
			'Period': ('Period', 190),
			'.': ('Period', 190),
			'Slash': ('Slash', 191),
			'/': ('Slash', 191),
			'Backquote': ('Backquote', 192),
			'`': ('Backquote', 192),
			'BracketLeft': ('BracketLeft', 219),
			'[': ('BracketLeft', 219),
			'Backslash': ('Backslash', 220),
			'\\': ('Backslash', 220),
			'BracketRight': ('BracketRight', 221),
			']': ('BracketRight', 221),
			'Quote': ('Quote', 222),
			"'": ('Quote', 222),
			# Media/Browser keys
			'AudioVolumeMute': ('AudioVolumeMute', 173),
			'AudioVolumeDown': ('AudioVolumeDown', 174),
			'AudioVolumeUp': ('AudioVolumeUp', 175),
			'MediaTrackNext': ('MediaTrackNext', 176),
			'MediaTrackPrevious': ('MediaTrackPrevious', 177),
			'MediaStop': ('MediaStop', 178),
			'MediaPlayPause': ('MediaPlayPause', 179),
			'BrowserBack': ('BrowserBack', 166),
			'BrowserForward': ('BrowserForward', 167),
			'BrowserRefresh': ('BrowserRefresh', 168),
			'BrowserStop': ('BrowserStop', 169),
			'BrowserSearch': ('BrowserSearch', 170),
			'BrowserFavorites': ('BrowserFavorites', 171),
			'BrowserHome': ('BrowserHome', 172),
			# Additional common keys
			'Clear': ('Clear', 12),
			'Pause': ('Pause', 19),
			'Select': ('Select', 41),
			'Print': ('Print', 42),
			'Execute': ('Execute', 43),
			'PrintScreen': ('PrintScreen', 44),
			'Help': ('Help', 47),
			'ContextMenu': ('ContextMenu', 93),
		}

		if key in key_map:
			return key_map[key]

		# Handle alphanumeric keys dynamically
		if len(key) == 1:
			if key.isalpha():
				# Letter keys: A-Z have VK codes 65-90
				return (f'Key{key.upper()}', ord(key.upper()))
			elif key.isdigit():
				# Digit keys: 0-9 have VK codes 48-57 (same as ASCII)
				return (f'Digit{key}', ord(key))

		# Fallback: use the key name as code, no virtual key code
		return (key, None)


# Backward compatibility: provide standalone function
def get_key_info(key: str) -> tuple[str, int | None]:
	"""Get the code and windowsVirtualKeyCode for a key.

	Args:
		key: Key name (e.g., 'Enter', 'ArrowUp', 'a', 'A')

	Returns:
		Tuple of (code, windowsVirtualKeyCode)

	Reference: Windows Virtual Key Codes
	https://docs.microsoft.com/en-us/windows/win32/inputdev/virtual-key-codes
	"""
	return Utils.get_key_info(key)
