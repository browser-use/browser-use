"""Tests for skill_cli/utils.py platform utilities."""

import os

from browser_use.skill_cli.utils import (
	_is_process_running,
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


class TestIsServerRunning:
	"""Tests for is_server_running function."""

	def test_no_pid_file_returns_false(self, tmp_path):
		"""Test that missing PID file returns False."""
		# Create a temp PID path that doesn't exist
		from browser_use.skill_cli import utils

		original_func = utils.get_pid_path
		try:
			utils.get_pid_path = lambda session: tmp_path / 'nonexistent.pid'
			assert is_server_running('test-session') is False
		finally:
			utils.get_pid_path = original_func

	def test_invalid_pid_content_returns_false(self, tmp_path):
		"""Test that invalid PID content returns False."""
		from browser_use.skill_cli import utils

		pid_file = tmp_path / 'test.pid'
		pid_file.write_text('not-a-number')

		original_func = utils.get_pid_path
		try:
			utils.get_pid_path = lambda session: pid_file
			assert is_server_running('test-session') is False
		finally:
			utils.get_pid_path = original_func

	def test_dead_process_returns_false(self, tmp_path):
		"""Test that a non-existent PID returns False."""
		from browser_use.skill_cli import utils

		pid_file = tmp_path / 'test.pid'
		pid_file.write_text('999999999')  # Non-existent PID

		original_func = utils.get_pid_path
		try:
			utils.get_pid_path = lambda session: pid_file
			assert is_server_running('test-session') is False
		finally:
			utils.get_pid_path = original_func

	def test_running_process_returns_true(self, tmp_path):
		"""Test that a running PID returns True."""
		from browser_use.skill_cli import utils

		pid_file = tmp_path / 'test.pid'
		pid_file.write_text(str(os.getpid()))  # Current process

		original_func = utils.get_pid_path
		try:
			utils.get_pid_path = lambda session: pid_file
			assert is_server_running('test-session') is True
		finally:
			utils.get_pid_path = original_func
