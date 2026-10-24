"""Run Pi tasks or Browser Harness programs through the Browser Use CLI."""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from importlib.metadata import PackageNotFoundError, version
from io import StringIO


def _browser_use_version() -> str:
	try:
		return version('browser-use')
	except PackageNotFoundError:
		return 'unknown'


def _set_harness_client_env() -> None:
	import os

	os.environ['BH_CLIENT'] = 'browser-use-cli'
	os.environ['BH_CLIENT_VERSION'] = _browser_use_version()


@contextmanager
def _without_harness_telemetry():
	previous = os.environ.get('BH_TELEMETRY')
	os.environ['BH_TELEMETRY'] = 'false'
	try:
		yield
	finally:
		if previous is None:
			os.environ.pop('BH_TELEMETRY', None)
		else:
			os.environ['BH_TELEMETRY'] = previous


def _run_mcp_stdio_server(module_name: str) -> None:
	"""Silence logging during structured CLI operations."""
	import asyncio
	import importlib
	import logging
	import os

	os.environ['BROWSER_USE_LOGGING_LEVEL'] = 'critical'
	os.environ['BROWSER_USE_SETUP_LOGGING'] = 'false'
	logging.disable(logging.CRITICAL)

	with _without_harness_telemetry():
		main = importlib.import_module(module_name).main
		asyncio.run(main())


def _run_cli_mcp_server() -> None:
	import argparse

	parser = argparse.ArgumentParser(prog='browser-use --mcp', description='Expose direct browser control through MCP.')
	parser.add_argument(
		'--browser', choices=('cloud', 'chrome', 'chromium'), default=os.environ.get('BROWSER_USE_BROWSER', 'cloud')
	)
	parser.add_argument('--cdp-url')
	options = parser.parse_args([arg for arg in sys.argv[1:] if arg not in {'--mcp', '--cli-mcp'}])
	os.environ['BROWSER_USE_BROWSER'] = options.browser
	if options.cdp_url:
		os.environ['BU_CDP_URL'] = options.cdp_url
		os.environ.pop('BU_CDP_WS', None)
	_run_mcp_stdio_server('browser_use.mcp.cli_mcp')


def _run_install_command(argv: list[str]) -> int:
	if any(arg in {'-h', '--help'} for arg in argv):
		print('usage: browser-use install')
		print()
		print('Install Chromium browser and system dependencies.')
		return 0

	import platform
	import subprocess

	print('Installing Chromium browser + system dependencies...')
	print('This may take a few minutes...\n')

	cmd = ['uvx', 'playwright', 'install', 'chromium']
	if platform.system() == 'Linux':
		cmd.append('--with-deps')
	cmd.append('--no-shell')

	result = subprocess.run(cmd)
	if result.returncode == 0:
		print('\nInstallation complete.')
		print('Ready to use. Run: uvx browser-use')
		return 0

	print('\nInstallation failed', file=sys.stderr)
	return result.returncode or 1


def _as_browser_use_cli_text(text: str) -> str:
	return text.replace('Browser Harness', 'Browser Use').replace('browser-harness', 'browser-use')


def _normalize_captured_cli_output(func, argv: list[str]) -> int:
	stdout = StringIO()
	stderr = StringIO()
	try:
		with redirect_stdout(stdout), redirect_stderr(stderr):
			result = func(argv)
	except SystemExit as exc:
		result = exc.code

	out = stdout.getvalue()
	err = stderr.getvalue()
	if out:
		print(_as_browser_use_cli_text(out), end='')
	if err:
		print(_as_browser_use_cli_text(err), end='', file=sys.stderr)
	if result is None:
		return 0
	if isinstance(result, int):
		return result
	if isinstance(result, str):
		print(_as_browser_use_cli_text(result), file=sys.stderr)
		return 1
	return 1


def _patch_browser_harness_cli_text() -> None:
	from browser_harness import auth, run, telemetry

	run.HELP = _as_browser_use_cli_text(run.HELP)
	if 'browser-use run <task>' not in run.HELP:
		run.HELP += '\nPi tasks: browser-use run <task> --model provider/model\n'
		run.HELP += 'Browser selection: --browser cloud|chrome|chromium or --cdp-url URL.\n'
		run.HELP += 'Python programs default to Cloud; local modes attach to a running browser.\n'
	run.USAGE = _as_browser_use_cli_text(run.USAGE)

	original_auth_cli = auth.run_auth_cli
	original_telemetry_cli = telemetry.run_telemetry_cli

	def run_auth_cli(argv: list[str]) -> int:
		if any(arg in {'-h', '--help'} for arg in argv):
			return _normalize_captured_cli_output(original_auth_cli, argv)
		return original_auth_cli(argv)

	def run_telemetry_cli(argv: list[str]) -> int:
		if argv and argv != ['status'] and argv != ['enable'] and argv != ['disable']:
			return _normalize_captured_cli_output(original_telemetry_cli, argv)
		return original_telemetry_cli(argv)

	auth.run_auth_cli = run_auth_cli
	telemetry.run_telemetry_cli = run_telemetry_cli


def _ensure_harness_browser(browser: str | None = None, cdp_url: str | None = None) -> None:
	browser = browser or os.environ.get('BROWSER_USE_BROWSER', 'cloud')
	if cdp_url:
		os.environ['BU_CDP_URL'] = cdp_url
		os.environ.pop('BU_CDP_WS', None)
	endpoint = os.environ.get('BU_CDP_URL') or os.environ.get('BU_CDP_WS')
	if endpoint:
		from hashlib import sha256

		os.environ.setdefault('BU_NAME', 'browser-use-cdp-' + sha256(endpoint.encode()).hexdigest()[:12])
		return
	if browser != 'cloud':
		return
	os.environ.setdefault('BU_NAME', 'browser-use-cloud')
	from browser_harness import admin

	name = os.environ['BU_NAME']
	if admin.daemon_alive(name):
		if admin.daemon_browser_kind(name) != 'cloud':
			raise RuntimeError('This daemon uses a local browser; use --browser chrome or choose another BU_NAME.')
		return
	if os.environ.get('BH_REQUIRE_EXISTING_DAEMON') == '1':
		admin.require_existing_daemon(name)
		return
	admin.start_remote_daemon(name)


def _run_browser_harness() -> int | None:
	import argparse

	parser = argparse.ArgumentParser(add_help=False)
	parser.add_argument(
		'--browser', choices=('cloud', 'chrome', 'chromium'), default=os.environ.get('BROWSER_USE_BROWSER', 'cloud')
	)
	parser.add_argument('--cdp-url')
	options, args = parser.parse_known_args(sys.argv[1:])
	if not args or args == ['--debug-clicks']:
		code = sys.stdin.read()
		if not code.strip():
			print(_EMPTY_STDIN_MESSAGE, file=sys.stderr)
			return 1
		sys.stdin = StringIO(code)
		if not code.lstrip().startswith(('start_remote_daemon(', 'stop_remote_daemon(')):
			_ensure_harness_browser(options.browser, options.cdp_url)

	from browser_harness import run

	_set_harness_client_env()
	_patch_browser_harness_cli_text()
	if args and args[0] == 'doctor' and args[1:]:
		if args[1:] in (['--help'], ['-h']):
			print('usage: browser-use doctor [--fix-snap]')
			return 0
		if args[1:] != ['--fix-snap']:
			print('usage: browser-use doctor [--fix-snap]', file=sys.stderr)
			sys.exit(2)
	original_argv = sys.argv
	try:
		sys.argv = [original_argv[0], *args]
		run.main()
	finally:
		sys.argv = original_argv
	return None


def _run_task(argv: list[str]) -> int:
	import argparse
	import asyncio
	import json
	from dataclasses import asdict

	parser = argparse.ArgumentParser(prog='browser-use run', description='Run a task with the Pi agent.')
	parser.add_argument('task', help='Task instructions')
	parser.add_argument('--model', default=os.environ.get('BROWSER_USE_MODEL'), help='Provider/model ID or BROWSER_USE_MODEL')
	parser.add_argument(
		'--browser', choices=('cloud', 'chrome', 'chromium'), default=os.environ.get('BROWSER_USE_BROWSER', 'cloud')
	)
	parser.add_argument('--cdp-url', help='Connect to an existing CDP endpoint')
	parser.add_argument('--base-url', help='Provider API endpoint')
	parser.add_argument('--profile-dir', help='Chrome user-data root or Chromium profile directory')
	parser.add_argument('--headed', action='store_true', help='Show a launched Chromium browser')
	parser.add_argument('--max-steps', type=int, default=100)
	parser.add_argument('--json', action='store_true', help='Print the full result as JSON')
	args = parser.parse_args(argv)
	if not args.model:
		parser.error('Set --model or BROWSER_USE_MODEL.')
	if args.max_steps < 1:
		parser.error('--max-steps must be positive.')
	cdp_url = args.cdp_url or os.environ.get('BU_CDP_URL') or os.environ.get('BU_CDP_WS')
	if cdp_url:
		browser = {'cdpUrl': cdp_url}
	elif args.browser == 'cloud':
		from browser_harness import auth

		browser = {'kind': 'cloud', 'apiKey': auth.get_browser_use_api_key()}
	else:
		browser = {'kind': args.browser}
		if args.profile_dir:
			browser['profileDir'] = args.profile_dir
		if args.browser == 'chromium':
			browser['headless'] = not args.headed

	async def run():
		from browser_use import BrowserUse

		options = {'baseUrl': args.base_url} if args.base_url else {}
		async with await BrowserUse.create(model=args.model, browser=browser, **options) as agent:
			return await agent.run(args.task, maxSteps=args.max_steps)

	result = asyncio.run(run())
	print(json.dumps(asdict(result), ensure_ascii=False) if args.json else result.text)
	return 0 if result.status == 'completed' else 1


# Map previous CLI commands to migration instructions.
_LEGACY_HINTS: dict[str, str] = {
	'open': 'new_tab("https://example.com")',
	'state': 'print(page_info())',
	'screenshot': 'print(capture_screenshot())',
	'eval': 'print(js("document.title"))',
	'cookies': 'print(cdp("Network.getCookies"))',
	'python': '# the CLI runs Python directly now — pipe it on stdin as shown below',
	'connect': '# use --browser chrome for your running Chrome or --cdp-url for an existing endpoint',
	'close': '# restart the local daemon with `browser-use --reload`; stop cloud browsers with stop_remote_daemon(name)',
	'sessions': '# named local sessions were removed — one default daemon; use BU_NAME=<name> for cloud daemons',
	'profile': '# profiles now come from your real Chrome; see the profile-sync interaction skill',
	'cloud': '# authenticate with `browser-use auth login`, then start_remote_daemon("<name>")',
	'daemon': '# the daemon starts automatically on every call; restart it with `browser-use --reload`',
	'record': '# session recording was removed; use capture_screenshot() per step',
	'mcp': '# MCP server mode is now the --mcp flag: `browser-use --mcp`',
	'--session': '# use BU_NAME=<name> as an env var for named cloud daemons; local runs use one default daemon',
	'--headed': '# local control always attaches to your real, visible Chrome — no flag needed',
	'--profile': '# use your real Chrome profile; for cloud cookie sync see the profile-sync interaction skill',
	'--json': '# output is whatever your Python prints — use print(json.dumps(...))',
	'-c': "# pipe code on stdin instead: echo 'print(page_info())' | browser-use",
	'--code': "# pipe code on stdin instead: echo 'print(page_info())' | browser-use",
}


def _legacy_command(args: list[str]) -> str | None:
	if not args:
		return None
	first = args[0].split('=', 1)[0]
	if first in _LEGACY_HINTS:
		return first
	return None


_CLI3_GUIDE = """Core helpers: new_tab(url), goto_url(url), page_info(), capture_screenshot(),
  click_at_xy(x, y), type_text(text), fill_input(selector, text), press_key(key),
  scroll(x, y), js(code), cdp(method, ...), wait_for_load(), wait_for_element(selector),
  list_tabs(), switch_tab(target), close_tab(target)

Read the full interface now:   browser-use skill show
Install the CLI 3.0 skill (upgrades the CLI and replaces any pre-existing browser-use skill):
                               browser-use skill install
Then load the freshly installed browser-use skill, and follow it to use the latest CLI.
Skill reference:               https://github.com/browser-use/browser-use/blob/main/browser_use/skills/browser-use/SKILL.md
Health check:                  browser-use --doctor"""


def _legacy_migration_message(command: str) -> str:
	hint = _LEGACY_HINTS[command]
	if hint.startswith('#'):
		replacement = f'  {hint.lstrip("# ")}\n\nExample:\n  browser-use <<\'PY\'\n  new_tab("https://example.com")\n  print(page_info())\n  PY'
	else:
		replacement = f"  browser-use <<'PY'\n  {hint}\n  PY"
	return f"""The browser-use CLI changed in 3.0, and '{command}' was removed.

The old preset subcommands are gone. To use the CLI, you write raw Python and
pipe it on stdin, and it runs in a persistent browser session. Browser management
(daemon startup, Chrome/CDP attach, tabs, waiting) is handled for you.

Replacement for '{command}':
{replacement}

{_CLI3_GUIDE}"""


def _unknown_helper_message(name: str) -> str:
	return f"""'{name}' is not defined in the browser-use CLI.

Example:
  browser-use <<'PY'
  new_tab("https://example.com")
  print(page_info())
  PY

{_CLI3_GUIDE}"""


def _unknown_exec_name(exc: NameError) -> str | None:
	import re

	name = getattr(exc, 'name', None)
	if name:
		return name
	m = re.search(r"'([A-Za-z_][A-Za-z0-9_]*)'", str(exc))
	return m.group(1) if m else None


def _raised_from_piped_code(exc: BaseException) -> bool:
	tb = exc.__traceback__
	last = None
	while tb is not None:
		last = tb
		tb = tb.tb_next
	return last is not None and last.tb_frame.f_code.co_filename == '<string>'


_QUICKSTART = """Welcome to the Browser Use CLI. Allow your coding agent to reliably control a web browser.

The CLI runs Pi tasks or Python browser programs. Cloud browsers are the default.

  browser-use <<'PY'
  new_tab("https://news.ycombinator.com")
  print(page_info())
  PY

Core helpers: new_tab(url), goto_url(url), page_info(),
  capture_screenshot(), click_at_xy(x, y), js(code), cdp(method, ...),
  wait_for_load()

Recommended: install the skill so your coding agent remembers this:

  browser-use skill install

You can also paste this into your agent to get started:

  Install or upgrade browser-use to the latest stable version with uv using
  Python 3.12, register the skill from `browser-use skill`, and connect it to
  my browser. Follow https://github.com/browser-use/browser-use if setup or
  connection fails.

More:
  browser-use run "Find the top Show HN post" --model provider/model
  browser-use --browser chrome  attach to your real Chrome
  browser-use --doctor     check install, daemon, and browser health
  browser-use --help       full command list
  docs: https://github.com/browser-use/browser-use/blob/main/browser_use/skills/browser-use/SKILL.md"""

_EMPTY_STDIN_MESSAGE = """browser-use received empty stdin. This CLI executes Python piped on stdin:
  browser-use <<'PY'
  print(page_info())
  PY"""


def _dispatch(args: list[str]) -> tuple[int | None, str]:
	if '--cli-mcp' in args:
		_run_cli_mcp_server()
		return 0, 'cli-mcp'
	if '--mcp' in args:
		_run_cli_mcp_server()
		return 0, 'mcp'
	if args and args[0] == 'install':
		return _run_install_command(args[1:]), 'install'
	if args and args[0] == 'run':
		return _run_task(args[1:]), 'run'
	if args and args[0] == 'skill':
		from browser_use.skills.install import handle as handle_skill_command

		return handle_skill_command(args[1:]), 'skill'

	legacy = _legacy_command(args)
	if legacy is not None:
		print(_legacy_migration_message(legacy), file=sys.stderr)
		return 2, f'legacy:{legacy}'

	if not args:
		if sys.stdin.isatty():
			print(_QUICKSTART)
			return 0, 'quickstart'
		code = sys.stdin.read()
		if not code.strip():
			print(_EMPTY_STDIN_MESSAGE, file=sys.stderr)
			return 1, 'run'
		sys.stdin = StringIO(code)

	try:
		with _without_harness_telemetry():
			return _run_browser_harness(), args[0] if args else 'run'
	except NameError as exc:
		name = _unknown_exec_name(exc)
		if name is None or not _raised_from_piped_code(exc):
			raise
		import traceback

		traceback.print_exc()
		print(_unknown_helper_message(name), file=sys.stderr)
		return 2, args[0] if args else 'run'


def browser_use_tui_main() -> int | None:
	print('browser-use-tui is deprecated; use browser-use instead.', file=sys.stderr)
	return main()


def main() -> int | None:
	args = sys.argv[1:]
	if args and args[0] == 'telemetry':
		return _run_browser_harness()
	result, _ = _dispatch(args)
	return result


if __name__ == '__main__':
	result = main()
	if result is not None:
		sys.exit(result)
