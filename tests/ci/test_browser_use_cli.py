import os
import subprocess
import sys
import tomllib
from pathlib import Path

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


def test_console_scripts_avoid_generic_names():
	# `uv tool install` aborts if any script name is already taken by another tool's executable.
	scripts = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['scripts']
	assert set(scripts) == {'browser-use', 'browseruse', 'browser-use-tui'}


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


def test_install_downloads_playwright_chromium_like_0x(monkeypatch, capsys):
	"""Kept from 0.x: local-browser users (QA, CI) still get a Chromium from `browser-use install`."""
	import platform
	import shutil
	import subprocess

	import browser_use.cli as browser_use_cli

	ran = []
	monkeypatch.setattr(shutil, 'which', lambda name: '/usr/bin/uvx')
	monkeypatch.setattr(platform, 'system', lambda: 'Linux')
	monkeypatch.setattr(subprocess, 'run', lambda cmd, **k: ran.append(cmd) or subprocess.CompletedProcess(cmd, 0))
	assert browser_use_cli._run_install_command([]) == 0
	assert ran == [['uvx', 'playwright', 'install', 'chromium', '--with-deps', '--no-shell']]
	out = capsys.readouterr().out
	assert 'Installation complete' in out and "Browser('chromium')" in out and "Browser('chrome')" in out

	monkeypatch.setattr(subprocess, 'run', lambda cmd, **k: subprocess.CompletedProcess(cmd, 3))
	assert browser_use_cli._run_install_command([]) == 3
	monkeypatch.setattr(shutil, 'which', lambda name: None)
	assert browser_use_cli._run_install_command([]) == 1
	assert 'playwright install chromium' in capsys.readouterr().err


def test_help_is_this_clis_own():
	"""M34: --help printed browser-harness's help: `doctor --json` (rc 2 here), a --update that updates browser-harness,
	and no login, logout, install or --cli-mcp."""
	result = _run_browser_use_cli('--help')
	assert result.returncode == 0 and result.stderr == ''
	for command in ('browser-use login', 'browser-use logout', 'browser-use install', '--cli-mcp', 'browser-use skill'):
		assert command in result.stdout
	assert 'doctor --json' not in result.stdout and 'browser-harness' not in result.stdout and '--update' not in result.stdout
	update = _run_browser_use_cli('--update', '-y')
	assert update.returncode == 2 and 'uv tool upgrade browser-use' in update.stderr
