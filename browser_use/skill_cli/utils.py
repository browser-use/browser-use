"""Platform utilities for CLI and daemon."""

import json as _json
import os
import platform
import re
import subprocess
import sys
import urllib.request
import zlib
from pathlib import Path


def is_process_alive(pid: int) -> bool:
	"""Check if a process is still running.

	On Windows, os.kill(pid, 0) calls TerminateProcess — so we use
	OpenProcess via ctypes instead.
	"""
	if sys.platform == 'win32':
		import ctypes

		PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
		handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
		if handle:
			ctypes.windll.kernel32.CloseHandle(handle)
			return True
		return False
	else:
		try:
			os.kill(pid, 0)
			return True
		except (OSError, ProcessLookupError):
			return False


def validate_session_name(session: str) -> None:
	"""Validate session name — reject path traversal and special characters.

	Raises ValueError on invalid name.
	"""
	if not re.match(r'^[a-zA-Z0-9_-]+$', session):
		raise ValueError(f'Invalid session name {session!r}: only letters, digits, hyphens, and underscores allowed')


def get_home_dir() -> Path:
	"""Get the browser-use home directory (~/.browser-use/).

	All CLI-managed files live here: config, sockets, PIDs, binaries, tunnels.
	Override with BROWSER_USE_HOME env var.
	"""
	env = os.environ.get('BROWSER_USE_HOME')
	if env:
		d = Path(env).expanduser()
	else:
		d = Path.home() / '.browser-use'
	d.mkdir(parents=True, exist_ok=True)
	return d


def get_socket_path(session: str = 'default') -> str:
	"""Get daemon socket path for a session.

	On Windows, returns a TCP address (tcp://127.0.0.1:PORT).
	On Unix, returns a Unix socket path.
	"""
	if sys.platform == 'win32':
		port = 49152 + zlib.adler32(session.encode()) % 16383
		return f'tcp://127.0.0.1:{port}'
	return str(get_home_dir() / f'{session}.sock')


def get_pid_path(session: str = 'default') -> Path:
	"""Get PID file path for a session."""
	return get_home_dir() / f'{session}.pid'


def find_chrome_executable() -> str | None:
	"""Find Chrome/Chromium executable on the system."""
	system = platform.system()

	if system == 'Darwin':
		# macOS
		paths = [
			'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
			'/Applications/Chromium.app/Contents/MacOS/Chromium',
			'/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary',
		]
		for path in paths:
			if os.path.exists(path):
				return path

	elif system == 'Linux':
		# Linux: try common commands
		for cmd in ['google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser']:
			try:
				result = subprocess.run(['which', cmd], capture_output=True, text=True)
				if result.returncode == 0:
					return result.stdout.strip()
			except Exception:
				pass

	elif system == 'Windows':
		# Windows: check common paths
		paths = [
			os.path.expandvars(r'%ProgramFiles%\Google\Chrome\Application\chrome.exe'),
			os.path.expandvars(r'%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe'),
			os.path.expandvars(r'%LocalAppData%\Google\Chrome\Application\chrome.exe'),
		]
		for path in paths:
			if os.path.exists(path):
				return path

	return None


def get_chrome_profile_path(profile: str | None) -> str | None:
	"""Get Chrome user data directory for a profile.

	If profile is None, returns the default Chrome user data directory.
	"""
	if profile is None:
		# Use default Chrome profile location
		system = platform.system()
		if system == 'Darwin':
			return str(Path.home() / 'Library' / 'Application Support' / 'Google' / 'Chrome')
		elif system == 'Linux':
			base = Path.home() / '.config'
			for name in ('google-chrome', 'chromium'):
				if (base / name).is_dir():
					return str(base / name)
			return str(base / 'google-chrome')
		elif system == 'Windows':
			return os.path.expandvars(r'%LocalAppData%\Google\Chrome\User Data')
	else:
		# Return the profile name - Chrome will use it as a subdirectory
		# The actual path will be user_data_dir/profile
		return profile

	return None


def get_chrome_user_data_dirs() -> list[Path]:
	"""Return candidate Chrome/Chromium user-data directories for the current OS.

	Covers Google Chrome, Chrome Canary, Chromium, and Brave on macOS/Linux/Windows.
	"""
	system = platform.system()
	home = Path.home()
	candidates: list[Path] = []

	if system == 'Darwin':
		base = home / 'Library' / 'Application Support'
		for name in ('Google/Chrome', 'Google/Chrome Canary', 'Chromium', 'BraveSoftware/Brave-Browser'):
			candidates.append(base / name)
	elif system == 'Linux':
		base = home / '.config'
		for name in ('google-chrome', 'google-chrome-unstable', 'chromium', 'BraveSoftware/Brave-Browser'):
			candidates.append(base / name)
	elif system == 'Windows':
		local_app_data = os.environ.get('LOCALAPPDATA', str(home / 'AppData' / 'Local'))
		base = Path(local_app_data)
		for name in (
			'Google\\Chrome\\User Data',
			'Google\\Chrome SxS\\User Data',
			'Chromium\\User Data',
			'BraveSoftware\\Brave-Browser\\User Data',
		):
			candidates.append(base / name)

	return [d for d in candidates if d.is_dir()]


def discover_chrome_cdp_url() -> str:
	"""Auto-discover a running Chrome instance's CDP WebSocket URL.

	Strategy:
	1. Read ``DevToolsActivePort`` from known Chrome data dirs.
	2. Probe ``/json/version`` via HTTP to get ``webSocketDebuggerUrl``.
	3. If HTTP fails, construct ``ws://`` URL directly from the port file.
	4. Fallback: probe well-known port 9222.

	Raises ``RuntimeError`` if no running Chrome with remote debugging is found.
	"""

	def _probe_http(port: int) -> str | None:
		"""Try GET http://127.0.0.1:{port}/json/version and return webSocketDebuggerUrl."""
		try:
			req = urllib.request.Request(f'http://127.0.0.1:{port}/json/version')
			with urllib.request.urlopen(req, timeout=2) as resp:
				data = _json.loads(resp.read())
				url = data.get('webSocketDebuggerUrl')
				if url and isinstance(url, str):
					return url
		except Exception:
			pass
		return None

	def _port_is_open(port: int) -> bool:
		"""Check if something is listening on 127.0.0.1:{port}."""
		import socket

		s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		try:
			s.settimeout(1)
			s.connect(('127.0.0.1', port))
			return True
		except OSError:
			return False
		finally:
			s.close()

	# --- Phase 1: DevToolsActivePort files ---
	for data_dir in get_chrome_user_data_dirs():
		port_file = data_dir / 'DevToolsActivePort'
		if not port_file.is_file():
			continue
		try:
			lines = port_file.read_text().strip().splitlines()
			if not lines:
				continue
			port = int(lines[0].strip())
			ws_path = lines[1].strip() if len(lines) > 1 else '/devtools/browser'
		except (ValueError, OSError):
			continue

		# Try HTTP probe first (gives us the full canonical URL)
		ws_url = _probe_http(port)
		if ws_url:
			return ws_url

		# HTTP may not respond (Chrome M144+), but if the port is open, trust the file
		if _port_is_open(port):
			return f'ws://127.0.0.1:{port}{ws_path}'

	# --- Phase 2: well-known fallback ports ---
	for port in (9222,):
		ws_url = _probe_http(port)
		if ws_url:
			return ws_url

	raise RuntimeError(
		'Could not discover a running Chrome instance with remote debugging enabled.\n'
		'Enable remote debugging in Chrome (chrome://inspect, or launch with --remote-debugging-port=9222) and try again.'
	)


def list_chrome_profiles() -> list[dict[str, str]]:
	"""List available Chrome profiles with their names.

	Returns:
		List of dicts with 'directory' and 'name' keys, ex:
		[{'directory': 'Default', 'name': 'Person 1'}, {'directory': 'Profile 1', 'name': 'Work'}]
	"""
	import json

	user_data_dir = get_chrome_profile_path(None)
	if user_data_dir is None:
		return []

	local_state_path = Path(user_data_dir) / 'Local State'
	if not local_state_path.exists():
		return []

	try:
		with open(local_state_path) as f:
			local_state = json.load(f)

		info_cache = local_state.get('profile', {}).get('info_cache', {})
		profiles = []
		for directory, info in info_cache.items():
			profiles.append(
				{
					'directory': directory,
					'name': info.get('name', directory),
				}
			)
		return sorted(profiles, key=lambda p: p['directory'])
	except (json.JSONDecodeError, KeyError, OSError):
		return []


def get_config_path() -> Path:
	"""Get browser-use config file path."""
	return get_home_dir() / 'config.json'


def get_bin_dir() -> Path:
	"""Get directory for CLI-managed binaries."""
	d = get_home_dir() / 'bin'
	d.mkdir(parents=True, exist_ok=True)
	return d


def get_tunnel_dir() -> Path:
	"""Get directory for tunnel metadata and logs."""
	return get_home_dir() / 'tunnels'


def migrate_legacy_paths() -> None:
	"""One-time migration of config from old XDG location to ~/.browser-use/.

	Copies (not moves) config.json if old location exists and new location does not.
	"""
	new_config = get_home_dir() / 'config.json'
	if new_config.exists():
		return

	# Check old XDG location
	if sys.platform == 'win32':
		old_base = Path(os.environ.get('APPDATA', Path.home()))
	else:
		old_base = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))
	old_config = old_base / 'browser-use' / 'config.json'

	if old_config.exists():
		import shutil

		shutil.copy2(str(old_config), str(new_config))
		print(f'Migrated config from {old_config} to {new_config}', file=sys.stderr)
