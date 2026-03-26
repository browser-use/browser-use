"""Tests for tunnel module - cloudflared binary management."""

from __future__ import annotations

import sys
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from browser_use.skill_cli.tunnel import TunnelManager, get_tunnel_manager

# =============================================================================
# Windows mocking helpers for _kill_process tests
# =============================================================================


@contextmanager
def _windows_ctypes_mock():
	"""Mock ctypes.windll so it can be used on non-Windows platforms.

	On real Windows, ctypes.windll is a ModuleType proxy that lazily loads
	ctypes/_windll__.pyd. On non-Windows, ctypes.windll raises AttributeError.
	We set the windll attribute on the ctypes module so that ctypes.windll.kernel32
	returns a MagicMock, enabling the Windows code path to run on Linux CI.
	"""
	import ctypes

	original_windll = getattr(ctypes, 'windll', None)

	class MockWindll:
		"""Stands in for ctypes.windll on non-Windows."""

		kernel32 = MagicMock()

		def __getattr__(self, name: str):
			raise AttributeError(f"module 'ctypes.windll' has no attribute '{name}'")

	mock_windll = MockWindll()

	try:
		ctypes.windll = mock_windll  # type: ignore[attr-defined]
		yield mock_windll
	finally:
		if original_windll is None:
			try:
				delattr(ctypes, 'windll')  # type: ignore[attr-defined]
			except AttributeError:
				pass
		else:
			ctypes.windll = original_windll  # type: ignore[attr-defined]


@contextmanager
def _windows_test_context():
	"""Patch sys.platform AND ctypes.windll so the Windows _kill_process path runs.

	Apply this to every TestKillProcessWindows test. It does NOT skip on
	non-Windows — the test body actually executes with mocked Windows internals.
	"""
	with _windows_ctypes_mock():
		original_platform = sys.platform
		try:
			sys.platform = 'win32'
			yield
		finally:
			sys.platform = original_platform


# =============================================================================
# TunnelManager tests
# =============================================================================


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


def test_tunnel_manager_status_not_found(tunnel_manager):
	"""Test get_status when cloudflared not found."""
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
# Tests for _kill_process — Windows path
# =============================================================================


class TestKillProcessWindows:
	"""Tests for _kill_process on Windows.

	These tests run on all CI platforms (Linux + Windows) using
	_windows_test_context() to mock sys.platform='win32' and ctypes.windll.
	"""

	@staticmethod
	def test_kill_process_windows_success_exits_immediately():
		"""Test Windows path: TerminateProcess succeeds and process exits immediately."""
		from browser_use.skill_cli.tunnel import _kill_process

		with _windows_test_context():
			import ctypes

			mock_handle = MagicMock()
			open_process = MagicMock(return_value=mock_handle)
			terminate_process = MagicMock(return_value=True)
			close_handle = MagicMock()

			ctypes.windll.kernel32.OpenProcess = open_process  # type: ignore[attr-defined]
			ctypes.windll.kernel32.TerminateProcess = terminate_process  # type: ignore[attr-defined]
			ctypes.windll.kernel32.CloseHandle = close_handle  # type: ignore[attr-defined]

			with patch(
				'browser_use.skill_cli.tunnel._is_process_alive',
				return_value=False,
			):
				result = _kill_process(1234)

			assert result is True
			open_process.assert_called_once_with(0x0001, False, 1234)
			terminate_process.assert_called_once_with(mock_handle, 1)
			close_handle.assert_called_once_with(mock_handle)

	@staticmethod
	def test_kill_process_windows_success_waits_for_exit():
		"""Test Windows path: TerminateProcess succeeds but process requires waiting."""
		from browser_use.skill_cli.tunnel import _kill_process

		with _windows_test_context():
			import ctypes

			mock_handle = MagicMock()
			open_process = MagicMock(return_value=mock_handle)
			terminate_process = MagicMock(return_value=True)
			close_handle = MagicMock()

			ctypes.windll.kernel32.OpenProcess = open_process  # type: ignore[attr-defined]
			ctypes.windll.kernel32.TerminateProcess = terminate_process  # type: ignore[attr-defined]
			ctypes.windll.kernel32.CloseHandle = close_handle  # type: ignore[attr-defined]

			call_count = [0]

			def fake_is_alive(pid: int) -> bool:
				call_count[0] += 1
				return call_count[0] <= 3

			with patch(
				'browser_use.skill_cli.tunnel._is_process_alive',
				side_effect=fake_is_alive,
			):
				with patch('browser_use.skill_cli.tunnel.time.sleep'):
					result = _kill_process(1234)

			assert result is True
			assert call_count[0] == 4  # 3 alive checks + 1 exit
			close_handle.assert_called_once_with(mock_handle)

	@staticmethod
	def test_kill_process_windows_open_process_returns_null():
		"""Test Windows path: OpenProcess returns NULL handle (process not found)."""
		from browser_use.skill_cli.tunnel import _kill_process

		with _windows_test_context():
			import ctypes

			open_process = MagicMock(return_value=None)
			ctypes.windll.kernel32.OpenProcess = open_process  # type: ignore[attr-defined]

			result = _kill_process(9999)

			assert result is False
			open_process.assert_called_once()

	@staticmethod
	def test_kill_process_windows_terminate_fails():
		"""Test Windows path: TerminateProcess returns False."""
		from browser_use.skill_cli.tunnel import _kill_process

		with _windows_test_context():
			import ctypes

			mock_handle = MagicMock()
			open_process = MagicMock(return_value=mock_handle)
			terminate_process = MagicMock(return_value=False)
			close_handle = MagicMock()

			ctypes.windll.kernel32.OpenProcess = open_process  # type: ignore[attr-defined]
			ctypes.windll.kernel32.TerminateProcess = terminate_process  # type: ignore[attr-defined]
			ctypes.windll.kernel32.CloseHandle = close_handle  # type: ignore[attr-defined]

			result = _kill_process(1234)

			assert result is False
			close_handle.assert_called_once_with(mock_handle)

	@staticmethod
	def test_kill_process_windows_timeout_not_exit():
		"""Test Windows path: TerminateProcess succeeds but process stays alive past timeout."""
		from browser_use.skill_cli.tunnel import _kill_process

		with _windows_test_context():
			import ctypes

			mock_handle = MagicMock()
			open_process = MagicMock(return_value=mock_handle)
			terminate_process = MagicMock(return_value=True)
			close_handle = MagicMock()

			ctypes.windll.kernel32.OpenProcess = open_process  # type: ignore[attr-defined]
			ctypes.windll.kernel32.TerminateProcess = terminate_process  # type: ignore[attr-defined]
			ctypes.windll.kernel32.CloseHandle = close_handle  # type: ignore[attr-defined]

			# Process stays alive through all 10 polling iterations (0.1s each = 1s total)
			with patch(
				'browser_use.skill_cli.tunnel._is_process_alive',
				return_value=True,
			):
				with patch('browser_use.skill_cli.tunnel.time.sleep'):
					result = _kill_process(1234)

			# TerminateProcess succeeded but process didn't exit within timeout
			assert result is False
			terminate_process.assert_called_once_with(mock_handle, 1)
			close_handle.assert_called_once_with(mock_handle)


# =============================================================================
# Tests for _kill_process — Unix path
# =============================================================================


class TestKillProcessUnix:
	"""Tests for _kill_process on Unix (non-Windows)."""

	def test_kill_process_unix_sigterm_kills_immediately(self):
		"""Test Unix path: SIGTERM kills process immediately."""
		from browser_use.skill_cli.tunnel import _kill_process

		original_platform = sys.platform
		try:
			sys.platform = 'linux'
			with patch('os.kill') as mock_kill:
				with patch(
					'browser_use.skill_cli.tunnel._is_process_alive',
					return_value=False,
				):
					result = _kill_process(1234)
			assert result is True
			mock_kill.assert_called_once_with(1234, 15)  # 15 = SIGTERM
		finally:
			sys.platform = original_platform

	def test_kill_process_unix_sigkill_after_grace_period(self):
		"""Test Unix path: SIGKILL sent after SIGTERM grace period expires."""
		import signal as signal_module

		from browser_use.skill_cli.tunnel import _kill_process

		original_platform = sys.platform
		# signal.SIGKILL does not exist on Windows — inject it before the call
		original_sigkill = getattr(signal_module, 'SIGKILL', None)
		signal_module.SIGKILL = 9  # type: ignore[attr-defined]
		try:
			sys.platform = 'linux'
			call_count = [0]

			def fake_is_alive(pid: int) -> bool:
				call_count[0] += 1
				return True  # Always alive

			with patch('os.kill') as mock_kill:
				with patch(
					'browser_use.skill_cli.tunnel._is_process_alive',
					side_effect=fake_is_alive,
				):
					with patch('browser_use.skill_cli.tunnel.time.sleep'):
						result = _kill_process(1234)
			assert result is True
			# Should have sent SIGTERM first, then SIGKILL after 10 sleeps
			assert mock_kill.call_count == 2
			mock_kill.assert_any_call(1234, 15)  # SIGTERM
			mock_kill.assert_any_call(1234, 9)  # SIGKILL
			assert call_count[0] == 10  # 10 alive checks during grace period → no early return
		finally:
			sys.platform = original_platform
			if original_sigkill is None:
				del signal_module.SIGKILL  # type: ignore[attr-defined]
			else:
				signal_module.SIGKILL = original_sigkill  # type: ignore[attr-defined]

	def test_kill_process_unix_process_not_found(self):
		"""Test Unix path: ProcessLookupError when process doesn't exist."""
		from browser_use.skill_cli.tunnel import _kill_process

		original_platform = sys.platform
		try:
			sys.platform = 'linux'
			with patch('os.kill', side_effect=ProcessLookupError('No such process')):
				result = _kill_process(9999)
			assert result is False
		finally:
			sys.platform = original_platform
