"""Tests for Windows process-alive and AF_UNIX socket compatibility in utils.py."""
import sys
from unittest.mock import MagicMock, patch


class MockWindll:
    """Mock for ctypes.windll on non-Windows platforms."""
    kernel32 = MagicMock()

    def __getattr__(self, name):
        raise AttributeError(f"module 'ctypes.windll' has no attribute '{name}'")


def test_get_windll_returns_windll_on_windows():
    """_get_windll() should return ctypes.windll on Windows."""
    from browser_use.skill_cli.utils import _get_windll

    with patch.object(sys, 'platform', 'win32'):
        import ctypes
        result = _get_windll()
        assert result is ctypes.windll, f"Expected ctypes.windll, got {result}"


def test_get_windll_returns_none_on_linux():
    """_get_windll() should return None (not raise AttributeError) on Linux."""
    from browser_use.skill_cli.utils import _get_windll

    with patch.object(sys, 'platform', 'linux'):
        result = _get_windll()
        assert result is None, f"Expected None on Linux, got {result}"


def test_is_process_alive_windows_with_mock():
    """is_process_alive should use OpenProcess via _get_windll() and return True when process exists."""
    from browser_use.skill_cli.utils import is_process_alive

    mock_windll = MockWindll()
    mock_handle = 1234
    mock_windll.kernel32.OpenProcess.return_value = mock_handle
    mock_windll.kernel32.CloseHandle.return_value = True

    with patch.object(sys, 'platform', 'win32'):
        with patch('browser_use.skill_cli.utils._get_windll', return_value=mock_windll):
            result = is_process_alive(12345)
            assert result is True
            mock_windll.kernel32.OpenProcess.assert_called_once()
            mock_windll.kernel32.CloseHandle.assert_called_once_with(mock_handle)


def test_is_process_alive_windows_returns_false_when_openprocess_fails():
    """is_process_alive should return False when OpenProcess returns NULL."""
    from browser_use.skill_cli.utils import is_process_alive

    mock_windll = MockWindll()
    mock_windll.kernel32.OpenProcess.return_value = None

    with patch.object(sys, 'platform', 'win32'):
        with patch('browser_use.skill_cli.utils._get_windll', return_value=mock_windll):
            result = is_process_alive(99999)
            assert result is False


def test_is_process_alive_windows_returns_false_when_windll_unavailable():
    """is_process_alive should return False when _get_windll() returns None."""
    from browser_use.skill_cli.utils import is_process_alive

    with patch.object(sys, 'platform', 'win32'):
        with patch('browser_use.skill_cli.utils._get_windll', return_value=None):
            result = is_process_alive(12345)
            assert result is False


def test_is_daemon_alive_returns_false_when_af_unix_unavailable():
    """is_daemon_alive should return False when AF_UNIX is not available."""
    from browser_use.skill_cli.utils import is_daemon_alive

    with patch.object(sys, 'platform', 'win32'):
        with patch.object(__import__('socket', fromlist=['AF_UNIX']), 'AF_UNIX', None):
            # Should not raise, should return False
            result = is_daemon_alive('nonexistent')
            assert result is False
