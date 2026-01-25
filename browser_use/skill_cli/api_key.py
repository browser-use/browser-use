"""API key management for browser-use CLI."""

import json
import os
import sys
from pathlib import Path


class APIKeyRequired(Exception):
	"""Raised when API key is required but not provided."""

	pass


def get_config_path() -> Path:
	"""Get browser-use config file path."""
	if sys.platform == 'win32':
		base = Path(os.environ.get('APPDATA', Path.home()))
	else:
		base = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))
	return base / 'browser-use' / 'config.json'


def require_api_key(feature: str = 'this feature') -> str:
	"""Get API key or raise helpful error.

	Checks in order:
	1. BROWSER_USE_API_KEY environment variable
	2. Config file (~/.config/browser-use/config.json)
	3. Interactive prompt (if TTY)
	4. Raises APIKeyRequired with helpful message
	"""
	# 1. Check environment
	key = os.environ.get('BROWSER_USE_API_KEY')
	if key:
		return key

	# 2. Check config file
	config_path = get_config_path()
	if config_path.exists():
		try:
			config = json.loads(config_path.read_text())
			if key := config.get('api_key'):
				return key
		except Exception:
			pass

	# 3. Interactive prompt (if TTY)
	if sys.stdin.isatty() and sys.stdout.isatty():
		return prompt_for_api_key(feature)

	# 4. Error with helpful message
	raise APIKeyRequired(
		f"""
╭─────────────────────────────────────────────────────────────╮
│  🔑 Browser-Use API Key Required                            │
│                                                             │
│  {feature} requires an API key.                             │
│                                                             │
│  Get yours at: https://browser-use.com/new-api-key            │
│                                                             │
│  Then set it via:                                           │
│    export BROWSER_USE_API_KEY=your_key_here                 │
│                                                             │
│  Or add to {config_path}:               │
│    {{"api_key": "your_key_here"}}                           │
╰─────────────────────────────────────────────────────────────╯
"""
	)


def prompt_for_api_key(feature: str) -> str:
	"""Interactive prompt for API key."""
	print(
		f"""
╭─────────────────────────────────────────────────────────────╮
│  🔑 Browser-Use API Key Required                            │
│                                                             │
│  {feature} requires an API key.                             │
│  Get yours at: https://browser-use.com/new-api-key            │
╰─────────────────────────────────────────────────────────────╯
"""
	)

	try:
		key = input('Enter API key: ').strip()
	except (EOFError, KeyboardInterrupt):
		raise APIKeyRequired('No API key provided')

	if not key:
		raise APIKeyRequired('No API key provided')

	try:
		save = input('Save to config? [y/N]: ').strip().lower()
		if save == 'y':
			save_api_key(key)
	except (EOFError, KeyboardInterrupt):
		pass

	return key


def save_api_key(key: str) -> None:
	"""Save API key to config file."""
	config_path = get_config_path()
	config_path.parent.mkdir(parents=True, exist_ok=True)

	config: dict = {}
	if config_path.exists():
		try:
			config = json.loads(config_path.read_text())
		except Exception:
			pass

	config['api_key'] = key
	config_path.write_text(json.dumps(config, indent=2))
	# Restrict permissions to owner only (0600)
	config_path.chmod(0o600)
	print(f'Saved to {config_path}')


def get_api_key() -> str | None:
	"""Get API key if available, without raising error."""
	try:
		return require_api_key('API key check')
	except APIKeyRequired:
		return None
