from __future__ import annotations

import json
import os
import platform
import subprocess
from pathlib import Path


def _chrome_user_data_dir_for_executable(executable_path: str | None) -> Path | None:
	if executable_path is None:
		return None

	system = platform.system()
	path = Path(executable_path)
	if system == 'Darwin':
		app_path = str(path)
		base = Path.home() / 'Library' / 'Application Support'
		if 'Chromium.app' in app_path:
			return base / 'Chromium'
		if 'Google Chrome Canary.app' in app_path:
			return base / 'Google' / 'Chrome Canary'
		if 'Google Chrome.app' in app_path:
			return base / 'Google' / 'Chrome'
	if system == 'Linux':
		name = path.name
		base = Path.home() / '.config'
		if name in {'chromium', 'chromium-browser'}:
			return base / 'chromium'
		if name in {'google-chrome', 'google-chrome-stable'}:
			return base / 'google-chrome'
	if system == 'Windows' and path.name.lower() == 'chrome.exe':
		return Path(os.path.expandvars(r'%LocalAppData%\Google\Chrome\User Data'))

	return None


def find_chrome_executable() -> str | None:
	"""Find Chrome/Chromium executable on the system."""
	system = platform.system()

	if system == 'Darwin':
		for path in (
			'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
			'/Applications/Chromium.app/Contents/MacOS/Chromium',
			'/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary',
		):
			if os.path.exists(path):
				return path

	elif system == 'Linux':
		for cmd in ('google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser'):
			try:
				result = subprocess.run(['which', cmd], capture_output=True, text=True)
				if result.returncode == 0:
					return result.stdout.strip()
			except Exception:
				pass

	elif system == 'Windows':
		for path in (
			os.path.expandvars(r'%ProgramFiles%\Google\Chrome\Application\chrome.exe'),
			os.path.expandvars(r'%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe'),
			os.path.expandvars(r'%LocalAppData%\Google\Chrome\Application\chrome.exe'),
		):
			if os.path.exists(path):
				return path

	return None


def get_chrome_profile_path(profile: str | None, executable_path: str | None = None) -> str | None:
	"""Get Chrome user data directory, or return a specific profile directory name."""
	if profile is not None:
		return profile

	if browser_user_data_dir := _chrome_user_data_dir_for_executable(executable_path):
		return str(browser_user_data_dir)

	system = platform.system()
	if system == 'Darwin':
		return str(Path.home() / 'Library' / 'Application Support' / 'Google' / 'Chrome')
	if system == 'Linux':
		base = Path.home() / '.config'
		for name in ('google-chrome', 'chromium'):
			if (base / name).is_dir():
				return str(base / name)
		return str(base / 'google-chrome')
	if system == 'Windows':
		return os.path.expandvars(r'%LocalAppData%\Google\Chrome\User Data')

	return None


def list_chrome_profiles() -> list[dict[str, str]]:
	"""List available Chrome profiles with their display names."""
	user_data_dir = get_chrome_profile_path(None, executable_path=find_chrome_executable())
	if user_data_dir is None:
		return []

	local_state_path = Path(user_data_dir) / 'Local State'
	if not local_state_path.exists():
		return []

	try:
		with open(local_state_path, encoding='utf-8') as f:
			local_state = json.load(f)

		if not isinstance(local_state, dict):
			return []
		info_cache = local_state.get('profile', {}).get('info_cache', {})
		if not isinstance(info_cache, dict):
			return []
		return sorted(
			[
				{
					'directory': directory,
					'name': info.get('name', directory),
				}
				for directory, info in info_cache.items()
				if isinstance(info, dict)
			],
			key=lambda profile: profile['directory'],
		)
	except (json.JSONDecodeError, KeyError, OSError, TypeError):
		return []
