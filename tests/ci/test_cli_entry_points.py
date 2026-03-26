"""Tests for CLI entry points (setup, doctor, tunnel) via the CLI.

These tests exercise the actual CLI entry points by invoking the main()
function, verifying that asyncio.run() is correctly used for Python 3.14
compatibility.
"""

import asyncio
import sys
from unittest.mock import patch

from browser_use.skill_cli import main as cli_main


class TestCliSetup:
	"""Tests for browser-use setup CLI entry point."""

	def test_setup_cli_entry_point_json(self):
		"""Test that setup command can be invoked via main() with --json flag."""
		# Mock the setup.handle to avoid actual system checks
		with patch('browser_use.skill_cli.commands.setup.handle') as mock_handle:
			mock_handle.return_value = {'status': 'success', 'checks': {}, 'validation': {}}
			# --json is a global flag that goes before the subcommand
			with patch.object(sys, 'argv', ['browser-use', '--json', 'setup']):
				exit_code = cli_main.main()
			assert exit_code == 0
			mock_handle.assert_called_once()

	def test_setup_cli_entry_point_with_yes_flag(self):
		"""Test that setup --yes can be invoked via main()."""
		with patch('browser_use.skill_cli.commands.setup.handle') as mock_handle:
			mock_handle.return_value = {'status': 'success', 'checks': {}, 'validation': {}}
			# Use --json to avoid UnicodeEncodeError from checkmark character on Windows GBK
			with patch.object(sys, 'argv', ['browser-use', '--json', 'setup', '--yes']):
				exit_code = cli_main.main()
			assert exit_code == 0
			# Verify handle was called with yes=True
			call_args = mock_handle.call_args
			assert call_args[0][1].get('yes') is True


class TestCliDoctor:
	"""Tests for browser-use doctor CLI entry point."""

	def test_doctor_cli_entry_point_json(self):
		"""Test that doctor command can be invoked via main() with --json flag."""
		with patch('browser_use.skill_cli.commands.doctor.handle') as mock_handle:
			mock_handle.return_value = {'status': 'healthy', 'checks': {}, 'summary': 'All checks passed'}
			with patch.object(sys, 'argv', ['browser-use', '--json', 'doctor']):
				exit_code = cli_main.main()
			assert exit_code == 0
			mock_handle.assert_called_once()


class TestCliTunnel:
	"""Tests for browser-use tunnel CLI entry points."""

	def test_tunnel_list_cli_entry_point(self):
		"""Test that tunnel list subcommand can be invoked via main()."""
		with patch('browser_use.skill_cli.tunnel.list_tunnels') as mock_list:
			mock_list.return_value = {'tunnels': []}
			with patch.object(sys, 'argv', ['browser-use', '--json', 'tunnel', 'list']):
				exit_code = cli_main.main()
			assert exit_code == 0
			mock_list.assert_called_once()

	def test_tunnel_stop_cli_entry_point(self):
		"""Test that tunnel stop <port> can be invoked via main()."""
		async def mock_stop(port):
			return {'stopped': port}

		with patch('browser_use.skill_cli.tunnel.stop_tunnel', mock_stop):
			with patch.object(sys, 'argv', ['browser-use', '--json', 'tunnel', 'stop', '8080']):
				exit_code = cli_main.main()
			assert exit_code == 0

	def test_tunnel_stop_all_cli_entry_point(self):
		"""Test that tunnel stop --all can be invoked via main()."""
		async def mock_stop_all():
			return {'stopped': [8080, 8081]}

		with patch('browser_use.skill_cli.tunnel.stop_all_tunnels', mock_stop_all):
			with patch.object(sys, 'argv', ['browser-use', '--json', 'tunnel', 'stop', '--all']):
				exit_code = cli_main.main()
			assert exit_code == 0

	def test_tunnel_unknown_subcommand(self):
		"""Test that unknown tunnel subcommand returns exit code 1."""
		with patch.object(sys, 'argv', ['browser-use', 'tunnel', 'unknown']):
			exit_code = cli_main.main()
		assert exit_code == 1


class TestCliNoDeprecatedGetEventLoop:
	"""Regression tests to ensure asyncio.get_event_loop() is NOT called during CLI execution.

	These tests verify that the deprecated asyncio.get_event_loop() API is absent
	in all CLI commands, preventing Python 3.14+ DeprecationWarning issues.
	"""

	def test_setup_no_get_event_loop(self):
		"""Test that setup command does NOT call asyncio.get_event_loop()."""
		with patch('browser_use.skill_cli.commands.setup.handle') as mock_handle:
			mock_handle.return_value = {'status': 'success', 'checks': {}, 'validation': {}}
			with patch('asyncio.get_event_loop', side_effect=RuntimeError('deprecated get_event_loop called')) as mock_get_loop:
				with patch.object(sys, 'argv', ['browser-use', '--json', 'setup']):
					exit_code = cli_main.main()
				assert exit_code == 0
				mock_get_loop.assert_not_called()

	def test_doctor_no_get_event_loop(self):
		"""Test that doctor command does NOT call asyncio.get_event_loop()."""
		with patch('browser_use.skill_cli.commands.doctor.handle') as mock_handle:
			mock_handle.return_value = {'status': 'healthy', 'checks': {}, 'summary': 'All checks passed'}
			with patch('asyncio.get_event_loop', side_effect=RuntimeError('deprecated get_event_loop called')) as mock_get_loop:
				with patch.object(sys, 'argv', ['browser-use', '--json', 'doctor']):
					exit_code = cli_main.main()
				assert exit_code == 0
				mock_get_loop.assert_not_called()

	def test_tunnel_list_no_get_event_loop(self):
		"""Test that tunnel list command does NOT call asyncio.get_event_loop()."""
		with patch('browser_use.skill_cli.tunnel.list_tunnels') as mock_list:
			mock_list.return_value = {'tunnels': []}
			with patch('asyncio.get_event_loop', side_effect=RuntimeError('deprecated get_event_loop called')) as mock_get_loop:
				with patch.object(sys, 'argv', ['browser-use', '--json', 'tunnel', 'list']):
					exit_code = cli_main.main()
				assert exit_code == 0
				mock_get_loop.assert_not_called()

	def test_tunnel_stop_no_get_event_loop(self):
		"""Test that tunnel stop command does NOT call asyncio.get_event_loop()."""
		async def mock_stop(port):
			return {'stopped': port}

		with patch('browser_use.skill_cli.tunnel.stop_tunnel', mock_stop):
			with patch('asyncio.get_event_loop', side_effect=RuntimeError('deprecated get_event_loop called')) as mock_get_loop:
				with patch.object(sys, 'argv', ['browser-use', '--json', 'tunnel', 'stop', '8080']):
					exit_code = cli_main.main()
				assert exit_code == 0
				mock_get_loop.assert_not_called()

	def test_tunnel_start_no_get_event_loop(self):
		"""Test that tunnel <port> command does NOT call asyncio.get_event_loop()."""
		async def mock_start(port):
			return {'tunnel_id': 'test', 'local_port': port, 'remote_port': 12345}

		with patch('browser_use.skill_cli.tunnel.start_tunnel', mock_start):
			with patch('asyncio.get_event_loop', side_effect=RuntimeError('deprecated get_event_loop called')) as mock_get_loop:
				with patch.object(sys, 'argv', ['browser-use', '--json', 'tunnel', '8080']):
					exit_code = cli_main.main()
				assert exit_code == 0
				mock_get_loop.assert_not_called()

	def test_tunnel_stop_all_no_get_event_loop(self):
		"""Test that tunnel stop --all command does NOT call asyncio.get_event_loop()."""
		async def mock_stop_all():
			return {'stopped': [8080, 8081]}

		with patch('browser_use.skill_cli.tunnel.stop_all_tunnels', mock_stop_all):
			with patch('asyncio.get_event_loop', side_effect=RuntimeError('deprecated get_event_loop called')) as mock_get_loop:
				with patch.object(sys, 'argv', ['browser-use', '--json', 'tunnel', 'stop', '--all']):
					exit_code = cli_main.main()
				assert exit_code == 0
				mock_get_loop.assert_not_called()
