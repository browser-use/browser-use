#!/usr/bin/env python3
"""
Browser-Use MCP Server Launcher

Convenience functions and utilities for starting and managing the MCP server.
"""

import logging
import subprocess
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def find_server_script() -> Path:
	"""Find the MCP server script path"""
	server_path = Path(__file__).parent / 'server.py'
	if not server_path.exists():
		raise FileNotFoundError(f'MCP server script not found at {server_path}')
	return server_path


def start_mcp_server(
	python_executable: Optional[str] = None, server_host: str = '127.0.0.1', server_port: int = 8766
) -> subprocess.Popen:
	"""
	Start the MCP server in a subprocess.

	Args:
		python_executable: Python executable to use (defaults to sys.executable)
		server_host: Host for the Browser Action Server
		server_port: Port for the Browser Action Server

	Returns:
		Subprocess Popen object
	"""
	if python_executable is None:
		python_executable = sys.executable

	server_script = find_server_script()

	# Environment variables for server configuration
	env = {
		'BROWSER_ACTION_SERVER_HOST': server_host,
		'BROWSER_ACTION_SERVER_PORT': str(server_port),
	}

	# Start the MCP server
	process = subprocess.Popen(
		[python_executable, str(server_script)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
	)

	logger.info(f'Started MCP server (PID: {process.pid})')
	return process


def get_claude_mcp_config(
	server_name: str = 'browser-use',
	python_executable: Optional[str] = None,
	server_host: str = '127.0.0.1',
	server_port: int = 8766,
) -> dict:
	"""
	Generate configuration for `claude mcp add` command.

	Args:
		server_name: Name for the MCP server
		python_executable: Python executable to use
		server_host: Host for the Browser Action Server
		server_port: Port for the Browser Action Server

	Returns:
		Dictionary with MCP server configuration
	"""
	if python_executable is None:
		python_executable = sys.executable

	server_script = find_server_script()

	return {
		'mcpServers': {
			server_name: {
				'command': python_executable,
				'args': [str(server_script)],
				'env': {'BROWSER_ACTION_SERVER_HOST': server_host, 'BROWSER_ACTION_SERVER_PORT': str(server_port)},
			}
		}
	}


def print_claude_mcp_instructions(server_name: str = 'browser-use', python_executable: Optional[str] = None):
	"""
	Print instructions for adding the MCP server to Claude Code.

	Args:
		server_name: Name for the MCP server
		python_executable: Python executable to use
	"""
	if python_executable is None:
		python_executable = sys.executable

	server_script = find_server_script()

	print('🔧 Browser-Use MCP Server Setup')
	print('=' * 50)
	print()
	print('To add this MCP server to Claude Code, run:')
	print()
	print(f'claude mcp add {server_name} {python_executable} {server_script}')
	print()
	print('Or with custom scope:')
	print()
	print(f'claude mcp add --scope user {server_name} {python_executable} {server_script}')
	print()
	print('Available tools after setup:')
	print('• browser_navigate(url, wait_until, timeout)')
	print('• browser_click(selector, timeout)')
	print('• browser_type(selector, text, timeout)')
	print('• browser_screenshot(timeout)')
	print('• browser_scroll(direction, amount, timeout)')
	print('• browser_status(timeout)')
	print('• browser_wait_for_element(selector, timeout)')
	print('• browser_server_status()')
	print('• browser_server_start(port, debug)')
	print()


if __name__ == '__main__':
	print_claude_mcp_instructions()
