from __future__ import annotations

import argparse
import difflib
import importlib.metadata
import importlib.resources
import importlib.util
import re
import sys
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO_OUTPUT_PATH = ROOT / 'skills' / 'browser-use' / 'SKILL.md'
DEFAULT_PACKAGE_OUTPUT_PATH = ROOT / 'browser_use' / 'skills' / 'browser-use' / 'SKILL.md'


class HarnessMismatch(Exception):
	pass


def _pinned_harness_skill() -> str:
	"""SKILL.md of the installed browser-harness, which must be the version pyproject.toml pins.

	The skill describes the harness the CLI runs, so it comes from that exact release, not from harness main.
	"""
	pyproject = (ROOT / 'pyproject.toml').read_text(encoding='utf-8')
	pin = re.search(r'"browser-harness==([^"]+)"', pyproject)
	if pin is None:
		raise HarnessMismatch('pyproject.toml has no exact browser-harness pin')
	try:
		installed = importlib.metadata.version('browser-harness')
	except importlib.metadata.PackageNotFoundError:
		raise HarnessMismatch('browser-harness is not installed; run `uv sync` first') from None
	if installed != pin.group(1):
		raise HarnessMismatch(
			f'browser-harness {installed} is installed but pyproject.toml pins {pin.group(1)}; run `uv sync` first'
		)
	return importlib.resources.files('browser_harness').joinpath('SKILL.md').read_text(encoding='utf-8')


def _read_source(source: str | None) -> str:
	if source is None:
		return _pinned_harness_skill()
	if source.startswith(('http://', 'https://')):
		with urlopen(source, timeout=30) as response:
			return response.read().decode('utf-8')
	return Path(source).read_text(encoding='utf-8')


def _to_browser_use_skill(text: str) -> str:
	module_path = ROOT / 'browser_use' / 'skills' / 'browser_use.py'
	if not module_path.exists():  # tests run against an installed wheel: the package's own copy
		from browser_use.skills.browser_use import as_browser_use_skill

		return as_browser_use_skill(text)
	spec = importlib.util.spec_from_file_location('browser_use_skill_rewriter', module_path)
	if spec is None or spec.loader is None:
		raise RuntimeError(f'Could not load Browser Use skill rewriter from {module_path}')
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)

	return module.as_browser_use_skill(text)


def _build_parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(description='Sync the Browser Use skill from the pinned browser-harness SKILL.md.')
	parser.add_argument(
		'--source', default=None, help='Source SKILL.md path or URL. Default: the installed, pinned browser-harness.'
	)
	parser.add_argument(
		'--output',
		type=Path,
		action='append',
		help='Output Browser Use SKILL.md path. May be passed more than once. Defaults to repo and package copies.',
	)
	parser.add_argument('--check', action='store_true', help='Fail if the output file is stale.')
	return parser


def main(argv: list[str] | None = None) -> int:
	args = _build_parser().parse_args(argv)
	try:
		expected = _to_browser_use_skill(_read_source(args.source))
	except HarnessMismatch as exc:
		print(exc, file=sys.stderr)
		return 2
	package_copy = DEFAULT_PACKAGE_OUTPUT_PATH
	if not (ROOT / 'browser_use').is_dir():  # tests run against an installed wheel: check the copy it ships
		package_copy = Path(str(importlib.resources.files('browser_use').joinpath('skills/browser-use/SKILL.md')))
	output_paths = args.output or [DEFAULT_REPO_OUTPUT_PATH, package_copy]

	if args.check:
		stale = False
		for output_path in output_paths:
			actual = output_path.read_text(encoding='utf-8') if output_path.exists() else ''
			if actual == expected:
				continue
			stale = True
			diff = ''.join(
				difflib.unified_diff(
					actual.splitlines(keepends=True),
					expected.splitlines(keepends=True),
					fromfile=str(output_path),
					tofile=f'{output_path} (expected)',
				)
			)
			print(diff, file=sys.stderr)
		return 1 if stale else 0

	for output_path in output_paths:
		output_path.parent.mkdir(parents=True, exist_ok=True)
		output_path.write_text(expected, encoding='utf-8')
		print(f'Synced {output_path} from {args.source or "the pinned browser-harness"}')
	return 0


if __name__ == '__main__':
	sys.exit(main())
