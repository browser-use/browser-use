"""Tests for tunnel module - cloudflared binary management."""

from __future__ import annotations

import sys
from contextlib import contextmanager
from types import ModuleType
from typing import Any
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

	This context manager also patches the ``ctypes`` attribute on the tunnel module
	itself — Python caches module imports, so the tunnel module's own ``ctypes``
	reference must also be replaced for the mock to take effect.
	"""
	import ctypes

	original_windll = getattr(ctypes, 'windll', None)

	class MockWindll:
		"""Stands in for ctypes.windll on non-Windows."""

		kernel32 = MagicMock()

		def __getattr__(self, name: str):
			raise AttributeError(f"module 'ctypes.windll' has no attribute '{name}'")

	mock_windll = MockWindll()

	import browser_use.skill_cli.tunnel as _tunnel_module

	original_tunnel_ctypes = getattr(_tunnel_module, 'ctypes', None)

	try:
		ctypes.windll = mock_windll  # type: ignore[attr-defined]
		_tunnel_module.ctypes = ctypes  # type: ignore[attr-defined]
		yield mock_windll
	finally:
		ctypes.windll = original_windll  # type: ignore[attr-defined]
		if original_tunnel_ctypes is None:
			try:
				delattr(_tunnel_module, 'ctypes')  # type: ignore[attr-defined]
			except AttributeError:
				pass
		else:
			_tunnel_module.ctypes = original_tunnel_ctypes  # type: ignore[attr-defined]


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


@contextmanager
def _unix_test_context():
	"""Patch sys.platform AND the signal module so Unix _kill_process path runs on Windows CI.

	On Windows, ``signal.SIGKILL`` does not exist (AttributeError), so the Unix
	path in _kill_process would crash at import-time or runtime on a real Windows
	machine or Windows CI runner.  This context manager:

	1. Patches ``sys.platform = "linux"`` so the platform check in tunnel.py takes
	   the Unix branch.
	2. Patches ``sys.modules["signal"]`` with a stub that provides SIGTERM=15 and
	   SIGKILL=9 regardless of the host platform.
	3. Patches the ``signal`` attribute on the tunnel module itself — Python caches
	   module imports, so the tunnel module's own ``signal`` reference must also be
	   replaced for the mock to take effect.
	"""
	import signal as _real_signal

	_original_signal = _real_signal

	class _MockSignalModule(ModuleType):
		"""Minimal signal module stub providing SIGTERM and SIGKILL on all platforms."""

		SIGTERM = 15
		SIGKILL = 9
		SIG_IGN = 1

		def __getattr__(self, name: str):
			# Delegate to the real signal module for any other constants
			return getattr(_real_signal, name)

	mock_signal = _MockSignalModule('signal')

	original_platform = sys.platform
	original_signal_module = sys.modules.get('signal')
	import browser_use.skill_cli.tunnel as _tunnel_module

	original_tunnel_signal = getattr(_tunnel_module, 'signal', None)

	try:
		sys.platform = 'linux'
		sys.modules['signal'] = mock_signal
		# Replace the cached reference in the tunnel module itself
		_tunnel_module.signal = mock_signal  # type: ignore[attr-defined]
		yield
	finally:
		sys.platform = original_platform
		if original_signal_module is None:
			del sys.modules['signal']
		else:
			sys.modules['signal'] = original_signal_module
		if original_tunnel_signal is None:
			try:
				delattr(_tunnel_module, 'signal')  # type: ignore[attr-defined]
			except AttributeError:
				pass
		else:
			_tunnel_module.signal = original_tunnel_signal  # type: ignore[attr-defined]


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

			ctypes.windll.kernel32.OpenProcess = open_process
			ctypes.windll.kernel32.TerminateProcess = terminate_process
			ctypes.windll.kernel32.CloseHandle = close_handle

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

			ctypes.windll.kernel32.OpenProcess = open_process
			ctypes.windll.kernel32.TerminateProcess = terminate_process
			ctypes.windll.kernel32.CloseHandle = close_handle

			call_count = [0]

			def fake_is_alive(pid: int) -> bool:
				call_count[0] += 1
				return call_count[0] <= 3

			with patch(
				'browser_use.skill_cli.tunnel._is_process_alive',
				side_effect=fake_is_alive,
			):
				result = _kill_process(1234)

			assert result is True
			assert call_count[0] == 4  # 3 alive checks + 1 exit
			close_handle.assert_called_once_with(mock_handle)

	@staticmethod
	def test_kill_process_windows_timeout_returns_true():
		"""Test Windows path: TerminateProcess succeeds but process outlives the timeout.

		The Windows path returns True once TerminateProcess has been issued, matching
		the Unix behaviour (which returns True after sending SIGKILL even if the
		process is still alive at the function-return boundary).
		"""
		from browser_use.skill_cli.tunnel import _kill_process

		with _windows_test_context():
			import ctypes

			mock_handle = MagicMock()
			open_process = MagicMock(return_value=mock_handle)
			terminate_process = MagicMock(return_value=True)
			close_handle = MagicMock()

			ctypes.windll.kernel32.OpenProcess = open_process
			ctypes.windll.kernel32.TerminateProcess = terminate_process
			ctypes.windll.kernel32.CloseHandle = close_handle

			# Process is still alive for all 10 timeout checks
			with patch(
				'browser_use.skill_cli.tunnel._is_process_alive',
				return_value=True,
			):
				result = _kill_process(1234)

			# Returns True: TerminateProcess succeeded, matching Unix semantics
			assert result is True
			close_handle.assert_called_once_with(mock_handle)

	@staticmethod
	def test_kill_process_windows_open_process_returns_null():
		"""Test Windows path: OpenProcess returns NULL handle (process not found)."""
		from browser_use.skill_cli.tunnel import _kill_process

		with _windows_test_context():
			import ctypes

			open_process = MagicMock(return_value=None)
			ctypes.windll.kernel32.OpenProcess = open_process

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

			ctypes.windll.kernel32.OpenProcess = open_process
			ctypes.windll.kernel32.TerminateProcess = terminate_process
			ctypes.windll.kernel32.CloseHandle = close_handle

			result = _kill_process(1234)

			assert result is False
			close_handle.assert_called_once_with(mock_handle)


# =============================================================================
# Tests for _kill_process — Unix path
# =============================================================================


class TestKillProcessUnix:
	"""Tests for _kill_process on Unix (non-Windows).

	These tests run on all CI platforms (Linux + Windows) using
	_unix_test_context() to mock sys.platform='linux' and provide
	signal.SIGTERM / signal.SIGKILL which do not exist on Windows.
	"""

	def test_kill_process_unix_sigterm_kills_immediately(self):
		"""Test Unix path: SIGTERM kills process immediately."""
		from browser_use.skill_cli.tunnel import _kill_process

		with _unix_test_context():
			with patch('os.kill') as mock_kill:
				with patch(
					'browser_use.skill_cli.tunnel._is_process_alive',
					return_value=False,
				):
					result = _kill_process(1234)

			assert result is True
			mock_kill.assert_called_once_with(1234, 15)  # 15 = SIGTERM

	def test_kill_process_unix_sigkill_after_grace_period(self):
		"""Test Unix path: SIGKILL sent after SIGTERM grace period expires."""
		from browser_use.skill_cli.tunnel import _kill_process

		with _unix_test_context():
			call_count = [0]

			def fake_is_alive(pid: int) -> bool:
				call_count[0] += 1
				return True  # Always alive — forces SIGKILL path

			with patch('os.kill') as mock_kill:
				with patch(
					'browser_use.skill_cli.tunnel._is_process_alive',
					side_effect=fake_is_alive,
				):
					result = _kill_process(1234)

			assert result is True
			# SIGTERM first, then SIGKILL after 10 sleeps
			assert mock_kill.call_count == 2
			mock_kill.assert_any_call(1234, 15)  # SIGTERM
			mock_kill.assert_any_call(1234, 9)  # SIGKILL
			# 10 grace-period _is_process_alive checks (always alive) → SIGKILL sent
			assert call_count[0] == 10

	def test_kill_process_unix_process_not_found(self):
		"""Test Unix path: ProcessLookupError when process doesn't exist."""
		from browser_use.skill_cli.tunnel import _kill_process

		with _unix_test_context():
			with patch('os.kill', side_effect=ProcessLookupError('No such process')):
				result = _kill_process(9999)

			assert result is False


# =============================================================================
# Tests for start_tunnel — platform-specific daemonisation
# =============================================================================


class TestStartTunnelPlatform:
	"""Tests for start_tunnel platform-specific spawn kwargs.

	On Windows, ``creationflags`` must be used instead of ``start_new_session``;
	on Unix, ``start_new_session=True`` is the correct approach.
	These tests spoof ``sys.platform`` to exercise both paths on Linux CI.
	"""

	@pytest.mark.asyncio
	async def test_start_tunnel_windows_passes_creationflags(self):
		"""Windows path: asyncio.create_subprocess_exec receives creationflags."""
		import asyncio
		import subprocess
		import tempfile
		from pathlib import Path

		original_platform = sys.platform
		try:
			sys.platform = 'win32'

			spawned_kwargs: dict[str, Any] = {}

			async def capture_spawn(
				*args: Any, **kwargs: Any
			) -> asyncio.subprocess.Process:
				spawned_kwargs.update(kwargs)
				return MagicMock(spec=asyncio.subprocess.Process)

			mock_log_file = MagicMock()
			mock_log_file.read_text.return_value = 'https://abc123.trycloudflare.com'
			mock_log_file.exists.return_value = True

			with _windows_ctypes_mock():
				with patch('shutil.which', return_value='/usr/bin/cloudflared'):
					with patch(
						'asyncio.create_subprocess_exec',
						side_effect=capture_spawn,
					):
						from browser_use.skill_cli.tunnel import start_tunnel

						# Use a temp dir so _tunnels_dir().mkdir() is a no-op and
						# _get_tunnel_file gives us a real Path for open(log_file_path, 'w')
						with tempfile.TemporaryDirectory() as tmp:
							tmp_path = Path(tmp)
							with patch(
								'browser_use.skill_cli.tunnel._load_tunnel_info',
								return_value=None,
							):
								with patch(
									'browser_use.skill_cli.tunnel._save_tunnel_info',
								):
									with patch(
										'browser_use.skill_cli.tunnel._get_tunnel_file',
										return_value=mock_log_file,
									):
										with patch(
											'browser_use.skill_cli.tunnel._tunnels_dir',
											return_value=tmp_path,
										):
											await start_tunnel(8080)

			# Windows: creationflags present, start_new_session absent
			assert 'creationflags' in spawned_kwargs
			assert (
				spawned_kwargs['creationflags']
				== subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
			)
			assert 'start_new_session' not in spawned_kwargs

		finally:
			sys.platform = original_platform

	@pytest.mark.asyncio
	async def test_start_tunnel_unix_passes_start_new_session(self):
		"""Unix path: asyncio.create_subprocess_exec receives start_new_session=True."""
		import asyncio
		import tempfile
		from pathlib import Path

		original_platform = sys.platform
		try:
			sys.platform = 'linux'

			spawned_kwargs: dict[str, Any] = {}

			async def capture_spawn(
				*args: Any, **kwargs: Any
			) -> asyncio.subprocess.Process:
				spawned_kwargs.update(kwargs)
				return MagicMock(spec=asyncio.subprocess.Process)

			mock_log_file = MagicMock()
			mock_log_file.read_text.return_value = 'https://abc123.trycloudflare.com'
			mock_log_file.exists.return_value = True

			with patch(
				'asyncio.create_subprocess_exec',
				side_effect=capture_spawn,
			):
				with patch('shutil.which', return_value='/usr/bin/cloudflared'):
					from browser_use.skill_cli.tunnel import start_tunnel

					with tempfile.TemporaryDirectory() as tmp:
						tmp_path = Path(tmp)
						with patch(
							'browser_use.skill_cli.tunnel._load_tunnel_info',
							return_value=None,
						):
							with patch(
								'browser_use.skill_cli.tunnel._save_tunnel_info',
							):
								with patch(
									'browser_use.skill_cli.tunnel._get_tunnel_file',
									return_value=mock_log_file,
								):
									with patch(
										'browser_use.skill_cli.tunnel._tunnels_dir',
										return_value=tmp_path,
									):
										await start_tunnel(8080)

			# Unix: start_new_session present, creationflags absent
			assert 'start_new_session' in spawned_kwargs
			assert spawned_kwargs['start_new_session'] is True
			assert 'creationflags' not in spawned_kwargs

		finally:
			sys.platform = original_platform

	def test_kill_process_unix_oserror_on_sigterm(self):
		"""Test Unix path: OSError (non-ProcessLookupError) on SIGTERM returns False."""
		from browser_use.skill_cli.tunnel import _kill_process

		with _unix_test_context():
			with patch("os.kill", side_effect=OSError("Operation not permitted")):
				result = _kill_process(1234)
			assert result is False
