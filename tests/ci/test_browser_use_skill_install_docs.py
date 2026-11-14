import importlib.metadata
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BROWSER_USE_REPO_SKILL_URL = 'https://raw.githubusercontent.com/browser-use/browser-use/main/skills/browser-use/SKILL.md'
EXPECTED_SKILL_INSTALL_PATHS = (
	Path('.agents') / 'skills' / 'browser-use' / 'SKILL.md',
	Path('.claude') / 'skills' / 'browser-use' / 'SKILL.md',
	Path('.codex') / 'skills' / 'browser-use' / 'SKILL.md',
	Path('.copilot') / 'skills' / 'browser-use' / 'SKILL.md',
	Path('.cursor') / 'skills' / 'browser-use' / 'SKILL.md',
	Path('.gemini') / 'skills' / 'browser-use' / 'SKILL.md',
	Path('.openclaw') / 'skills' / 'browser-use' / 'SKILL.md',
	Path('.config') / 'opencode' / 'skills' / 'browser-use' / 'SKILL.md',
)


def _fake_command(bin_dir: Path, name: str, code: str) -> None:
	"""A command on PATH that runs this Python: a shebang script on POSIX, a .cmd wrapper on Windows."""
	script = bin_dir / f'{name}.py'
	script.write_text(code, encoding='utf-8')
	if sys.platform == 'win32':
		(bin_dir / f'{name}.cmd').write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding='utf-8')
	else:
		exe = bin_dir / name
		exe.write_text(f'#!{sys.executable}\n{code}', encoding='utf-8')
		exe.chmod(0o755)


def _fake_browser_harness_tools(tmp_path: Path, skill_text: str) -> Path:
	bin_dir = tmp_path / 'bin'
	bin_dir.mkdir()
	_fake_command(
		bin_dir,
		'uv',
		'import os, pathlib, sys\n'
		f'if sys.argv[1:] == ["tool", "dir"]: sys.exit(print({str(tmp_path / "uv-tools")!r}))\n'
		'pathlib.Path(os.environ["UV_TOOL_INSTALL_ARGS_FILE"]).write_text(" ".join(sys.argv[1:]), encoding="utf-8")\n',
	)
	_fake_command(  # another program called browser-harness on PATH: never run, never the skill's source
		bin_dir,
		'browser-harness',
		'import pathlib, sys\n'
		f'pathlib.Path({str(tmp_path / "harness-ran")!r}).write_text(" ".join(sys.argv[1:]))\n'
		f'sys.stdout.buffer.write({skill_text!r}.encode("utf-8"))\n',
	)
	return bin_dir


def _isolated_env(tmp_path: Path, bin_dir: Path, home: Path) -> dict[str, str]:
	"""Fake tools first on PATH; HOME and USERPROFILE (Windows' home) inside tmp_path."""
	env = os.environ.copy()
	env.pop('XDG_CONFIG_HOME', None)
	env['HOME'] = env['USERPROFILE'] = str(home)
	env['PATH'] = os.pathsep.join(part for part in (str(bin_dir), env.get('PATH', '')) if part)
	env['PYTHONPATH'] = os.pathsep.join(part for part in (str(ROOT), env.get('PYTHONPATH', '')) if part)
	env['UV_TOOL_INSTALL_ARGS_FILE'] = str(tmp_path / 'uv-args.txt')
	return env


def test_docs_install_browser_use_skill_from_package_alias():
	readme = (ROOT / 'README.md').read_text(encoding='utf-8')

	assert 'run `browser-use skill install` to register the skill' in readme
	assert 'mkdir -p ~/.claude/skills/browser-use' not in readme
	assert 'uv run --with "browser-use[browser-harness]" python -c' not in readme
	assert 'from browser_use.skills import browser_use_skill_text' not in readme
	assert BROWSER_USE_REPO_SKILL_URL not in readme
	assert 'raw.githubusercontent.com/browser-use/browser-harness/main/SKILL.md' not in readme


def test_cloud_v4_reference_scopes_workspace_file_listing():
	api_v4 = (ROOT / 'skills' / 'cloud' / 'references' / 'api-v4.md').read_text(encoding='utf-8')

	assert 'client.workspaces.files(workspace.id)' in api_v4
	assert 'client.workspaces.files()' not in api_v4
	python_examples = re.findall(r'```python\n(.*?)```', api_v4, flags=re.DOTALL)
	assert python_examples
	assert all('BrowserUse' in example for example in python_examples if 'client.' in example)


def test_remote_browser_skill_uses_current_cli():
	remote_skill = (ROOT / 'skills' / 'remote-browser' / 'SKILL.md').read_text(encoding='utf-8')

	for removed_command in (
		'browser-use open',
		'browser-use state',
		'browser-use click',
		'browser-use input',
		'browser-use tab',
		'browser-use screenshot',
		'browser-use eval',
		'browser-use cookies',
		'browser-use close',
		'browser-use sessions',
		'browser-use tunnel',
		'browser-use wait',
		'browser-use register',
		'browser-use cloud connect',
		'browser-use --connect',
		'browser_use/skill_cli/README.md',
	):
		assert removed_command not in remote_skill

	for current_command in (
		"browser-use <<'PY'",
		'start_remote_daemon("r7k2")',
		'BU_NAME=r7k2 browser-use',
		'new_tab("https://example.com")',
		'print(page_info())',
		'stop_remote_daemon("r7k2")',
	):
		assert current_command in remote_skill


def test_skill_install_and_show_use_this_packages_skill_and_never_run_browser_harness(tmp_path):
	"""H10, M32: `skill install` / `show` ran whichever `browser-harness` came first on PATH (a fake one was installed as
	the skill), and that run sent browser-harness's own telemetry unscrubbed (CDP host, 10 KB of output)."""
	from browser_use.skills.browser_use import skill_text

	bin_dir = _fake_browser_harness_tools(tmp_path, '---\nname: evil\n---\n\n# Not the skill\n')

	home = tmp_path / 'home'
	for stale in (home / path for path in EXPECTED_SKILL_INSTALL_PATHS):
		stale.parent.mkdir(parents=True)
		stale.write_text('stale browser-use skill', encoding='utf-8')

	uv_args = tmp_path / 'uv-args.txt'
	env = _isolated_env(tmp_path, bin_dir, home)

	result = subprocess.run(
		[sys.executable, '-m', 'browser_use.cli', 'skill', 'install'],
		cwd=ROOT,
		env=env,
		capture_output=True,
		text=True,
		timeout=10,
	)

	assert result.returncode == 0, result.stderr
	assert not uv_args.exists()  # M33: the CLI is reinstalled only with --install-cli
	for installed in (home / path for path in EXPECTED_SKILL_INSTALL_PATHS):
		assert installed.read_text(encoding='utf-8') == skill_text()
	shown = subprocess.run(  # cp1252: a Windows console's code page wrote the skill's em dashes as 0x97
		[sys.executable, '-m', 'browser_use.cli', 'skill', 'show'],
		cwd=ROOT,
		env={**env, 'PYTHONIOENCODING': 'cp1252'},
		capture_output=True,
		timeout=10,
	)
	assert shown.returncode == 0 and shown.stdout.decode('utf-8') == skill_text()
	assert not (tmp_path / 'harness-ran').exists()


def test_skill_install_reinstalls_the_cli_only_when_asked(tmp_path):
	"""M33: `skill install` ran `uv tool install --force browser-use==<version>` by default, replacing the user's own
	install of the CLI. It is opt-in now (--install-cli), pinned to the running version."""
	bin_dir = _fake_browser_harness_tools(tmp_path, '')
	env = _isolated_env(tmp_path, bin_dir, tmp_path / 'home')
	uv_args = tmp_path / 'uv-args.txt'
	for args, installs in ((['--target', 'claude'], False), (['--target', 'claude', '--install-cli'], True)):
		result = subprocess.run(
			[sys.executable, '-m', 'browser_use.cli', 'skill', 'install', *args],
			cwd=ROOT,
			env=env,
			capture_output=True,
			text=True,
			timeout=10,
		)
		assert result.returncode == 0, result.stderr
		assert uv_args.exists() is installs
	# Pinned: unpinned, uv installs the latest stable (0.x) over a 1.0 rc install
	version = importlib.metadata.version('browser-use')
	python = f'{sys.version_info[0]}.{sys.version_info[1]}'
	assert uv_args.read_text(encoding='utf-8') == f'tool install --python {python} --upgrade --force browser-use=={version}'


def test_install_cli_never_replaces_the_uv_tool_it_runs_from(monkeypatch, tmp_path, capsys):
	"""win-cli-2: `browser-use skill install --install-cli` from `uv tool install browser-use` ran `uv tool install
	--force` over its own tool env. Windows locks the running exe: uv deleted browser_use, failed on Scripts, and left the
	CLI broken (ModuleNotFoundError) with no skill written. Run from that tool, this version is installed already."""
	from browser_use.skills import install

	tool_dir = tmp_path / 'uv-tools'
	calls = []

	def run(args, **kwargs):
		calls.append(args[1:])
		return subprocess.CompletedProcess(args, 0, stdout=f'{tool_dir}\n' if args[1:] == ['tool', 'dir'] else '')

	monkeypatch.setattr(install.shutil, 'which', lambda name: 'uv')
	monkeypatch.setattr(install.subprocess, 'run', run)
	monkeypatch.setattr(install.sys, 'prefix', str(tool_dir / 'browser-use'))
	assert install.handle(['install', '--install-cli', '--path', str(tmp_path / 'skill')]) == 0
	assert [c for c in calls if c[:2] == ['tool', 'install']] == []
	assert (tmp_path / 'skill' / 'SKILL.md').is_file()
	assert 'already installed as a uv tool' in capsys.readouterr().out

	calls.clear()  # from another environment (a venv, uvx) it still installs the tool
	monkeypatch.setattr(install.sys, 'prefix', str(tmp_path / 'venv'))
	assert install.handle(['install', '--install-cli', '--path', str(tmp_path / 'skill')]) == 0
	assert [c[:2] for c in calls] == [['tool', 'dir'], ['tool', 'install']]


@pytest.mark.parametrize('probe', [(2, ''), (0, '')])
def test_install_cli_never_reinstalls_when_uv_cannot_say_where_its_tools_are(monkeypatch, tmp_path, probe):
	"""cubic: a failed `uv tool dir` fell through to `uv tool install --force`, so the uv tool this CLI runs from could
	still replace its own env (win-cli-2). Without the tool dir it cannot tell, so it installs nothing."""
	from browser_use.skills import install

	calls = []

	def run(args, **kwargs):
		calls.append(args[1:])
		return subprocess.CompletedProcess(args, probe[0], stdout=probe[1])

	monkeypatch.setattr(install.shutil, 'which', lambda name: 'uv')
	monkeypatch.setattr(install.subprocess, 'run', run)
	with pytest.raises(RuntimeError, match='uv tool dir'):
		install._install_browser_use_tool()
	assert calls == [['tool', 'dir']]


def test_browser_use_cli_validates_destination_before_installing_harness(tmp_path):
	bin_dir = _fake_browser_harness_tools(tmp_path, '---\nname: browser-harness\n---\n\n# Browser Harness\n')
	blocking_file = tmp_path / 'not-a-directory'
	blocking_file.write_text('blocks skill directory creation', encoding='utf-8')

	uv_args = tmp_path / 'uv-args.txt'
	env = _isolated_env(tmp_path, bin_dir, tmp_path / 'home')

	result = subprocess.run(
		[sys.executable, '-m', 'browser_use.cli', 'skill', 'install', '--install-cli', '--path', str(blocking_file / 'nested')],
		cwd=ROOT,
		env=env,
		capture_output=True,
		text=True,
		timeout=10,
	)

	assert result.returncode == 1
	assert 'is not a directory' in result.stderr
	assert not uv_args.exists()


def test_skill_install_reads_utf8_whatever_the_locale(tmp_path):
	"""Windows CI: the installer decoded the skill with cp1252 and crashed on non-ASCII skill text."""
	from browser_use.skills.browser_use import skill_text

	bin_dir = _fake_browser_harness_tools(tmp_path, '')
	home = tmp_path / 'home'
	env = _isolated_env(tmp_path, bin_dir, home)
	env.update(LC_ALL='C', LANG='C', PYTHONUTF8='0', PYTHONCOERCECLOCALE='0', PYTHONIOENCODING='ascii')  # a non-UTF-8 locale
	result = subprocess.run(
		[sys.executable, '-m', 'browser_use.cli', 'skill', 'install', '--no-install', '--target', 'claude'],
		cwd=ROOT,
		env=env,
		capture_output=True,
		timeout=30,
	)
	assert result.returncode == 0, result.stderr.decode('utf-8', 'replace')
	installed = (home / '.claude' / 'skills' / 'browser-use' / 'SKILL.md').read_text(encoding='utf-8')
	assert installed == skill_text()


def test_open_source_skill_shows_only_1_0_code():
	"""M7: the bundled open-source skill taught 0.x code that breaks on 1.0 (@sandbox, ChatGroq, BrowserProfile,
	ChatAnthropic(temperature=...), use_vision=...)."""
	import ast

	import browser_use
	from browser_use.agent.service import REMOVED as AGENT_REMOVED
	from browser_use.browser.browser import REMOVED as BROWSER_REMOVED

	skill_dir = ROOT / 'skills' / 'open-source'
	assert [p.name for p in skill_dir.rglob('*') if p.is_file()] == ['SKILL.md']
	text = (skill_dir / 'SKILL.md').read_text(encoding='utf-8')
	generic = {
		'timeout',
		'id',
		'env',
		'args',
		'headers',
		'source',
		'skills',
		'base_url',
	}  # also 1.0 words (run(timeout=...), ChatOpenAI(base_url=...))
	for name in {*AGENT_REMOVED, *BROWSER_REMOVED, 'temperature'} - generic:
		assert not re.search(rf'(?<![\w.]){name}=', text), name
	for code in re.findall(r'```python\n(.*?)```', text, flags=re.DOTALL):
		tree = ast.parse(code)
		for node in ast.walk(tree):
			if isinstance(node, ast.ImportFrom) and node.module == 'browser_use':
				for alias in node.names:
					assert alias.name in browser_use.__all__, alias.name


def test_skill_install_writes_only_installed_agents_and_reports_write_errors(tmp_path):
	"""C49: with an empty HOME, `skill install` created all 8 agent dirs (~/.cursor, ~/.gemini, ...); `--path x/MY.md` made
	a directory named MY.md; an unwritable --path crashed with a raw PermissionError traceback."""
	from browser_use.skills.browser_use import SKILL_DESCRIPTION, skill_text

	assert 'use_cloud' not in SKILL_DESCRIPTION  # 1.0 spelling is Browser()
	bin_dir = _fake_browser_harness_tools(tmp_path, '')
	home = tmp_path / 'home'
	(home / '.codex').mkdir(parents=True)
	(home / '.config' / 'opencode').mkdir(parents=True)
	env = _isolated_env(tmp_path, bin_dir, home)

	def install(*args: str) -> subprocess.CompletedProcess[str]:
		return subprocess.run(
			[sys.executable, '-m', 'browser_use.cli', 'skill', 'install', *args],
			cwd=ROOT,
			env=env,
			capture_output=True,
			text=True,
			timeout=10,
		)

	result = install()
	assert result.returncode == 0, result.stderr
	written = sorted(str(p.relative_to(home)) for p in home.rglob('SKILL.md'))
	assert written == sorted(
		str(path) for path in EXPECTED_SKILL_INSTALL_PATHS if path.parts[0] in ('.agents', '.codex', '.config')
	)
	assert sorted(p.name for p in home.iterdir()) == ['.agents', '.codex', '.config']

	assert install('--target', 'gemini').returncode == 0  # an explicit target still creates its dir
	assert (home / '.gemini' / 'skills' / 'browser-use' / 'SKILL.md').is_file()

	custom = tmp_path / 'custom' / 'MYSKILL.md'
	assert install('--path', str(custom)).returncode == 0
	assert custom.read_text(encoding='utf-8') == skill_text()

	if sys.platform != 'win32' and os.geteuid() != 0:
		readonly = tmp_path / 'readonly'
		readonly.mkdir(mode=0o500)
		result = install('--path', str(readonly / 'x'))
		assert result.returncode == 1
		assert 'Error: cannot write' in result.stderr and 'Traceback' not in result.stderr
		# review: the first unwritable target (~/.agents, written first) skipped every agent after it
		shared, codex = (home / p / 'skills' / 'browser-use' / 'SKILL.md' for p in ('.agents', '.codex'))
		shared.chmod(0o400)
		codex.unlink()
		result = install()
		assert result.returncode == 1 and f'Error: cannot write {shared}' in result.stderr
		assert codex.read_text(encoding='utf-8') == skill_text()


def test_readme_links_are_absolute_so_they_work_on_pypi():
	"""README.md is the PyPI long_description, where a relative link (MIGRATING.md, LICENSE, static/ images) is dead."""
	text = (ROOT / 'README.md').read_text(encoding='utf-8')
	relative = re.findall(r'(?:src|srcset|href)="(?!https?:|#)[^"]*"|\]\((?!https?:|#|mailto:)[^)]*\)', text)
	assert relative == []


def test_readme_python_blocks_run_as_scripts():
	"""The README's local-browser example ended in a top-level `result = await agent.run()`: pasted into agent.py it
	is a SyntaxError ('await' outside function). Every block must compile as a plain script, as the docs' do."""
	text = (ROOT / 'README.md').read_text(encoding='utf-8')
	blocks = re.findall(r'```python\n(.*?)```', text, re.S)
	assert blocks
	for block in blocks:
		compile(block, 'README.md', 'exec')


def test_mcp_registry_entry_runs_this_version():
	"""server.json is bumped by hand: it still ran `uvx browser-use==0.13.11 --cli-mcp` three releases later."""
	import json
	import tomllib

	version = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))['project']['version']
	server = json.loads((ROOT / 'server.json').read_text(encoding='utf-8'))
	assert [server['version'], *(p['version'] for p in server['packages'])] == [version, version]


def test_repo_skills_teach_no_removed_cli_commands_or_agent_args():
	"""skills/ (pulled from the repo by `npx skills add`) taught `browser-use cloud ...` (1.0: "'cloud' was removed"),
	Agent(skills=[...]) (TypeError) and the 0.x key file ~/.browser-use/config.json, which `browser-use login` never writes."""
	stale = ('browser-use cloud ', 'skills=[', '.browser-use/config.json')
	found = [
		f'{path.relative_to(ROOT)}: {s}'
		for path in (ROOT / 'skills').rglob('*.md')
		for s in stale
		if s in path.read_text(encoding='utf-8')
	]
	assert found == []


def _skill_sync_script():
	import importlib.util

	spec = importlib.util.spec_from_file_location('skill_sync_under_test', ROOT / 'scripts' / 'sync_browser_harness_skill.py')
	assert spec and spec.loader
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


def test_skill_gate_checks_against_the_pinned_harness_skill_with_no_network(monkeypatch):
	"""package-8: the gate read browser-harness main from GitHub, so it broke whenever harness main moved."""
	import socket

	def no_network(*args, **kwargs):
		raise AssertionError('the skill gate went to the network')

	monkeypatch.setattr(socket, 'create_connection', no_network)
	assert _skill_sync_script().main(['--check']) == 0


def test_skill_gate_refuses_a_harness_that_is_not_the_pinned_version(monkeypatch, capsys):
	script = _skill_sync_script()
	monkeypatch.setattr(script.importlib.metadata, 'version', lambda name: '0.0.1')
	assert script.main(['--check']) == 2
	assert 'browser-harness 0.0.1 is installed' in capsys.readouterr().err


def test_install_cli_keeps_the_python_the_cli_runs_on(monkeypatch, tmp_path):
	"""rc5 cli-1: --install-cli ran `uv tool install --python 3.12 --force`. A tool env on 3.13 was rebuilt as 3.12,
	deleting the lib/python3.13 files the running CLI then read the skill from: no SKILL.md written, exit 1, and the
	user's tool silently moved to 3.12."""
	from browser_use.skills import install

	calls = []

	def run(args, **kwargs):
		calls.append(args[1:])
		return subprocess.CompletedProcess(args, 0, stdout=f'{tmp_path / "uv-tools"}\n' if args[1:] == ['tool', 'dir'] else '')

	monkeypatch.setattr(install.shutil, 'which', lambda name: 'uv')
	monkeypatch.setattr(install.subprocess, 'run', run)
	with monkeypatch.context() as m:
		m.setattr(install.sys, 'version_info', (3, 13, 5, 'final', 0))
		install._install_browser_use_tool()
	installs = [c for c in calls if c[:2] == ['tool', 'install']]
	assert len(installs) == 1 and installs[0][2:4] == ['--python', '3.13'], installs
