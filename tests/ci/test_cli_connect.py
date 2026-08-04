"""Tests for browser-use --connect flag (Chrome CDP auto-discovery)."""

import http.server
import json
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest


def run_cli(*args: str) -> subprocess.CompletedProcess:
	"""Run the CLI as a subprocess, returning the result."""
	import os

	env = os.environ.copy()
	env.pop('BROWSER_USE_API_KEY', None)

	return subprocess.run(
		[sys.executable, '-m', 'browser_use.skill_cli.main', *args],
		capture_output=True,
		text=True,
		env=env,
		timeout=15,
	)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def chrome_data_dir(tmp_path: Path, monkeypatch):
	"""Create a fake Chrome data directory and patch get_chrome_user_data_dirs."""
	data_dir = tmp_path / 'FakeChrome'
	data_dir.mkdir()

	import browser_use.skill_cli.utils as utils_mod

	monkeypatch.setattr(utils_mod, 'get_chrome_user_data_dirs', lambda: [data_dir])
	return data_dir


def _find_free_port() -> int:
	"""Find a free TCP port on localhost."""
	with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
		s.bind(('127.0.0.1', 0))
		return s.getsockname()[1]


def _start_json_version_server(port: int, ws_url: str):
	"""Start a minimal HTTP server that responds to /json/version with a webSocketDebuggerUrl."""

	class Handler(http.server.BaseHTTPRequestHandler):
		def do_GET(self):
			if self.path == '/json/version':
				body = json.dumps({'webSocketDebuggerUrl': ws_url}).encode()
				self.send_response(200)
				self.send_header('Content-Type', 'application/json')
				self.send_header('Content-Length', str(len(body)))
				self.end_headers()
				self.wfile.write(body)
			else:
				self.send_error(404)

		def log_message(self, format, *_args):
			pass  # silence logs

	server = http.server.HTTPServer(('127.0.0.1', port), Handler)
	thread = threading.Thread(target=server.serve_forever, daemon=True)
	thread.start()
	return server


def _start_tcp_listener(port: int) -> socket.socket:
	"""Start a bare TCP listener (accepts connections but serves no HTTP)."""
	srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
	srv.bind(('127.0.0.1', port))
	srv.listen(16)  # larger backlog so HTTP probe doesn't exhaust it
	return srv


# ---------------------------------------------------------------------------
# Unit tests for discover_chrome_cdp_url
# ---------------------------------------------------------------------------


def test_discover_from_devtools_active_port(chrome_data_dir: Path):
	"""DevToolsActivePort exists + /json/version responds → return webSocketDebuggerUrl."""
	from browser_use.skill_cli.utils import discover_chrome_cdp_url

	port = _find_free_port()
	expected_ws = f'ws://127.0.0.1:{port}/devtools/browser/abc123'

	# Write DevToolsActivePort
	(chrome_data_dir / 'DevToolsActivePort').write_text(f'{port}\n/devtools/browser/abc123\n')

	# Start HTTP server that serves /json/version
	server = _start_json_version_server(port, expected_ws)
	try:
		result = discover_chrome_cdp_url()
		assert result == expected_ws
	finally:
		server.shutdown()


def test_discover_direct_ws_when_http_fails(chrome_data_dir: Path):
	"""DevToolsActivePort exists, port is open, but no HTTP → fall back to ws:// from file."""
	from browser_use.skill_cli.utils import discover_chrome_cdp_url

	port = _find_free_port()

	(chrome_data_dir / 'DevToolsActivePort').write_text(f'{port}\n/devtools/browser/xyz789\n')

	# Start a bare TCP listener (no HTTP)
	srv = _start_tcp_listener(port)
	try:
		result = discover_chrome_cdp_url()
		assert result == f'ws://127.0.0.1:{port}/devtools/browser/xyz789'
	finally:
		srv.close()


def test_discover_stale_port_falls_through(chrome_data_dir: Path):
	"""DevToolsActivePort with a dead port, no fallback listeners → RuntimeError."""
	from browser_use.skill_cli.utils import discover_chrome_cdp_url

	# Use a port that nothing is listening on
	port = _find_free_port()
	(chrome_data_dir / 'DevToolsActivePort').write_text(f'{port}\n/devtools/browser/stale\n')

	with pytest.raises(RuntimeError, match='remote debugging'):
		discover_chrome_cdp_url()


def test_discover_no_chrome_errors(chrome_data_dir: Path):
	"""No DevToolsActivePort at all, no fallback listeners → RuntimeError."""
	from browser_use.skill_cli.utils import discover_chrome_cdp_url

	# chrome_data_dir exists but has no DevToolsActivePort file
	with pytest.raises(RuntimeError, match='remote debugging'):
		discover_chrome_cdp_url()


def test_discover_fallback_well_known_port(chrome_data_dir: Path):
	"""No DevToolsActivePort, but port 9222 serves /json/version → returns that URL."""
	from browser_use.skill_cli.utils import discover_chrome_cdp_url

	expected_ws = 'ws://127.0.0.1:9222/devtools/browser/fallback'

	# No DevToolsActivePort file — discovery should fall through to port 9222
	try:
		server = _start_json_version_server(9222, expected_ws)
	except OSError:
		pytest.skip('Port 9222 already in use')

	try:
		result = discover_chrome_cdp_url()
		assert result == expected_ws
	finally:
		server.shutdown()


# ---------------------------------------------------------------------------
# CLI integration tests (subprocess)
# ---------------------------------------------------------------------------


def test_connect_shows_deprecation():
	"""--connect should show deprecation message."""
	result = run_cli('--connect', 'open', 'https://example.com')
	assert result.returncode == 1
	assert '--connect has been replaced' in result.stderr


def test_connect_shows_in_help():
	"""--help output should contain --connect."""
	result = run_cli('--help')
	assert '--connect' in result.stdout
