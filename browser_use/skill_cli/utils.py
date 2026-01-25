"""Platform utilities for CLI and server."""

import hashlib
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path


def get_socket_path(session: str) -> str:
	"""Get socket path for session.

	On Windows, returns a TCP address (tcp://localhost:PORT).
	On Unix, returns a Unix socket path.
	"""
	if sys.platform == 'win32':
		# Windows: use TCP on deterministic port (49152-65535)
		port = 49152 + (int(hashlib.md5(session.encode()).hexdigest()[:4], 16) % 16383)
		return f'tcp://localhost:{port}'
	return str(Path(tempfile.gettempdir()) / f'browser-use-{session}.sock')


def get_pid_path(session: str) -> Path:
	"""Get PID file path for session."""
	return Path(tempfile.gettempdir()) / f'browser-use-{session}.pid'


def get_log_path(session: str) -> Path:
	"""Get log file path for session."""
	return Path(tempfile.gettempdir()) / f'browser-use-{session}.log'


def is_server_running(session: str) -> bool:
	"""Check if server is running for session."""
	pid_path = get_pid_path(session)
	if not pid_path.exists():
		return False
	try:
		pid = int(pid_path.read_text().strip())
		# Check if process exists
		os.kill(pid, 0)
		return True
	except (OSError, ValueError):
		# Process doesn't exist or invalid PID
		return False


def find_all_sessions() -> list[str]:
	"""Find all running browser-use sessions by scanning PID files."""
	sessions = []
	tmpdir = Path(tempfile.gettempdir())
	for pid_file in tmpdir.glob('browser-use-*.pid'):
		# Extract session name from filename: browser-use-{session}.pid
		name = pid_file.stem.replace('browser-use-', '', 1)
		if is_server_running(name):
			sessions.append(name)
	return sessions


def cleanup_session_files(session: str) -> None:
	"""Remove session socket and PID files."""
	sock_path = get_socket_path(session)
	pid_path = get_pid_path(session)

	# Remove socket file (Unix only)
	if not sock_path.startswith('tcp://'):
		try:
			os.unlink(sock_path)
		except OSError:
			pass

	# Remove PID file
	try:
		pid_path.unlink()
	except OSError:
		pass


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
			return str(Path.home() / '.config' / 'google-chrome')
		elif system == 'Windows':
			return os.path.expandvars(r'%LocalAppData%\Google\Chrome\User Data')
	else:
		# Return the profile name - Chrome will use it as a subdirectory
		# The actual path will be user_data_dir/profile
		return profile

	return None


def get_config_dir() -> Path:
	"""Get browser-use config directory."""
	if sys.platform == 'win32':
		base = Path(os.environ.get('APPDATA', Path.home()))
	else:
		base = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))
	return base / 'browser-use'


def get_config_path() -> Path:
	"""Get browser-use config file path."""
	return get_config_dir() / 'config.json'
