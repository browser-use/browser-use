from __future__ import annotations

import argparse
import difflib
import importlib.util
import sys
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_URL = 'https://raw.githubusercontent.com/browser-use/browser-harness/refs/heads/main/SKILL.md'
DEFAULT_REPO_OUTPUT_PATH = ROOT / 'skills' / 'browser-use' / 'SKILL.md'
DEFAULT_PACKAGE_OUTPUT_PATH = ROOT / 'browser_use' / 'skills' / 'browser-use' / 'SKILL.md'


def _read_source(source: str) -> str:
	if source.startswith(('http://', 'https://')):
		with urlopen(source, timeout=30) as response:
			return response.read().decode('utf-8')
	return Path(source).read_text(encoding='utf-8')


def _to_browser_use_skill(text: str) -> str:
	module_path = ROOT / 'browser_use' / 'skills' / 'browser_use.py'
	spec = importlib.util.spec_from_file_location('browser_use_skill_rewriter', module_path)
	if spec is None or spec.loader is None:
		raise RuntimeError(f'Could not load Browser Use skill rewriter from {module_path}')
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)

	return module.as_browser_use_skill(text)


def _build_parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(description='Sync the Browser Use skill from browser-harness/SKILL.md.')
	parser.add_argument('--source', default=DEFAULT_SOURCE_URL, help='Source SKILL.md path or URL.')
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
	expected = _to_browser_use_skill(_read_source(args.source))
	output_paths = args.output or [DEFAULT_REPO_OUTPUT_PATH, DEFAULT_PACKAGE_OUTPUT_PATH]

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
		print(f'Synced {output_path} from {args.source}')
	return 0


if __name__ == '__main__':
	sys.exit(main())
