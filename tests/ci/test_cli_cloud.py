"""Tests for browser-use cloud CLI command."""

import json
import subprocess
import sys
from pathlib import Path

from pytest_httpserver import HTTPServer
from werkzeug.wrappers import Request, Response

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def run_cli(*args: str, env_override: dict | None = None, api_key: str | None = None) -> subprocess.CompletedProcess:
	"""Run the CLI as a subprocess, returning the result.

	If api_key is provided, writes it to a temp config.json via BROWSER_USE_HOME
	(the CLI reads API keys from config.json only, not env vars).
	"""
	import os
	import tempfile

	env = os.environ.copy()
	# Prevent real API key from leaking into tests
	env.pop('BROWSER_USE_API_KEY', None)
	if env_override:
		env.update(env_override)

	# Write API key to temp config.json if requested
	if api_key is not None:
		tmp_home = env.get('BROWSER_USE_HOME')
		if not tmp_home:
			tmp_home = tempfile.mkdtemp()
			env['BROWSER_USE_HOME'] = tmp_home
		config_path = Path(tmp_home) / 'config.json'
		existing = json.loads(config_path.read_text()) if config_path.exists() else {}
		existing['api_key'] = api_key
		config_path.write_text(json.dumps(existing))

	return subprocess.run(
		[sys.executable, '-m', 'browser_use.skill_cli.main', 'cloud', *args],
		capture_output=True,
		text=True,
		env=env,
		timeout=15,
	)


# ---------------------------------------------------------------------------
# Login / Logout
# ---------------------------------------------------------------------------


def test_cloud_no_args_shows_usage():
	result = run_cli()
	# No args → usage on stdout, exit 1
	assert result.returncode == 1
	assert 'Usage' in result.stdout
	assert 'login' in result.stdout


def test_cloud_login_saves_key(tmp_path: Path):
	config_path = tmp_path / 'config.json'
	result = run_cli(
		'login',
		'sk-test-key-123',
		env_override={
			'BROWSER_USE_HOME': str(tmp_path),
		},
	)
	assert result.returncode == 0
	assert 'saved' in result.stdout.lower()

	# Verify file was written
	real_config = tmp_path / 'config.json'
	assert real_config.exists()
	data = json.loads(real_config.read_text())
	assert data['api_key'] == 'sk-test-key-123'


def test_cloud_logout_removes_key(tmp_path: Path):
	# First save a key
	config_file = tmp_path / 'config.json'
	config_file.write_text(json.dumps({'api_key': 'sk-remove-me'}))

	result = run_cli(
		'logout',
		env_override={'BROWSER_USE_HOME': str(tmp_path)},
	)
	assert result.returncode == 0
	assert 'removed' in result.stdout.lower()

	# Config file should be deleted (was only key)
	assert not config_file.exists()


def test_cloud_logout_no_key(tmp_path: Path):
	result = run_cli(
		'logout',
		env_override={'BROWSER_USE_HOME': str(tmp_path)},
	)
	assert result.returncode == 0
	assert 'no api key' in result.stdout.lower()


# ---------------------------------------------------------------------------
# REST passthrough
# ---------------------------------------------------------------------------


def test_cloud_rest_get(httpserver: HTTPServer):
	httpserver.expect_request('/api/v2/browsers', method='GET').respond_with_json(
		{'browsers': [{'id': 'b1', 'status': 'running'}]}
	)

	result = run_cli(
		'v2',
		'GET',
		'/browsers',
		env_override={
			'BROWSER_USE_CLOUD_BASE_URL_V2': httpserver.url_for('/api/v2'),
		},
		api_key='sk-test',
	)
	assert result.returncode == 0
	data = json.loads(result.stdout)
	assert data['browsers'][0]['id'] == 'b1'


def test_cloud_rest_post_with_body(httpserver: HTTPServer):
	body_to_send = {'task': 'Search for AI news', 'url': 'https://google.com'}

	def handler(request: Request) -> Response:
		assert request.content_type == 'application/json'
		received = json.loads(request.data)
		assert received == body_to_send
		return Response(json.dumps({'id': 'task-1', 'status': 'created'}), content_type='application/json')

	httpserver.expect_request('/api/v2/tasks', method='POST').respond_with_handler(handler)

	result = run_cli(
		'v2',
		'POST',
		'/tasks',
		json.dumps(body_to_send),
		env_override={
			'BROWSER_USE_CLOUD_BASE_URL_V2': httpserver.url_for('/api/v2'),
		},
		api_key='sk-test',
	)
	assert result.returncode == 0
	data = json.loads(result.stdout)
	assert data['id'] == 'task-1'


def test_cloud_rest_sends_auth_header(httpserver: HTTPServer):
	def handler(request: Request) -> Response:
		assert request.headers.get('X-Browser-Use-API-Key') == 'sk-secret-key'
		return Response(json.dumps({'ok': True}), content_type='application/json')

	httpserver.expect_request('/api/v2/test', method='GET').respond_with_handler(handler)

	result = run_cli(
		'v2',
		'GET',
		'/test',
		env_override={
			'BROWSER_USE_CLOUD_BASE_URL_V2': httpserver.url_for('/api/v2'),
		},
		api_key='sk-secret-key',
	)
	assert result.returncode == 0


def test_cloud_rest_4xx_exits_2(httpserver: HTTPServer):
	httpserver.expect_request('/api/v2/bad', method='GET').respond_with_json({'error': 'not found'}, status=404)

	result = run_cli(
		'v2',
		'GET',
		'/bad',
		env_override={
			'BROWSER_USE_CLOUD_BASE_URL_V2': httpserver.url_for('/api/v2'),
			# Prevent spec fetch from hanging
			'BROWSER_USE_OPENAPI_SPEC_URL_V2': 'http://127.0.0.1:1/nope',
		},
		api_key='sk-test',
	)
	assert result.returncode == 2
	assert 'HTTP 404' in result.stderr


def test_cloud_rest_no_api_key_errors(tmp_path: Path):
	result = run_cli(
		'v2',
		'GET',
		'/browsers',
		env_override={
			'BROWSER_USE_HOME': str(tmp_path),
		},
	)
	# _get_api_key calls sys.exit(1)
	assert result.returncode == 1
	assert 'no api key' in result.stderr.lower()


# ---------------------------------------------------------------------------
# Polling
# ---------------------------------------------------------------------------


def test_cloud_poll_finishes(httpserver: HTTPServer):
	# First call: running, second call: finished
	call_count = {'n': 0}

	def handler(request: Request) -> Response:
		call_count['n'] += 1
		if call_count['n'] == 1:
			return Response(json.dumps({'status': 'running', 'cost': 0.0012}), content_type='application/json')
		return Response(json.dumps({'status': 'finished', 'cost': 0.0050, 'result': 'done'}), content_type='application/json')

	httpserver.expect_request('/api/v2/tasks/t-123', method='GET').respond_with_handler(handler)

	result = run_cli(
		'v2',
		'poll',
		't-123',
		env_override={
			'BROWSER_USE_CLOUD_BASE_URL_V2': httpserver.url_for('/api/v2'),
		},
		api_key='sk-test',
	)
	assert result.returncode == 0
	data = json.loads(result.stdout)
	assert data['status'] == 'finished'
	assert 'status: finished' in result.stderr


def test_cloud_poll_failed_exits_2(httpserver: HTTPServer):
	httpserver.expect_request('/api/v2/tasks/t-fail', method='GET').respond_with_json(
		{'status': 'failed', 'cost': 0.0001, 'error': 'timeout'}
	)

	result = run_cli(
		'v2',
		'poll',
		't-fail',
		env_override={
			'BROWSER_USE_CLOUD_BASE_URL_V2': httpserver.url_for('/api/v2'),
		},
		api_key='sk-test',
	)
	assert result.returncode == 2


# ---------------------------------------------------------------------------
# URL construction
# ---------------------------------------------------------------------------


def test_cloud_url_construction(httpserver: HTTPServer):
	"""Path without leading / should still work."""
	httpserver.expect_request('/api/v2/browsers', method='GET').respond_with_json({'ok': True})

	result = run_cli(
		'v2',
		'GET',
		'browsers',  # no leading /
		env_override={
			'BROWSER_USE_CLOUD_BASE_URL_V2': httpserver.url_for('/api/v2'),
		},
		api_key='sk-test',
	)
	assert result.returncode == 0
	data = json.loads(result.stdout)
	assert data['ok'] is True


# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------


def test_cloud_help_flag():
	"""--help should show something useful even without spec."""
	result = run_cli(
		'v2',
		'--help',
		env_override={
			# Point to unreachable spec URL so static fallback is used
			'BROWSER_USE_OPENAPI_SPEC_URL_V2': 'http://127.0.0.1:1/nope',
		},
	)
	assert result.returncode == 0
	assert 'browser-use cloud v2' in result.stdout.lower()
