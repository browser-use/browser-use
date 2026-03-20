#!/usr/bin/env python3
"""Fast CLI for browser-use. STDLIB ONLY - must start in <50ms.

This is the main entry point for the browser-use CLI. It uses only stdlib
imports to ensure fast startup, delegating heavy operations to the daemon
which loads once and stays running.
"""

import argparse
import asyncio
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import zlib
from pathlib import Path

# =============================================================================
# Early command interception (before heavy imports)
# These commands don't need the daemon infrastructure
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
		# Skip other flags (--headed, etc.)
		i += 1

	sys.argv = new_argv
	init_main()
	sys.exit(0)

# Handle 'cloud --help' / 'cloud -h' early — argparse intercepts --help before
# REMAINDER can capture it, so we route to our custom usage printer directly.
# Only intercept when --help is immediately after 'cloud' (not 'cloud v2 --help').
if _get_subcommand() == 'cloud':
	cloud_idx = sys.argv.index('cloud')
	if cloud_idx + 1 < len(sys.argv) and sys.argv[cloud_idx + 1] in ('--help', '-h'):
		from browser_use.skill_cli.commands.cloud import handle_cloud_command

		sys.exit(handle_cloud_command(['--help']))

# =============================================================================
# Utility functions (inlined to avoid imports)
# =============================================================================


def _get_home_dir() -> Path:
	"""Get browser-use home directory.

	Must match utils.get_home_dir().
	"""
	env = os.environ.get('BROWSER_USE_HOME')
	if env:
		d = Path(env).expanduser()
	else:
		d = Path.home() / '.browser-use'
	d.mkdir(parents=True, exist_ok=True)
	return d


def _get_socket_path(session: str = 'default') -> str:
	"""Get daemon socket path for a session.

	Must match utils.get_socket_path().
	"""
	if sys.platform == 'win32':
		port = 49152 + zlib.adler32(session.encode()) % 16383
		return f'tcp://127.0.0.1:{port}'
	return str(_get_home_dir() / f'{session}.sock')


def _get_pid_path(session: str = 'default') -> Path:
	"""Get PID file path for a session.

	Must match utils.get_pid_path().
	"""
	return _get_home_dir() / f'{session}.pid'


def _connect_to_daemon(timeout: float = 60.0, session: str = 'default') -> socket.socket:
	"""Connect to daemon socket."""
	sock_path = _get_socket_path(session)

	if sock_path.startswith('tcp://'):
		_, hostport = sock_path.split('://', 1)
		host, port = hostport.split(':')
		sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		addr: str | tuple[str, int] = (host, int(port))
	else:
		sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
		addr = sock_path

	try:
		sock.settimeout(timeout)
		sock.connect(addr)
	except Exception:
		sock.close()
		raise

	return sock


def _is_daemon_alive(session: str = 'default') -> bool:
	"""Check if daemon is alive by attempting socket connect."""
	try:
		sock = _connect_to_daemon(timeout=0.5, session=session)
		sock.close()
		return True
	except OSError:
		# Clean up stale socket on Unix
		sock_path = _get_socket_path(session)
		if not sock_path.startswith('tcp://'):
			Path(sock_path).unlink(missing_ok=True)
		return False


def ensure_daemon(
	headed: bool,
	profile: str | None,
	cdp_url: str | None = None,
	*,
	session: str = 'default',
	explicit_config: bool = False,
	use_cloud: bool = False,
	cloud_timeout: int | None = None,
	cloud_proxy_country_code: str | None = None,
	cloud_profile_id: str | None = None,
) -> None:
	"""Start daemon if not running. Errors on config mismatch."""
	if _is_daemon_alive(session):
		if not explicit_config:
			return  # Daemon is alive, user didn't request specific config — reuse it

		# User explicitly set --headed/--profile/--cdp-url — check config matches
		try:
			response = send_command('ping', {}, session=session)
			if response.get('success'):
				data = response.get('data', {})
				if (
					data.get('headed') == headed
					and data.get('profile') == profile
					and data.get('cdp_url') == cdp_url
					and data.get('use_cloud') == use_cloud
				):
					return  # Already running with correct config

				# Config mismatch — error, don't auto-restart (avoids orphan cascades)
				print(
					f'Error: Session {session!r} is already running with different config.\n'
					f'Run `browser-use{" --session " + session if session != "default" else ""} close` first.',
					file=sys.stderr,
				)
				sys.exit(1)
			return  # Ping returned failure — daemon alive but can't verify config, reuse it
		except Exception:
			return  # Daemon alive but not responsive — reuse it, can't safely restart

	# Build daemon command
	cmd = [
		sys.executable,
		'-m',
		'browser_use.skill_cli.daemon',
		'--session',
		session,
	]
	if headed:
		cmd.append('--headed')
	if profile:
		cmd.extend(['--profile', profile])
	if cdp_url:
		cmd.extend(['--cdp-url', cdp_url])
	if use_cloud:
		cmd.append('--use-cloud')
	if cloud_timeout is not None:
		cmd.extend(['--cloud-timeout', str(cloud_timeout)])
	if cloud_proxy_country_code is not None:
		cmd.extend(['--cloud-proxy-country', cloud_proxy_country_code])
	if cloud_profile_id is not None:
		cmd.extend(['--cloud-profile-id', cloud_profile_id])

	# Set up environment
	env = os.environ.copy()

	# Start daemon as background process
	if sys.platform == 'win32':
		subprocess.Popen(
			cmd,
			env=env,
			creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW,
			stdout=subprocess.DEVNULL,
			stderr=subprocess.DEVNULL,
		)
	else:
		subprocess.Popen(
			cmd,
			env=env,
			start_new_session=True,
			stdout=subprocess.DEVNULL,
			stderr=subprocess.DEVNULL,
		)

	# Wait for daemon to be ready
	for _ in range(100):  # 5 seconds max
		if _is_daemon_alive(session):
			return
		time.sleep(0.05)

	print('Error: Failed to start daemon', file=sys.stderr)
	sys.exit(1)


def send_command(action: str, params: dict, *, session: str = 'default') -> dict:
	"""Send command to daemon and get response."""
	request = {
		'id': f'r{int(time.time() * 1000000) % 1000000}',
		'action': action,
		'params': params,
	}

	sock = _connect_to_daemon(session=session)
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
			return {'id': request['id'], 'success': False, 'error': 'No response from daemon'}

		return json.loads(data.decode())
	finally:
		sock.close()


# =============================================================================
# CLI Commands
# =============================================================================


def build_parser() -> argparse.ArgumentParser:
	"""Build argument parser with all commands."""
	# Build epilog
	epilog_parts = []

	epilog_parts.append("""Cloud API:
  browser-use cloud login <api-key>             # Save API key
  browser-use cloud connect                     # Provision cloud browser
  browser-use cloud v2 GET /browsers            # List browsers
  browser-use cloud v2 POST /tasks '{...}'      # Create task
  browser-use cloud v2 poll <task-id>           # Poll task until done
  browser-use cloud v2 --help                   # Show API endpoints""")

	epilog_parts.append("""
Setup:
  browser-use open https://example.com          # Navigate to URL
  browser-use install                           # Install Chromium browser
  browser-use init                              # Generate template file""")

	parser = argparse.ArgumentParser(
		prog='browser-use',
		description='Browser automation CLI for browser-use',
		formatter_class=argparse.RawDescriptionHelpFormatter,
		epilog='\n'.join(epilog_parts),
	)

	# Global flags
	parser.add_argument('--headed', action='store_true', help='Show browser window')
	parser.add_argument(
		'--profile',
		nargs='?',
		const='Default',
		default=None,
		help='Use real Chrome with profile (bare --profile uses "Default")',
	)
	parser.add_argument(
		'--cdp-url',
		default=None,
		help='Connect to existing browser via CDP URL (http:// or ws://)',
	)
	parser.add_argument(
		'--connect',
		action='store_true',
		help='Auto-discover and connect to running Chrome via CDP',
	)
	parser.add_argument('--session', default=None, help='Session name (default: "default")')
	parser.add_argument('--json', action='store_true', help='Output as JSON')
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

	# upload <index> <path>
	p = subparsers.add_parser('upload', help='Upload file to file input element')
	p.add_argument('index', type=int, help='Element index of file input')
	p.add_argument('path', help='Path to file to upload')

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

	# close
	close_p = subparsers.add_parser('close', help='Close browser and stop daemon')
	close_p.add_argument('--all', action='store_true', help='Close all sessions')

	# sessions
	subparsers.add_parser('sessions', help='List active browser sessions')

	# -------------------------------------------------------------------------
	# Cloud API (Generic REST passthrough)
	# -------------------------------------------------------------------------

	cloud_p = subparsers.add_parser('cloud', help='Browser-Use Cloud API')
	cloud_p.add_argument('cloud_args', nargs=argparse.REMAINDER, help='cloud subcommand args')

	# -------------------------------------------------------------------------
	# Profile Management
	# -------------------------------------------------------------------------

	profile_p = subparsers.add_parser('profile', help='Manage browser profiles (profile-use)')
	profile_p.add_argument('profile_args', nargs=argparse.REMAINDER, help='profile-use arguments')

	return parser


def _handle_cloud_connect(cloud_args: list[str], args: argparse.Namespace, session: str) -> int:
	"""Handle `browser-use cloud connect` — provision cloud browser and connect."""
	# Parse connect-specific args
	connect_parser = argparse.ArgumentParser(prog='browser-use cloud connect', add_help=False)
	connect_parser.add_argument('--timeout', type=int, default=None, help='Cloud browser timeout in seconds')
	connect_parser.add_argument('--proxy-country', default=None, help='Cloud browser proxy country code')
	connect_parser.add_argument('--profile-id', default=None, help='Cloud browser profile ID')
	connect_args, _ = connect_parser.parse_known_args(cloud_args)

	# Mutual exclusivity checks
	if getattr(args, 'connect', False):
		print('Error: --connect and cloud connect are mutually exclusive', file=sys.stderr)
		return 1
	if args.cdp_url:
		print('Error: --cdp-url and cloud connect are mutually exclusive', file=sys.stderr)
		return 1
	if args.profile:
		print('Error: --profile and cloud connect are mutually exclusive', file=sys.stderr)
		return 1

	# Start daemon with cloud config
	ensure_daemon(
		args.headed,
		None,
		session=session,
		explicit_config=True,
		use_cloud=True,
		cloud_timeout=connect_args.timeout,
		cloud_proxy_country_code=connect_args.proxy_country,
		cloud_profile_id=connect_args.profile_id,
	)

	# Send connect command to force immediate session creation
	response = send_command('connect', {}, session=session)

	if args.json:
		print(json.dumps(response))
	else:
		if response.get('success'):
			data = response.get('data', {})
			print(f'status: {data.get("status", "unknown")}')
			if 'live_url' in data:
				print(f'live_url: {data["live_url"]}')
			if 'cdp_url' in data:
				print(f'cdp_url: {data["cdp_url"]}')
		else:
			print(f'Error: {response.get("error")}', file=sys.stderr)
			return 1

	return 0


def _handle_sessions(args: argparse.Namespace) -> int:
	"""List active daemon sessions."""
	home_dir = _get_home_dir()
	sessions: list[dict] = []

	for pid_file in sorted(home_dir.glob('*.pid')):
		name = pid_file.stem
		if not name:
			continue

		try:
			pid = int(pid_file.read_text().strip())
		except (OSError, ValueError):
			pid_file.unlink(missing_ok=True)
			continue

		# Check if process is alive (os.kill(pid, 0) terminates on Windows, use OpenProcess instead)
		if sys.platform == 'win32':
			import ctypes

			_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
			_handle = ctypes.windll.kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
			if _handle:
				ctypes.windll.kernel32.CloseHandle(_handle)
				_alive = True
			else:
				_alive = False
		else:
			try:
				os.kill(pid, 0)
				_alive = True
			except (OSError, ProcessLookupError):
				_alive = False
		if not _alive:
			# Dead — clean up stale files
			pid_file.unlink(missing_ok=True)
			sock_path = _get_socket_path(name)
			if not sock_path.startswith('tcp://'):
				Path(sock_path).unlink(missing_ok=True)
			continue

		entry: dict = {'name': name, 'pid': pid}

		# Try to ping for config info
		try:
			resp = send_command('ping', {}, session=name)
			if resp.get('success'):
				data = resp.get('data', {})
				config_parts = []
				if data.get('headed'):
					config_parts.append('headed')
				if data.get('profile'):
					config_parts.append(f'profile={data["profile"]}')
				if data.get('cdp_url'):
					config_parts.append('cdp')
				if data.get('use_cloud'):
					config_parts.append('cloud')
				entry['config'] = ', '.join(config_parts) if config_parts else 'headless'
		except Exception:
			entry['config'] = '?'

		sessions.append(entry)

	if args.json:
		print(json.dumps({'sessions': sessions}))
	else:
		if sessions:
			print(f'{"SESSION":<16} {"PID":<8} CONFIG')
			for s in sessions:
				print(f'{s["name"]:<16} {s["pid"]:<8} {s.get("config", "")}')
		else:
			print('No active sessions')

	return 0


def _handle_close_all(args: argparse.Namespace) -> int:
	"""Close all active sessions."""
	home_dir = _get_home_dir()
	# Snapshot the list first to avoid mutating during iteration
	pid_files = list(home_dir.glob('*.pid'))
	closed = 0

	for pid_file in pid_files:
		name = pid_file.stem
		if not name:
			continue

		if _is_daemon_alive(name):
			try:
				send_command('shutdown', {}, session=name)
				closed += 1
			except Exception:
				pass

	if args.json:
		print(json.dumps({'closed': closed}))
	else:
		if closed:
			print(f'Closed {closed} session(s)')
		else:
			print('No active sessions')

	return 0


def _migrate_legacy_files() -> None:
	"""One-time cleanup of old daemon files and config migration."""
	# Migrate config from old XDG location
	from browser_use.skill_cli.utils import migrate_legacy_paths

	migrate_legacy_paths()

	# Clean up old single-socket daemon (pre-multi-session)
	legacy_path = Path(tempfile.gettempdir()) / 'browser-use-cli.sock'
	if sys.platform == 'win32':
		sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		try:
			sock.settimeout(0.5)
			sock.connect(('127.0.0.1', 49200))
			req = json.dumps({'id': 'legacy', 'action': 'shutdown', 'params': {}}) + '\n'
			sock.sendall(req.encode())
		except OSError:
			pass
		finally:
			sock.close()
	elif legacy_path.exists():
		sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
		try:
			sock.settimeout(0.5)
			sock.connect(str(legacy_path))
			req = json.dumps({'id': 'legacy', 'action': 'shutdown', 'params': {}}) + '\n'
			sock.sendall(req.encode())
		except OSError:
			legacy_path.unlink(missing_ok=True)
		finally:
			sock.close()

	# Clean up old ~/.browser-use/run/ directory (stale PID/socket files)
	old_run_dir = Path.home() / '.browser-use' / 'run'
	if old_run_dir.is_dir():
		for stale_file in old_run_dir.glob('browser-use-*'):
			stale_file.unlink(missing_ok=True)
		# Remove the directory if empty
		try:
			old_run_dir.rmdir()
		except OSError:
			pass


def main() -> int:
	"""Main entry point."""
	parser = build_parser()
	args = parser.parse_args()

	if not args.command:
		parser.print_help()
		return 0

	# Resolve session name
	session = args.session or os.environ.get('BROWSER_USE_SESSION', 'default')
	if not re.match(r'^[a-zA-Z0-9_-]+$', session):
		print(f'Error: Invalid session name {session!r}: only letters, digits, hyphens, underscores', file=sys.stderr)
		return 1

	# Handle sessions command (before daemon interaction)
	if args.command == 'sessions':
		return _handle_sessions(args)

	# Handle cloud subcommands
	if args.command == 'cloud':
		cloud_args = getattr(args, 'cloud_args', [])

		# Intercept 'cloud connect' — needs daemon, not REST passthrough
		if cloud_args and cloud_args[0] == 'connect':
			return _handle_cloud_connect(cloud_args[1:], args, session)

		# All other cloud subcommands are stateless REST passthroughs
		from browser_use.skill_cli.commands.cloud import handle_cloud_command

		return handle_cloud_command(cloud_args)

	# Handle profile subcommand — passthrough to profile-use Go binary
	if args.command == 'profile':
		from browser_use.skill_cli.profile_use import run_profile_use

		profile_argv = getattr(args, 'profile_args', [])
		return run_profile_use(profile_argv)

	# Handle setup command
	if args.command == 'setup':
		from browser_use.skill_cli.commands import setup

		loop = asyncio.get_event_loop()
		result = loop.run_until_complete(
			setup.handle(
				'setup',
				{
					'yes': getattr(args, 'yes', False),
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

	# Handle close — shutdown daemon
	if args.command == 'close':
		if getattr(args, 'all', False):
			return _handle_close_all(args)

		if _is_daemon_alive(session):
			try:
				response = send_command('shutdown', {}, session=session)
				if args.json:
					print(json.dumps(response))
				else:
					print('Browser closed')
			except Exception:
				print('Browser closed')
		else:
			if args.json:
				print(json.dumps({'success': True, 'data': {'shutdown': True}}))
			else:
				print('No active browser session')
		return 0

	# Mutual exclusivity: --connect, --cdp-url, and --profile
	if args.connect and args.cdp_url:
		print('Error: --connect and --cdp-url are mutually exclusive', file=sys.stderr)
		return 1
	if args.connect and args.profile:
		print('Error: --connect and --profile are mutually exclusive', file=sys.stderr)
		return 1
	if args.cdp_url and args.profile:
		print('Error: --cdp-url and --profile are mutually exclusive', file=sys.stderr)
		return 1

	# Resolve --connect to a CDP URL
	if args.connect:
		from browser_use.skill_cli.utils import discover_chrome_cdp_url

		try:
			args.cdp_url = discover_chrome_cdp_url()
		except RuntimeError as e:
			print(f'Error: {e}', file=sys.stderr)
			return 1

	# One-time legacy migration
	_migrate_legacy_files()

	# Ensure daemon is running
	# Only restart on config mismatch if the user explicitly passed config flags
	explicit_config = any(flag in sys.argv for flag in ('--headed', '--profile', '--cdp-url', '--connect'))
	ensure_daemon(args.headed, args.profile, args.cdp_url, session=session, explicit_config=explicit_config)

	# Build params from args
	params = {}
	skip_keys = {'command', 'headed', 'json', 'cdp_url', 'session', 'connect'}

	for key, value in vars(args).items():
		if key not in skip_keys and value is not None:
			params[key] = value

	# Resolve file paths to absolute before sending to daemon (daemon may have different CWD)
	if args.command == 'upload' and 'path' in params:
		params['path'] = str(Path(params['path']).expanduser().resolve())

	# Add profile to params for commands that need it
	if args.profile:
		params['profile'] = args.profile

	# Send command to daemon
	response = send_command(args.command, params, session=session)

	# Output response
	if args.json:
		print(json.dumps(response))
	else:
		if response.get('success'):
			data = response.get('data')
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
