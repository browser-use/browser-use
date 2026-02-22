"""Cloudflared tunnel binary management.

This module manages the cloudflared binary for tunnel support.
Cloudflared must be installed via install.sh or manually by the user.

Tunnels are managed independently of browser sessions - they are purely
a network utility for exposing local ports via Cloudflare quick tunnels.

Tunnels survive CLI process exit by:
1. Spawning cloudflared as a daemon (start_new_session=True)
2. Tracking tunnel info via PID files in ~/.browser-use/tunnels/
"""

import asyncio
import json
import logging
import os
import re
import shutil
import signal
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Pattern to extract tunnel URL from cloudflared output
_URL_PATTERN = re.compile(r'(https://\S+\.trycloudflare\.com)')

# Directory for tunnel PID files
_TUNNELS_DIR = Path.home() / '.browser-use' / 'tunnels'


class TunnelManager:
	"""Manages cloudflared binary location."""

	def __init__(self) -> None:
		self._binary_path: str | None = None

	def get_binary_path(self) -> str:
		"""Get cloudflared binary path.

		Returns:
			Absolute path to cloudflared binary

		Raises:
			RuntimeError: If cloudflared is not installed
		"""
		# Cached result from previous call
		if self._binary_path:
			return self._binary_path

		# Check system installation
		system_binary = shutil.which('cloudflared')
		if system_binary:
			logger.info('Using cloudflared: %s', system_binary)
			self._binary_path = system_binary
			return system_binary

		# Not found
		raise RuntimeError(
			'cloudflared not installed.\n\n'
			'Install cloudflared:\n'
			'  macOS:   brew install cloudflared\n'
			'  Linux:   curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o ~/.local/bin/cloudflared && chmod +x ~/.local/bin/cloudflared\n'
			'  Windows: winget install Cloudflare.cloudflared\n\n'
			'Or re-run install.sh which installs cloudflared automatically.\n\n'
			'Then retry: browser-use tunnel <port>'
		)

	def is_available(self) -> bool:
		"""Check if cloudflared is available."""
		if self._binary_path:
			return True
		return shutil.which('cloudflared') is not None

	def get_status(self) -> dict[str, Any]:
		"""Get tunnel capability status for doctor command."""
		system_binary = shutil.which('cloudflared')
		if system_binary:
			return {
				'available': True,
				'source': 'system',
				'path': system_binary,
				'note': 'cloudflared installed',
			}

		return {
			'available': False,
			'source': None,
			'path': None,
			'note': 'cloudflared not installed - run install.sh or install manually',
		}


# Global singleton instance
_tunnel_manager: TunnelManager | None = None


def get_tunnel_manager() -> TunnelManager:
	"""Get the global TunnelManager instance (singleton pattern)."""
	global _tunnel_manager
	if _tunnel_manager is None:
		_tunnel_manager = TunnelManager()
	return _tunnel_manager


# =============================================================================
# PID File Management
# =============================================================================


def _get_tunnel_file(port: int) -> Path:
	"""Get the path to a tunnel's info file."""
	return _TUNNELS_DIR / f'{port}.json'


def _save_tunnel_info(port: int, pid: int, url: str) -> None:
	"""Save tunnel info to disk."""
	_TUNNELS_DIR.mkdir(parents=True, exist_ok=True)
	_get_tunnel_file(port).write_text(json.dumps({'port': port, 'pid': pid, 'url': url}))


def _load_tunnel_info(port: int) -> dict[str, Any] | None:
	"""Load tunnel info from disk, returning None if not found or process dead."""
	tunnel_file = _get_tunnel_file(port)
	if not tunnel_file.exists():
		return None

	try:
		info = json.loads(tunnel_file.read_text())
		pid = info.get('pid')
		if pid and _is_process_alive(pid):
			return info
		# Process dead, clean up stale file
		tunnel_file.unlink(missing_ok=True)
		return None
	except (json.JSONDecodeError, OSError):
		tunnel_file.unlink(missing_ok=True)
		return None


def _delete_tunnel_info(port: int) -> None:
	"""Delete tunnel info file."""
	_get_tunnel_file(port).unlink(missing_ok=True)


def _is_process_alive(pid: int) -> bool:
	"""Check if a process is still running."""
	try:
		os.kill(pid, 0)
		return True
	except (OSError, ProcessLookupError):
		return False


def _kill_process(pid: int) -> bool:
	"""Kill a process by PID. Returns True if killed, False if already dead."""
	try:
		os.kill(pid, signal.SIGTERM)
		# Give it a moment to terminate gracefully
		for _ in range(10):
			if not _is_process_alive(pid):
				return True
			import time

			time.sleep(0.1)
		# Force kill if still alive
		os.kill(pid, signal.SIGKILL)
		return True
	except (OSError, ProcessLookupError):
		return False


# =============================================================================
# Standalone Tunnel Functions (no browser session required)
# =============================================================================


async def start_tunnel(port: int) -> dict[str, Any]:
	"""Start a cloudflare quick tunnel for a local port.

	The tunnel runs as a daemon process that survives CLI exit.

	Args:
		port: Local port to tunnel

	Returns:
		Dict with 'url' and 'port' on success, or 'error' on failure
	"""
	# Check if tunnel already exists for this port
	existing = _load_tunnel_info(port)
	if existing:
		return {'url': existing['url'], 'port': port, 'existing': True}

	# Get cloudflared binary
	try:
		tunnel_manager = get_tunnel_manager()
		cloudflared_binary = tunnel_manager.get_binary_path()
	except RuntimeError as e:
		return {'error': str(e)}

	# Create log file for cloudflared stderr (avoids SIGPIPE when parent exits)
	_TUNNELS_DIR.mkdir(parents=True, exist_ok=True)
	log_file_path = _TUNNELS_DIR / f'{port}.log'
	log_file = open(log_file_path, 'w')  # noqa: ASYNC230

	# Spawn cloudflared as a daemon
	# - start_new_session=True: survives parent exit
	# - stderr to file: avoids SIGPIPE when parent's pipe closes
	process = await asyncio.create_subprocess_exec(
		cloudflared_binary,
		'tunnel',
		'--url',
		f'http://localhost:{port}',
		stdout=asyncio.subprocess.DEVNULL,
		stderr=log_file,
		start_new_session=True,
	)

	# Poll the log file until we find the tunnel URL
	url: str | None = None
	try:
		import time

		deadline = time.time() + 15
		while time.time() < deadline:
			# Check if process died
			if process.returncode is not None:
				log_file.close()
				content = log_file_path.read_text() if log_file_path.exists() else ''
				return {'error': f'cloudflared exited unexpectedly: {content[:500]}'}

			# Read log file content
			try:
				content = log_file_path.read_text()
				match = _URL_PATTERN.search(content)
				if match:
					url = match.group(1)
					break
			except OSError:
				pass

			await asyncio.sleep(0.2)
	except Exception as e:
		process.terminate()
		log_file.close()
		return {'error': f'Failed to start tunnel: {e}'}

	if url is None:
		process.terminate()
		log_file.close()
		return {'error': 'Timed out waiting for cloudflare tunnel URL (15s)'}

	# Close log file handle to avoid leaking file descriptors
	log_file.close()

	# Save tunnel info to disk so it persists across CLI invocations
	_save_tunnel_info(port, process.pid, url)
	logger.info(f'Tunnel started: localhost:{port} -> {url} (pid={process.pid})')

	return {'url': url, 'port': port}


def list_tunnels() -> dict[str, Any]:
	"""List active tunnels.

	Returns:
		Dict with 'tunnels' list and 'count'
	"""
	tunnels = []
	if _TUNNELS_DIR.exists():
		for tunnel_file in _TUNNELS_DIR.glob('*.json'):
			try:
				port = int(tunnel_file.stem)
				info = _load_tunnel_info(port)
				if info:
					tunnels.append({'port': info['port'], 'url': info['url']})
			except (ValueError, json.JSONDecodeError):
				continue
	return {'tunnels': tunnels, 'count': len(tunnels)}


async def stop_tunnel(port: int) -> dict[str, Any]:
	"""Stop a tunnel for a specific port.

	Args:
		port: Port number to stop tunnel for

	Returns:
		Dict with 'stopped' port and 'url' on success, or 'error'
	"""
	info = _load_tunnel_info(port)
	if not info:
		return {'error': f'No tunnel running on port {port}'}

	url = info['url']
	pid = info['pid']
	_kill_process(pid)
	_delete_tunnel_info(port)
	# Clean up log file
	log_file = _TUNNELS_DIR / f'{port}.log'
	log_file.unlink(missing_ok=True)
	logger.info(f'Tunnel stopped: localhost:{port}')

	return {'stopped': port, 'url': url}


async def stop_all_tunnels() -> dict[str, Any]:
	"""Stop all active tunnels.

	Returns:
		Dict with 'stopped' list of ports
	"""
	stopped = []
	if _TUNNELS_DIR.exists():
		for tunnel_file in _TUNNELS_DIR.glob('*.json'):
			try:
				port = int(tunnel_file.stem)
				result = await stop_tunnel(port)
				if 'stopped' in result:
					stopped.append(port)
			except ValueError:
				continue

	return {'stopped': stopped, 'count': len(stopped)}
