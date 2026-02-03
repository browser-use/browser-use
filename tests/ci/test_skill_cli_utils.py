"""Tests for skill_cli/utils.py platform utilities."""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from browser_use.skill_cli.utils import (
	_is_process_running,
	get_pid_path,
	is_server_running,
)


class TestIsProcessRunning:
	"""Tests for _is_process_running cross-platform function."""

	def test_current_process_is_running(self):
		"""Test that the current process is detected as running."""
		# Our own process should definitely be running
		current_pid = os.getpid()
		assert _is_process_running(current_pid) is True

	def test_nonexistent_pid_is_not_running(self):
		"""Test that a non-existent PID is detected as not running."""
		# Use a very high PID that's unlikely to exist
		nonexistent_pid = 999999999
		assert _is_process_running(nonexistent_pid) is False

	def test_negative_pid_is_not_running(self):
		"""Test that negative PIDs are handled gracefully."""
		# Negative PIDs should return False, not crash
		assert _is_process_running(-1) is False

	def test_zero_pid_is_not_running(self):
		"""Test that zero PID is handled gracefully."""
		# Zero PID should return False
		assert _is_process_running(0) is False

	@pytest.mark.skipif(sys.platform != 'win32', reason='Windows-specific test')
	def test_windows_uses_ctypes(self):
		"""Test that Windows implementation uses ctypes.windll.kernel32."""
		with patch('ctypes.windll.kernel32.OpenProcess') as mock_open:
			with patch('ctypes.windll.kernel32.CloseHandle') as mock_close:
				mock_open.return_value = 12345  # Mock a valid handle
				result = _is_process_running(os.getpid())
				
				mock_open.assert_called_once()
				mock_close.assert_called_once_with(12345)
				assert result is True

	@pytest.mark.skipif(sys.platform == 'win32', reason='Unix-specific test')
	def test_unix_uses_os_kill(self):
		"""Test that Unix implementation uses os.kill with signal 0."""
		with patch('os.kill') as mock_kill:
			mock_kill.return_value = None  # No exception means process exists
			result = _is_process_running(os.getpid())
			
			mock_kill.assert_called_once_with(os.getpid(), 0)
			assert result is True


class TestIsServerRunning:
	"""Tests for is_server_running function."""

	def test_no_pid_file_returns_false(self, tmp_path):
		"""Test that missing PID file returns False."""
		with patch('browser_use.skill_cli.utils.get_pid_path') as mock_path:
			mock_path.return_value = tmp_path / 'nonexistent.pid'
			assert is_server_running('test-session') is False

	def test_invalid_pid_content_returns_false(self, tmp_path):
		"""Test that invalid PID content returns False."""
		pid_file = tmp_path / 'test.pid'
		pid_file.write_text('not-a-number')
		
		with patch('browser_use.skill_cli.utils.get_pid_path') as mock_path:
			mock_path.return_value = pid_file
			assert is_server_running('test-session') is False

	def test_dead_process_returns_false(self, tmp_path):
		"""Test that a non-existent PID returns False."""
		pid_file = tmp_path / 'test.pid'
		pid_file.write_text('999999999')  # Non-existent PID
		
		with patch('browser_use.skill_cli.utils.get_pid_path') as mock_path:
			mock_path.return_value = pid_file
			assert is_server_running('test-session') is False

	def test_running_process_returns_true(self, tmp_path):
		"""Test that a running PID returns True."""
		pid_file = tmp_path / 'test.pid'
		pid_file.write_text(str(os.getpid()))  # Current process
		
		with patch('browser_use.skill_cli.utils.get_pid_path') as mock_path:
			mock_path.return_value = pid_file
			assert is_server_running('test-session') is True
