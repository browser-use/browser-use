import os
import shutil
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
	Path('.config') / 'opencode' / 'skills' / 'browser-use' / 'SKILL.md',
)


def _write_fake_command(bin_dir: Path, name: str, source: str) -> None:
	if os.name == 'nt':
		(bin_dir / f'{name}.py').write_text(source, encoding='utf-8')
		(bin_dir / f'{name}.cmd').write_text(
			f'@echo off\n"{sys.executable}" "%~dp0{name}.py" %*\n',
			encoding='utf-8',
		)
		return

	executable = bin_dir / name
	executable.write_text(f'#!/usr/bin/env python3\n{source}', encoding='utf-8')
	executable.chmod(0o755)


def _fake_browser_harness_tools(tmp_path: Path, skill_text: str) -> Path:
	bin_dir = tmp_path / 'bin'
	bin_dir.mkdir()

	_write_fake_command(
		bin_dir,
		'uv',
		'import os, pathlib, sys\n'
		'pathlib.Path(os.environ["UV_TOOL_INSTALL_ARGS_FILE"]).write_text(" ".join(sys.argv[1:]), encoding="utf-8")\n',
	)

	_write_fake_command(
		bin_dir,
		'browser-harness',
		'import sys\n'
		f'text = {skill_text!r}\n'
		'if sys.argv[1:] == ["skill"]:\n'
		'    print(text, end="")\n'
		'else:\n'
		'    print("usage: browser-harness skill", file=sys.stderr)\n'
		'    sys.exit(2)\n',
	)
	return bin_dir


def _isolated_cli_env(tmp_path: Path, bin_dir: Path, uv_args: Path) -> dict[str, str]:
	home = tmp_path / 'home'
	env = os.environ.copy()
	env['HOME'] = str(home)
	env['USERPROFILE'] = str(home)
	env['XDG_CONFIG_HOME'] = str(home / '.config')
	env['PATH'] = os.pathsep.join(part for part in (str(bin_dir), env.get('PATH', '')) if part)
	env['PYTHONPATH'] = os.pathsep.join(part for part in (str(ROOT), env.get('PYTHONPATH', '')) if part)
	env['UV_TOOL_INSTALL_ARGS_FILE'] = str(uv_args)

	for name in ('uv', 'browser-harness'):
		executable = shutil.which(name, path=env['PATH'])
		assert executable is not None
		assert Path(executable).resolve().parent == bin_dir.resolve()

	return env


def test_docs_install_browser_use_skill_from_package_alias():
	readme = (ROOT / 'README.md').read_text(encoding='utf-8')

	assert 'run `browser-use skill install` to register the skill' in readme
	assert 'mkdir -p ~/.claude/skills/browser-use' not in readme
	assert 'uv run --with "browser-use[browser-harness]" python -c' not in readme
	assert 'from browser_use.skills import browser_use_skill_text' not in readme
	assert BROWSER_USE_REPO_SKILL_URL not in readme
	assert 'raw.githubusercontent.com/browser-use/browser-harness/main/SKILL.md' not in readme


def test_browser_use_cli_installs_browser_harness_package_skill(tmp_path):
	bin_dir = _fake_browser_harness_tools(tmp_path, '---\nname: browser-harness\n---\n\n# Browser Harness\n')

	home = tmp_path / 'home'
	for stale in (home / path for path in EXPECTED_SKILL_INSTALL_PATHS):
		stale.parent.mkdir(parents=True)
		stale.write_text('stale browser-use skill', encoding='utf-8')

	uv_args = tmp_path / 'uv-args.txt'
	env = _isolated_cli_env(tmp_path, bin_dir, uv_args)

	result = subprocess.run(
		[sys.executable, '-m', 'browser_use.cli', 'skill', 'install'],
		cwd=ROOT,
		env=env,
		capture_output=True,
		text=True,
		timeout=10,
	)

	assert result.returncode == 0, result.stderr
	assert uv_args.read_text(encoding='utf-8') == 'tool install --python 3.12 --upgrade --force browser-use'
	expected = (
		'---\n'
		'name: browser-use\n'
		'description: "Direct browser control via CDP for web interaction: automation, scraping, testing, screenshots, and site/app work."\n'
		'---\n\n'
		'# Browser Use\n'
	)
	for installed in (home / path for path in EXPECTED_SKILL_INSTALL_PATHS):
		assert installed.read_text(encoding='utf-8') == expected


def test_browser_use_cli_validates_destination_before_installing_harness(tmp_path):
	bin_dir = _fake_browser_harness_tools(tmp_path, '---\nname: browser-harness\n---\n\n# Browser Harness\n')
	blocking_file = tmp_path / 'not-a-directory'
	blocking_file.write_text('blocks skill directory creation', encoding='utf-8')

	uv_args = tmp_path / 'uv-args.txt'
	env = _isolated_cli_env(tmp_path, bin_dir, uv_args)

	result = subprocess.run(
		[sys.executable, '-m', 'browser_use.cli', 'skill', 'install', '--path', str(blocking_file / 'nested')],
		cwd=ROOT,
		env=env,
		capture_output=True,
		text=True,
		timeout=10,
	)

	assert result.returncode == 1
	assert 'is not a directory' in result.stderr
	assert not uv_args.exists()
