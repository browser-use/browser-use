"""Install configuration - tracks which browser modes are available.

This module manages the installation configuration that determines which browser
modes (chromium, real, safari, remote) are available based on how browser-use was installed.

Config file: ~/.browser-use/install-config.json

When no config file exists (e.g., pip install users), all modes are available by default.
"""

import json
import platform
import subprocess
from pathlib import Path
from typing import Literal

CONFIG_PATH = Path.home() / '.browser-use' / 'install-config.json'
SAFARI_APP_PATH = Path('/Applications/Safari.app')
MINIMUM_SAFARI_VERSION = '26.3.1'
MINIMUM_MACOS_VERSION = '26.0'

ModeType = Literal['chromium', 'real', 'safari', 'remote']

# Chromium-family local modes share the same install requirement.
CHROMIUM_LOCAL_MODES: set[str] = {'chromium', 'real'}
SAFARI_LOCAL_MODES: set[str] = {'safari'}
LOCAL_MODES: set[str] = CHROMIUM_LOCAL_MODES | SAFARI_LOCAL_MODES

DEFAULT_BROWSER_MODE = 'chromium'


def _read_safari_version() -> str:
	"""Read Safari version without triggering GUI automation side effects."""
	try:
		result = subprocess.run(
			['defaults', 'read', f'{SAFARI_APP_PATH}/Contents/Info', 'CFBundleShortVersionString'],
			check=True,
			capture_output=True,
			text=True,
			timeout=2,
		)
		return result.stdout.strip()
	except Exception:
		return '0.0.0'


def _read_macos_version() -> str:
	"""Read the current macOS version."""
	try:
		result = subprocess.run(['sw_vers', '-productVersion'], check=True, capture_output=True, text=True, timeout=2)
		return result.stdout.strip()
	except Exception:
		return '0.0'


def _version_at_least(version: str, minimum: str) -> bool:
	"""Compare dotted version strings."""

	def parse(raw: str) -> tuple[int, ...]:
		return tuple(int(piece) for piece in raw.split('.') if piece.isdigit())

	current = parse(version)
	required = parse(minimum)
	width = max(len(current), len(required))
	return current + (0,) * (width - len(current)) >= required + (0,) * (width - len(required))


def _is_safari_runtime_supported() -> bool:
	"""Return True only when the host can actually start the Safari backend."""
	if platform.system() != 'Darwin' or not SAFARI_APP_PATH.exists():
		return False
	return _version_at_least(_read_macos_version(), MINIMUM_MACOS_VERSION) and _version_at_least(
		_read_safari_version(), MINIMUM_SAFARI_VERSION
	)


def _default_installed_modes() -> list[str]:
	"""Return platform-aware default browser modes."""
	modes = ['chromium', 'real', 'remote']
	if _is_safari_runtime_supported():
		modes.append('safari')
	return modes


def get_config() -> dict:
	"""Read install config. Returns default if not found.

	Default config enables all modes (for pip install users).
	"""
	if not CONFIG_PATH.exists():
		return {
			'installed_modes': _default_installed_modes(),
			'default_mode': DEFAULT_BROWSER_MODE,
		}

	try:
		return json.loads(CONFIG_PATH.read_text())
	except (json.JSONDecodeError, OSError):
		# Config file corrupt, return default
		return {
			'installed_modes': _default_installed_modes(),
			'default_mode': DEFAULT_BROWSER_MODE,
		}


def save_config(installed_modes: list[str], default_mode: str) -> None:
	"""Save install config."""
	CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
	CONFIG_PATH.write_text(
		json.dumps(
			{
				'installed_modes': installed_modes,
				'default_mode': default_mode,
			},
			indent=2,
		)
	)


def is_mode_available(mode: str) -> bool:
	"""Check if a browser mode is available based on installation config.

	Args:
		mode: The browser mode to check ('chromium', 'real', 'safari', or 'remote')

	Returns:
		True if the mode is available, False otherwise
	"""
	config = get_config()
	installed = config.get('installed_modes', [])

	# Map 'real' to same category as 'chromium' (both are Chromium-family local modes)
	if mode in CHROMIUM_LOCAL_MODES:
		return bool(CHROMIUM_LOCAL_MODES & set(installed))

	if mode in SAFARI_LOCAL_MODES:
		return _is_safari_runtime_supported() and bool(SAFARI_LOCAL_MODES & set(installed))

	return mode in installed


def get_default_mode() -> str:
	"""Get the default browser mode based on installation config."""
	default_mode = get_config().get('default_mode', DEFAULT_BROWSER_MODE)
	if is_mode_available(default_mode):
		return default_mode

	for mode in get_available_modes():
		return mode

	return DEFAULT_BROWSER_MODE


def get_available_modes() -> list[str]:
	"""Get list of available browser modes."""
	return [mode for mode in get_config().get('installed_modes', _default_installed_modes()) if is_mode_available(mode)]


def get_mode_unavailable_error(mode: str) -> str:
	"""Generate a helpful error message when a mode is not available.

	Args:
		mode: The unavailable mode that was requested

	Returns:
		A formatted error message with instructions for reinstalling
	"""
	available = get_available_modes()

	if mode in CHROMIUM_LOCAL_MODES:
		install_flag = '--full'
		mode_desc = 'Local Chromium browser mode'
	elif mode in SAFARI_LOCAL_MODES:
		install_flag = '--full'
		mode_desc = 'Safari real-profile mode'
	else:
		install_flag = '--full'
		mode_desc = 'Remote browser mode'

	extra_help = ''
	if mode == 'safari':
		extra_help = '\nSafari mode also requires Safari 26.3.1+ and macOS 26+.'

	return (
		f"Error: {mode_desc} '{mode}' not installed.\n"
		f'Available modes: {", ".join(available)}\n\n'
		f'To install all modes, reinstall with:\n'
		f'  curl -fsSL https://browser-use.com/cli/install.sh | bash -s -- {install_flag}'
		f'{extra_help}'
	)
