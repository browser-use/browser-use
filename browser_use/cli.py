"""Browser Use CLI backed by Browser Harness"""

from __future__ import annotations

import sys
import time
from contextlib import redirect_stderr, redirect_stdout
from importlib.metadata import PackageNotFoundError, version
from io import StringIO


def _browser_use_version() -> str:
	try:
		return version('browser-use')
	except PackageNotFoundError:
		return 'unknown'


def _exit_code(result: int | str | None) -> int:
	if result is None:
		return 0
	if isinstance(result, int):
		return result
	return 1


def _set_harness_client_env() -> None:
	import os

	os.environ['BH_CLIENT'] = 'browser-use-cli'
	os.environ['BH_CLIENT_VERSION'] = _browser_use_version()
	os.environ.setdefault('BH_DEVICE_NAME', 'browser-use')  # names the key `login` creates in the dashboard


def _scrub_harness_telemetry() -> None:
	"""browser-harness's cli_event carries the piped code, its output, helper arguments and error text. In the
	browser-use CLI those never leave the machine: every event is scrubbed right before it is sent (TELEMETRY.md)."""
	from browser_harness import telemetry

	send = telemetry._send_detached
	if getattr(send, '__bu_scrubbed__', False):
		return
	from browser_use.telemetry.stats import scrub_cli_event

	def scrubbed(payload: dict) -> None:
		send(scrub_cli_event(payload))

	scrubbed.__bu_scrubbed__ = True  # type: ignore[attr-defined]
	telemetry._send_detached = scrubbed


def _capture_via_harness(
	*,
	command: str,
	start_time: float,
	result: int | str | None = None,
	error_message: str | None = None,
) -> None:
	try:
		from browser_harness import telemetry as harness_telemetry

		capture_cli_event = getattr(harness_telemetry, 'capture_cli_event', None)
		if capture_cli_event is None:
			return
		_set_harness_client_env()
		_scrub_harness_telemetry()
		code = _exit_code(result)
		capture_cli_event(
			action='error' if code else 'completed',
			command=command,
			duration_seconds=time.monotonic() - start_time,
			exit_code=code,
			error_message=error_message,
		)
	except Exception:
		pass


def _run_mcp_stdio_server(module_name: str) -> None:
	"""Silence all logging"""
	import asyncio
	import importlib
	import logging
	import os

	os.environ['BROWSER_USE_LOGGING_LEVEL'] = 'critical'
	os.environ['BROWSER_USE_SETUP_LOGGING'] = 'false'
	logging.disable(logging.CRITICAL)

	main = importlib.import_module(module_name).main
	asyncio.run(main())


def _run_mcp_server() -> None:
	# The 0.x --mcp server (browser_navigate, browser_click, ...) ran the removed engine. Its clients now get the
	# browser-harness exec server (browser_exec, browser_screenshot): a protocol change, see MIGRATING.md.
	print(
		'browser-use --mcp is deprecated and now serves the --cli-mcp tools (browser_exec, browser_screenshot); '
		'switch your MCP config to --cli-mcp.',
		file=sys.stderr,
	)
	_run_cli_mcp_server()


def _run_cli_mcp_server() -> None:
	_run_mcp_stdio_server('browser_use.mcp.cli_mcp')


INSTALL_TEXT = """browser-use 1.0 does not download a browser (0.x installed Playwright Chromium; nothing uses it now).

Pick where the agent's browser runs:
  Browser()                   Browser Use Cloud browser (default). Needs a key: browser-use login
  Browser('chromium')         a fresh local Chrome/Chromium/Edge with its own temp profile
                              (headless when there is no display: servers, Docker, CI)
  Browser('chrome')           the Chrome you have open, with your logins (browser-harness discovery)
  Browser('chrome', profile='Work')
                              a new Chrome on a temporary copy of your Chrome profile 'Work'

Check the local setup: browser-use --doctor"""


def _run_install_command(argv: list[str]) -> int:
	if any(arg in {'-h', '--help'} for arg in argv):
		print('usage: browser-use install')
		print()
		print('Explain how browser-use 1.0 finds a browser (it no longer downloads one).')
		return 0
	print(INSTALL_TEXT)
	return 0


LOGIN_DONE = (
	'Signed in. One key for the library (default model and cloud browser), this CLI, the MCP server\n'
	'(browser-use --cli-mcp) and browser-harness. Try it:\n'
	'  python -c "from browser_use import Agent; print(Agent(\'Find the top story on Hacker News\').run_sync().final_result())"'
)


def _run_login_command(argv: list[str]) -> int:
	"""browser-use login [--device-code | --api-key-stdin] [--no-open] [--json]: browser-harness's OAuth login, same
	key store (~/.config/browser-harness/auth.json), so one login works everywhere. browser-use logout removes it."""
	import os

	from browser_harness import auth

	_set_harness_client_env()
	command = ['login', *argv]
	if any(arg in {'-h', '--help'} for arg in argv):
		return _normalize_captured_cli_output(auth.run_auth_cli, command)
	code = auth.run_auth_cli(command)
	if code == 0 and '--json' not in argv:
		print(LOGIN_DONE)
		if os.environ.get('BROWSER_USE_API_KEY'):
			print('Note: BROWSER_USE_API_KEY is set in this shell and takes precedence over the stored key.')
	return code


def _run_logout_command(argv: list[str]) -> int:
	from browser_harness import auth

	return _normalize_captured_cli_output(auth.run_auth_cli, ['logout', *argv])


def _run_init_command(argv: list[str]) -> int:
	print(
		'browser-use init (project templates) was removed in 1.0. Start from:\n'
		"  from browser_use import Agent\n  print(Agent('Find the top story on Hacker News').run_sync().final_result())",
		file=sys.stderr,
	)
	return 2


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


_delegated_to_harness = False


def _run_browser_harness() -> int | None:
	from browser_harness import run

	global _delegated_to_harness

	_set_harness_client_env()
	_scrub_harness_telemetry()
	_patch_browser_harness_cli_text()
	args = sys.argv[1:]
	if args and args[0] == 'doctor' and args[1:]:
		if args[1:] in (['--help'], ['-h']):
			print('usage: browser-use doctor [--fix-snap]')
			return 0
		if args[1:] != ['--fix-snap']:
			print('usage: browser-use doctor [--fix-snap]', file=sys.stderr)
			sys.exit(2)
	_delegated_to_harness = True
	run.main()
	return None


# Subcommands and flags from the pre-3.0 CLI; maps to hint
_LEGACY_HINTS: dict[str, str] = {
	'open': 'new_tab("https://example.com")',
	'state': 'print(page_info())',
	'screenshot': 'print(capture_screenshot())',
	'eval': 'print(js("document.title"))',
	'cookies': 'print(cdp("Network.getCookies"))',
	'python': '# the CLI runs Python directly now — pipe it on stdin as shown below',
	'run': '# write the steps as Python using the pre-imported helpers shown below',
	'connect': '# connecting is automatic — the default flow attaches to your running Chrome',
	'close': '# restart the local daemon with `browser-use --reload`; stop cloud browsers with stop_remote_daemon(name)',
	'sessions': '# named local sessions were removed — one default daemon; use BU_NAME=<name> for cloud daemons',
	'profile': '# profiles now come from your real Chrome; see the profile-sync interaction skill',
	'cloud': '# authenticate with `browser-use login`, then start_remote_daemon("<name>")',
	'daemon': '# the daemon starts automatically on every call; restart it with `browser-use --reload`',
	'record': '# session recording was removed; use capture_screenshot() per step',
	'mcp': '# MCP server mode is now the --cli-mcp flag: `browser-use --cli-mcp`',
	'--session': '# use BU_NAME=<name> as an env var for named cloud daemons; local runs use one default daemon',
	'--headed': '# local control always attaches to your real, visible Chrome — no flag needed',
	'--cdp-url': '# use the BU_CDP_URL=<url> env var instead of a flag',
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

The CLI allows your agent to control the browser via Python, and it manages the browser in the background.

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

  Install browser-use 1.0 (`uv tool install --prerelease allow 'browser-use>=1.0.0rc1'`)
  with Python 3.12, register the skill from `browser-use skill`, and connect it to
  my browser. Follow https://github.com/browser-use/browser-use if setup or
  connection fails.

More:
  browser-use login        sign in once for cloud browsers and the default model
  browser-use --doctor     check install, daemon, and browser health
  browser-use --help       full command list
  docs: https://github.com/browser-use/browser-use/blob/main/browser_use/skills/browser-use/SKILL.md"""

_EMPTY_STDIN_MESSAGE = """browser-use received empty stdin. This CLI executes Python piped on stdin:
  browser-use <<'PY'
  print(page_info())
  PY"""


def _command_name(args: list[str]) -> str:
	if '--cli-mcp' in args:
		return 'cli-mcp'
	if '--mcp' in args:
		return 'mcp'
	if args and args[0] == 'install':
		return 'install'
	if args and args[0] == 'init':
		return 'init'
	if '--template' in args or '-t' in args:
		return 'init'
	if args and args[0] == 'skill':
		return 'skill'
	legacy = _legacy_command(args)
	if legacy is not None:
		return f'legacy:{legacy}'
	return args[0] if args else 'run'


def _dispatch(args: list[str]) -> tuple[int | None, str]:
	if '--cli-mcp' in args:
		_run_cli_mcp_server()
		return 0, 'cli-mcp'
	if '--mcp' in args:
		_run_mcp_server()
		return 0, 'mcp'
	if args and args[0] == 'install':
		return _run_install_command(args[1:]), 'install'
	if args and args[0] == 'login':
		return _run_login_command(args[1:]), 'login'
	if args and args[0] == 'logout':
		return _run_logout_command(args[1:]), 'logout'
	if args and args[0] == 'init':
		return _run_init_command(args[1:]), 'init'
	if '--template' in args or '-t' in args:
		return _run_init_command(args), 'init'
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

	from browser_harness.auth import CloudAuthRequired

	try:
		return _run_browser_harness(), args[0] if args else 'run'
	except CloudAuthRequired:  # its message names `browser-harness auth login`, not on PATH for `uv tool install browser-use`
		print('Not signed in to Browser Use Cloud. Run `browser-use login`, then retry.', file=sys.stderr)
		return 1, args[0] if args else 'run'
	except NameError as exc:
		name = _unknown_exec_name(exc)
		if name is None or not _raised_from_piped_code(exc):
			raise
		import traceback

		traceback.print_exc()
		print(_unknown_helper_message(name), file=sys.stderr)
		return 2, args[0] if args else 'run'


class _StderrTail:
	"""Pass-through stderr wrapper that remembers the tail as error context."""

	def __init__(self, wrapped):
		self._wrapped = wrapped
		self.tail = ''

	def write(self, text):
		self.tail = (self.tail + text)[-500:]
		return self._wrapped.write(text)

	def __getattr__(self, name):
		return getattr(self._wrapped, name)


def browser_use_tui_main() -> int | None:
	print('browser-use-tui is deprecated; use browser-use instead.', file=sys.stderr)
	return main()


def main() -> int | None:
	global _delegated_to_harness

	_delegated_to_harness = False
	args = sys.argv[1:]
	start_time = time.monotonic()
	command = _command_name(args)
	stderr_tail = _StderrTail(sys.stderr)
	sys.stderr = stderr_tail
	try:
		result, command = _dispatch(args)
	except SystemExit as exc:
		result = exc.code
		if not _delegated_to_harness:
			_capture_via_harness(
				command=command,
				start_time=start_time,
				result=result,
				error_message=str(result) if isinstance(result, str) else stderr_tail.tail.strip() or None,
			)
		raise
	except Exception as exc:
		if not _delegated_to_harness:
			_capture_via_harness(command=command, start_time=start_time, result=1, error_message=str(exc))
		raise
	finally:
		sys.stderr = stderr_tail._wrapped

	if not _delegated_to_harness:
		_capture_via_harness(
			command=command,
			start_time=start_time,
			result=result,
			error_message=(stderr_tail.tail.strip() or None) if _exit_code(result) else None,
		)
	return result


if __name__ == '__main__':
	result = main()
	if result is not None:
		sys.exit(result)
