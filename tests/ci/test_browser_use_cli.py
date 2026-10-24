import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _run_browser_use_cli(*args: str, module: str = 'browser_use.cli') -> subprocess.CompletedProcess[str]:
	env = os.environ.copy()
	env['PYTHONPATH'] = os.pathsep.join(part for part in (str(ROOT), env.get('PYTHONPATH', '')) if part)
	return subprocess.run(
		[sys.executable, '-m', module, *args],
		cwd=ROOT,
		env=env,
		capture_output=True,
		text=True,
		timeout=20,
	)


def test_browser_use_doctor_help_prints_browser_use_usage():
	result = _run_browser_use_cli('doctor', '--help')

	assert result.returncode == 0
	assert result.stdout == 'usage: browser-use doctor [--fix-snap]\n'
	assert result.stderr == ''


def test_browser_use_module_entrypoint_matches_cli_entrypoint():
	cli_result = _run_browser_use_cli('doctor', '--help')
	module_result = _run_browser_use_cli('doctor', '--help', module='browser_use')

	assert module_result.returncode == cli_result.returncode == 0
	assert module_result.stdout == cli_result.stdout
	assert module_result.stderr == cli_result.stderr == ''


def test_normalize_captured_cli_output_handles_string_system_exit(capsys):
	from browser_use.cli import _normalize_captured_cli_output

	def exits_with_string(_argv):
		raise SystemExit('browser-harness failed')

	assert _normalize_captured_cli_output(exits_with_string, []) == 1
	captured = capsys.readouterr()
	assert captured.out == ''
	assert captured.err == 'browser-use failed\n'


def test_browser_use_tui_is_deprecated_alias(monkeypatch, capsys):
	import browser_use.cli as browser_use_cli

	monkeypatch.setattr(browser_use_cli, 'main', lambda: 0)

	assert browser_use_cli.browser_use_tui_main() == 0
	assert capsys.readouterr().err == 'browser-use-tui is deprecated; use browser-use instead.\n'


def test_pi_task_help_requires_no_browser_or_runtime():
	result = _run_browser_use_cli('run', '--help')

	assert result.returncode == 0, result.stderr
	assert 'Run a task with the Pi agent.' in result.stdout
	assert '--browser {cloud,chrome,chromium}' in result.stdout
	assert '--cdp-url' in result.stdout


@pytest.mark.parametrize(
	'extra, message',
	[([], 'Set --model or BROWSER_USE_MODEL.'), (['--model', 'test/model', '--max-steps', '0'], '--max-steps must be positive.')],
)
def test_pi_task_rejects_invalid_options_before_connecting(monkeypatch, extra, message):
	monkeypatch.delenv('BROWSER_USE_MODEL', raising=False)
	result = _run_browser_use_cli('run', 'Read the page title', *extra)

	assert result.returncode == 2
	assert message in result.stderr


@pytest.mark.parametrize(
	'browser, cdp_url, inherited_ws',
	[
		('chrome', None, None),
		('chromium', None, None),
		('cloud', 'http://127.0.0.1:9222', 'ws://prior-browser'),
		('cloud', None, 'ws://explicit-browser'),
	],
)
def test_explicit_local_browser_avoids_cloud_provisioning(monkeypatch, browser, cdp_url, inherited_ws):
	from browser_use.cli import _ensure_harness_browser

	monkeypatch.setitem(sys.modules, 'browser_harness', None)
	monkeypatch.delenv('BU_NAME', raising=False)
	monkeypatch.delenv('BU_CDP_URL', raising=False)
	monkeypatch.delenv('BU_CDP_WS', raising=False)
	if inherited_ws:
		monkeypatch.setenv('BU_CDP_WS', inherited_ws)
	_ensure_harness_browser(browser, cdp_url)
	if cdp_url:
		assert os.environ['BU_CDP_URL'] == cdp_url
		assert 'BU_CDP_WS' not in os.environ


def test_cloud_default_rejects_a_local_daemon(monkeypatch):
	from browser_use.cli import _ensure_harness_browser

	monkeypatch.delenv('BU_CDP_URL', raising=False)
	monkeypatch.delenv('BU_CDP_WS', raising=False)
	monkeypatch.setenv('BU_NAME', 'existing-local-session')
	admin = SimpleNamespace(daemon_alive=lambda name: True, daemon_browser_kind=lambda name: 'local')
	monkeypatch.setitem(sys.modules, 'browser_harness', SimpleNamespace(admin=admin))

	with pytest.raises(RuntimeError, match='use --browser chrome'):
		_ensure_harness_browser('cloud')


def test_cloud_default_uses_a_separate_named_session(monkeypatch):
	from browser_use.cli import _ensure_harness_browser

	for key in ('BU_NAME', 'BU_CDP_URL', 'BU_CDP_WS', 'BH_REQUIRE_EXISTING_DAEMON', 'BROWSER_USE_BROWSER'):
		monkeypatch.delenv(key, raising=False)
	started = []
	admin = SimpleNamespace(daemon_alive=lambda name: False, start_remote_daemon=started.append)
	monkeypatch.setitem(sys.modules, 'browser_harness', SimpleNamespace(admin=admin))

	_ensure_harness_browser()

	assert started == ['browser-use-cloud']
	assert os.environ['BU_NAME'] == 'browser-use-cloud'


def test_direct_mcp_help_lists_explicit_browser_choices():
	result = _run_browser_use_cli('--mcp', '--help')

	assert result.returncode == 0, result.stderr
	assert 'Expose direct browser control through MCP.' in result.stdout
	assert '--browser {cloud,chrome,chromium}' in result.stdout
	assert '--cdp-url' in result.stdout


@pytest.mark.parametrize(
	'code, failed, output',
	[('print("ready")', False, 'ready'), ('1 / 0', True, 'ZeroDivisionError'), ('raise SystemExit(4)', True, 'SystemExit: 4')],
)
def test_direct_mcp_distinguishes_execution_failure(code, failed, output):
	import asyncio

	pytest.importorskip('mcp')
	from mcp import ClientSession, StdioServerParameters
	from mcp.client.stdio import stdio_client

	async def check():
		program = (
			'import asyncio; from browser_use.mcp.cli_mcp import CLIMCPServer; '
			'server=CLIMCPServer(); server._ensure_daemon=lambda code: None; asyncio.run(server.run())'
		)
		params = StdioServerParameters(
			command=sys.executable,
			args=['-c', program],
			env=dict(os.environ, PYTHONPATH=str(ROOT), DO_NOT_TRACK='1', ANONYMIZED_TELEMETRY='false'),
		)
		async with stdio_client(params) as (reader, writer):
			async with ClientSession(reader, writer) as session:
				await session.initialize()
				result = await session.call_tool('browser_exec', {'code': code})
				assert result.is_error is failed
				content = result.content[0]
				assert content.type == 'text'
				assert output in content.text

	asyncio.run(asyncio.wait_for(check(), 10))


@pytest.mark.parametrize('failure', [False, True])
def test_direct_program_suppresses_legacy_payload_and_restores_harness(monkeypatch, capsys, failure):
	from io import StringIO

	import browser_harness.run as harness_run
	from browser_harness import telemetry
	import browser_use.cli as cli

	for key in telemetry.DISABLE_ENVS:
		monkeypatch.delenv(key, raising=False)
	monkeypatch.setenv('BH_TELEMETRY', 'true')
	monkeypatch.setattr(telemetry, '_load_config', lambda: {})
	monkeypatch.setattr(telemetry, '_install_id', lambda: '00000000-0000-4000-8000-000000000000')
	payloads = []
	monkeypatch.setattr(telemetry, '_send_detached', payloads.append)
	monkeypatch.setattr(cli, '_ensure_harness_browser', lambda *args: None)
	monkeypatch.setattr(harness_run, 'ensure_daemon', lambda: None)
	monkeypatch.setattr(harness_run, 'print_update_banner', lambda: None)
	monkeypatch.setattr(harness_run, 'daemon_alive', lambda: True)
	monkeypatch.setattr(harness_run, '_local_chrome_listening', lambda: True)
	monkeypatch.setattr(sys, 'argv', ['browser-use'])
	code = 'print("private-output")'
	if failure:
		code += '; raise ValueError("private-error")'
	monkeypatch.setattr(sys, 'stdin', StringIO(code))

	if failure:
		with pytest.raises(ValueError, match='private-error'):
			cli.main()
	else:
		assert cli.main() is None

	assert 'private-output' in capsys.readouterr().out
	assert payloads == []
	assert os.environ['BH_TELEMETRY'] == 'true'
	telemetry.capture_cli_event(action='completed', command='script', task='independent-harness')
	assert payloads[0]['properties']['task'] == 'independent-harness'


def test_direct_program_child_inherits_legacy_suppression(monkeypatch):
	from io import StringIO

	from browser_harness import admin
	import browser_use.cli as cli

	monkeypatch.delenv('BH_TELEMETRY', raising=False)
	monkeypatch.delenv('BU_CDP_URL', raising=False)
	monkeypatch.delenv('BU_CDP_WS', raising=False)
	monkeypatch.delenv('BH_REQUIRE_EXISTING_DAEMON', raising=False)
	monkeypatch.setenv('BROWSER_USE_BROWSER', 'cloud')
	monkeypatch.setattr(admin, 'daemon_alive', lambda name: False)

	def start_child(name):
		result = subprocess.run(
			[
				sys.executable,
				'-c',
				'import os; from browser_harness.telemetry import is_enabled; print(os.environ.get("BH_TELEMETRY"), is_enabled())',
			],
			capture_output=True,
			text=True,
			check=True,
			timeout=5,
		)
		assert result.stdout == 'false False\n'
		raise RuntimeError('stop-before-provisioning')

	monkeypatch.setattr(admin, 'start_remote_daemon', start_child)
	monkeypatch.setattr(sys, 'argv', ['browser-use'])
	monkeypatch.setattr(sys, 'stdin', StringIO('print("private-code")'))

	with pytest.raises(RuntimeError, match='stop-before-provisioning'):
		cli.main()

	assert 'BH_TELEMETRY' not in os.environ


def test_pi_task_keeps_its_telemetry_environment(monkeypatch):
	import browser_use.cli as cli

	monkeypatch.setenv('BH_TELEMETRY', 'true')
	monkeypatch.setattr(sys, 'argv', ['browser-use', 'run', 'Read the title'])

	def run_task(args):
		assert os.environ['BH_TELEMETRY'] == 'true'
		return 0

	monkeypatch.setattr(cli, '_run_task', run_task)
	assert cli.main() == 0


def test_telemetry_status_preserves_independent_harness_preference(monkeypatch, capsys):
	import json

	from browser_harness import telemetry
	import browser_use.cli as cli

	for key in telemetry.DISABLE_ENVS:
		monkeypatch.delenv(key, raising=False)
	monkeypatch.setattr(telemetry, '_load_config', lambda: {'install_id': '00000000-0000-4000-8000-000000000000'})
	monkeypatch.setattr(sys, 'argv', ['browser-use', 'telemetry', 'status'])

	with pytest.raises(SystemExit) as exc:
		cli.main()

	assert exc.value.code == 0
	assert json.loads(capsys.readouterr().out)['enabled'] is True


def test_direct_mcp_suppresses_legacy_payload_and_restores_environment(monkeypatch):
	import importlib
	import logging

	from browser_harness import telemetry
	import browser_use.cli as cli

	for key in telemetry.DISABLE_ENVS:
		monkeypatch.delenv(key, raising=False)
	monkeypatch.setattr(telemetry, '_load_config', lambda: {})
	payloads = []
	monkeypatch.setattr(telemetry, '_send_detached', payloads.append)

	async def main():
		telemetry.capture_cli_event(action='error', command='mcp', task='private-code', error_message='private-error')
		assert os.environ['BH_TELEMETRY'] == 'false'

	monkeypatch.setattr(importlib, 'import_module', lambda name: SimpleNamespace(main=main))
	monkeypatch.setattr(logging, 'disable', lambda level: None)
	monkeypatch.setenv('BROWSER_USE_LOGGING_LEVEL', 'debug')
	monkeypatch.setenv('BROWSER_USE_SETUP_LOGGING', 'true')
	cli._run_mcp_stdio_server('browser_use.mcp.cli_mcp')

	assert payloads == []
	assert 'BH_TELEMETRY' not in os.environ
