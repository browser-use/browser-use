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
import signal
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


def _read_auth_token(session: str = 'default') -> str:
	"""Read per-session auth token written by the daemon.

	Must match utils.get_auth_token_path().
	Returns empty string if the token file is missing (pre-auth daemon).
	"""
	token_path = _get_home_dir() / f'{session}.token'
	try:
		return token_path.read_text().strip()
	except OSError:
		return ''


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


def _is_pid_alive(pid: int) -> bool:
	"""Check if a process with the given PID exists. Cross-platform."""
	if sys.platform == 'win32':
		import ctypes

		_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
		handle = ctypes.windll.kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
		if handle:
			ctypes.windll.kernel32.CloseHandle(handle)
			return True
		return False
	try:
		os.kill(pid, 0)
		return True
	except (OSError, ProcessLookupError):
		return False


def _is_daemon_process(pid: int) -> bool:
	"""Check if the process at PID is a browser-use daemon. Cross-platform."""
	_marker = 'browser_use.skill_cli.daemon'
	try:
		if sys.platform == 'linux':
			cmdline = Path(f'/proc/{pid}/cmdline').read_bytes().decode(errors='replace')
			return _marker in cmdline
		elif sys.platform == 'win32':
			# Use wmic to get the command line on Windows
			import subprocess as _sp

			result = _sp.run(
				['wmic', 'process', 'where', f'ProcessId={pid}', 'get', 'CommandLine', '/format:list'],
				capture_output=True,
				text=True,
				timeout=5,
			)
			return _marker in result.stdout
		else:
			# macOS and other POSIX
			import subprocess as _sp

			result = _sp.run(['ps', '-p', str(pid), '-o', 'command='], capture_output=True, text=True, timeout=5)
			return _marker in result.stdout
	except Exception:
		return False


def _terminate_pid(pid: int) -> bool:
	"""Best-effort terminate a process. Returns True if confirmed dead.

	POSIX: SIGTERM, poll 5s, escalate to SIGKILL.
	Windows: TerminateProcess (hard kill, skips all daemon cleanup).
	"""
	if sys.platform == 'win32':
		import ctypes

		_PROCESS_TERMINATE = 0x0001
		handle = ctypes.windll.kernel32.OpenProcess(_PROCESS_TERMINATE, False, pid)
		if handle:
			ctypes.windll.kernel32.TerminateProcess(handle, 1)
			ctypes.windll.kernel32.CloseHandle(handle)
		return not _is_pid_alive(pid)

	try:
		os.kill(pid, signal.SIGTERM)
	except (OSError, ProcessLookupError):
		return True

	# Poll for exit
	for _ in range(50):  # 5s at 100ms intervals
		time.sleep(0.1)
		if not _is_pid_alive(pid):
			return True

	# Escalate to SIGKILL
	try:
		os.kill(pid, signal.SIGKILL)
	except (OSError, ProcessLookupError):
		return True
	time.sleep(0.2)
	return not _is_pid_alive(pid)


def _read_session_state(session: str) -> dict | None:
	"""Read session state file. Returns None if missing or corrupt."""
	state_path = _get_home_dir() / f'{session}.state.json'
	if not state_path.exists():
		return None
	try:
		return json.loads(state_path.read_text())
	except (json.JSONDecodeError, OSError):
		return None


def _get_state_path(session: str) -> Path:
	return _get_home_dir() / f'{session}.state.json'


class _SessionProbe:
	"""Snapshot of a session's health. Never deletes anything — callers decide cleanup."""

	__slots__ = ('name', 'phase', 'updated_at', 'pid', 'pid_alive', 'socket_reachable', 'socket_pid')

	def __init__(
		self,
		name: str,
		phase: str | None = None,
		updated_at: float | None = None,
		pid: int | None = None,
		pid_alive: bool = False,
		socket_reachable: bool = False,
		socket_pid: int | None = None,
	):
		self.name = name
		self.phase = phase
		self.updated_at = updated_at
		self.pid = pid
		self.pid_alive = pid_alive
		self.socket_reachable = socket_reachable
		self.socket_pid = socket_pid


def _probe_session(session: str) -> _SessionProbe:
	"""Non-destructive probe of a session's state. Never deletes files."""
	probe = _SessionProbe(name=session)

	# 1. Read state file
	state = _read_session_state(session)
	state_pid: int | None = None
	if state:
		probe.phase = state.get('phase')
		probe.updated_at = state.get('updated_at')
		state_pid = state.get('pid')

	# 2. Read PID file
	pid_file_pid: int | None = None
	pid_path = _get_pid_path(session)
	if pid_path.exists():
		try:
			pid_file_pid = int(pid_path.read_text().strip())
		except (OSError, ValueError):
			pass

	# 3. Try socket connect + ping for PID (before reconciliation)
	try:
		sock = _connect_to_daemon(timeout=0.5, session=session)
		sock.close()
		probe.socket_reachable = True
		try:
			resp = send_command('ping', {}, session=session)
			if resp.get('success'):
				probe.socket_pid = resp.get('data', {}).get('pid')
		except Exception:
			pass
	except OSError:
		probe.socket_reachable = False

	# 4. Reconcile PIDs
	state_alive = bool(state_pid and _is_pid_alive(state_pid))
	pidfile_alive = bool(pid_file_pid and _is_pid_alive(pid_file_pid))

	if state_alive and pidfile_alive and state_pid != pid_file_pid:
		# Split-brain: both PIDs alive but different.
		# Use socket_pid to break the tie.
		if probe.socket_pid == state_pid:
			probe.pid = state_pid
		elif probe.socket_pid == pid_file_pid:
			probe.pid = pid_file_pid
		else:
			# Socket unreachable or answers with unknown PID — can't resolve
			probe.pid = pid_file_pid  # .pid file is written later, so prefer it
		probe.pid_alive = True
	elif state_alive:
		probe.pid = state_pid
		probe.pid_alive = True
	elif pidfile_alive:
		probe.pid = pid_file_pid
		probe.pid_alive = True
	else:
		probe.pid = state_pid or pid_file_pid
		probe.pid_alive = False

	return probe


def _clean_session_files(session: str) -> None:
	"""Remove all files for a session (state, PID, socket)."""
	_get_state_path(session).unlink(missing_ok=True)
	_get_pid_path(session).unlink(missing_ok=True)
	sock_path = _get_socket_path(session)
	if not sock_path.startswith('tcp://'):
		Path(sock_path).unlink(missing_ok=True)


def _is_daemon_alive(session: str = 'default') -> bool:
	"""Check if daemon is alive by socket reachability."""
	return _probe_session(session).socket_reachable


def ensure_daemon(
	headed: bool,
	profile: str | None,
	cdp_url: str | None = None,
	*,
	session: str = 'default',
	explicit_config: bool = False,
	use_cloud: bool = False,
	cloud_profile_id: str | None = None,
	cloud_proxy_country_code: str | None = None,
	cloud_timeout: int | None = None,
) -> None:
	"""Start daemon if not running. Uses state file for phase-aware decisions."""
	probe = _probe_session(session)

	# Socket reachable — daemon is alive and responding
	if probe.socket_reachable:
		if not explicit_config:
			return  # Reuse it

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

	# Socket unreachable but process alive — phase-aware decisions
	if probe.pid_alive and probe.phase:
		now = time.time()
		age = now - probe.updated_at if probe.updated_at else float('inf')

		if probe.phase == 'initializing' and age < 15:
			# Daemon is booting, wait for socket
			for _ in range(30):
				time.sleep(0.5)
				if _is_daemon_alive(session):
					return
			# Still not reachable — fall through to error

		elif probe.phase in ('starting', 'ready', 'running') and age < 60:
			# Daemon is alive but socket broke, or starting browser
			print(
				f'Error: Session {session!r} is alive (phase={probe.phase}) but socket unreachable.\n'
				f'Run `browser-use{" --session " + session if session != "default" else ""} close` first.',
				file=sys.stderr,
			)
			sys.exit(1)

		elif probe.phase == 'shutting_down' and age < 15:
			# Daemon is shutting down, wait for it to finish
			for _ in range(30):
				time.sleep(0.5)
				if not probe.pid or not _is_pid_alive(probe.pid):
					break
			# Fall through to spawn

		# Stale phase — daemon stuck or crashed without terminal state
		elif probe.pid and _is_daemon_process(probe.pid):
			_terminate_pid(probe.pid)

	# Clean up stale files before spawning
	_clean_session_files(session)

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
	if cloud_profile_id is not None:
		cmd.extend(['--cloud-profile-id', cloud_profile_id])
	if cloud_proxy_country_code is not None:
		cmd.extend(['--cloud-proxy-country', cloud_proxy_country_code])
	if cloud_timeout is not None:
		cmd.extend(['--cloud-timeout', str(cloud_timeout)])

	# Set up environment
	env = os.environ.copy()

	# For cloud mode, inject API key from config.json into daemon env.
	# The library's CloudBrowserClient reads BROWSER_USE_API_KEY env var directly,
	# so we inject it to prevent fallback to ~/.config/browseruse/cloud_auth.json.
	if use_cloud:
		from browser_use.skill_cli.config import get_config_value

		cli_api_key = get_config_value('api_key')
		if cli_api_key:
			env['BROWSER_USE_API_KEY'] = str(cli_api_key)

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

	# Wait for daemon to be ready — use state file for phase-aware waiting
	deadline = time.time() + 15
	while time.time() < deadline:
		probe = _probe_session(session)
		if probe.socket_reachable:
			return
		# Daemon wrote state and PID is alive — still booting, keep waiting
		if probe.pid_alive and probe.phase in ('initializing', 'ready', 'starting', 'running'):
			time.sleep(0.2)
			continue
		# Daemon wrote terminal state — startup failed
		if probe.phase in ('failed', 'stopped'):
			break
		time.sleep(0.2)

	print('Error: Failed to start daemon', file=sys.stderr)
	sys.exit(1)


def send_command(action: str, params: dict, *, session: str = 'default', agent_id: str = '__shared__') -> dict:
	"""Send command to daemon and get response."""
	request = {
		'id': f'r{int(time.time() * 1000000) % 1000000}',
		'action': action,
		'params': params,
		'agent_id': agent_id,
		'token': _read_auth_token(session),
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
		default=False,
		help='(Deprecated) Use "browser-use connect" instead',
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

	# register

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

	# connect (to local Chrome)
	subparsers.add_parser('connect', help='Connect to running Chrome via CDP')

	# config
	config_p = subparsers.add_parser('config', help='Manage CLI configuration')
	config_sub = config_p.add_subparsers(dest='config_command')
	p = config_sub.add_parser('set', help='Set a config value')
	p.add_argument('key', help='Config key')
	p.add_argument('value', help='Config value')
	p = config_sub.add_parser('get', help='Get a config value')
	p.add_argument('key', help='Config key')
	config_sub.add_parser('list', help='List all config values')
	p = config_sub.add_parser('unset', help='Remove a config value')
	p.add_argument('key', help='Config key')

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
	p = subparsers.add_parser('input', help='Clear-then-type into specific element; pass "" to clear only')
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

	# tab (list, switch, close)
	tab_p = subparsers.add_parser('tab', help='Tab management (list, switch, close)')
	tab_sub = tab_p.add_subparsers(dest='tab_command')

	tab_sub.add_parser('list', help='List all tabs with lock status')

	p = tab_sub.add_parser('new', help='Open a new blank tab')
	p.add_argument('url', nargs='?', default='about:blank', help='URL to open (default: about:blank)')

	p = tab_sub.add_parser('switch', help='Switch to tab')
	p.add_argument('tab', type=int, help='Tab index')

	p = tab_sub.add_parser('close', help='Close tab(s)')
	p.add_argument('tabs', type=int, nargs='*', help='Tab indices to close (current if none)')

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
	"""Handle `browser-use cloud connect` — zero-config cloud browser provisioning."""
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

	# Validate API key exists before spawning daemon (shows our CLI error, not library's)
	from browser_use.skill_cli.commands.cloud import (
		_get_api_key,
		_get_cloud_connect_proxy,
		_get_cloud_connect_timeout,
		_get_or_create_cloud_profile,
	)

	_get_api_key()  # exits with helpful message if no key

	cloud_profile_id = _get_or_create_cloud_profile()

	# Start daemon with cloud config
	if not args.json:
		print('Connecting...', end='', flush=True)
	ensure_daemon(
		args.headed,
		None,
		session=session,
		explicit_config=True,
		use_cloud=True,
		cloud_profile_id=cloud_profile_id,
		cloud_proxy_country_code=_get_cloud_connect_proxy(),
		cloud_timeout=_get_cloud_connect_timeout(),
	)

	# Send connect command to force immediate session creation
	response = send_command('connect', {}, session=session)

	if args.json:
		print(json.dumps(response))
	else:
		print('\r' + ' ' * 20 + '\r', end='')  # clear "Connecting..."
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

	# Discover sessions from union of PID files + state files
	session_names: set[str] = set()
	for pid_file in home_dir.glob('*.pid'):
		if pid_file.stem:
			session_names.add(pid_file.stem)
	for state_file in home_dir.glob('*.state.json'):
		name = state_file.name.removesuffix('.state.json')
		if name:
			session_names.add(name)

	for name in sorted(session_names):
		probe = _probe_session(name)

		if not probe.pid_alive:
			# Don't delete if socket is still reachable — daemon alive despite stale PID
			if not probe.socket_reachable:
				_clean_session_files(name)
				continue

		# Terminal state + dead PID already handled above.
		# If phase is terminal but PID is alive, the daemon restarted and
		# the stale state file belongs to a previous instance — only clean
		# the state file, not the PID/socket which the live daemon owns.
		if probe.phase in ('stopped', 'failed'):
			_get_state_path(name).unlink(missing_ok=True)
			# Fall through to show the live session

		entry: dict = {'name': name, 'pid': probe.pid or 0, 'phase': probe.phase or '?'}

		# Try to ping for config info
		if probe.socket_reachable:
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
						entry['cdp_url'] = data['cdp_url']
						if not data.get('use_cloud'):
							config_parts.append('cdp')
					if data.get('use_cloud'):
						config_parts.append('cloud')
					entry['config'] = ', '.join(config_parts) if config_parts else 'headless'
			except Exception:
				entry['config'] = '?'
		else:
			entry['config'] = '?'

		sessions.append(entry)

	# Sweep orphaned sockets that have no corresponding live session
	live_names = {s['name'] for s in sessions}
	for sock_file in home_dir.glob('*.sock'):
		if sock_file.stem not in live_names:
			sock_file.unlink(missing_ok=True)

	if args.json:
		print(json.dumps({'sessions': sessions}))
	else:
		if sessions:
			print(f'{"SESSION":<16} {"PHASE":<14} {"PID":<8} CONFIG')
			for s in sessions:
				print(f'{s["name"]:<16} {s.get("phase", "?"):<14} {s["pid"]:<8} {s.get("config", "")}')
		else:
			print('No active sessions')

	return 0


def _close_session(session: str) -> bool:
	"""Close a single session. Returns True if something was closed/killed.

	Only cleans up files after the daemon process is confirmed dead.
	"""
	probe = _probe_session(session)

	if probe.socket_reachable:
		print('Closing...', end='', flush=True)
		try:
			send_command('shutdown', {}, session=session)
		except Exception:
			pass  # Shutdown may have been accepted even if response failed
		# Poll for PID disappearance (up to 15s: 10s browser cleanup + margin)
		confirmed_dead = not probe.pid  # No PID to check = assume success
		if probe.pid:
			for _ in range(150):
				time.sleep(0.1)
				if not _is_pid_alive(probe.pid):
					confirmed_dead = True
					break
		if confirmed_dead:
			_clean_session_files(session)
		return True

	if probe.pid_alive and probe.pid and _is_daemon_process(probe.pid):
		dead = _terminate_pid(probe.pid)
		if dead:
			_clean_session_files(session)
		return dead

	# Nothing alive — clean up stale files if any exist
	if probe.pid or probe.phase:
		_clean_session_files(session)
	return False


def _handle_close_all(args: argparse.Namespace) -> int:
	"""Close all active sessions."""
	home_dir = _get_home_dir()

	# Discover sessions from union of PID files + state files
	session_names: set[str] = set()
	for pid_file in home_dir.glob('*.pid'):
		if pid_file.stem:
			session_names.add(pid_file.stem)
	for state_file in home_dir.glob('*.state.json'):
		name = state_file.name.removesuffix('.state.json')
		if name:
			session_names.add(name)

	closed = 0
	for name in sorted(session_names):
		if _close_session(name):
			closed += 1

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

		result = setup.handle(yes=getattr(args, 'yes', False))

		if args.json:
			print(json.dumps(result))
		elif 'error' in result:
			print(f'Error: {result["error"]}', file=sys.stderr)
			return 1
		return 0

	# Handle doctor command
	if args.command == 'doctor':
		from browser_use.skill_cli.commands import doctor

		result = asyncio.run(doctor.handle())

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

			# Show config state
			from browser_use.skill_cli.config import CLI_DOCS_URL, get_config_display

			entries = get_config_display()
			print(f'\nConfig ({_get_home_dir() / "config.json"}):\n')
			for entry in entries:
				if entry['is_set']:
					icon = '✓'
					val = 'set' if entry['sensitive'] else entry['value']
				else:
					icon = '○'
					val = entry['value'] if entry['value'] else 'not set'
				print(f'  {icon} {entry["key"]}: {val}')
			print(f'  Docs: {CLI_DOCS_URL}')

		return 0

	# Handle config command
	if args.command == 'config':
		from browser_use.skill_cli.config import (
			CLI_DOCS_URL,
			get_config_display,
			get_config_value,
			set_config_value,
			unset_config_value,
		)

		config_cmd = getattr(args, 'config_command', None)

		if config_cmd == 'set':
			try:
				set_config_value(args.key, args.value)
				print(f'{args.key} = {args.value}')
			except ValueError as e:
				print(f'Error: {e}', file=sys.stderr)
				return 1

		elif config_cmd == 'get':
			val = get_config_value(args.key)
			if val is not None:
				print(val)
			else:
				print(f'{args.key}: not set', file=sys.stderr)

		elif config_cmd == 'unset':
			try:
				unset_config_value(args.key)
				print(f'{args.key} removed')
			except ValueError as e:
				print(f'Error: {e}', file=sys.stderr)
				return 1

		elif config_cmd == 'list' or config_cmd is None:
			entries = get_config_display()
			print(f'Config ({_get_home_dir() / "config.json"}):')
			for entry in entries:
				if entry['is_set']:
					icon = '✓'
					val = 'set' if entry['sensitive'] else entry['value']
				else:
					icon = '○'
					val = entry['value'] if entry['value'] else 'not set'
				print(f'  {icon} {entry["key"]}: {val}')
			print(f'  Docs: {CLI_DOCS_URL}')

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
				result = asyncio.run(tunnel.stop_all_tunnels())
			elif port_arg is not None:
				result = asyncio.run(tunnel.stop_tunnel(port_arg))
			else:
				print('Usage: browser-use tunnel stop <port> | --all', file=sys.stderr)
				return 1
		elif pos is not None:
			try:
				port = int(pos)
			except ValueError:
				print(f'Unknown tunnel subcommand: {pos}', file=sys.stderr)
				return 1
			result = asyncio.run(tunnel.start_tunnel(port))
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

		closed = _close_session(session)
		if args.json:
			print(json.dumps({'success': True, 'data': {'shutdown': True}}))
		else:
			print('\r' + ' ' * 20 + '\r', end='')  # clear "Closing..."
			if closed:
				print('Browser closed')
			elif closed is False and _probe_session(session).pid_alive:
				print('Warning: daemon may still be shutting down', file=sys.stderr)
			else:
				print('No active browser session')
		return 0

	# Handle --connect deprecation
	if args.connect:
		print('Note: --connect has been replaced.', file=sys.stderr)
		print('  To connect to Chrome:  browser-use connect', file=sys.stderr)
		print('  For cloud browser:     browser-use cloud connect', file=sys.stderr)
		print('  For multiple agents:   use --session NAME per agent', file=sys.stderr)
		return 1

	# Handle connect command (discover local Chrome, start daemon)
	if args.command == 'connect':
		from browser_use.skill_cli.utils import discover_chrome_cdp_url

		try:
			cdp_url = discover_chrome_cdp_url()
		except RuntimeError as e:
			print(f'Error: {e}', file=sys.stderr)
			return 1

		ensure_daemon(args.headed, None, cdp_url=cdp_url, session=session, explicit_config=True)
		response = send_command('connect', {}, session=session)

		if args.json:
			print(json.dumps(response))
		else:
			if response.get('success'):
				data = response.get('data', {})
				print(f'status: {data.get("status", "unknown")}')
				if 'cdp_url' in data:
					print(f'cdp_url: {data["cdp_url"]}')
			else:
				print(f'Error: {response.get("error")}', file=sys.stderr)
				return 1
		return 0

	# Mutual exclusivity
	if args.cdp_url and args.profile:
		print('Error: --cdp-url and --profile are mutually exclusive', file=sys.stderr)
		return 1

	# One-time legacy migration
	_migrate_legacy_files()

	# Ensure daemon is running
	explicit_config = any(flag in sys.argv for flag in ('--headed', '--profile', '--cdp-url'))
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
