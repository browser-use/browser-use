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


def test_mcp_dependency_is_a_range_not_an_exact_pin():
	# An exact `mcp==` pin makes projects that need a newer mcp (e.g. pydantic-ai-slim[mcp] via fastmcp) unresolvable.
	deps = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['dependencies']
	assert [d for d in deps if d.startswith('mcp')] == ['mcp>=2.1.1,<3']


def test_the_cli_extra_still_resolves():
	# 0.x docs and install-script.yml install `browser-use[cli]`; without the extra uv and pip warn on every install.
	extras = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['optional-dependencies']
	assert extras['cli'] == []


def test_browser_use_doctor_help_prints_browser_use_usage():
	result = _run_browser_use_cli('doctor', '--help')

	assert result.returncode == 0
	assert result.stdout == 'usage: browser-use doctor [--fix-snap]\n'
	assert result.stderr == ''


def test_browser_use_doctor_names_browser_use_and_passes_without_a_daemon(tmp_path):
	"""C48: --doctor ran browser-harness's doctor: header `browser-harness doctor`, its version, and exit 1 with
	[FAIL] rows whenever the daemon was stopped (every call starts it) or nobody was signed in (optional)."""
	env = {**os.environ, 'BH_HOME': str(tmp_path), 'BU_NAME': f'doctor-test-{os.getpid()}', 'BROWSER_USE_API_KEY': 'k'}
	env['PYTHONPATH'] = str(ROOT)
	for argv in (['--doctor'], ['doctor']):
		result = subprocess.run(
			[sys.executable, '-m', 'browser_use.cli', *argv], cwd=ROOT, env=env, capture_output=True, text=True, timeout=20
		)
		assert result.returncode == 0, result.stdout + result.stderr
		assert result.stdout.startswith('browser-use ')
		assert 'stopped (the next call starts it)' in result.stdout
		assert 'browser-harness doctor' not in result.stdout and 'FAIL' not in result.stdout


def test_browser_use_doctor_fix_snap_names_browser_use():
	result = _run_browser_use_cli('doctor', '--fix-snap')

	assert result.returncode == 0
	assert 'browser-use --doctor' in result.stdout and 'browser-harness --doctor' not in result.stdout


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


def test_0x_agent_task_commands_point_to_agent():
	"""C51: `run`, `-p` and `--prompt` started an agent task in 0.x; they said 'changed in 3.0' or printed harness usage."""
	import browser_use.cli as browser_use_cli

	for args in (['run', 'go to example.com'], ['-p', 'find stars'], ['--prompt=find stars']):
		code, command = browser_use_cli._dispatch(args)
		assert code == 2 and command == f'legacy:{args[0].split("=")[0]}'
		message = browser_use_cli._legacy_migration_message(command.removeprefix('legacy:'))
		assert 'changed in 1.0' in message and 'from browser_use import Agent' in message and '3.0' not in message
		assert 'python -c' not in message


def test_0x_page_commands_name_the_helper_that_replaced_them(capsys):
	"""rr-climcp 4: the docs say the 0.x subcommands print what replaced them; `browser-use click 5` (and type, input,
	keys, scroll, back, hover) printed browser-harness's generic usage and exit 1."""
	import browser_use.cli as browser_use_cli

	for args, helper in (
		(['click', '5'], 'click_at_xy('), (['type', 'hi'], 'type_text('), (['input', '3', 'hi'], 'fill_input('),
		(['keys', 'Enter'], 'press_key('), (['scroll', 'down'], 'scroll('), (['back'], 'history.back()'),
		(['hover', '4'], 'mouseMoved'),
	):  # fmt: skip
		assert browser_use_cli._dispatch(args) == (2, f'legacy:{args[0]}')
		err = capsys.readouterr().err
		assert f"'{args[0]}' was removed" in err and helper in err, err


def test_bh_runtime_dir_keeps_one_socket_per_bu_name(tmp_path):
	# C47: with BH_RUNTIME_DIR set (the fix our AF_UNIX-too-long error suggests), browser-harness names every daemon's
	# files plain bu.sock / bu.pid, so `BU_NAME=b browser-use --reload` stopped daemon a and b drove a's browser.
	ep = 'port' if sys.platform == 'win32' else 'sock'  # the daemon's endpoint file: Windows uses TCP, not AF_UNIX
	for f in ('bu.' + ep, 'bu.pid', 'bu-a.' + ep, 'bu-a.pid', 'bu-b.' + ep, 'bu-b.pid'):
		(tmp_path / f).touch()
	env = {k: v for k, v in os.environ.items() if not k.startswith('BH_')}
	env.update(BH_RUNTIME_DIR=str(tmp_path), BU_NAME='b', PYTHONPATH=str(ROOT))
	r = subprocess.run(
		[sys.executable, '-m', 'browser_use.cli', '--reload'], cwd=ROOT, env=env, capture_output=True, text=True, timeout=30
	)
	assert r.returncode == 0, r.stderr
	assert sorted(p.name for p in tmp_path.iterdir()) == sorted(['bu-a.pid', 'bu-a.' + ep, 'bu.pid', 'bu.' + ep])


def test_first_run_text_gives_the_readmes_agent_prompt(monkeypatch, capsys):
	"""bu1-docs-1107: `browser-use` in a terminal told users to paste a pre-release install (`--prerelease allow
	'browser-use>=1.0.0rc1'`) and linked a SKILL.md on main. The prompt it prints is the README's, word for word."""
	import re

	import browser_use.cli as browser_use_cli

	monkeypatch.setattr(sys.stdin, 'isatty', lambda: True)
	assert browser_use_cli._dispatch([]) == (0, 'quickstart')
	printed = capsys.readouterr().out
	pasted = printed.split('paste this into your agent to get started:\n\n', 1)[1].split('\n\n', 1)[0]
	readme = (ROOT / 'README.md').read_text(encoding='utf-8')
	assert ' '.join(pasted.split()) in re.findall(r'```text\n(.+?)\n```', readme, re.S)
	assert 'prerelease' not in printed and 'docs.browser-use.com' in printed


def test_piped_code_never_tells_the_agent_to_update_browser_harness(tmp_path):
	"""Live: once browser-harness has a newer release on PyPI, every piped call printed (daily) `[browser-harness] agents:
	run browser-harness --update -y`. browser-use pins browser-harness exactly: that command is not on PATH for
	`uv tool install browser-use`, and in a venv it upgrades browser-harness past the pin. Updates come with browser-use."""
	import json
	import time

	(tmp_path / 'version-cache.json').write_text(json.dumps({'tag': '99.0.0', 'fetched_at': time.time()}))
	env = {k: v for k, v in os.environ.items() if not k.startswith(('BH_', 'BU_'))}
	env.update(BH_HOME=str(tmp_path), BU_NAME=f'update-test-{os.getpid()}', BU_CDP_URL='http://127.0.0.1:1')
	env.update(PYTHONPATH=str(ROOT), ANONYMIZED_TELEMETRY='false')
	r = subprocess.run(
		[sys.executable, '-m', 'browser_use.cli'],
		input='print("ran")\nif False: start_remote_daemon()',  # a cloud call anywhere in the code: no local attach first
		cwd=ROOT,
		env=env,
		capture_output=True,
		text=True,
		timeout=60,
	)
	assert 'update available' not in r.stderr and '--update' not in r.stderr, r.stderr
	assert (r.returncode, r.stdout) == (0, 'ran\n'), r.stderr


def test_browser_harness_hints_name_commands_this_install_has(monkeypatch, capsys):
	"""Live: piped code printed browser-harness's own lines, e.g. its macOS Allow-popup hint `run BU_NAME=x
	browser-harness mac-approve in another shell`. `uv tool install browser-use` puts no browser-harness on PATH, so the
	agent's next command failed; `browser-use mac-approve` is the same helper. The cell's own output is left alone."""
	from browser_harness import run

	from browser_use import cli

	def harness_main():
		print('browser-harness: Chrome is asking "Allow remote debugging?" — run `BU_NAME=w browser-harness mac-approve` '
			'in another shell or click Allow to continue.', file=sys.stderr)  # fmt: skip
		print('browser-harness: fatal: see ~/.config/browser-harness/tmp/bu-w.log', file=sys.stderr)
		print('cell output names browser-harness', file=sys.stderr)

	monkeypatch.setattr(run, 'main', harness_main)
	monkeypatch.setattr(sys, 'argv', ['browser-use'])
	monkeypatch.setenv('BH_UPDATE_CHECK', '0')
	stderr = sys.stderr
	cli._run_browser_harness('print(1)')
	assert sys.stderr is stderr
	assert capsys.readouterr().err.splitlines() == [
		'browser-use: Chrome is asking "Allow remote debugging?" — run `BU_NAME=w browser-use mac-approve` in another '
		'shell or click Allow to continue.',
		'browser-use: fatal: see ~/.config/browser-harness/tmp/bu-w.log',
		'cell output names browser-harness',
	]


def test_mac_approve_names_browser_use(monkeypatch, capsys):
	"""Live: `browser-use mac-approve --help` printed `usage: browser-harness mac-approve`, and its setup / not-found
	answers said to run `browser-harness mac-approve` again: not on PATH for `uv tool install browser-use`."""
	import pytest
	from browser_harness import macos

	from browser_use import cli

	monkeypatch.setenv('BH_UPDATE_CHECK', '0')
	monkeypatch.setattr(
		macos,
		'approve_remote_debugging',
		lambda: ('not-found', 'retry the browser command and run `browser-harness mac-approve` when the prompt appears'),
	)
	for argv, code, out in (
		(['mac-approve', '--help'], 2, 'usage: browser-use mac-approve\n'),
		(['mac-approve'], 1, 'not-found: retry the browser command and run `browser-use mac-approve` when the prompt appears\n'),
	):
		monkeypatch.setattr(sys, 'argv', ['browser-use', *argv])
		with pytest.raises(SystemExit) as exited:
			cli.main()
		assert exited.value.code == code and capsys.readouterr().out == out
