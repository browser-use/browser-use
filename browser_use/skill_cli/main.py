#!/usr/bin/env python3
"""Fast CLI for browser-use. STDLIB ONLY - must start in <50ms.

This is the main entry point for the browser-use CLI. It uses only stdlib
imports to ensure fast startup, delegating heavy operations to the session
server which loads once and stays running.
"""

import argparse
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
		port = 49152 + (int(hashlib.md5(session.encode()).hexdigest()[:4], 16) % 16383)
		return f'tcp://localhost:{port}'
	return str(Path(tempfile.gettempdir()) / f'browser-use-{session}.sock')


def get_pid_path(session: str) -> Path:
	"""Get PID file path for session."""
	return Path(tempfile.gettempdir()) / f'browser-use-{session}.pid'


def is_server_running(session: str) -> bool:
	"""Check if server is running for session."""
	pid_path = get_pid_path(session)
	if not pid_path.exists():
		return False
	try:
		pid = int(pid_path.read_text().strip())
		os.kill(pid, 0)
		return True
	except (OSError, ValueError):
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


def ensure_server(
	session: str,
	browser: str,
	headed: bool,
	profile: str | None,
	api_key: str | None,
	cdp_url: str | None = None,
	browser_exe: str | None = None,
	user_data_dir: str | None = None,
	no_copy_profile: bool = False,
) -> bool:
	"""Start server if not running. Returns True if started."""
	# Check if server is already running and responsive
	if is_server_running(session):
		try:
			sock = connect_to_server(session, timeout=0.1)
			sock.close()
			return False  # Already running
		except Exception:
			pass  # Server dead, restart

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
	if browser_exe:
		cmd.extend(['--browser-exe', browser_exe])
	if user_data_dir:
		cmd.extend(['--user-data-dir', user_data_dir])
	if no_copy_profile:
		cmd.append('--no-copy-profile')
	if cdp_url:
		cmd.extend(['--cdp-url', cdp_url])

	# Set up environment
	env = os.environ.copy()
	if api_key:
		env['BROWSER_USE_API_KEY'] = api_key
	if no_copy_profile:
		env['BROWSER_USE_NO_COPY_PROFILE'] = '1'

	# Start server as background process
	if sys.platform == 'win32':
		# Windows: use CREATE_NEW_PROCESS_GROUP
		subprocess.Popen(
			cmd,
			env=env,
			creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
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

	# Wait for server to be ready
	for _ in range(100):  # 5 seconds max
		if is_server_running(session):
			try:
				sock = connect_to_server(session, timeout=0.1)
				sock.close()
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
	parser = argparse.ArgumentParser(
		prog='browser-use',
		description='Browser automation CLI for browser-use',
		formatter_class=argparse.RawDescriptionHelpFormatter,
		epilog="""
Examples:
  browser-use install                    # Install Chromium browser
  browser-use init                       # Generate template file (interactive)
  browser-use init --template default    # Generate specific template
  browser-use --mcp                      # Run as MCP server
  browser-use open https://example.com
  browser-use click 5
  browser-use type "Hello World"
  browser-use python "print(browser.url)"
  browser-use run "Fill the contact form"
  browser-use sessions
  browser-use close
""",
	)

	# Global flags
	parser.add_argument('--session', '-s', default='default', help='Session name (default: default)')
	parser.add_argument('--browser', '-b', choices=['chromium', 'real', 'remote'], default='chromium', help='Browser mode')
	parser.add_argument('--headed', action='store_true', help='Show browser window')
	parser.add_argument('--browser-exe', help='Path to Chrome/Chromium executable (real browser mode)')
	parser.add_argument('--user-data-dir', help='Chrome user data directory (real browser mode)')
	parser.add_argument(
		'--profile',
		help='Cloud profile id (remote) or Chrome profile directory name (real)',
	)
	parser.add_argument('--no-copy-profile', action='store_true', help='Use profile in-place without copying')
	parser.add_argument('--cdp-url', help='CDP URL to connect to existing browser (e.g., http://localhost:9222)')
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

	# -------------------------------------------------------------------------
	# Browser Control Commands
	# -------------------------------------------------------------------------

	# open <url>
	p = subparsers.add_parser('open', help='Navigate to URL')
	p.add_argument('url', help='URL to navigate to')

	# click <index>
	p = subparsers.add_parser('click', help='Click element by index')
	p.add_argument('index', type=int, help='Element index from state')

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

	p = subparsers.add_parser('run', help='Run agent task (requires API key)')
	p.add_argument('task', help='Task description')
	p.add_argument('--max-steps', type=int, default=100, help='Maximum steps')

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
	# Profile Management
	# -------------------------------------------------------------------------

	profile_p = subparsers.add_parser('profile', help='Manage browser profiles')
	profile_sub = profile_p.add_subparsers(dest='profile_command')

	# profile list-local
	profile_sub.add_parser('list-local', help='List local Chrome profiles')

	# Cloud profile commands
	# profile list
	p = profile_sub.add_parser('list', help='List cloud profiles')
	p.add_argument('--page', type=int, default=1, help='Page number')
	p.add_argument('--page-size', type=int, default=10, help='Items per page')

	# profile create
	p = profile_sub.add_parser('create', help='Create cloud profile')
	p.add_argument('--name', help='Profile name')

	# profile get <id>
	p = profile_sub.add_parser('get', help='Get cloud profile details')
	p.add_argument('id', help='Profile ID')

	# profile update <id>
	p = profile_sub.add_parser('update', help='Update cloud profile')
	p.add_argument('id', help='Profile ID')
	p.add_argument('--name', required=True, help='New profile name')

	# profile delete <id>
	p = profile_sub.add_parser('delete', help='Delete cloud profile')
	p.add_argument('id', help='Profile ID')

	# profile cookies <profile> - list cookies by domain in a local profile
	p = profile_sub.add_parser('cookies', help='List cookies by domain in a local profile')
	p.add_argument('profile', help='Local profile name (e.g. "Default", "Profile 1")')

	# profile sync - sync local profile to cloud
	p = profile_sub.add_parser('sync', help='Sync local Chrome profile to cloud')
	p.add_argument('--from', dest='from_profile', help='Local profile name (e.g. "Default", "Profile 1")')
	p.add_argument('--name', help='Cloud profile name (default: auto-generated)')
	p.add_argument('--domain', help='Only sync cookies for this domain (e.g. "youtube.com")')

	return parser


def cloud_api_request(method: str, endpoint: str, body: dict | None = None) -> dict:
	"""Make authenticated request to Browser-Use Cloud API.

	Returns dict with 'success', 'data' or 'error'.
	"""
	import urllib.error
	import urllib.request

	from browser_use.skill_cli.api_key import APIKeyRequired, require_api_key

	try:
		api_key = require_api_key('Cloud profiles')
	except APIKeyRequired as e:
		return {'success': False, 'error': str(e)}

	url = f'https://api.browser-use.com/api/v2{endpoint}'
	headers = {
		'X-Browser-Use-API-Key': api_key,
		'Content-Type': 'application/json',
	}

	data = json.dumps(body).encode() if body else None
	req = urllib.request.Request(url, data=data, headers=headers, method=method)

	try:
		with urllib.request.urlopen(req) as resp:
			if resp.status == 204:  # No content (e.g., delete)
				return {'success': True, 'data': {}}
			return {'success': True, 'data': json.loads(resp.read().decode())}
	except urllib.error.HTTPError as e:
		try:
			error_body = json.loads(e.read().decode())
			error_msg = error_body.get('detail', str(e))
		except Exception:
			error_msg = str(e)
		return {'success': False, 'error': f'{e.code}: {error_msg}'}
	except urllib.error.URLError as e:
		return {'success': False, 'error': f'Connection error: {e.reason}'}


def handle_profile_command(args: argparse.Namespace) -> int:
	"""Handle profile subcommands."""
	if args.profile_command == 'list-local':
		profiles = list_local_chrome_profiles()

		if args.json:
			print(json.dumps({'profiles': profiles}))
		else:
			if profiles:
				print('Local Chrome profiles:')
				for p in profiles:
					email_str = f' ({p["email"]})' if p['email'] != 'local' else ''
					print(f'  {p["id"]}: {p["name"]}{email_str}')
			else:
				print('No Chrome profiles found')
		return 0

	elif args.profile_command == 'list':
		# List cloud profiles
		endpoint = f'/profiles?pageNumber={args.page}&pageSize={args.page_size}'
		result = cloud_api_request('GET', endpoint)

		if not result['success']:
			print(f'Error: {result["error"]}', file=sys.stderr)
			return 1

		data = result['data']
		if args.json:
			print(json.dumps(data))
		else:
			items = data.get('items', [])
			total = data.get('totalItems', 0)
			if items:
				print(f'Cloud profiles ({len(items)}/{total}):')
				for p in items:
					name = p.get('name') or '(unnamed)'
					domains = p.get('cookieDomains') or []
					domain_str = f' [{len(domains)} domains]' if domains else ''
					print(f'  {p["id"]}: {name}{domain_str}')
			else:
				print('No cloud profiles found')
		return 0

	elif args.profile_command == 'create':
		# Create cloud profile
		body = {}
		if args.name:
			body['name'] = args.name

		result = cloud_api_request('POST', '/profiles', body)

		if not result['success']:
			print(f'Error: {result["error"]}', file=sys.stderr)
			return 1

		data = result['data']
		if args.json:
			print(json.dumps(data))
		else:
			name = data.get('name') or '(unnamed)'
			print(f'Created profile: {data["id"]}')
			print(f'  Name: {name}')
		return 0

	elif args.profile_command == 'get':
		# Get cloud profile details
		result = cloud_api_request('GET', f'/profiles/{args.id}')

		if not result['success']:
			print(f'Error: {result["error"]}', file=sys.stderr)
			return 1

		data = result['data']
		if args.json:
			print(json.dumps(data))
		else:
			print(f'Profile: {data["id"]}')
			print(f'  Name: {data.get("name") or "(unnamed)"}')
			print(f'  Created: {data.get("createdAt", "unknown")}')
			print(f'  Updated: {data.get("updatedAt", "unknown")}')
			print(f'  Last used: {data.get("lastUsedAt") or "never"}')
			domains = data.get('cookieDomains') or []
			if domains:
				print(f'  Cookie domains ({len(domains)}):')
				for d in domains[:10]:
					print(f'    - {d}')
				if len(domains) > 10:
					print(f'    ... and {len(domains) - 10} more')
		return 0

	elif args.profile_command == 'update':
		# Update cloud profile
		body = {'name': args.name}
		result = cloud_api_request('PATCH', f'/profiles/{args.id}', body)

		if not result['success']:
			print(f'Error: {result["error"]}', file=sys.stderr)
			return 1

		data = result['data']
		if args.json:
			print(json.dumps(data))
		else:
			print(f'Updated profile: {data["id"]}')
			print(f'  Name: {data.get("name") or "(unnamed)"}')
		return 0

	elif args.profile_command == 'delete':
		# Delete cloud profile
		result = cloud_api_request('DELETE', f'/profiles/{args.id}')

		if not result['success']:
			print(f'Error: {result["error"]}', file=sys.stderr)
			return 1

		if args.json:
			print(json.dumps({'deleted': args.id}))
		else:
			print(f'Deleted profile: {args.id}')
		return 0

	elif args.profile_command == 'cookies':
		# List cookies by domain in a local profile
		return handle_profile_cookies(args)

	elif args.profile_command == 'sync':
		# Sync local profile to cloud
		return handle_profile_sync(args)

	# No subcommand specified
	print('Usage: browser-use profile <command>')
	print('Commands: list-local, list, create, get, update, delete, cookies, sync')
	return 1


def list_local_chrome_profiles() -> list[dict]:
	"""List local Chrome profiles from the Local State file."""
	local_state_paths = [
		Path.home() / 'Library/Application Support/Google/Chrome/Local State',  # macOS
		Path.home() / '.config/google-chrome/Local State',  # Linux
		Path.home() / 'AppData/Local/Google/Chrome/User Data/Local State',  # Windows
	]

	local_state = None
	for path in local_state_paths:
		if path.exists():
			local_state = path
			break

	if not local_state:
		return []

	try:
		data = json.loads(local_state.read_text())
		profiles_info = data.get('profile', {}).get('info_cache', {})

		profiles = []
		for profile_id, info in profiles_info.items():
			profiles.append(
				{
					'id': profile_id,
					'name': info.get('name', 'Unknown'),
					'email': info.get('user_name') or info.get('gaia_name') or 'local',
				}
			)

		return profiles
	except Exception:
		return []


def handle_profile_cookies(args: argparse.Namespace) -> int:
	"""List cookies by domain in a local Chrome profile."""
	import asyncio
	from collections import defaultdict

	# Get local profiles
	local_profiles = list_local_chrome_profiles()
	if not local_profiles:
		print('Error: No local Chrome profiles found', file=sys.stderr)
		return 1

	# Find the matching profile
	profile_arg = args.profile
	selected_profile = None
	for p in local_profiles:
		if p['id'] == profile_arg or p['name'] == profile_arg:
			selected_profile = p
			break

	if not selected_profile:
		print(f'Error: Profile "{profile_arg}" not found', file=sys.stderr)
		print('Available profiles:')
		for p in local_profiles:
			print(f'  {p["id"]}: {p["name"]}')
		return 1

	profile_id = selected_profile['id']
	print(f'Loading cookies from: {selected_profile["name"]} ({selected_profile["email"]})')

	async def get_cookies() -> list:
		from browser_use.skill_cli.sessions import create_browser_session

		# Start local browser headless
		local_session = await create_browser_session(
			'real',
			headed=False,
			profile=profile_id,
		)
		await local_session.start()

		try:
			return await local_session._cdp_get_cookies() or []
		finally:
			await local_session.kill()

	try:
		cookies = asyncio.get_event_loop().run_until_complete(get_cookies())
	except RuntimeError:
		cookies = asyncio.run(get_cookies())

	if not cookies:
		print('No cookies found')
		return 0

	# Group by domain
	domain_counts: dict[str, int] = defaultdict(int)
	for c in cookies:
		domain = c.get('domain', 'unknown')
		# Remove leading dot for grouping
		if domain.startswith('.'):
			domain = domain[1:]
		domain_counts[domain] += 1

	# Sort by count (descending)
	sorted_domains = sorted(domain_counts.items(), key=lambda x: (-x[1], x[0]))

	if args.json:
		print(json.dumps({'domains': dict(sorted_domains), 'total': len(cookies)}))
	else:
		print(f'\nCookies by domain ({len(cookies)} total):')
		for domain, count in sorted_domains:
			print(f'  {domain}: {count}')
		print()
		print('To sync a specific domain:')
		print(f'  browser-use profile sync --from "{profile_id}" --domain <domain>')

	return 0


def handle_profile_sync(args: argparse.Namespace) -> int:
	"""Sync a local Chrome profile to Browser-Use Cloud.

	This command:
	1. Lists local profiles (if --from not specified)
	2. Creates a cloud profile
	3. Exports cookies from local Chrome (headless)
	4. Imports cookies to cloud profile
	"""
	import asyncio
	import tempfile

	from browser_use.skill_cli.api_key import APIKeyRequired, require_api_key

	# Check API key first
	try:
		require_api_key('Profile sync')
	except APIKeyRequired as e:
		print(f'Error: {e}', file=sys.stderr)
		return 1

	# Get local profiles
	local_profiles = list_local_chrome_profiles()
	if not local_profiles:
		print('Error: No local Chrome profiles found', file=sys.stderr)
		return 1

	# Determine which profile to sync
	from_profile = args.from_profile
	if not from_profile:
		# Show available profiles and ask user to specify
		print('Available local profiles:')
		for p in local_profiles:
			print(f'  {p["id"]}: {p["name"]} ({p["email"]})')
		print()
		print('Use --from to specify a profile:')
		print('  browser-use profile sync --from "Default"')
		print('  browser-use profile sync --from "Profile 1"')
		return 1

	# Find the matching profile
	selected_profile = None
	for p in local_profiles:
		if p['id'] == from_profile or p['name'] == from_profile:
			selected_profile = p
			break

	if not selected_profile:
		print(f'Error: Profile "{from_profile}" not found', file=sys.stderr)
		print('Available profiles:')
		for p in local_profiles:
			print(f'  {p["id"]}: {p["name"]}')
		return 1

	profile_id = selected_profile['id']
	profile_name = selected_profile['name']
	domain_filter = args.domain

	# Generate cloud profile name
	if args.name:
		cloud_name = args.name
	elif domain_filter:
		cloud_name = f'Chrome - {profile_name} ({domain_filter})'
	else:
		cloud_name = f'Chrome - {profile_name}'

	if domain_filter:
		print(f'Syncing: {profile_name} → {domain_filter} cookies only')
	else:
		print(f'Syncing: {profile_name} ({selected_profile["email"]})')

	# Step 1: Create cloud profile
	print('  Creating cloud profile...')
	result = cloud_api_request('POST', '/profiles', {'name': cloud_name})
	if not result['success']:
		print(f'Error creating cloud profile: {result["error"]}', file=sys.stderr)
		return 1

	cloud_profile_id = result['data']['id']
	print(f'  ✓ Created: {cloud_profile_id}')

	# Step 2: Export cookies from local Chrome (headless)
	print('  Extracting cookies from local Chrome...')

	async def sync_cookies() -> tuple[int, str | None]:
		from browser_use.skill_cli.sessions import create_browser_session

		# Start local browser headless
		local_session = await create_browser_session(
			'real',
			headed=False,
			profile=profile_id,
		)
		await local_session.start()

		try:
			# Get cookies via direct CDP
			cookies = await local_session._cdp_get_cookies()

			if not cookies:
				return 0, 'No cookies found in local profile'

			# Filter by domain if specified
			if domain_filter:
				filtered = []
				for c in cookies:
					cookie_domain = c.get('domain', '')
					# Remove leading dot for comparison
					if cookie_domain.startswith('.'):
						cookie_domain = cookie_domain[1:]
					# Match if domain ends with filter (e.g. "youtube.com" matches ".youtube.com" and "www.youtube.com")
					if cookie_domain == domain_filter or cookie_domain.endswith('.' + domain_filter):
						filtered.append(c)
				cookies = filtered
				if not cookies:
					return 0, f'No cookies found for domain: {domain_filter}'

			# Save to temp file
			cookies_file = Path(tempfile.gettempdir()) / f'browser-use-sync-{cloud_profile_id}.json'
			cookies_file.write_text(json.dumps(cookies, indent=2))

			return len(cookies), str(cookies_file)
		finally:
			await local_session.kill()

	try:
		cookie_count, cookies_file = asyncio.get_event_loop().run_until_complete(sync_cookies())
	except RuntimeError:
		# No event loop running
		cookie_count, cookies_file = asyncio.run(sync_cookies())

	if cookie_count == 0:
		print(f'  ⚠ {cookies_file}')  # cookies_file contains error message
		return 1

	assert cookies_file is not None  # Type guard: if cookie_count > 0, cookies_file is a valid path
	print(f'  ✓ Extracted {cookie_count} cookies')

	# Step 3: Import cookies to cloud profile
	print('  Uploading cookies to cloud...')

	async def upload_cookies(cookies_path: str) -> tuple[int, str | None]:
		from browser_use.skill_cli.sessions import create_browser_session

		# Start remote browser with the new profile
		remote_session = await create_browser_session(
			'remote',
			headed=False,
			profile=cloud_profile_id,
		)
		await remote_session.start()

		try:
			# Load cookies
			cookies = json.loads(Path(cookies_path).read_text())

			# Set cookies via CDP
			cdp_session = await remote_session.get_or_create_cdp_session(target_id=None, focus=False)
			if not cdp_session:
				return 0, 'Failed to connect to remote browser'

			# Build cookie list for bulk set
			cookie_list = []
			for c in cookies:
				cookie_params = {
					'name': c['name'],
					'value': c['value'],
					'domain': c.get('domain'),
					'path': c.get('path', '/'),
					'secure': c.get('secure', False),
					'httpOnly': c.get('httpOnly', False),
				}
				if c.get('sameSite'):
					cookie_params['sameSite'] = c['sameSite']
				if c.get('expires'):
					cookie_params['expires'] = c['expires']
				cookie_list.append(cookie_params)

			# Set all cookies in one call
			try:
				await cdp_session.cdp_client.send.Network.setCookies(
					params={'cookies': cookie_list},
					session_id=cdp_session.session_id,
				)
				return len(cookie_list), None
			except Exception as e:
				return 0, f'Failed to set cookies: {e}'
		finally:
			await remote_session.kill()

	try:
		uploaded_count, error = asyncio.get_event_loop().run_until_complete(upload_cookies(cookies_file))
	except RuntimeError:
		uploaded_count, error = asyncio.run(upload_cookies(cookies_file))

	# Clean up temp file
	Path(cookies_file).unlink(missing_ok=True)

	if error:
		print(f'  Error: {error}', file=sys.stderr)
		return 1

	print(f'  ✓ Uploaded {uploaded_count} cookies')
	print()
	print('✓ Profile synced successfully!')
	print(f'  Cloud profile ID: {cloud_profile_id}')
	print(f'  Name: {cloud_name}')
	print()
	print('Use with:')
	print(f'  browser-use --browser remote --profile {cloud_profile_id} open <url>')

	if args.json:
		print(
			json.dumps(
				{
					'profile_id': cloud_profile_id,
					'name': cloud_name,
					'cookies_synced': uploaded_count,
				}
			)
		)

	return 0


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

	# Ensure server is running
	profile = getattr(args, 'profile', None)

	ensure_server(
		args.session,
		args.browser,
		args.headed,
		profile,
		args.api_key,
		getattr(args, 'cdp_url', None),
		getattr(args, 'browser_exe', None),
		getattr(args, 'user_data_dir', None),
		getattr(args, 'no_copy_profile', False),
	)

	# Build params from args
	params = {}
	skip_keys = {
		'command',
		'session',
		'browser',
		'headed',
		'profile',
		'json',
		'api_key',
		'server_command',
		'cdp_url',
		'browser_exe',
		'user_data_dir',
		'no_copy_profile',
	}

	for key, value in vars(args).items():
		if key not in skip_keys and value is not None:
			params[key] = value

	# Send command to server
	response = send_command(args.session, args.command, params)

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
