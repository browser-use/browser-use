"""Install configuration - tracks which browser modes are available.

This module manages the installation configuration that determines which browser
modes (chromium, real, remote) are available based on how browser-use was installed.

Config file: ~/.browser-use/install-config.json

When no config file exists (e.g., pip install users), all modes are available by default.
"""

import json
from pathlib import Path
from typing import Literal

CONFIG_PATH = Path.home() / '.browser-use' / 'install-config.json'

ModeType = Literal['chromium', 'real', 'remote']

# Local modes (both require Chromium to be installed)
LOCAL_MODES: set[str] = {'chromium', 'real'}


def get_config() -> dict:
	"""Read install config. Returns default if not found.

	Default config enables all modes (for pip install users).
	"""
	if not CONFIG_PATH.exists():
		return {
			'installed_modes': ['chromium', 'real', 'remote'],
			'default_mode': 'chromium',
		}

	try:
		return json.loads(CONFIG_PATH.read_text())
	except (json.JSONDecodeError, OSError):
		# Config file corrupt, return default
		return {
			'installed_modes': ['chromium', 'real', 'remote'],
			'default_mode': 'chromium',
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
		mode: The browser mode to check ('chromium', 'real', or 'remote')

	Returns:
		True if the mode is available, False otherwise
	"""
	config = get_config()
	installed = config.get('installed_modes', [])

	# Map 'real' to same category as 'chromium' (both are local)
	# If either local mode is installed, both are available
	if mode in LOCAL_MODES:
		return bool(LOCAL_MODES & set(installed))

	return mode in installed


def get_default_mode() -> str:
	"""Get the default browser mode based on installation config."""
	return get_config().get('default_mode', 'chromium')


def get_available_modes() -> list[str]:
	"""Get list of available browser modes."""
	return get_config().get('installed_modes', ['chromium', 'real', 'remote'])


def get_mode_unavailable_error(mode: str) -> str:
	"""Generate a helpful error message when a mode is not available.

	Args:
		mode: The unavailable mode that was requested

	Returns:
		A formatted error message with instructions for reinstalling
	"""
	available = get_available_modes()

	if mode in LOCAL_MODES:
		install_flag = '--full'
		mode_desc = 'Local browser mode'
	else:
		install_flag = '--full'
		mode_desc = 'Remote browser mode'

	return (
		f"Error: {mode_desc} '{mode}' not installed.\n"
		f'Available modes: {", ".join(available)}\n\n'
		f'To install all modes, reinstall with:\n'
		f'  curl -fsSL https://browser-use.com/cli/install.sh | bash -s -- {install_flag}'
	)
