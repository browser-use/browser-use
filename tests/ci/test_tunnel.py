"""Tests for tunnel module - cloudflared binary management."""

from unittest.mock import MagicMock, patch

import pytest

from browser_use.skill_cli.tunnel import TunnelManager, get_tunnel_manager


@pytest.fixture
def tunnel_manager():
	"""Create a fresh TunnelManager instance for testing."""
	return TunnelManager()


def test_tunnel_manager_system_cloudflared(tunnel_manager):
	"""Test that system cloudflared is found."""
	with patch('shutil.which', return_value='/usr/local/bin/cloudflared'):
		binary_path = tunnel_manager.get_binary_path()
		assert binary_path == '/usr/local/bin/cloudflared'


def test_tunnel_manager_caches_result(tunnel_manager):
	"""Test that binary path is cached after first call."""
	with patch('shutil.which', return_value='/usr/local/bin/cloudflared'):
		path1 = tunnel_manager.get_binary_path()
		# Reset shutil.which to ensure it's not called again
		with patch('shutil.which', side_effect=Exception('Should be cached')):
			path2 = tunnel_manager.get_binary_path()
		assert path1 == path2


def test_tunnel_manager_not_installed(tunnel_manager):
	"""Test that RuntimeError is raised when cloudflared not found."""
	with patch('shutil.which', return_value=None):
		with pytest.raises(RuntimeError) as exc_info:
			tunnel_manager.get_binary_path()
		assert 'cloudflared not installed' in str(exc_info.value)


def test_tunnel_manager_is_available_cached(tunnel_manager):
	"""Test is_available check with cached binary path."""
	tunnel_manager._binary_path = '/usr/local/bin/cloudflared'
	assert tunnel_manager.is_available() is True


def test_tunnel_manager_is_available_system(tunnel_manager):
	"""Test is_available check finds system cloudflared."""
	with patch('shutil.which', return_value='/usr/local/bin/cloudflared'):
		assert tunnel_manager.is_available() is True


def test_tunnel_manager_is_available_not_found(tunnel_manager):
	"""Test is_available when cloudflared not found."""
	with patch('shutil.which', return_value=None):
		assert tunnel_manager.is_available() is False


def test_tunnel_manager_status_installed(tunnel_manager):
	"""Test get_status returns correct info when cloudflared installed."""
	with patch('shutil.which', return_value='/usr/local/bin/cloudflared'):
		status = tunnel_manager.get_status()
		assert status['available'] is True
		assert status['source'] == 'system'
		assert status['path'] == '/usr/local/bin/cloudflared'


def test_tunnel_manager_status_not_installed(tunnel_manager):
	"""Test get_status when cloudflared not installed."""
	with patch('shutil.which', return_value=None):
		status = tunnel_manager.get_status()
		assert status['available'] is False
		assert status['source'] is None
		assert 'not installed' in status['note']


def test_get_tunnel_manager_singleton():
	"""Test that get_tunnel_manager returns a singleton."""
	# Reset the global singleton
	import browser_use.skill_cli.tunnel as tunnel_module

	tunnel_module._tunnel_manager = None

	mgr1 = get_tunnel_manager()
	mgr2 = get_tunnel_manager()
	assert mgr1 is mgr2


# Tests for _pid_exists with ctypes mocking (Windows)
@patch('sys.platform', 'win32')
def test_pid_exists_windows_process_exists():
	"""Test _pid_exists returns True when process exists on Windows."""
	# Reload the module to pick up the module-level ctypes import
	import importlib
	import browser_use.skill_cli.utils as utils_module
	importlib.reload(utils_module)
	from browser_use.skill_cli.utils import _pid_exists

	with patch.object(utils_module.ctypes, 'windll') as mock_windll:
		# Mock OpenProcess returning a valid handle
		mock_handle = 0x1234
		mock_windll.kernel32.OpenProcess.return_value = mock_handle
		mock_windll.kernel32.GetLastError.return_value = 0

		result = _pid_exists(12345)
		assert result is True
		mock_windll.kernel32.OpenProcess.assert_called_once()
		mock_windll.kernel32.CloseHandle.assert_called_once_with(mock_handle)


@patch('sys.platform', 'win32')
def test_pid_exists_windows_process_not_found():
	"""Test _pid_exists returns False when process doesn't exist on Windows (ERROR_INVALID_PARAMETER)."""
	import importlib
	import browser_use.skill_cli.utils as utils_module
	importlib.reload(utils_module)
	from browser_use.skill_cli.utils import _pid_exists

	with patch.object(utils_module.ctypes, 'windll') as mock_windll:
		# Mock OpenProcess returning None (process doesn't exist)
		mock_windll.kernel32.OpenProcess.return_value = None
		# ERROR_INVALID_PARAMETER (87) means process doesn't exist
		mock_windll.kernel32.GetLastError.return_value = 87

		result = _pid_exists(99999)
		assert result is False
		mock_windll.kernel32.OpenProcess.assert_called_once()


@patch('sys.platform', 'win32')
def test_pid_exists_windows_access_denied():
	"""Test _pid_exists returns False when access denied (ERROR_ACCESS_DENIED).

	Access denied means we can't verify it's our tunnel process, so return False
	to avoid false positives from stale PID files.
	"""
	import importlib
	import browser_use.skill_cli.utils as utils_module
	importlib.reload(utils_module)
	from browser_use.skill_cli.utils import _pid_exists

	with patch.object(utils_module.ctypes, 'windll') as mock_windll:
		# Mock OpenProcess returning None due to access denied
		mock_windll.kernel32.OpenProcess.return_value = None
		# ERROR_ACCESS_DENIED (5) means process exists but no access
		mock_windll.kernel32.GetLastError.return_value = 5

		result = _pid_exists(12345)
		# Should return False because we can't confirm it's our process
		assert result is False


@patch('sys.platform', 'win32')
def test_pid_exists_unix():
	"""Test _pid_exists uses os.kill on Unix."""
	import importlib
	import browser_use.skill_cli.utils as utils_module
	importlib.reload(utils_module)
	from browser_use.skill_cli.utils import _pid_exists

	with patch('sys.platform', 'linux'):
		with patch('os.kill') as mock_kill:
			result = _pid_exists(12345)
			assert result is True
			mock_kill.assert_called_once_with(12345, 0)


@patch('sys.platform', 'win32')
def test_kill_orphaned_server_windows_terminate_success():
	"""Test kill_orphaned_server successfully terminates process on Windows."""
	import importlib
	import browser_use.skill_cli.utils as utils_module
	importlib.reload(utils_module)
	from browser_use.skill_cli.utils import kill_orphaned_server, get_pid_path

	# Create a mock PID file
	with patch.object(utils_module, 'get_pid_path') as mock_get_pid_path:
		with patch.object(utils_module, 'is_session_locked') as mock_is_locked:
			with patch.object(utils_module, '_pid_exists') as mock_pid_exists:
				with patch.object(utils_module, 'cleanup_session_files'):
					# Setup mocks
					mock_pid_path = utils_module.Path('/tmp/browser-use-test.pid')
					mock_get_pid_path.return_value = mock_pid_path
					mock_pid_path.exists.return_value = True
					mock_pid_path.read_text.return_value = '12345'
					mock_is_locked.return_value = False  # Not locked = orphan
					mock_pid_exists.return_value = True  # Process exists

					# Mock ctypes
					with patch.object(utils_module.ctypes, 'windll') as mock_windll:
						mock_handle = 0x1234
						mock_windll.kernel32.OpenProcess.return_value = mock_handle
						mock_windll.kernel32.TerminateProcess.return_value = True
						mock_windll.kernel32.CloseHandle.return_value = True

						result = kill_orphaned_server('test-session')

						assert result is True
						mock_windll.kernel32.OpenProcess.assert_called()
						mock_windll.kernel32.TerminateProcess.assert_called_once_with(mock_handle, 1)
						mock_windll.kernel32.CloseHandle.assert_called_once_with(mock_handle)
