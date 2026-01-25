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


def ensure_server(session: str, browser: str, headed: bool, profile: str | None, api_key: str | None) -> bool:
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

	# Set up environment
	env = os.environ.copy()
	if api_key:
		env['BROWSER_USE_API_KEY'] = api_key

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
	parser.add_argument('--profile', help='Chrome profile (real browser mode)')
	parser.add_argument('--json', action='store_true', help='Output as JSON')
	parser.add_argument('--api-key', help='Browser-Use API key')

	subparsers = parser.add_subparsers(dest='command', help='Command to execute')

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
	ensure_server(args.session, args.browser, args.headed, args.profile, args.api_key)

	# Build params from args
	params = {}
	skip_keys = {'command', 'session', 'browser', 'headed', 'profile', 'json', 'api_key', 'server_command'}

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
