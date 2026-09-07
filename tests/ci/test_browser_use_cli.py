import json
import os
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

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
	assert result.stdout == 'usage: browser-use doctor [--fix-snap|--json [--require-existing-daemon]]\n'
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


def test_browser_use_version_reports_installed_distribution():
	result = _run_browser_use_cli('--version')

	assert result.returncode == 0
	assert result.stdout.strip() == version('browser-use')
	assert result.stderr == ''


@pytest.mark.parametrize('args', [('--json', '--require-existing-daemon'), ('--require-existing-daemon', '--json')])
def test_browser_use_doctor_json_reports_missing_daemon_without_starting_one(monkeypatch, tmp_path, args):
	monkeypatch.setenv('BH_HOME', str(tmp_path))
	monkeypatch.delenv('BROWSER_HARNESS_HOME', raising=False)
	monkeypatch.delenv('BU_NAME', raising=False)
	result = _run_browser_use_cli('doctor', *args)

	assert result.returncode == 1
	report = json.loads(result.stdout)
	assert report['healthy'] is False
	assert report['require_existing_daemon'] is True
	assert report['daemon']['alive'] is False
	assert result.stderr == ''
	assert not list(tmp_path.rglob('*.sock'))


@pytest.mark.parametrize('args', [('--require-existing-daemon',), ('--json', '--json'), ('--json', '--fix-snap'), ('--wat',)])
def test_browser_use_doctor_still_rejects_invalid_options(args):
	result = _run_browser_use_cli('doctor', *args)

	assert result.returncode == 2
	assert result.stdout == ''
	assert result.stderr == 'usage: browser-use doctor [--fix-snap|--json [--require-existing-daemon]]\n'
