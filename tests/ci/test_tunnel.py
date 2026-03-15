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


# =============================================================================
# Tests for Windows process management
# =============================================================================


class TestIsProcessAliveWindows:
	"""Tests for _is_process_alive on Windows."""

	@patch('sys.platform', 'win32')
	def test_is_process_alive_windows_process_exists(self):
		"""Test _is_process_alive returns True when process exists on Windows."""
		from browser_use.skill_cli.tunnel import _is_process_alive

		# Reset ctypes initialization to allow our mock to work
		import browser_use.skill_cli.tunnel as tunnel_module
		tunnel_module._ctypes_initialized = False

		with patch.object(tunnel_module, '_setup_windows_ctypes') as mock_setup:
			mock_kernel32 = MagicMock()
			# WAIT_TIMEOUT (0x102) = still running
			mock_kernel32.WaitForSingleObject.return_value = 0x102
			mock_kernel32.OpenProcess.return_value = 1234  # Non-null handle
			mock_setup.return_value = mock_kernel32

			result = _is_process_alive(12345)

			assert result is True
			mock_kernel32.OpenProcess.assert_called_once()
			mock_kernel32.WaitForSingleObject.assert_called_once_with(1234, 0)
			mock_kernel32.CloseHandle.assert_called_once_with(1234)

	@patch('sys.platform', 'win32')
	def test_is_process_alive_windows_process_not_exists(self):
		"""Test _is_process_alive returns False when process doesn't exist on Windows."""
		from browser_use.skill_cli.tunnel import _is_process_alive

		import browser_use.skill_cli.tunnel as tunnel_module
		tunnel_module._ctypes_initialized = False

		with patch.object(tunnel_module, '_setup_windows_ctypes') as mock_setup:
			mock_kernel32 = MagicMock()
			mock_kernel32.OpenProcess.return_value = 0  # Null handle = not found
			mock_setup.return_value = mock_kernel32

			result = _is_process_alive(99999)

			assert result is False
			mock_kernel32.CloseHandle.assert_not_called()

	@patch('sys.platform', 'win32')
	def test_is_process_alive_windows_exception(self):
		"""Test _is_process_alive returns False on exception on Windows."""
		from browser_use.skill_cli.tunnel import _is_process_alive

		import browser_use.skill_cli.tunnel as tunnel_module
		tunnel_module._ctypes_initialized = False

		with patch.object(tunnel_module, '_setup_windows_ctypes') as mock_setup:
			mock_kernel32 = MagicMock()
			mock_kernel32.OpenProcess.side_effect = Exception("Test error")
			mock_setup.return_value = mock_kernel32

			result = _is_process_alive(12345)

			assert result is False


class TestKillProcessWindows:
	"""Tests for _kill_process on Windows."""

	@patch('sys.platform', 'win32')
	def test_kill_process_windows_success(self):
		"""Test _kill_process returns True on successful termination on Windows."""
		from browser_use.skill_cli.tunnel import _kill_process

		import browser_use.skill_cli.tunnel as tunnel_module
		tunnel_module._ctypes_initialized = False

		with patch.object(tunnel_module, '_setup_windows_ctypes') as mock_setup:
			mock_kernel32 = MagicMock()
			mock_kernel32.OpenProcess.return_value = 1234
			mock_kernel32.TerminateProcess.return_value = True
			# First call: process still alive, second call: process terminated
			mock_kernel32.WaitForSingleObject.side_effect = [0x102, 0x0]
			mock_setup.return_value = mock_kernel32

			result = _kill_process(12345)

			assert result is True
			mock_kernel32.OpenProcess.assert_called()
			mock_kernel32.TerminateProcess.assert_called_once_with(1234, 1)

	@patch('sys.platform', 'win32')
	def test_kill_process_windows_not_found(self):
		"""Test _kill_process returns False when process doesn't exist on Windows."""
		from browser_use.skill_cli.tunnel import _kill_process

		import browser_use.skill_cli.tunnel as tunnel_module
		tunnel_module._ctypes_initialized = False

		with patch.object(tunnel_module, '_setup_windows_ctypes') as mock_setup:
			mock_kernel32 = MagicMock()
			mock_kernel32.OpenProcess.return_value = 0  # Can't open process
			mock_setup.return_value = mock_kernel32

			result = _kill_process(99999)

			assert result is False

	@patch('sys.platform', 'win32')
	def test_kill_process_windows_terminate_fails(self):
		"""Test _kill_process returns False when TerminateProcess fails on Windows."""
		from browser_use.skill_cli.tunnel import _kill_process

		import browser_use.skill_cli.tunnel as tunnel_module
		tunnel_module._ctypes_initialized = False

		with patch.object(tunnel_module, '_setup_windows_ctypes') as mock_setup:
			mock_kernel32 = MagicMock()
			mock_kernel32.OpenProcess.return_value = 1234
			mock_kernel32.TerminateProcess.return_value = False  # Failed
			mock_setup.return_value = mock_kernel32

			result = _kill_process(12345)

			assert result is False

	@patch('sys.platform', 'win32')
	def test_kill_process_windows_still_alive_after_retries(self):
		"""Test _kill_process returns False when process is still alive after all retries."""
		from browser_use.skill_cli.tunnel import _kill_process

		import browser_use.skill_cli.tunnel as tunnel_module
		tunnel_module._ctypes_initialized = False

		with patch.object(tunnel_module, '_setup_windows_ctypes') as mock_setup:
			mock_kernel32 = MagicMock()
			mock_kernel32.OpenProcess.return_value = 1234
			mock_kernel32.TerminateProcess.return_value = True
			# Process keeps returning "still running" (WAIT_TIMEOUT) for all 10 retries
			mock_kernel32.WaitForSingleObject.return_value = 0x102
			mock_setup.return_value = mock_kernel32

			result = _kill_process(12345)

			# Should return False because process is still alive after all retries
			assert result is False
			# Verify all 10 retries were attempted
			assert mock_kernel32.WaitForSingleObject.call_count == 10
