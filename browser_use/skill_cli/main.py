#!/usr/bin/env python3
"""Fast CLI for browser-use. STDLIB ONLY - must start in <50ms.

This is the main entry point for the browser-use CLI. It uses only stdlib
imports to ensure fast startup, delegating heavy operations to the session
server which loads once and stays running.
"""

import argparse
import asyncio
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# =============================================================================
# Early command interception (before heavy imports)
# These commands don't need the session server infrastructure
# =============================================================================

# Handle --mcp flag early to prevent logging initialization
if '--mcp' in sys.argv:
	import logging

	os.environ['BROWSER_USE_LOGGING_LEVEL'] = 'critical'
	os.environ['BROWSER_USE_SETUP_LOGGING'] = 'false'
	logging.disable(logging.CRITICAL)

	import asyncio

	from browser_use.mcp.server import main as mcp_main

	asyncio.run(mcp_main())
	sys.exit(0)


# Helper to find the subcommand (first non-flag argument)
def _get_subcommand() -> str | None:
	"""Get the first non-flag argument (the subcommand)."""
	for arg in sys.argv[1:]:
		if not arg.startswith('-'):
			return arg
	return None


# Handle 'install' command - installs Chromium browser + system dependencies
if _get_subcommand() == 'install':
	import platform

	print('📦 Installing Chromium browser + system dependencies...')
	print('⏳ This may take a few minutes...\n')

	# Build command - only use --with-deps on Linux (it fails on Windows/macOS)
	cmd = ['uvx', 'playwright', 'install', 'chromium']
	if platform.system() == 'Linux':
		cmd.append('--with-deps')
	cmd.append('--no-shell')

	result = subprocess.run(cmd)

	if result.returncode == 0:
		print('\n✅ Installation complete!')
		print('🚀 Ready to use! Run: uvx browser-use')
	else:
		print('\n❌ Installation failed')
		sys.exit(1)
	sys.exit(0)

# Handle 'init' command - generate template files
# Uses _get_subcommand() to check if 'init' is the actual subcommand,
# not just anywhere in argv (prevents hijacking: browser-use run "init something")
if _get_subcommand() == 'init':
	from browser_use.init_cmd import main as init_main

	# Check if --template or -t flag is present without a value
	# If so, just remove it and let init_main handle interactive mode
	if '--template' in sys.argv or '-t' in sys.argv:
		try:
			template_idx = sys.argv.index('--template') if '--template' in sys.argv else sys.argv.index('-t')
			template = sys.argv[template_idx + 1] if template_idx + 1 < len(sys.argv) else None

			# If template is not provided or is another flag, remove the flag and use interactive mode
			if not template or template.startswith('-'):
				if '--template' in sys.argv:
					sys.argv.remove('--template')
				else:
					sys.argv.remove('-t')
		except (ValueError, IndexError):
			pass

	# Remove 'init' from sys.argv so click doesn't see it as an unexpected argument
	sys.argv.remove('init')
	init_main()
	sys.exit(0)

# Handle --template flag directly (without 'init' subcommand)
# Delegate to init_main() which handles full template logic (directories, manifests, etc.)
if '--template' in sys.argv:
	from browser_use.init_cmd import main as init_main

	# Build clean argv for init_main: keep only init-relevant flags
	new_argv = [sys.argv[0]]  # program name

	i = 1
	while i < len(sys.argv):
		arg = sys.argv[i]
		# Keep --template/-t and its value
		if arg in ('--template', '-t'):
			new_argv.append(arg)
			if i + 1 < len(sys.argv) and not sys.argv[i + 1].startswith('-'):
				new_argv.append(sys.argv[i + 1])
				i += 1
		# Keep --output/-o and its value
		elif arg in ('--output', '-o'):
			new_argv.append(arg)
			if i + 1 < len(sys.argv) and not sys.argv[i + 1].startswith('-'):
				new_argv.append(sys.argv[i + 1])
				i += 1
		# Keep --force/-f and --list/-l flags
		elif arg in ('--force', '-f', '--list', '-l'):
			new_argv.append(arg)
		# Skip other flags (--session, --browser, --headed, etc.)
		i += 1

	sys.argv = new_argv
	init_main()
	sys.exit(0)

# =============================================================================
# Utility functions (inlined to avoid imports)
# =============================================================================


def get_socket_path(session: str) -> str:
	"""Get socket path for session."""
	if sys.platform == 'win32':
		# Use 127.0.0.1 explicitly (not localhost) to avoid IPv6 binding issues
		port = 49152 + (int(hashlib.md5(session.encode()).hexdigest()[:4], 16) % 16383)
		return f'tcp://127.0.0.1:{port}'
	return str(Path(tempfile.gettempdir()) / f'browser-use-{session}.sock')


def get_pid_path(session: str) -> Path:
	"""Get PID file path for session."""
	return Path(tempfile.gettempdir()) / f'browser-use-{session}.pid'


def _pid_exists(pid: int) -> bool:
	"""Check if a process with given PID exists.

	On Windows, uses ctypes to call OpenProcess (os.kill doesn't work reliably).
	On Unix, uses os.kill(pid, 0) which is the standard approach.
	"""
	if sys.platform == 'win32':
		import ctypes

		PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
		handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
		if handle:
			ctypes.windll.kernel32.CloseHandle(handle)
			return True
		return False
	else:
		try:
			os.kill(pid, 0)
			return True
		except OSError:
			return False


def is_server_running(session: str) -> bool:
	"""Check if server is running for session."""
	pid_path = get_pid_path(session)
	if not pid_path.exists():
		return False
	try:
		pid = int(pid_path.read_text().strip())
		return _pid_exists(pid)
	except (OSError, ValueError):
		# Can't read PID file or invalid PID
		return False


def connect_to_server(session: str, timeout: float = 60.0) -> socket.socket:
	"""Connect to session server."""
	sock_path = get_socket_path(session)

	if sock_path.startswith('tcp://'):
		# Windows: TCP connection
		_, hostport = sock_path.split('://', 1)
		host, port = hostport.split(':')
		sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		sock.settimeout(timeout)
		sock.connect((host, int(port)))
	else:
		# Unix socket
		sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
		sock.settimeout(timeout)
		sock.connect(sock_path)

	return sock


def get_session_metadata_path(session: str) -> Path:
	"""Get path to session metadata file (stores browser_mode, headed, profile)."""
	return Path(tempfile.gettempdir()) / f'browser-use-{session}.meta'


def ensure_server(session: str, browser: str, headed: bool, profile: str | None, api_key: str | None) -> bool:
	"""Start server if not running. Returns True if started."""
	from browser_use.skill_cli.utils import is_session_locked, kill_orphaned_server

	meta_path = get_session_metadata_path(session)

	# Check if server is already running AND holding its lock (healthy server)
	if is_server_running(session) and is_session_locked(session):
		try:
			sock = connect_to_server(session, timeout=0.5)  # Increased from 0.1s
			sock.close()

			# Check browser mode matches existing session
			if meta_path.exists():
				try:
					meta = json.loads(meta_path.read_text())
					existing_mode = meta.get('browser_mode', 'chromium')
					if existing_mode != browser:
						# Only error if user explicitly requested 'remote' but session is local
						# This prevents losing cloud features (live_url, etc.)
						# The reverse case (requesting local but having remote) is fine -
						# user still gets a working browser, just with more features
						if browser == 'remote' and existing_mode != 'remote':
							print(
								f"Error: Session '{session}' is running with --browser {existing_mode}, "
								f'but --browser remote was requested.\n\n'
								f'Cloud browser features (live_url) require a remote session.\n\n'
								f'Options:\n'
								f'  1. Close and restart: browser-use close && browser-use --browser remote open <url>\n'
								f'  2. Use different session: browser-use --browser remote --session other <command>\n'
								f'  3. Use existing local browser: browser-use --browser {existing_mode} <command>',
								file=sys.stderr,
							)
							sys.exit(1)
				except (json.JSONDecodeError, OSError):
					pass  # Metadata file corrupt, ignore

			return False  # Already running with correct mode
		except Exception:
			pass  # Server not responsive, continue to restart logic

	# Kill any orphaned server (has PID file but no lock)
	kill_orphaned_server(session)

	# Build server command
	cmd = [
		sys.executable,
		'-m',
		'browser_use.skill_cli.server',
		'--session',
		session,
		'--browser',
		browser,
	]
	if headed:
		cmd.append('--headed')
	if profile:
		cmd.extend(['--profile', profile])

	# Set up environment
	env = os.environ.copy()
	if api_key:
		env['BROWSER_USE_API_KEY'] = api_key

	# Start server as background process
	if sys.platform == 'win32':
		# Windows: CREATE_NO_WINDOW prevents console window from appearing
		# CREATE_NEW_PROCESS_GROUP allows the process to survive parent exit
		subprocess.Popen(
			cmd,
			env=env,
			creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW,
			stdout=subprocess.DEVNULL,
			stderr=subprocess.DEVNULL,
		)
	else:
		# Unix: use start_new_session
		subprocess.Popen(
			cmd,
			env=env,
			start_new_session=True,
			stdout=subprocess.DEVNULL,
			stderr=subprocess.DEVNULL,
		)

	# Wait for server to be ready (must have PID, lock, and responsive socket)
	for _ in range(100):  # 5 seconds max
		if is_server_running(session) and is_session_locked(session):
			try:
				sock = connect_to_server(session, timeout=0.5)
				sock.close()

				# Write metadata file to track session config
				meta_path.write_text(
					json.dumps(
						{
							'browser_mode': browser,
							'headed': headed,
							'profile': profile,
						}
					)
				)

				return True
			except Exception:
				pass
		time.sleep(0.05)

	print('Error: Failed to start session server', file=sys.stderr)
	sys.exit(1)


def send_command(session: str, action: str, params: dict) -> dict:
	"""Send command to server and get response."""
	request = {
		'id': f'r{int(time.time() * 1000000) % 1000000}',
		'action': action,
		'session': session,
		'params': params,
	}

	sock = connect_to_server(session)
	try:
		# Send request
		sock.sendall((json.dumps(request) + '\n').encode())

		# Read response
		data = b''
		while not data.endswith(b'\n'):
			chunk = sock.recv(4096)
			if not chunk:
				break
			data += chunk

		if not data:
			return {'id': request['id'], 'success': False, 'error': 'No response from server'}

		return json.loads(data.decode())
	finally:
		sock.close()


# =============================================================================
# CLI Commands
# =============================================================================


def build_parser() -> argparse.ArgumentParser:
	"""Build argument parser with all commands."""
	# Import install config to get available modes and default
	from browser_use.skill_cli.install_config import get_available_modes, get_default_mode

	available_modes = get_available_modes()
	default_mode = get_default_mode()

	# Build epilog dynamically based on available modes
	epilog_parts = []

	if 'chromium' in available_modes or 'real' in available_modes:
		epilog_parts.append("""Local Mode (default):
  browser-use run "Fill the form"               # Uses local browser + your API keys
  browser-use run "task" --llm gpt-4o           # Specify model (requires API key)
  browser-use open https://example.com""")

	if 'remote' in available_modes:
		if 'chromium' in available_modes:
			# Full install - show how to switch to remote
			epilog_parts.append("""
Remote Mode (--browser remote):
  browser-use -b remote run "task"              # Cloud execution (US proxy default)
  browser-use -b remote run "task" --llm gpt-4o # Specify cloud model
  browser-use -b remote --profile <id> run "task"  # Use cloud profile
  browser-use -b remote run "task" --proxy-country gb     # UK proxy
  browser-use -b remote run "task" --session-id <id>      # Reuse session
  browser-use -b remote run "task" --wait       # Wait for completion

Task Management:
  browser-use task list                         # List recent cloud tasks
  browser-use task status <task-id>             # Check task status
  browser-use task stop <task-id>               # Stop running task""")
		else:
			# Remote-only install
			epilog_parts.append("""
Examples:
  browser-use run "task"                        # Cloud execution (US proxy default)
  browser-use run "task" --llm gpt-4o           # Specify model
  browser-use --profile <id> run "task"         # Use cloud profile
  browser-use run "task" --proxy-country gb     # UK proxy
  browser-use run "task" --session-id <id>      # Reuse existing session
  browser-use run "task" --wait                 # Wait for completion

Task Management:
  browser-use task list                         # List recent cloud tasks
  browser-use task status <task-id>             # Check task status
  browser-use task stop <task-id>               # Stop running task""")

	epilog_parts.append("""
Setup:
  browser-use install                           # Install Chromium browser
  browser-use init                              # Generate template file""")

	parser = argparse.ArgumentParser(
		prog='browser-use',
		description='Browser automation CLI for browser-use',
		formatter_class=argparse.RawDescriptionHelpFormatter,
		epilog='\n'.join(epilog_parts),
	)

	# Global flags
	parser.add_argument('--session', '-s', default='default', help='Session name (default: default)')
	parser.add_argument(
		'--browser',
		'-b',
		choices=available_modes,
		default=default_mode,
		help=f'Browser mode (available: {", ".join(available_modes)})',
	)
	parser.add_argument('--headed', action='store_true', help='Show browser window')
	parser.add_argument('--profile', help='Browser profile (local name or cloud ID)')
	parser.add_argument('--json', action='store_true', help='Output as JSON')
	parser.add_argument('--api-key', help='Browser-Use API key')
	parser.add_argument('--mcp', action='store_true', help='Run as MCP server (JSON-RPC via stdin/stdout)')
	parser.add_argument('--template', help='Generate template file (use with --output for custom path)')

	subparsers = parser.add_subparsers(dest='command', help='Command to execute')

	# -------------------------------------------------------------------------
	# Setup Commands (handled early, before argparse)
	# -------------------------------------------------------------------------

	# install
	subparsers.add_parser('install', help='Install Chromium browser + system dependencies')

	# init
	p = subparsers.add_parser('init', help='Generate browser-use template file')
	p.add_argument('--template', '-t', help='Template name (interactive if not specified)')
	p.add_argument('--output', '-o', help='Output file path')
	p.add_argument('--force', '-f', action='store_true', help='Overwrite existing files')
	p.add_argument('--list', '-l', action='store_true', help='List available templates')

	# setup
	p = subparsers.add_parser('setup', help='Configure browser-use for first-time use')
	p.add_argument('--mode', choices=['local', 'remote', 'full'], default='local', help='Setup mode (local/remote/full)')
	p.add_argument('--api-key', help='Browser-Use API key')
	p.add_argument('--yes', '-y', action='store_true', help='Skip interactive prompts')

	# doctor
	subparsers.add_parser('doctor', help='Check browser-use installation and dependencies')

	# -------------------------------------------------------------------------
	# Browser Control Commands
	# -------------------------------------------------------------------------

	# open <url>
	p = subparsers.add_parser('open', help='Navigate to URL')
	p.add_argument('url', help='URL to navigate to')

	# click <index> OR click <x> <y>
	p = subparsers.add_parser('click', help='Click element by index or coordinates (x y)')
	p.add_argument('args', nargs='+', type=int, help='Element index OR x y coordinates')

	# type <text>
	p = subparsers.add_parser('type', help='Type text')
	p.add_argument('text', help='Text to type')

	# input <index> <text>
	p = subparsers.add_parser('input', help='Type text into specific element')
	p.add_argument('index', type=int, help='Element index')
	p.add_argument('text', help='Text to type')

	# scroll [up|down]
	p = subparsers.add_parser('scroll', help='Scroll page')
	p.add_argument('direction', nargs='?', default='down', choices=['up', 'down'], help='Scroll direction')
	p.add_argument('--amount', type=int, default=500, help='Scroll amount in pixels')

	# back
	subparsers.add_parser('back', help='Go back in history')

	# screenshot [path]
	p = subparsers.add_parser('screenshot', help='Take screenshot')
	p.add_argument('path', nargs='?', help='Save path (outputs base64 if not provided)')
	p.add_argument('--full', action='store_true', help='Full page screenshot')

	# state
	subparsers.add_parser('state', help='Get browser state (URL, title, elements)')

	# switch <tab>
	p = subparsers.add_parser('switch', help='Switch to tab')
	p.add_argument('tab', type=int, help='Tab index')

	# close-tab [tab]
	p = subparsers.add_parser('close-tab', help='Close tab')
	p.add_argument('tab', type=int, nargs='?', help='Tab index (current if not specified)')

	# keys <keys>
	p = subparsers.add_parser('keys', help='Send keyboard keys')
	p.add_argument('keys', help='Keys to send (e.g., "Enter", "Control+a")')

	# select <index> <value>
	p = subparsers.add_parser('select', help='Select dropdown option')
	p.add_argument('index', type=int, help='Element index')
	p.add_argument('value', help='Value to select')

	# eval <js>
	p = subparsers.add_parser('eval', help='Execute JavaScript')
	p.add_argument('js', help='JavaScript code to execute')

	# extract <query>
	p = subparsers.add_parser('extract', help='Extract data using LLM')
	p.add_argument('query', help='What to extract')

	# hover <index>
	p = subparsers.add_parser('hover', help='Hover over element')
	p.add_argument('index', type=int, help='Element index')

	# dblclick <index>
	p = subparsers.add_parser('dblclick', help='Double-click element')
	p.add_argument('index', type=int, help='Element index')

	# rightclick <index>
	p = subparsers.add_parser('rightclick', help='Right-click element')
	p.add_argument('index', type=int, help='Element index')

	# -------------------------------------------------------------------------
	# Cookies Commands
	# -------------------------------------------------------------------------

	cookies_p = subparsers.add_parser('cookies', help='Cookie operations')
	cookies_sub = cookies_p.add_subparsers(dest='cookies_command')

	# cookies get [--url URL]
	p = cookies_sub.add_parser('get', help='Get all cookies')
	p.add_argument('--url', help='Filter by URL')

	# cookies set <name> <value>
	p = cookies_sub.add_parser('set', help='Set a cookie')
	p.add_argument('name', help='Cookie name')
	p.add_argument('value', help='Cookie value')
	p.add_argument('--domain', help='Cookie domain')
	p.add_argument('--path', default='/', help='Cookie path')
	p.add_argument('--secure', action='store_true', help='Secure cookie')
	p.add_argument('--http-only', action='store_true', help='HTTP-only cookie')
	p.add_argument('--same-site', choices=['Strict', 'Lax', 'None'], help='SameSite attribute')
	p.add_argument('--expires', type=float, help='Expiration timestamp')

	# cookies clear [--url URL]
	p = cookies_sub.add_parser('clear', help='Clear cookies')
	p.add_argument('--url', help='Clear only for URL')

	# cookies export <file>
	p = cookies_sub.add_parser('export', help='Export cookies to JSON file')
	p.add_argument('file', help='Output file path')
	p.add_argument('--url', help='Filter by URL')

	# cookies import <file>
	p = cookies_sub.add_parser('import', help='Import cookies from JSON file')
	p.add_argument('file', help='Input file path')

	# -------------------------------------------------------------------------
	# Wait Commands
	# -------------------------------------------------------------------------

	wait_p = subparsers.add_parser('wait', help='Wait for conditions')
	wait_sub = wait_p.add_subparsers(dest='wait_command')

	# wait selector <css>
	p = wait_sub.add_parser('selector', help='Wait for CSS selector')
	p.add_argument('selector', help='CSS selector')
	p.add_argument('--timeout', type=int, default=30000, help='Timeout in ms')
	p.add_argument('--state', choices=['attached', 'detached', 'visible', 'hidden'], default='visible', help='Element state')

	# wait text <text>
	p = wait_sub.add_parser('text', help='Wait for text')
	p.add_argument('text', help='Text to wait for')
	p.add_argument('--timeout', type=int, default=30000, help='Timeout in ms')

	# -------------------------------------------------------------------------
	# Get Commands (info retrieval)
	# -------------------------------------------------------------------------

	get_p = subparsers.add_parser('get', help='Get information')
	get_sub = get_p.add_subparsers(dest='get_command')

	# get title
	get_sub.add_parser('title', help='Get page title')

	# get html [--selector SELECTOR]
	p = get_sub.add_parser('html', help='Get page HTML')
	p.add_argument('--selector', help='CSS selector to scope HTML')

	# get text <index>
	p = get_sub.add_parser('text', help='Get element text')
	p.add_argument('index', type=int, help='Element index')

	# get value <index>
	p = get_sub.add_parser('value', help='Get input element value')
	p.add_argument('index', type=int, help='Element index')

	# get attributes <index>
	p = get_sub.add_parser('attributes', help='Get element attributes')
	p.add_argument('index', type=int, help='Element index')

	# get bbox <index>
	p = get_sub.add_parser('bbox', help='Get element bounding box')
	p.add_argument('index', type=int, help='Element index')

	# -------------------------------------------------------------------------
	# Python Execution
	# -------------------------------------------------------------------------

	p = subparsers.add_parser('python', help='Execute Python code')
	p.add_argument('code', nargs='?', help='Python code to execute')
	p.add_argument('--file', '-f', help='Execute Python file')
	p.add_argument('--reset', action='store_true', help='Reset Python namespace')
	p.add_argument('--vars', action='store_true', help='Show defined variables')

	# -------------------------------------------------------------------------
	# Agent Tasks
	# -------------------------------------------------------------------------

	from browser_use.skill_cli.install_config import is_mode_available

	remote_available = is_mode_available('remote')
	local_available = is_mode_available('chromium')

	p = subparsers.add_parser('run', help='Run agent task (requires API key)')
	p.add_argument('task', help='Task description')
	p.add_argument('--max-steps', type=int, help='Maximum steps')
	# Model selection (works both locally and remotely)
	p.add_argument('--llm', help='LLM model (gpt-4o, claude-sonnet-4-20250514, gemini-2.0-flash)')

	# Cloud-only flags - only show if remote mode is available
	if remote_available:
		# Add [remote] hint only if both modes are available (--full install)
		remote_hint = '[remote] ' if local_available else ''
		p.add_argument('--session-id', help=f'{remote_hint}Reuse existing cloud session ID')
		p.add_argument('--proxy-country', help=f'{remote_hint}Proxy country code')
		p.add_argument('--stream', action='store_true', help=f'{remote_hint}Stream output in real-time')
		p.add_argument('--wait', action='store_true', help=f'{remote_hint}Wait for task to complete (default: async)')
		p.add_argument('--flash', action='store_true', help=f'{remote_hint}Enable flash mode')
		p.add_argument('--keep-alive', action='store_true', help=f'{remote_hint}Keep session alive after task')
		p.add_argument('--thinking', action='store_true', help=f'{remote_hint}Enable extended reasoning')
		p.add_argument('--vision', action='store_true', default=None, help=f'{remote_hint}Enable vision')
		p.add_argument('--no-vision', action='store_true', help=f'{remote_hint}Disable vision')
		# New SDK features
		p.add_argument('--start-url', help=f'{remote_hint}URL to start the task from')
		p.add_argument('--metadata', action='append', metavar='KEY=VALUE', help=f'{remote_hint}Task metadata (can repeat)')
		p.add_argument('--secret', action='append', metavar='KEY=VALUE', help=f'{remote_hint}Task secrets (can repeat)')
		p.add_argument(
			'--allowed-domain',
			action='append',
			metavar='DOMAIN',
			help=f'{remote_hint}Restrict navigation to domains (can repeat)',
		)
		p.add_argument('--skill-id', action='append', metavar='ID', help=f'{remote_hint}Enable skill IDs (can repeat)')
		p.add_argument('--structured-output', metavar='SCHEMA', help=f'{remote_hint}JSON schema for structured output')
		p.add_argument('--judge', action='store_true', help=f'{remote_hint}Enable judge mode')
		p.add_argument('--judge-ground-truth', metavar='TEXT', help=f'{remote_hint}Expected answer for judge evaluation')

	# -------------------------------------------------------------------------
	# Task Management (Cloud) - only available if remote mode is installed
	# -------------------------------------------------------------------------

	if remote_available:
		task_p = subparsers.add_parser('task', help='Manage cloud tasks')
		task_sub = task_p.add_subparsers(dest='task_command')

		# task list
		p = task_sub.add_parser('list', help='List recent tasks')
		p.add_argument('--limit', type=int, default=10, help='Maximum number of tasks to list')
		p.add_argument('--status', choices=['running', 'finished', 'stopped', 'failed'], help='Filter by status')
		p.add_argument('--session', help='Filter by session ID')
		p.add_argument('--json', action='store_true', help='Output as JSON')

		# task status <task_id>
		p = task_sub.add_parser('status', help='Get task status')
		p.add_argument('task_id', help='Task ID')
		p.add_argument('--compact', '-c', action='store_true', help='Show all steps with reasoning')
		p.add_argument('--verbose', '-v', action='store_true', help='Show all steps with full details (URLs, actions)')
		p.add_argument('--last', '-n', type=int, metavar='N', help='Show only the last N steps')
		p.add_argument('--reverse', '-r', action='store_true', help='Show steps newest first (100, 99, 98...)')
		p.add_argument('--step', '-s', type=int, metavar='N', help='Show specific step number')
		p.add_argument('--json', action='store_true', help='Output as JSON')

		# task stop <task_id>
		p = task_sub.add_parser('stop', help='Stop running task')
		p.add_argument('task_id', help='Task ID')
		p.add_argument('--json', action='store_true', help='Output as JSON')

		# task logs <task_id>
		p = task_sub.add_parser('logs', help='Get task logs')
		p.add_argument('task_id', help='Task ID')
		p.add_argument('--json', action='store_true', help='Output as JSON')

	# -------------------------------------------------------------------------
	# Cloud Session Management - only available if remote mode is installed
	# -------------------------------------------------------------------------

	if remote_available:
		session_p = subparsers.add_parser('session', help='Manage cloud sessions')
		session_sub = session_p.add_subparsers(dest='session_command')

		# session list
		p = session_sub.add_parser('list', help='List cloud sessions')
		p.add_argument('--limit', type=int, default=10, help='Maximum number of sessions to list')
		p.add_argument('--status', choices=['active', 'stopped'], help='Filter by status')
		p.add_argument('--json', action='store_true', help='Output as JSON')

		# session get <session_id>
		p = session_sub.add_parser('get', help='Get session details')
		p.add_argument('session_id', help='Session ID')
		p.add_argument('--json', action='store_true', help='Output as JSON')

		# session stop <session_id> or session stop --all
		p = session_sub.add_parser('stop', help='Stop cloud session(s)')
		p.add_argument('session_id', nargs='?', help='Session ID (or use --all)')
		p.add_argument('--all', action='store_true', help='Stop all active sessions')
		p.add_argument('--json', action='store_true', help='Output as JSON')

		# session create - Create session without task
		p = session_sub.add_parser('create', help='Create a new cloud session')
		p.add_argument('--profile', help='Cloud profile ID')
		p.add_argument('--proxy-country', help='Proxy country code')
		p.add_argument('--start-url', help='Initial URL to navigate to')
		p.add_argument('--screen-size', metavar='WxH', help='Screen size (e.g., 1920x1080)')
		p.add_argument('--keep-alive', action='store_true', default=None, help='Keep session alive')
		p.add_argument('--no-keep-alive', dest='keep_alive', action='store_false', help='Do not keep session alive')
		p.add_argument('--persist-memory', action='store_true', default=None, help='Persist memory between tasks')
		p.add_argument('--no-persist-memory', dest='persist_memory', action='store_false', help='Do not persist memory')
		p.add_argument('--json', action='store_true', help='Output as JSON')

		# session share <session_id> - Create or delete public share
		p = session_sub.add_parser('share', help='Manage public share URL')
		p.add_argument('session_id', help='Session ID')
		p.add_argument('--delete', action='store_true', help='Delete the public share')
		p.add_argument('--json', action='store_true', help='Output as JSON')

	# -------------------------------------------------------------------------
	# Tunnel Commands
	# -------------------------------------------------------------------------

	tunnel_p = subparsers.add_parser('tunnel', help='Expose localhost via Cloudflare tunnel')
	tunnel_p.add_argument(
		'port_or_subcommand',
		nargs='?',
		default=None,
		help='Port number to tunnel, or subcommand (list, stop)',
	)
	tunnel_p.add_argument('port_arg', nargs='?', type=int, help='Port number (for stop subcommand)')
	tunnel_p.add_argument('--all', action='store_true', help='Stop all tunnels (use with: tunnel stop --all)')

	# -------------------------------------------------------------------------
	# Session Management
	# -------------------------------------------------------------------------

	# sessions
	subparsers.add_parser('sessions', help='List active sessions')

	# close
	p = subparsers.add_parser('close', help='Close session')
	p.add_argument('--all', action='store_true', help='Close all sessions')

	# -------------------------------------------------------------------------
	# Server Control
	# -------------------------------------------------------------------------

	server_p = subparsers.add_parser('server', help='Server control')
	server_sub = server_p.add_subparsers(dest='server_command')
	server_sub.add_parser('status', help='Check server status')
	server_sub.add_parser('stop', help='Stop server')
	server_sub.add_parser('logs', help='View server logs')

	# -------------------------------------------------------------------------
	# Profile Management (mode-aware: use -b real or -b remote)
	# -------------------------------------------------------------------------

	profile_p = subparsers.add_parser('profile', help='Manage browser profiles (use -b real or -b remote)')
	profile_sub = profile_p.add_subparsers(dest='profile_command')

	# profile list - lists local or cloud profiles based on -b flag
	p = profile_sub.add_parser('list', help='List profiles (local with -b real, cloud with -b remote)')
	p.add_argument('--page', type=int, default=1, help='Page number (cloud only)')
	p.add_argument('--page-size', type=int, default=20, help='Items per page (cloud only)')

	# profile get <id>
	p = profile_sub.add_parser('get', help='Get profile details')
	p.add_argument('id', help='Profile ID or name')

	# profile create (cloud only)
	p = profile_sub.add_parser('create', help='Create profile (cloud only)')
	p.add_argument('--name', help='Profile name')

	# profile update <id> (cloud only)
	p = profile_sub.add_parser('update', help='Update profile (cloud only)')
	p.add_argument('id', help='Profile ID')
	p.add_argument('--name', required=True, help='New profile name')

	# profile delete <id> (cloud only)
	p = profile_sub.add_parser('delete', help='Delete profile (cloud only)')
	p.add_argument('id', help='Profile ID')

	# profile cookies <id> - list cookies by domain (local only)
	p = profile_sub.add_parser('cookies', help='List cookies by domain (local only, requires -b real)')
	p.add_argument('id', help='Profile ID or name (e.g. "Default", "Profile 1")')

	# profile sync - sync local profile to cloud
	p = profile_sub.add_parser('sync', help='Sync local Chrome profile to cloud')
	p.add_argument('--from', dest='from_profile', help='Local profile name (e.g. "Default", "Profile 1")')
	p.add_argument('--name', help='Cloud profile name (default: auto-generated)')
	p.add_argument('--domain', help='Only sync cookies for this domain (e.g. "youtube.com")')

	return parser


def handle_server_command(args: argparse.Namespace) -> int:
	"""Handle server subcommands."""
	if args.server_command == 'status':
		if is_server_running(args.session):
			print(f'Server for session "{args.session}" is running')
			return 0
		else:
			print(f'Server for session "{args.session}" is not running')
			return 1

	elif args.server_command == 'stop':
		if not is_server_running(args.session):
			print(f'Server for session "{args.session}" is not running')
			return 0
		response = send_command(args.session, 'shutdown', {})
		if response.get('success'):
			print(f'Server for session "{args.session}" stopped')
			return 0
		else:
			print(f'Error: {response.get("error")}', file=sys.stderr)
			return 1

	elif args.server_command == 'logs':
		log_path = Path(tempfile.gettempdir()) / f'browser-use-{args.session}.log'
		if log_path.exists():
			print(log_path.read_text())
		else:
			print('No logs found')
		return 0

	return 0


def _parse_key_value_list(items: list[str] | None) -> dict[str, str | None] | None:
	"""Parse a list of 'key=value' strings into a dict."""
	if not items:
		return None
	result: dict[str, str | None] = {}
	for item in items:
		if '=' in item:
			key, value = item.split('=', 1)
			result[key] = value
	return result if result else None


def _handle_remote_run_with_wait(args: argparse.Namespace) -> int:
	"""Handle remote run with --wait directly (prints task info immediately, then waits)."""
	import asyncio

	from browser_use.skill_cli.commands import cloud_session, cloud_task

	if not args.task:
		print('Error: No task provided', file=sys.stderr)
		return 1

	try:
		# Handle vision flag (--vision vs --no-vision)
		vision: bool | None = None
		if getattr(args, 'vision', False):
			vision = True
		elif getattr(args, 'no_vision', False):
			vision = False

		# Parse key=value list params
		metadata = _parse_key_value_list(getattr(args, 'metadata', None))
		secrets = _parse_key_value_list(getattr(args, 'secret', None))

		# Build session params
		session_id = getattr(args, 'session_id', None)
		profile_id = getattr(args, 'profile', None)
		proxy_country = getattr(args, 'proxy_country', None)

		# Create session first if profile or proxy specified and no session_id
		if (profile_id or proxy_country) and not session_id:
			session = cloud_session.create_session(
				profile_id=profile_id,
				proxy_country=proxy_country,
				keep_alive=getattr(args, 'keep_alive', None),
			)
			session_id = session.id

		# Create task with all cloud-only flags
		task_response = cloud_task.create_task(
			task=args.task,
			llm=args.llm,
			session_id=session_id,
			max_steps=args.max_steps,
			flash_mode=getattr(args, 'flash', None),
			thinking=getattr(args, 'thinking', None),
			vision=vision,
			start_url=getattr(args, 'start_url', None),
			metadata=metadata,
			secrets=secrets,
			allowed_domains=getattr(args, 'allowed_domain', None),
			skill_ids=getattr(args, 'skill_id', None),
			structured_output=getattr(args, 'structured_output', None),
			judge=getattr(args, 'judge', None),
			judge_ground_truth=getattr(args, 'judge_ground_truth', None),
		)

		# Print initial info immediately
		print(f'mode: {args.browser}')
		print(f'task_id: {task_response.id}')
		print(f'session_id: {task_response.session_id}')
		print('waiting...', end='', flush=True)

		# Wait for completion
		try:
			result = asyncio.run(cloud_task.poll_until_complete(task_response.id))
		except KeyboardInterrupt:
			print(f'\nInterrupted. Task {task_response.id} continues remotely.')
			return 0

		# Print final result
		print(' done.')
		print(f'status: {result.status}')
		print(f'output: {result.output}')
		if result.cost:
			print(f'cost: {result.cost}')

		return 0

	except Exception as e:
		print(f'Error: {e}', file=sys.stderr)
		return 1


def main() -> int:
	"""Main entry point."""
	parser = build_parser()
	args = parser.parse_args()

	if not args.command:
		parser.print_help()
		return 0

	# Handle server subcommands without starting server
	if args.command == 'server':
		return handle_server_command(args)

	# Handle profile subcommands without starting server
	if args.command == 'profile':
		from browser_use.skill_cli.commands.profile import handle_profile_command

		return handle_profile_command(args)

	# Handle sessions list - find all running sessions
	if args.command == 'sessions':
		from browser_use.skill_cli.utils import find_all_sessions

		session_names = find_all_sessions()
		sessions = [{'name': name, 'status': 'running'} for name in session_names]

		if args.json:
			print(json.dumps(sessions))
		else:
			if sessions:
				for s in sessions:
					print(f'  {s["name"]}: {s["status"]}')
			else:
				print('No active sessions')
		return 0

	# Handle close --all by closing all running sessions
	if args.command == 'close' and getattr(args, 'all', False):
		from browser_use.skill_cli.utils import find_all_sessions

		session_names = find_all_sessions()
		closed = []
		for name in session_names:
			try:
				response = send_command(name, 'close', {})
				if response.get('success'):
					closed.append(name)
					# Clean up metadata file
					meta_path = get_session_metadata_path(name)
					if meta_path.exists():
						meta_path.unlink()
			except Exception:
				pass  # Server may already be stopping

		if args.json:
			print(json.dumps({'closed': closed, 'count': len(closed)}))
		else:
			if closed:
				print(f'Closed {len(closed)} session(s): {", ".join(closed)}')
			else:
				print('No active sessions')
		return 0

	# Handle setup command
	if args.command == 'setup':
		from browser_use.skill_cli.commands import setup

		loop = asyncio.get_event_loop()
		result = loop.run_until_complete(
			setup.handle(
				'setup',
				{
					'mode': args.mode,
					'api_key': args.api_key,
					'yes': args.yes,
					'json': args.json,
				},
			)
		)

		if args.json:
			print(json.dumps(result))
		elif 'error' in result:
			print(f'Error: {result["error"]}', file=sys.stderr)
			return 1
		else:
			if result.get('status') == 'success':
				print('\n✓ Setup complete!')
				print(f'\nMode: {result["mode"]}')
				print('Next: browser-use open https://example.com')
		return 0

	# Handle doctor command
	if args.command == 'doctor':
		from browser_use.skill_cli.commands import doctor

		loop = asyncio.get_event_loop()
		result = loop.run_until_complete(doctor.handle())

		if args.json:
			print(json.dumps(result))
		else:
			# Print check results
			checks = result.get('checks', {})
			print('\nDiagnostics:\n')
			for name, check in checks.items():
				status = check.get('status', 'unknown')
				message = check.get('message', '')
				note = check.get('note', '')
				fix = check.get('fix', '')

				if status == 'ok':
					icon = '✓'
				elif status == 'warning':
					icon = '⚠'
				elif status == 'missing':
					icon = '○'
				else:
					icon = '✗'

				print(f'  {icon} {name}: {message}')
				if note:
					print(f'      {note}')
				if fix:
					print(f'      Fix: {fix}')

			print('')
			if result.get('status') == 'healthy':
				print('✓ All checks passed!')
			else:
				print(f'⚠ {result.get("summary", "Some checks need attention")}')
		return 0

	# Handle task command - cloud task management
	if args.command == 'task':
		from browser_use.skill_cli.commands.cloud_task import handle_task_command

		return handle_task_command(args)

	# Handle session command - cloud session management
	if args.command == 'session':
		from browser_use.skill_cli.commands.cloud_session import handle_session_command

		return handle_session_command(args)

	# Handle tunnel command - runs independently of browser session
	if args.command == 'tunnel':
		from browser_use.skill_cli import tunnel

		pos = getattr(args, 'port_or_subcommand', None)

		if pos == 'list':
			result = tunnel.list_tunnels()
		elif pos == 'stop':
			port_arg = getattr(args, 'port_arg', None)
			if getattr(args, 'all', False):
				# stop --all
				result = asyncio.get_event_loop().run_until_complete(tunnel.stop_all_tunnels())
			elif port_arg is not None:
				result = asyncio.get_event_loop().run_until_complete(tunnel.stop_tunnel(port_arg))
			else:
				print('Usage: browser-use tunnel stop <port> | --all', file=sys.stderr)
				return 1
		elif pos is not None:
			try:
				port = int(pos)
			except ValueError:
				print(f'Unknown tunnel subcommand: {pos}', file=sys.stderr)
				return 1
			result = asyncio.get_event_loop().run_until_complete(tunnel.start_tunnel(port))
		else:
			print('Usage: browser-use tunnel <port> | list | stop <port>', file=sys.stderr)
			return 0

		# Output result
		if args.json:
			print(json.dumps(result))
		else:
			if 'error' in result:
				print(f'Error: {result["error"]}', file=sys.stderr)
				return 1
			elif 'url' in result:
				existing = ' (existing)' if result.get('existing') else ''
				print(f'url: {result["url"]}{existing}')
			elif 'tunnels' in result:
				if result['tunnels']:
					for t in result['tunnels']:
						print(f'  port {t["port"]}: {t["url"]}')
				else:
					print('No active tunnels')
			elif 'stopped' in result:
				if isinstance(result['stopped'], list):
					if result['stopped']:
						print(f'Stopped {len(result["stopped"])} tunnel(s): {", ".join(map(str, result["stopped"]))}')
					else:
						print('No tunnels to stop')
				else:
					print(f'Stopped tunnel on port {result["stopped"]}')
		return 0

	# Validate requested mode is available based on installation config
	from browser_use.skill_cli.install_config import get_mode_unavailable_error, is_mode_available

	if not is_mode_available(args.browser):
		print(get_mode_unavailable_error(args.browser), file=sys.stderr)
		return 1

	# Set API key in environment if provided
	if args.api_key:
		os.environ['BROWSER_USE_API_KEY'] = args.api_key

	# Validate API key for remote browser mode upfront
	if args.browser == 'remote':
		from browser_use.skill_cli.api_key import APIKeyRequired, require_api_key

		try:
			api_key = require_api_key('Remote browser')
			# Ensure it's in environment for the cloud client
			os.environ['BROWSER_USE_API_KEY'] = api_key
		except APIKeyRequired as e:
			print(f'Error: {e}', file=sys.stderr)
			return 1

	# Validate --profile flag usage
	if args.profile and args.browser == 'chromium':
		print(
			'Error: --profile is not supported in chromium mode.\n'
			'Use -b real for local Chrome profiles or -b remote for cloud profiles.',
			file=sys.stderr,
		)
		return 1

	# Handle remote run with --wait directly (prints task_id immediately, then waits)
	if args.browser == 'remote' and args.command == 'run' and getattr(args, 'wait', False):
		return _handle_remote_run_with_wait(args)

	# Ensure server is running
	ensure_server(args.session, args.browser, args.headed, args.profile, args.api_key)

	# Build params from args
	params = {}
	skip_keys = {'command', 'session', 'browser', 'headed', 'json', 'api_key', 'server_command'}

	for key, value in vars(args).items():
		if key not in skip_keys and value is not None:
			params[key] = value

	# Add profile to params for commands that need it (agent tasks, etc.)
	# Note: profile is passed to ensure_server for local browser profile,
	# but also needs to be in params for cloud profile ID in remote mode
	if args.profile:
		params['profile'] = args.profile

	# Send command to server
	response = send_command(args.session, args.command, params)

	# Clean up metadata file on successful close
	if args.command == 'close' and response.get('success'):
		meta_path = get_session_metadata_path(args.session)
		if meta_path.exists():
			meta_path.unlink()

	# Output response
	if args.json:
		# Add mode to JSON output for browser-related commands
		if args.command in ('open', 'run', 'state', 'click', 'type', 'input', 'scroll', 'screenshot'):
			response['mode'] = args.browser
		print(json.dumps(response))
	else:
		if response.get('success'):
			data = response.get('data')
			# Show mode for browser-related commands (first line of output)
			if args.command in ('open', 'run'):
				print(f'mode: {args.browser}')
			if data is not None:
				if isinstance(data, dict):
					# Special case: raw text output (e.g., state command)
					if '_raw_text' in data:
						print(data['_raw_text'])
					else:
						for key, value in data.items():
							# Skip internal fields
							if key.startswith('_'):
								continue
							if key == 'screenshot' and len(str(value)) > 100:
								print(f'{key}: <{len(value)} bytes>')
							else:
								print(f'{key}: {value}')
				elif isinstance(data, str):
					print(data)
				else:
					print(data)
		else:
			print(f'Error: {response.get("error")}', file=sys.stderr)
			return 1

	return 0


if __name__ == '__main__':
	sys.exit(main())
