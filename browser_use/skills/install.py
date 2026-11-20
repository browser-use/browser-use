from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

SKILL_NAME = 'browser-use'
DEFAULT_TARGET = 'all'


def _xdg_config_home() -> Path:
	config_home = os.environ.get('XDG_CONFIG_HOME')
	if config_home:
		return Path(config_home).expanduser()
	return Path.home() / '.config'


def _home_skill_dir(assistant: str) -> Path:
	return Path.home() / f'.{assistant}' / 'skills' / SKILL_NAME


TARGET_DIR_BUILDERS = {
	'agents': lambda: _home_skill_dir('agents'),
	'claude': lambda: _home_skill_dir('claude'),
	'codex': lambda: _home_skill_dir('codex'),
	'copilot': lambda: _home_skill_dir('copilot'),
	'cursor': lambda: _home_skill_dir('cursor'),
	'gemini': lambda: _home_skill_dir('gemini'),
	'openclaw': lambda: _home_skill_dir('openclaw'),
	'opencode': lambda: _xdg_config_home() / 'opencode' / 'skills' / SKILL_NAME,
}

TARGET_NAMES = tuple(TARGET_DIR_BUILDERS)


def _all_target_skill_paths() -> list[Path]:
	paths = [build_dir() / 'SKILL.md' for build_dir in TARGET_DIR_BUILDERS.values()]
	legacy_opencode = Path.home() / '.config' / 'opencode' / 'skills' / SKILL_NAME / 'SKILL.md'
	if legacy_opencode not in paths:
		paths.append(legacy_opencode)
	# ~/.agents (the shared skills dir) always; the others only for agents already installed (~/.claude, ~/.codex, ...)
	return [path for path in paths if path == paths[0] or path.parents[2].is_dir()]


def _load_skill_text_from_package() -> str:
	"""The skill of this browser-use install. Never another program's: a `browser-harness` on PATH may be another
	version (or not browser-harness at all), and running it sent browser-harness's own unscrubbed telemetry."""
	from browser_use.skills.browser_use import skill_text

	return skill_text()


def _install_browser_use_tool() -> None:
	uv = shutil.which('uv')
	if not uv:
		raise RuntimeError('Installing the Browser Use skill requires `uv`. Install uv, then rerun `browser-use skill install`.')

	from browser_use.utils import get_browser_use_version

	version = get_browser_use_version()
	if version == 'unknown':
		raise RuntimeError('Cannot tell which browser-use version is running; rerun without --install-cli.')
	# Run from the uv tool itself, this version is the installed tool: --force would delete the env this process runs
	# from. On Windows the running exe is locked, so uv got halfway and left no browser_use module (win-cli-2).
	# A failed probe could be that tool too: never --force it unchecked
	probe = subprocess.run([uv, 'tool', 'dir'], capture_output=True, text=True)
	tool_dir = probe.stdout.strip()
	if probe.returncode != 0 or not tool_dir:
		raise RuntimeError('Cannot tell where uv keeps its tools (`uv tool dir` failed); rerun without --install-cli.')
	if Path(sys.prefix).resolve() == (Path(tool_dir) / 'browser-use').resolve():
		print(f'browser-use {version} is already installed as a uv tool (this one); not reinstalling it.')
		return
	# Pinned to the running version: unpinned, uv picks the latest stable, which replaces a 1.0 rc install with 0.x.
	# The running Python: a forced 3.12 rebuilt a 3.13 tool env as 3.12, deleting the files this process still reads
	python = f'{sys.version_info[0]}.{sys.version_info[1]}'
	args = ['tool', 'install', '--python', python, '--upgrade', '--force', f'browser-use=={version}']
	result = subprocess.run([uv, *args])
	if result.returncode != 0:
		raise RuntimeError(f'Failed to install browser-use with `uv {" ".join(args)}`.')


def _build_parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(
		prog='browser-use skill',
		description='Print or install the Browser Use skill.',
	)
	subparsers = parser.add_subparsers(dest='command')

	subparsers.add_parser('show', help='Print the skill text to stdout')

	install = subparsers.add_parser('install', help='Install the skill')
	install.add_argument(
		'--target',
		choices=sorted([*TARGET_NAMES, 'all']),
		default=DEFAULT_TARGET,
		help='Assistant skill directory to install into',
	)
	install.add_argument(
		'--path',
		type=Path,
		help='Custom output directory or .md file path',
	)
	install.add_argument(
		'--force',
		action='store_true',
		help='Accepted for compatibility; install overwrites existing SKILL.md files by default',
	)
	install.add_argument(
		'--install-cli',
		action='store_true',
		help='Also (re)install this browser-use version as a uv tool (`uv tool install --force`)',
	)
	install.add_argument('--no-install', action='store_true', help='Accepted for compatibility; the default now')

	return parser


def _resolve_output_paths(target: str, custom_path: Path | None) -> list[Path]:
	if custom_path is None:
		if target == 'all':
			return _all_target_skill_paths()
		return [TARGET_DIR_BUILDERS[target]() / 'SKILL.md']

	path = custom_path.expanduser()
	if path.suffix == '.md':
		return [path]
	return [path / 'SKILL.md']


def _validate_output_paths(output_paths: list[Path]) -> None:
	for output_path in output_paths:
		if output_path.exists() and output_path.is_dir():
			raise RuntimeError(f'{output_path} is a directory, expected a SKILL.md file path.')
		ancestor = output_path.parent
		while not ancestor.exists():
			if ancestor.parent == ancestor:
				break
			ancestor = ancestor.parent
		if ancestor.exists() and not ancestor.is_dir():
			raise RuntimeError(f'{ancestor} is not a directory.')


def handle(argv: list[str]) -> int:
	parser = _build_parser()
	args = parser.parse_args(argv)

	command = args.command or 'show'

	if command == 'show':
		try:
			text = _load_skill_text_from_package()
		except RuntimeError as exc:
			print(f'Error: {exc}', file=sys.stderr)
			return 1
		# UTF-8 whatever the console's code page: `skill show > SKILL.md` on Windows wrote cp1252 (or raised on a character
		# it lacks)
		sys.stdout.flush()
		sys.stdout.buffer.write(text.encode('utf-8'))
		sys.stdout.buffer.flush()
		return 0

	if command == 'install':
		try:
			output_paths = _resolve_output_paths(args.target, args.path)
			_validate_output_paths(output_paths)
			if args.install_cli:  # opt-in: it replaces the user's own browser-use tool install
				_install_browser_use_tool()
			text = _load_skill_text_from_package()
		except RuntimeError as exc:
			print(f'Error: {exc}', file=sys.stderr)
			return 1

		failed = False
		for output_path in output_paths:  # one unwritable agent dir must not skip the others
			try:
				output_path.parent.mkdir(parents=True, exist_ok=True)
				output_path.write_text(text, encoding='utf-8')
			except OSError as exc:
				print(f'Error: cannot write {output_path}: {exc.strerror}', file=sys.stderr)
				failed = True
				continue
			print(f'Installed Browser Use skill to {output_path}')
		return 1 if failed else 0

	parser.print_help()
	return 1
