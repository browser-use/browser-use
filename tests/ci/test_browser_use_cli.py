import asyncio
import os
import re
import subprocess
import sys
import tomllib
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


def test_console_scripts_avoid_generic_names():
	# `uv tool install` aborts if any script name is already taken by another tool's executable.
	scripts = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['scripts']
	assert set(scripts) == {'browser-use', 'browseruse', 'browser-use-tui'}


def test_migrating_names_every_removed_0x_script_and_extra():
	"""0.x shipped `bu` / `browser` and extras 1.0 dropped; MIGRATING.md is the map of every removed surface."""
	migrating = (ROOT / 'MIGRATING.md').read_text(encoding='utf-8')
	project = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']
	scripts_0x = {'browser-use', 'browseruse', 'bu', 'browser', 'browser-use-tui'}
	extras_0x = {'openai-tools', 'cli', 'core', 'aws', 'oci', 'video', 'examples', 'eval', 'cli-oci', 'all'}
	removed = sorted((scripts_0x - set(project['scripts'])) | (extras_0x - set(project['optional-dependencies'])))
	assert {'bu', 'browser', 'aws', 'core'} <= set(removed)
	assert [name for name in removed if f'`{name}`' not in migrating and f'`[{name}]`' not in migrating] == []


def test_every_dependency_is_an_exact_pin():
	# Supply-chain policy: a compromised release of any direct dependency must never reach users via a range.
	# Bump pins on purpose, together with uv.lock and [tool.uv] exclude-newer.
	project = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']
	deps = project['dependencies'] + [d for extra in project['optional-dependencies'].values() for d in extra]
	specs = {d: re.sub(r'\[[^\]]*\]', '', d) for d in deps if not d.startswith('browser-use[')}
	loose = [d for d, spec in specs.items() if spec.count('==') != 1 or any(c in spec for c in '<>~!,*;')]
	assert loose == []


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


def test_browser_use_doctor_names_browser_use_install_once_for_snap_and_for_no_browser(monkeypatch, capsys):
	"""rc5 local-2: the find_binary error now names `browser-use install`, so doctor stopped adding it; a Snap-only
	Ubuntu (its default chromium) then lost the hint, though `browser-use install` fixes it there too."""
	from browser_harness import admin

	import browser_use.browser.browser as browser_module
	import browser_use.browser.local as local_module
	from browser_use import cli

	monkeypatch.setenv('BROWSER_USE_API_KEY', 'k')
	monkeypatch.setattr(browser_module, '_name_daemon_files', lambda: None)
	monkeypatch.setattr(admin, '_chrome_running', lambda: False)
	monkeypatch.setattr(admin, 'daemon_alive', lambda: False)
	for error in (
		local_module._snap_error('/usr/bin/chromium-browser'),
		"No Chrome, Chromium or Edge found (tried x). Install one or run `browser-use install` (Playwright's Chromium).",
	):

		def find_binary(*_a, error=error, **_k):
			raise RuntimeError(error)

		monkeypatch.setattr(local_module, 'find_binary', find_binary)
		assert cli._run_doctor() == 0
		line = next(line for line in capsys.readouterr().out.splitlines() if 'local browser' in line)
		assert line.count('browser-use install') == 1, line
		assert 'browser-harness' not in line, line  # `browser-harness doctor --fix-snap` is not on a uv tool install's PATH


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


def test_stdin_from_the_null_device_is_empty_stdin_not_the_quickstart():
	"""win-cli-8: on Windows NUL is a character device, so isatty() is True: `browser-use < NUL` (and a coding agent's
	subprocess with stdin=DEVNULL) printed the quickstart with exit 0 instead of the empty-stdin error."""
	r = subprocess.run(
		[sys.executable, '-m', 'browser_use.cli'],
		cwd=ROOT,
		env={**os.environ, 'PYTHONPATH': str(ROOT)},
		stdin=subprocess.DEVNULL,
		capture_output=True,
		text=True,
		timeout=60,
	)
	assert r.returncode == 1, (r.stdout, r.stderr)
	assert 'received empty stdin' in r.stderr and 'Welcome' not in r.stdout


def test_every_install_line_pins_the_released_version_exactly():
	"""Users and their agents copy these lines: each pins browser-use with == to this release, never >=."""
	import tomllib

	v = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['version']
	for f in ('README.md', 'examples/simple.py', 'skills/open-source/SKILL.md'):
		text = (ROOT / f).read_text(encoding='utf-8')
		assert f'browser-use=={v}' in text, f
		assert not re.search(r'browser-use\s*>=', text), f


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


def _serve_body_late(delay_s: float, body: bytes = b'<title>late body</title><p>hi</p>'):
	"""A local page whose server sends the headers at once and the HTML delay_s later. Returns (server, url)."""
	import threading
	import time
	from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

	class Handler(BaseHTTPRequestHandler):
		def do_GET(self):
			self.send_response(200)
			self.send_header('Content-Type', 'text/html')
			self.send_header('Content-Length', str(len(body)))
			self.end_headers()
			self.wfile.flush()
			time.sleep(delay_s)
			self.wfile.write(body)

		def log_message(self, *a):
			pass

	server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
	threading.Thread(target=server.serve_forever, daemon=True).start()
	return server, f'http://127.0.0.1:{server.server_address[1]}/page'


@pytest.mark.parametrize('surface', ['cli', 'mcp', 'repl'])
async def test_the_documented_first_example_waits_for_the_new_document(daemon, tmp_path, monkeypatch, surface):
	"""cli-1: `new_tab(url); print(page_info())`, the first example of the CLI help, the docs and the MCP tool, failed
	about half the time on local Chromium with "Cannot read properties of null (reading 'scrollWidth')": new_tab()
	returns once the new document commits, before its parser has made <html>. A body sent late makes that every time."""
	server, url = _serve_body_late(0.5)
	code = f'new_tab({url!r})\ninfo = page_info()\nprint(info["title"], info["pw"] > 0)\nclose_tab()'
	try:
		if surface == 'cli':
			pythonpath = os.pathsep.join(p for p in (str(ROOT), os.environ.get('PYTHONPATH', '')) if p)
			env = {**os.environ, 'PYTHONPATH': pythonpath, **daemon}
			cmd = [sys.executable, '-m', 'browser_use.cli']
			r = await asyncio.to_thread(subprocess.run, cmd, input=code, env=env, capture_output=True, text=True, timeout=60)
			out, failed = r.stdout + r.stderr, r.returncode != 0
		elif surface == 'mcp':
			from browser_harness import admin, helpers

			from browser_use.mcp import cli_mcp

			monkeypatch.setattr(admin, 'NAME', daemon['BU_NAME'])
			monkeypatch.setattr(helpers, 'NAME', daemon['BU_NAME'])
			monkeypatch.setattr(helpers, 'page_info', helpers.page_info)  # the server wraps it for this process
			out, failed = cli_mcp.CLIMCPServer()._execute(code)
		else:
			from browser_use.repl import Repl

			repl = Repl(tmp_path, daemon)
			try:
				r = await repl.call('exec', code, 60)
			finally:
				await repl.close()
			out, failed = r['output'] + (r['error'] or ''), r['error'] is not None
	finally:
		server.shutdown()
	assert not failed and 'late body True' in out, out


async def test_page_info_waiting_for_the_document_still_reports_a_dialog(daemon, monkeypatch):
	"""cli-1: a page that alert()s as it loads opens the dialog while page_info() waits for <html>. page_info() returns
	{dialog}, as browser-harness documents, instead of timing out on an evaluate the open dialog blocks."""
	from browser_harness import admin, helpers

	from browser_use.mcp import cli_mcp

	server, url = _serve_body_late(0.5, b'<script>alert("hi")</script><p>x</p>')
	monkeypatch.setattr(admin, 'NAME', daemon['BU_NAME'])
	monkeypatch.setattr(helpers, 'NAME', daemon['BU_NAME'])
	monkeypatch.setattr(helpers, 'page_info', helpers.page_info)  # the server wraps it for this process
	code = f'new_tab({url!r})\ninfo = page_info()\ncdp("Page.handleJavaScriptDialog", accept=True)\nclose_tab()\nprint(info)'
	try:
		out, failed = cli_mcp.CLIMCPServer()._execute(code)
	finally:
		server.shutdown()
	assert not failed and "'dialog'" in out and "'hi'" in out, out
