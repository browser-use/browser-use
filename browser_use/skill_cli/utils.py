"""Platform utilities for CLI and server."""

import hashlib
import os
import platform
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import IO

import portalocker


def get_socket_path(session: str) -> str:
	"""Get socket path for session.

	On Windows, returns a TCP address (tcp://127.0.0.1:PORT).
	On Unix, returns a Unix socket path.
	"""
	if sys.platform == 'win32':
		# Windows: use TCP on deterministic port (49152-65535)
		# Use 127.0.0.1 explicitly (not localhost) to avoid IPv6 binding issues
		port = 49152 + (int(hashlib.md5(session.encode()).hexdigest()[:4], 16) % 16383)
		return f'tcp://127.0.0.1:{port}'
	return str(Path(tempfile.gettempdir()) / f'browser-use-{session}.sock')


def get_pid_path(session: str) -> Path:
	"""Get PID file path for session."""
	return Path(tempfile.gettempdir()) / f'browser-use-{session}.pid'


def get_log_path(session: str) -> Path:
	"""Get log file path for session."""
	return Path(tempfile.gettempdir()) / f'browser-use-{session}.log'


def get_lock_path(session: str) -> Path:
	"""Get lock file path for session."""
	return Path(tempfile.gettempdir()) / f'browser-use-{session}.lock'


def _pid_exists(pid: int) -> bool:
	"""Check if a process with given PID exists.

	On Windows, uses ctypes to call OpenProcess (os.kill doesn't work reliably).
	On Unix, uses os.kill(pid, 0) which is the standard approach.
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
		except OSError:
			return False


def is_server_running(session: str) -> bool:
	"""Check if server is running for session."""
	pid_path = get_pid_path(session)
	if not pid_path.exists():
		return False
	try:
		pid = int(pid_path.read_text().strip())
		return _pid_exists(pid)
	except (OSError, ValueError):
		# Can't read PID file or invalid PID
		return False


def try_acquire_server_lock(session: str) -> IO | None:
	"""Try to acquire the server lock non-blocking.

	Returns:
		Lock file handle if acquired (caller must keep in scope to maintain lock),
		None if lock is already held by another process.
	"""
	lock_path = get_lock_path(session)
	lock_path.parent.mkdir(parents=True, exist_ok=True)
	lock_path.touch(exist_ok=True)

	lock_file = open(lock_path, 'r+')
	try:
		portalocker.lock(lock_file, portalocker.LOCK_EX | portalocker.LOCK_NB)
		return lock_file
	except portalocker.LockException:
		lock_file.close()
		return None


def is_session_locked(session: str) -> bool:
	"""Check if session has an active lock (server is holding it)."""
	lock_path = get_lock_path(session)
	if not lock_path.exists():
		return False

	try:
		with open(lock_path, 'r+') as f:
			portalocker.lock(f, portalocker.LOCK_EX | portalocker.LOCK_NB)
			portalocker.unlock(f)
			return False  # Lock acquired = no one holding it
	except portalocker.LockException:
		return True  # Lock failed = someone holding it
	except OSError:
		return False  # File access error


def kill_orphaned_server(session: str) -> bool:
	"""Kill an orphaned server (has PID file but no lock).

	An orphaned server is one where the process is running but it doesn't
	hold the session lock (e.g., because a newer server took over the lock
	file but didn't kill the old process).

	Returns:
		True if an orphan was found and killed.
	"""
	pid_path = get_pid_path(session)
	if not pid_path.exists():
		return False

	# Check if session is locked (server alive and holding lock)
	if is_session_locked(session):
		return False  # Not an orphan - server is healthy

	# PID exists but no lock - orphan situation
	try:
		pid = int(pid_path.read_text().strip())
		if _pid_exists(pid):
			# Kill the orphaned process
			if sys.platform == 'win32':
				import ctypes

				PROCESS_TERMINATE = 1
				handle = ctypes.windll.kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
				if handle:
					ctypes.windll.kernel32.TerminateProcess(handle, 1)
					ctypes.windll.kernel32.CloseHandle(handle)
			else:
				os.kill(pid, signal.SIGKILL)
			return True
	except (OSError, ValueError):
		pass

	# Clean up stale files even if we couldn't kill (process may be gone)
	cleanup_session_files(session)
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
	"""Remove session socket, PID, lock, and metadata files."""
	sock_path = get_socket_path(session)
	pid_path = get_pid_path(session)
	lock_path = get_lock_path(session)
	meta_path = Path(tempfile.gettempdir()) / f'browser-use-{session}.meta'

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

	# Remove lock file
	try:
		lock_path.unlink()
	except OSError:
		pass

	# Remove metadata file
	try:
		meta_path.unlink()
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
