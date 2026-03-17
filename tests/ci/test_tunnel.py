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
	from browser_use.skill_cli.utils import _pid_exists

	with patch('browser_use.skill_cli.utils.ctypes') as mock_ctypes:
		# Mock OpenProcess returning a valid handle
		mock_handle = 0x1234
		mock_ctypes.windll.kernel32.OpenProcess.return_value = mock_handle
		mock_ctypes.windll.kernel32.GetLastError.return_value = 0
		mock_ctypes.wintypes.HANDLE = int
		mock_ctypes.wintypes.DWORD = int
		mock_ctypes.wintypes.BOOL = int
		mock_ctypes.wintypes.UINT = int

		result = _pid_exists(12345)
		assert result is True
		mock_ctypes.windll.kernel32.OpenProcess.assert_called_once()
		mock_ctypes.windll.kernel32.CloseHandle.assert_called_once_with(mock_handle)


@patch('sys.platform', 'win32')
def test_pid_exists_windows_process_not_found():
	"""Test _pid_exists returns False when process doesn't exist on Windows (ERROR_INVALID_PARAMETER)."""
	from browser_use.skill_cli.utils import _pid_exists

	with patch('browser_use.skill_cli.utils.ctypes') as mock_ctypes:
		# Mock OpenProcess returning None (process doesn't exist)
		mock_ctypes.windll.kernel32.OpenProcess.return_value = None
		# ERROR_INVALID_PARAMETER (87) means process doesn't exist
		mock_ctypes.windll.kernel32.GetLastError.return_value = 87
		mock_ctypes.wintypes.HANDLE = int
		mock_ctypes.wintypes.DWORD = int
		mock_ctypes.wintypes.BOOL = int
		mock_ctypes.wintypes.UINT = int

		result = _pid_exists(99999)
		assert result is False
		mock_ctypes.windll.kernel32.OpenProcess.assert_called_once()


@patch('sys.platform', 'win32')
def test_pid_exists_windows_access_denied():
	"""Test _pid_exists returns True when access denied but process exists (ERROR_ACCESS_DENIED)."""
	from browser_use.skill_cli.utils import _pid_exists

	with patch('browser_use.skill_cli.utils.ctypes') as mock_ctypes:
		# Mock OpenProcess returning None due to access denied
		mock_ctypes.windll.kernel32.OpenProcess.return_value = None
		# ERROR_ACCESS_DENIED (5) means process exists but no access
		mock_ctypes.windll.kernel32.GetLastError.return_value = 5
		mock_ctypes.wintypes.HANDLE = int
		mock_ctypes.wintypes.DWORD = int
		mock_ctypes.wintypes.BOOL = int
		mock_ctypes.wintypes.UINT = int

		result = _pid_exists(12345)
		# Should return True because process exists even though we can't access it
		assert result is True


@patch('sys.platform', 'win32')
def test_pid_exists_unix():
	"""Test _pid_exists uses os.kill on Unix."""
	from browser_use.skill_cli.utils import _pid_exists

	with patch('sys.platform', 'linux'):
		with patch('os.kill') as mock_kill:
			result = _pid_exists(12345)
			assert result is True
			mock_kill.assert_called_once_with(12345, 0)


@patch('sys.platform', 'win32')
def test_kill_orphaned_server_windows_terminate_success():
	"""Test kill_orphaned_server successfully terminates process on Windows."""
	from browser_use.skill_cli.utils import kill_orphaned_server

	with patch('browser_use.skill_cli.utils._pid_exists', return_value=True):
		with patch('browser_use.skill_cli.utils._is_process_alive', return_value=True):
			with patch('browser_use.skill_cli.utils._load_tunnel_info', return_value={'port': 8080, 'pid': 12345, 'url': 'http://example.com'}):
				with patch('browser_use.skill_cli.utils._delete_tunnel_info'):
					with patch('browser_use.skill_cli.utils.cleanup_session_files'):
						with patch('browser_use.skill_cli.utils.ctypes') as mock_ctypes:
							mock_handle = 0x1234
							mock_ctypes.windll.kernel32.OpenProcess.return_value = mock_handle
							mock_ctypes.windll.kernel32.TerminateProcess.return_value = True
							mock_ctypes.windll.kernel32.CloseHandle.return_value = True
							mock_ctypes.wintypes.HANDLE = int
							mock_ctypes.wintypes.DWORD = int
							mock_ctypes.wintypes.BOOL = int
							mock_ctypes.wintypes.UINT = int

							result = kill_orphaned_server('test-session')

							assert result is True
							mock_ctypes.windll.kernel32.OpenProcess.assert_called()
							mock_ctypes.windll.kernel32.TerminateProcess.assert_called_once_with(mock_handle, 1)
							mock_ctypes.windll.kernel32.CloseHandle.assert_called_once_with(mock_handle)


@patch('sys.platform', 'win32')
def test_kill_orphaned_server_windows_terminate_failure():
	"""Test kill_orphaned_server returns False when TerminateProcess fails on Windows."""
	from browser_use.skill_cli.utils import kill_orphaned_server

	with patch('browser_use.skill_cli.utils._pid_exists', return_value=True):
		with patch('browser_use.skill_cli.utils._is_process_alive', return_value=True):
			with patch('browser_use.skill_cli.utils._load_tunnel_info', return_value={'port': 8080, 'pid': 12345, 'url': 'http://example.com'}):
				with patch('browser_use.skill_cli.utils._delete_tunnel_info'):
					with patch('browser_use.skill_cli.utils.cleanup_session_files'):
						with patch('browser_use.skill_cli.utils.ctypes') as mock_ctypes:
							mock_handle = 0x1234
							mock_ctypes.windll.kernel32.OpenProcess.return_value = mock_handle
							# TerminateProcess returns False (failure)
							mock_ctypes.windll.kernel32.TerminateProcess.return_value = False
							mock_ctypes.windll.kernel32.CloseHandle.return_value = True
							mock_ctypes.wintypes.HANDLE = int
							mock_ctypes.wintypes.DWORD = int
							mock_ctypes.wintypes.BOOL = int
							mock_ctypes.wintypes.UINT = int

							result = kill_orphaned_server('test-session')

							# Should return False because termination failed
							assert result is False
							mock_ctypes.windll.kernel32.OpenProcess.assert_called()
							mock_ctypes.windll.kernel32.TerminateProcess.assert_called_once_with(mock_handle, 1)
							mock_ctypes.windll.kernel32.CloseHandle.assert_called_once_with(mock_handle)
