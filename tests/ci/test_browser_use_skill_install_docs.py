import importlib.metadata
import os
import re
import subprocess
import sys
from pathlib import Path

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
	shown = subprocess.run(
		[sys.executable, '-m', 'browser_use.cli', 'skill', 'show'], cwd=ROOT, env=env, capture_output=True, timeout=10
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
	assert uv_args.read_text(encoding='utf-8') == f'tool install --python 3.12 --upgrade --force browser-use=={version}'


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
