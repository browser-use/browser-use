"""Browser Use CLI backed by Browser Harness"""

from __future__ import annotations

import shutil
import sys
import time
from contextlib import redirect_stderr, redirect_stdout
from importlib.metadata import PackageNotFoundError, version
from io import StringIO, TextIOWrapper
from pathlib import Path
from typing import TYPE_CHECKING, Any


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
	browser-use CLI the code, output and arguments never leave the machine, the error message is sent as its exception
	line with credentials scrubbed, or as its class when the piped code raised it (stats.scrub_cli_event): every event is scrubbed, then sent by the library's
	sender to the library's PostHog project under its device id, next to the same machine's agent_events (browser-harness
	would send it to its own project under its own install id, and create that id). ANONYMIZED_TELEMETRY turns it off as
	in the library (browser-harness alone only knows 0, false, no and off): its is_enabled() says so too, else it built the
	event before the send was dropped."""
	from browser_harness import telemetry

	from browser_use.config import CONFIG

	enabled = telemetry.is_enabled
	if not getattr(enabled, '__bu_scrubbed__', False):

		def is_enabled() -> bool:
			return bool(CONFIG.ANONYMIZED_TELEMETRY) and enabled()

		is_enabled.__bu_scrubbed__ = True  # type: ignore[attr-defined]
		telemetry.is_enabled = is_enabled
	if not getattr(telemetry._install_id, '__bu_scrubbed__', False):

		def install_id(config: dict | None = None, *, create: bool = True) -> str | None:
			"""The id `browser-use telemetry status` shows: the one cli_event is sent under."""
			from browser_use.telemetry.service import get_or_create_device_id

			return get_or_create_device_id() if create and CONFIG.ANONYMIZED_TELEMETRY else None

		install_id.__bu_scrubbed__ = True  # type: ignore[attr-defined]
		telemetry._install_id = install_id
	if not getattr(telemetry.status, '__bu_scrubbed__', False):
		harness_status = telemetry.status

		def status() -> dict:
			"""`browser-use telemetry status|enable|disable`: whether browser-use sends, ANONYMIZED_TELEMETRY read as the
			library reads it (browser-harness alone took n or disable for on)."""
			from browser_use.telemetry import service

			out = harness_status()
			service._harness_config_disabled = bool(out.get('disabled_by_config'))  # enable/disable just changed it
			out['disabled_by_env'] = bool(out.get('disabled_by_env')) or not CONFIG.ANONYMIZED_TELEMETRY
			out['enabled'] = service.telemetry().enabled
			if not out['enabled']:
				out['install_id'] = None
			return out

		status.__bu_scrubbed__ = True  # type: ignore[attr-defined]
		telemetry.status = status
	if getattr(telemetry._send_detached, '__bu_scrubbed__', False):
		return

	def scrubbed(payload: dict) -> None:
		from browser_use.telemetry.service import Job
		from browser_use.telemetry.service import telemetry as product_telemetry
		from browser_use.telemetry.stats import scrub_cli_event

		if not product_telemetry().enabled:
			return

		event = scrub_cli_event(payload, sys.exc_info()[1])  # browser-harness sends while it handles the piped code's error
		props = event.get('properties') or {}
		product_telemetry().notice = False  # no log line on the CLI's stderr each call (it never had one)
		product_telemetry().capture_run(Job(str(event.get('event') or 'cli_event'), lambda steps, keys: props))

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


def _run_mcp_stdio_server(module_name: str, **kwargs: Any) -> None:
	"""Silence all logging"""
	import asyncio
	import importlib
	import logging
	import os

	os.environ['BROWSER_USE_LOGGING_LEVEL'] = 'critical'
	os.environ['BROWSER_USE_SETUP_LOGGING'] = 'false'
	logging.disable(logging.CRITICAL)

	main = importlib.import_module(module_name).main
	asyncio.run(main(**kwargs))


def _mcp_browser_options() -> dict[str, Any]:
	"""The 0.x --mcp server's browser restrictions (0.x config.py, mcp/server.py): allowed_domains and prohibited_domains
	of config.json's default browser_profile, BROWSER_USE_ALLOWED_DOMAINS over them. Ignoring them gave an MCP client
	restricted to one site a browser that goes anywhere. A proxy, which 1.0 cannot run locally, raises."""
	import json
	import os
	from pathlib import Path

	from browser_use.exceptions import removed

	if os.environ.get('BROWSER_USE_CONFIG_PATH'):
		path = Path(os.environ['BROWSER_USE_CONFIG_PATH']).expanduser()
	elif os.environ.get('BROWSER_USE_CONFIG_DIR'):
		path = Path(os.environ['BROWSER_USE_CONFIG_DIR']).expanduser() / 'config.json'
	else:
		path = Path(os.environ.get('XDG_CONFIG_HOME') or '~/.config').expanduser() / 'browseruse' / 'config.json'
	try:
		profiles = list((json.loads(path.read_text(encoding='utf-8')).get('browser_profile') or {}).values())
	except (OSError, ValueError, AttributeError):  # no config, or one 0.x itself replaced with a fresh default
		profiles = []
	profile = next((p for p in profiles if isinstance(p, dict) and p.get('default')), profiles[0] if profiles else {})
	profile = profile if isinstance(profile, dict) else {}
	options = {k: profile[k] for k in ('allowed_domains', 'prohibited_domains') if profile.get(k)}
	if domains := os.environ.pop('BROWSER_USE_ALLOWED_DOMAINS', '').strip():  # Browser() raises on the variable itself
		options['allowed_domains'] = [d.strip() for d in domains.split(',') if d.strip()]
	proxy_env = [
		k
		for k in ('BROWSER_USE_PROXY_URL', 'BROWSER_USE_NO_PROXY', 'BROWSER_USE_PROXY_USERNAME', 'BROWSER_USE_PROXY_PASSWORD')
		if os.environ.get(k)
	]
	if profile.get('proxy') or proxy_env:
		where = proxy_env[0] if proxy_env else f'the proxy of the default browser_profile in {path}'
		raise ValueError(removed(f'browser-use --mcp with a proxy ({where})', "Browser('chromium') has no proxy yet; remove it."))
	return options


def _run_mcp_server(command: str = 'browser-use --mcp') -> int:
	# The 0.x --mcp server (browser_navigate, browser_click, ...) ran the removed engine. Its clients now get the
	# browser-harness exec server (browser_exec, browser_screenshot): a protocol change, see MIGRATING.md. It keeps the
	# 0.x server's own Chromium and its domain restrictions: an old config must not start driving the user's logged-in
	# Chrome, or go to sites it was kept off.
	print(
		f'{command} is deprecated and now serves the --cli-mcp tools (browser_exec, browser_screenshot, '
		'browser_login, browser_feedback) on its own Chromium; browser-use --cli-mcp drives your own Chrome instead.',
		file=sys.stderr,
	)
	from browser_use.domains import DomainRules

	try:
		options = _mcp_browser_options()
		DomainRules.of(options.get('allowed_domains'), options.get('prohibited_domains'))  # a bad pattern: here, not mid-protocol
	except (TypeError, ValueError) as e:
		print(f'{command}: {e}', file=sys.stderr)
		return 2
	_run_mcp_stdio_server('browser_use.mcp.cli_mcp', own_browser=True, **options)
	return 0


def _run_cli_mcp_server() -> None:
	_run_mcp_stdio_server('browser_use.mcp.cli_mcp')


def _run_mcp_error_server(message: str) -> None:
	"""--cli-mcp / --mcp where nothing can run (browser-harness cannot create its dirs): a server that starts and answers
	every tool call with message, but browser_feedback, which still reports. Exiting before initialize left message in
	the MCP host's log and showed the agent only 'Connection closed'."""
	import asyncio

	import mcp.server.stdio
	import mcp.types as types
	from mcp.server import Server

	from browser_use.telemetry import feedback

	server = Server('browser-use', version=_browser_use_version(), instructions=message)
	tools = [
		types.Tool(
			name='browser_exec',
			description='Execute Python in the browser-use session.',
			input_schema={'type': 'object', 'properties': {'code': {'type': 'string'}}, 'required': ['code']},
		),
		types.Tool(**feedback.MCP_TOOL),  # browser-use being broken is what feedback is for
	]

	async def list_tools(_context: Any, _params: Any) -> types.ListToolsResult:
		return types.ListToolsResult(tools=tools)

	async def call_tool(_context: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
		text, failed = f'Error: {message}', True
		if params.name == 'browser_feedback':
			text, failed = feedback.mcp_call(params.arguments or {})
		return types.CallToolResult(content=[types.TextContent(type='text', text=text)], is_error=failed)

	server.add_request_handler('tools/list', types.PaginatedRequestParams, list_tools)
	server.add_request_handler('tools/call', types.CallToolRequestParams, call_tool)

	async def serve() -> None:
		async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
			await server.run(read_stream, write_stream, server.create_initialization_options())

	asyncio.run(serve())


def _run_doctor() -> int:
	"""browser-use --doctor. browser-harness's doctor named itself, showed its own version and failed a stopped daemon
	(every call starts one) and a missing sign-in (optional), so a healthy fresh install exited 1. Exit 1 only when
	nothing can run: no local browser and no key."""
	import platform

	from browser_harness import admin

	from browser_use.auth import browser_use_api_key
	from browser_use.browser.browser import _name_daemon_files
	from browser_use.browser.local import find_binary

	_name_daemon_files()  # the daemon this checks is the one the next call would use
	print(f'browser-use {_browser_use_version()} (browser-harness {admin._version()}), Python {platform.python_version()}')
	try:
		local = find_binary()
	except RuntimeError as e:  # none installed (its error names `browser-use install`), or only a Snap one (it does not)
		local, local_text = None, str(e).splitlines()[0]
		if 'browser-use install' not in local_text:  # Playwright's Chromium is found past a Snap one
			local_text += '  (or: browser-use install)'
	else:
		local_text = local
	try:
		key = bool(browser_use_api_key())
		key_text = 'yes'
	except RuntimeError:  # MissingAPIKeyError
		key, key_text = False, 'none: browser-use login (Browser() and the bu-* models need it)'
	chrome_text = 'yes' if admin._chrome_running() else "no (Browser('chrome') needs it; the CLI then runs its own Chromium)"
	print(f'  local browser   {local_text}')
	print(f'  Chrome running  {chrome_text}')
	print(f'  daemon          {"running" if admin.daemon_alive() else "stopped (the next call starts it)"}')
	if _own_chromium_ws():
		print('  own Chromium    open: the CLI drives it, not your Chrome (browser-use --reload closes it)')
	print(f'  cloud key       {key_text}')
	return 0 if (local or key) else 1


INSTALL_TEXT = """Pick where the agent's browser runs:
  Browser()                   Browser Use Cloud browser (default). Needs a key: browser-use login
  Browser('chromium')         a fresh local Chrome/Chromium/Edge (or the Chromium just installed) with its own temp profile
                              (headless when there is no display: servers, Docker, CI)
  Browser('chrome')           the Chrome you have open, with your logins (browser-harness discovery)
  Browser('chrome', profile='Work')
                              a new Chrome on a temporary copy of your Chrome profile 'Work'

Check the local setup: browser-use --doctor"""


def _run_install_command(argv: list[str]) -> int:
	if any(arg in {'-h', '--help'} for arg in argv):
		print('usage: browser-use install')
		print()
		print("Install Playwright's Chromium (+ system dependencies on Linux) for Browser('chromium').")
		print('Not needed for the default cloud browser or a Chrome you already have.')
		return 0
	import platform
	import shutil
	import subprocess

	if not shutil.which('uvx'):
		print(
			'uvx not found. Install uv from https://docs.astral.sh/uv/ or run: pip install playwright && playwright install chromium',
			file=sys.stderr,
		)
		return 1
	print('Installing Chromium browser + system dependencies...\nThis may take a few minutes...\n')
	cmd = ['uvx', 'playwright', 'install', 'chromium']
	if platform.system() == 'Linux':
		cmd.append('--with-deps')
	cmd.append('--no-shell')
	result = subprocess.run(cmd)
	if result.returncode != 0:
		print('\nInstallation failed', file=sys.stderr)
		return result.returncode or 1
	print('\nInstallation complete.\n')
	print(INSTALL_TEXT)
	return 0


LOGIN_DONE = (
	'Signed in. One key for the library (default model and cloud browser), this CLI and the MCP server\n'
	'(browser-use --cli-mcp). Try it in Python:\n'
	'  from browser_use import Agent\n'
	"  print(Agent('Find the top story on Hacker News').run_sync().final_result())"
)


def _read_api_key_stdin() -> str:
	"""The key for `login --api-key-stdin`, checked before anything is stored."""
	import ssl
	import urllib.error
	import urllib.request

	from browser_harness import auth

	from browser_use.auth import KEYS_URL
	from browser_use.utils import urlopen_keyed

	key = auth._read_manual_api_key()  # piped stdin, or a hidden prompt on a terminal; rejects empty and short input
	if not key.startswith('bu_'):
		raise auth.AuthError(f'that is not a Browser Use API key (they start with bu_); create one at {KEYS_URL} and paste it')
	if not key.isascii() or any(c.isspace() or not c.isprintable() for c in key):  # stored, it would break every request
		raise auth.AuthError(
			f'the key has a space, line break, control or non-ASCII character inside it; copy it again from {KEYS_URL} and paste it whole'
		)
	request = urllib.request.Request(f'{auth.auth_base()}/api/v4/browsers?pageSize=1', headers={'X-Browser-Use-API-Key': key})
	try:  # one read-only call, so a mistyped or revoked key is never stored and "Signed in" is true
		urlopen_keyed(request, 15).close()
	except urllib.error.HTTPError as e:
		if e.code == 401:  # a 403 is a real key without the browser scope: it still works for the bu-* models
			raise auth.AuthError(
				f'Browser Use Cloud rejected that key (HTTP 401); create one at {KEYS_URL} and paste it'
			) from None
	except OSError as e:
		reason = getattr(e, 'reason', e)  # urllib wraps the handshake's error in URLError
		if isinstance(reason, ssl.SSLError):  # a certificate the TLS check refused is not offline
			why = getattr(reason, 'verify_message', None) or reason  # the certificate problem itself, when there is one
			raise auth.AuthError(
				f'could not check the key: the TLS connection to {auth.auth_base()} failed ({why}); '
				'the key was not stored. Behind a TLS-inspecting proxy, set SSL_CERT_FILE to its CA bundle and retry'
			) from None
		# offline: store it; the first cloud call reports a bad key
	return key


def _run_login_command(argv: list[str]) -> int:
	"""browser-use login [--device-code | --api-key-stdin] [--no-open] [--json]: browser-harness's OAuth login, same
	key store (~/.config/browser-harness/auth.json), so one login works everywhere. browser-use logout removes it."""
	import os

	from browser_harness import auth

	from browser_use.auth import harden_login_callback, set_aside_corrupt_store

	_set_harness_client_env()
	command = ['login', *argv]
	if any(arg in {'-h', '--help'} for arg in argv):
		return _normalize_captured_cli_output(auth.run_auth_cli, command)
	try:  # Ctrl-C at the hidden key prompt, during the key check or while it waits for the approval: nothing stored
		if '--api-key-stdin' in argv:
			try:
				sys.stdin = StringIO(_read_api_key_stdin())
			except auth.AuthError as e:
				print(e, file=sys.stderr)
				return 1
		harden_login_callback()
		if notice := set_aside_corrupt_store():
			print(notice, file=sys.stderr)
		code = auth.run_auth_cli(command)
	except KeyboardInterrupt:
		print('Login cancelled.', file=sys.stderr)
		return 130
	if code == 0 and '--json' not in argv:
		print(LOGIN_DONE)
		if os.environ.get('BROWSER_USE_API_KEY'):
			print('Note: BROWSER_USE_API_KEY is set in this shell and takes precedence over the stored key.')
	return code


def _run_logout_command(argv: list[str]) -> int:
	import json

	from browser_harness import auth

	from browser_use.auth import corrupt_store_path

	if (path := corrupt_store_path()) and not any(arg in {'-h', '--help'} for arg in argv):
		path.unlink()  # an unreadable store holds no usable key; logging out removes it
		print(json.dumps({'status': 'logged-out', 'path': str(path), 'note': 'the file was corrupt'}, indent=2))
		return 0
	return _normalize_captured_cli_output(auth.run_auth_cli, ['logout', *argv])


def _run_init_command(argv: list[str]) -> int:
	print(
		'browser-use init (project templates) was removed in 1.0. Start from:\n'
		"  from browser_use import Agent\n  print(Agent('Find the top story on Hacker News').run_sync().final_result())",
		file=sys.stderr,
	)
	return 2


def _run_feedback_command(argv: list[str]) -> int:
	"""`browser-use feedback "what happened"` (or the text piped on stdin): one library_feedback event to the Browser Use
	team, also with usage stats off (the user sends it). Waits for the send, so the line it prints is true."""
	import argparse

	from browser_use.telemetry import feedback
	from browser_use.telemetry.service import telemetry

	parser = argparse.ArgumentParser(
		prog='browser-use feedback',
		description='Tell the Browser Use team what went wrong with browser-use. Secrets, API keys, emails, URL queries '
		'and home folders in the text are replaced before it is sent.',
	)
	parser.add_argument('message', nargs='*', help='what happened (or pipe it on stdin)')
	parser.add_argument('--category', choices=feedback.CATEGORIES, default='bug')
	args = parser.parse_args(argv)
	if not args.message and isinstance(sys.stdin, TextIOWrapper) and not sys.stdin.isatty():
		sys.stdin.reconfigure(encoding='utf-8-sig', errors='replace')  # Windows read a pipe as cp1252 (see _dispatch)
	text = ' '.join(args.message) or ('' if _stdin_is_terminal() else sys.stdin.read())
	if not text.strip():
		parser.print_usage(sys.stderr)
		print(
			"browser-use feedback: say what happened, e.g. browser-use feedback 'goto_url hangs on example.com'", file=sys.stderr
		)
		return 2
	sender = telemetry()
	sender.notice = False  # the CLI's stderr stays its own
	job = feedback.capture('cli', text, args.category, consent=True)
	if job is None:  # run by a model's code (BU_MODEL_CODE)
		print(feedback.MODEL_CODE, file=sys.stderr)
		return 1
	if not sender.flush(10) or job.sent is None:  # still sending at exit: the exit sender takes it
		print('Sending your feedback to the Browser Use team in the background. Thanks!')
	elif job.sent:
		print('Sent your feedback to the Browser Use team. Thanks!')
	elif sender.enabled:  # kept in the outbox
		print('Could not reach the Browser Use team now; your feedback is saved and sent on the next browser-use run.')
	else:
		print('Could not reach the Browser Use team; nothing was sent. Try again later.', file=sys.stderr)
		return 1
	return 0


def _as_browser_use_cli_text(text: str) -> str:
	"""Rebrand command names in browser-harness output; paths (~/.config/browser-harness/auth.json) stay real."""
	import re

	return re.sub(r'(?<![/\\])browser-harness(?![/\\])', 'browser-use', text.replace('Browser Harness', 'Browser Use'))


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

	from browser_use.auth import harden_login_callback

	harden_login_callback()  # `browser-use auth login` runs browser-harness's login too
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
	fix_snap = run.run_doctor_fix_snap  # its text named `browser-harness --doctor`
	run.run_doctor_fix_snap = lambda: _normalize_captured_cli_output(lambda _argv: fix_snap(), [])
	from browser_harness import macos

	if not getattr(macos.run_cli, '__bu_rebranded__', False):  # its answers said to run `browser-harness mac-approve`
		mac_approve = macos.run_cli

		def run_mac_approve(argv: list[str]) -> int:
			return _normalize_captured_cli_output(mac_approve, argv)  # one line at the end: nothing to stream

		run_mac_approve.__bu_rebranded__ = True  # type: ignore[attr-defined]
		macos.run_cli = run_mac_approve


_delegated_to_harness = False


def _guard_cloud_browsers(run, code: str | None) -> None:
	"""Cloud browser rules for piped code (browser_use/harness_cloud.py), installed in the namespace it runs in."""
	from browser_use import harness_cloud

	harness_cloud.install(vars(run))
	vars(run)['ensure_daemon'] = _with_own_chromium(harness_cloud.ensure_daemon, vars(run))
	if (
		code
		and harness_cloud.calls_cloud_admin(code)
		and not code.lstrip().startswith(tuple(f'{n}(' for n in harness_cloud.CLOUD_ADMIN))
	):
		# browser-harness only skips its pre-run ensure_daemon() when the code *starts* with start_remote_daemon(; for
		# `b = start_remote_daemon(...)` that call would attach the local Chrome first. Skip it once, here too.
		guarded = vars(run)['ensure_daemon']

		def skip_pre_run_attach(*args, **kwargs) -> None:
			vars(run)['ensure_daemon'] = guarded

		vars(run)['ensure_daemon'] = skip_pre_run_attach


OWN_CHROMIUM = 'default-chromium'
"""The daemon of the CLI's own Chromium. Never 'default': that one is the user's Chrome, and Browser('chrome') and
--cli-mcp take a live default daemon to be it (they then drove this temp-profile Chromium as "your own Chrome")."""


def _own_chromium_dir() -> Path:
	"""The profile of the CLI's own Chromium, next to its daemon's pid file: the next call finds it there."""
	from browser_harness import _ipc as ipc

	return ipc.pid_path(OWN_CHROMIUM).with_suffix('.chromium')


def _own_chromium_ws() -> str | None:
	"""The browser websocket of the CLI's own Chromium while it runs, read from its own profile (never a guessed port).
	Only the Chromium that wrote that DevToolsActivePort answers with its websocket: a process that took the port after
	it exited never matches (Windows too, where _left_over cannot tell)."""
	import json
	import urllib.request

	from browser_use.browser import local

	udd = _own_chromium_dir()
	if not (ws := local._ws_url(udd, udd / 'none.log')):
		return None
	try:
		opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # an HTTP_PROXY never sees localhost
		with opener.open(f'http://{ws.split("/")[2]}/json/version', timeout=1) as r:
			return ws if json.loads(r.read()).get('webSocketDebuggerUrl') == ws else None
	except (OSError, ValueError, AttributeError):
		return None


def _start_own_chromium(why: str, setup: RuntimeError | None) -> str:
	"""Launch the CLI's own Chromium (headless with no display) on a fresh profile, detached: it outlives this call.
	As --cli-mcp: Playwright's Chromium is installed first only on a machine with no browser and no display."""
	from browser_use.auth import browser_use_api_key
	from browser_use.browser import local
	from browser_use.mcp.cli_mcp import _install_chromium, no_browser_text

	udd, installed, chromium = _own_chromium_dir(), '', local.LocalBrowser()
	shutil.rmtree(udd, ignore_errors=True)
	try:
		try:
			ws = chromium.start(user_data_dir=udd)
		except RuntimeError as e:
			if not str(e).startswith('No Chrome, Chromium or Edge found') or local.has_display():
				raise
			installed = f" Installed Playwright's Chromium first ({_install_chromium():.0f} s)."
			ws = chromium.start(user_data_dir=udd)
	except Exception as e:
		chromium.stop()  # one that did not open its DevTools port in time is still running
		if setup is not None:  # a browser find_binary cannot launch (Brave, Arc): the setup steps are the way
			raise setup from None
		try:
			browser_use_api_key()
			cloud = ', or start a cloud browser: start_remote_daemon()'
		except RuntimeError:  # MissingAPIKeyError, or a corrupt key store
			cloud = ', or for a Browser Use Cloud browser: browser-use login, then start_remote_daemon()'
		raise RuntimeError(no_browser_text(f"no Chrome to attach ({why}), and browser-use's own Chromium", e, cloud)) from None
	print(
		f"browser-use: Browser: browser-use's own Chromium on a temp profile, not your Chrome ({why}). Later calls "
		f'use it too; `browser-use --reload` closes it.{installed}',
		file=sys.stderr,
	)
	return ws


def _route(name: str, namespace: dict[str, Any]) -> None:
	"""This process's helpers drive daemon name. Unlike harness_cloud.route, BU_NAME stays unset: a nested `browser-use`
	call makes the same choice, and nothing reads the routing as an explicit BU_NAME."""
	from browser_harness import admin, helpers

	admin.NAME = helpers.NAME = namespace['NAME'] = name


def _with_own_chromium(ensure_daemon: Any, namespace: dict[str, Any]) -> Any:
	"""The CLI's ensure_daemon: where the user's Chrome cannot be used (no display, remote debugging off, none installed),
	a Chromium of the CLI's own, as --cli-mcp does (mcp/cli_mcp.py), under its own daemon (OWN_CHROMIUM) that every later
	call is routed to until `browser-use --reload`. An explicit choice is never replaced: BU_NAME, BU_CDP_URL / BU_CDP_WS,
	a cloud daemon, a default daemon already attached, a user's Chrome that is set up (or whose toggle is on and still
	starting)."""

	def ensure(wait: float | None = None, name: str | None = None, env: dict[str, str] | None = None) -> None:
		import os

		from browser_harness import admin, daemon

		from browser_use import harness_cloud

		if name or env or os.environ.get('BU_NAME') or not admin._is_local_chrome_mode():
			return ensure_daemon(wait=wait, name=name, env=env)
		_route('default', namespace)  # a second ensure in this process starts over
		if harness_cloud.was_cloud(admin.NAME):
			return ensure_daemon(wait=wait)
		for attached in (OWN_CHROMIUM, 'default'):  # its own Chromium until --reload, else a default daemon attached
			try:
				admin.require_existing_daemon(attached)
			except RuntimeError:
				continue
			return _route(attached, namespace)
		ws = _own_chromium_ws()  # still running from an earlier call, whose daemon died or was stopped
		if ws is None:
			try:
				return ensure_daemon(wait=wait)
			except RuntimeError as e:
				if not str(e).startswith('remote-debugging-setup:'):
					raise
				from browser_use.mcp.cli_mcp import _no_chrome_here, _setup_reason

				why, setup = _no_chrome_here(), None
				if why is None:
					if daemon.remote_debugging_toggle_profiles():  # Chrome is starting with it on: the next call attaches
						raise
					why, setup = _setup_reason(e, 'run `browser-use --reload`'), e
			lock = admin._spawn_lock(OWN_CHROMIUM, timeout=90.0)  # concurrent cold calls: one launches the Chromium
			lock.path = _own_chromium_dir().with_suffix('.chromiumlock')
			with lock:
				if lock.fd is None:  # another call is still launching it (or installing Chromium): never a second one
					raise RuntimeError('daemon-starting: another browser-use call is still starting its browser; retry')
				ws = _own_chromium_ws() or _start_own_chromium(why, setup)
		ensure_daemon(wait=wait, name=OWN_CHROMIUM, env={'BU_CDP_WS': ws, 'BH_TAB_MARKER': '0'})  # one spawn at a time
		_route(OWN_CHROMIUM, namespace)

	return ensure


def _close_own_chromium() -> None:
	"""`browser-use --reload`: the CLI's own Chromium closes too, so the next call looks for the user's Chrome again."""
	from browser_harness import admin

	from browser_use.browser import local

	try:
		admin.restart_daemon(OWN_CHROMIUM)
	except Exception:  # a pending daemon it would not signal: its Chromium closes below, so it ends too
		pass
	if ws := _own_chromium_ws():
		local._close_over_cdp(ws)
		deadline = time.monotonic() + 5
		while _own_chromium_ws() and time.monotonic() < deadline:
			time.sleep(0.1)
	shutil.rmtree(_own_chromium_dir(), ignore_errors=True)


class _HarnessStderr:
	"""sys.stderr (and sys.stdout for a subcommand) while browser-harness runs. Its own lines ("browser-harness: ...",
	the macOS Allow-popup hint `run browser-harness mac-approve`, `usage: browser-harness video ...`) named a command
	`uv tool install browser-use` does not put on PATH. For piped code only its "browser-harness: " lines are its own;
	a subcommand (video, recordings, --reload) prints nothing but its own text."""

	def __init__(self, wrapped, subcommand: bool = False):
		self._wrapped = wrapped
		self._subcommand = subcommand

	def write(self, text):
		if self._subcommand or text.startswith('browser-harness: '):  # not the cell's own output
			text = _as_browser_use_cli_text(text)
		return self._wrapped.write(text)

	def __getattr__(self, name):
		return getattr(self._wrapped, name)


def _run_browser_harness(code: str | None = None) -> int | None:
	import os

	from browser_harness import helpers, run

	from browser_use.browser.browser import _name_daemon_files
	from browser_use.repl import worker
	from browser_use.repl.capture import install as install_capture
	from browser_use.repl.page_info import install as install_page_info

	global _delegated_to_harness

	_name_daemon_files()  # with BH_RUNTIME_DIR set, every BU_NAME would otherwise share one bu.sock
	# browser-harness's daily "agents: run `browser-harness --update -y`": browser-use pins it exactly, so that command
	# is not on PATH (uv tool install) or upgrades it past the pin (a venv). It updates with browser-use (--update).
	os.environ['BH_UPDATE_CHECK'] = '0'
	_set_harness_client_env()
	_scrub_harness_telemetry()
	_patch_browser_harness_cli_text()
	_guard_cloud_browsers(run, code)
	install_page_info()  # cli-1: run.py star-imported the helpers already, so rebind its name too
	run.page_info = helpers.page_info
	install_capture()  # win-cli-5: a hidden tab's screenshot gets the Agent's activate fallback
	run.cdp = helpers.cdp
	# The Agent's http_get, plain HTTP from this machine: browser-harness's sends the URL and headers to the fetch-use
	# proxy whenever BROWSER_USE_API_KEY is set (localhost and intranet URLs then fail, Authorization leaves the machine)
	run.http_get = worker.http_get
	args = sys.argv[1:]
	if args == ['--reload']:  # restarting a name on purpose is how it may drive a local Chrome again after a cloud one
		from browser_use import harness_cloud

		harness_cloud.forget(run.NAME)
		_close_own_chromium()
	if args and args[0] == 'doctor' and args[1:]:
		if args[1:] in (['--help'], ['-h']):
			print('usage: browser-use doctor [--fix-snap]')
			return 0
		if args[1:] != ['--fix-snap']:
			print('usage: browser-use doctor [--fix-snap]', file=sys.stderr)
			sys.exit(2)
	_delegated_to_harness = True
	subcommand = bool(args) and args[0] != '--debug-clicks'  # --debug-clicks still runs piped code
	stdout, stderr = sys.stdout, sys.stderr
	sys.stderr = _HarnessStderr(stderr, subcommand)
	if subcommand:  # `video --help`, `video init`'s "next: ... run browser-harness video review"
		sys.stdout = _HarnessStderr(stdout, subcommand)
	try:
		run.main()
	finally:
		sys.stdout, sys.stderr = stdout, stderr
	return None


_AGENT_HINT = (
	'# the CLI runs Python, not agent tasks; run an agent with the library, in Python:\n'
	"  from browser_use import Agent\n  print(Agent('<task>').run_sync().final_result())"
)

# Subcommands and flags from the 0.x CLI; maps to hint
_LEGACY_HINTS: dict[str, str] = {
	'open': 'new_tab("https://example.com")',
	'state': 'print(page_info())',
	'screenshot': 'print(capture_screenshot())',
	'eval': 'print(js("document.title"))',
	'cookies': 'print(cdp("Network.getCookies"))',
	# the 0.x page commands: coordinates come from page_info() and a screenshot, not element indexes
	'click': 'click_at_xy(200, 300)',
	'type': 'type_text("hello")',
	'input': 'fill_input("input[name=q]", "hello")',
	'keys': 'press_key("Enter")',
	'scroll': 'scroll(640, 400, dy=600)  # dy > 0 scrolls down',
	'back': 'js("history.back()")',
	'hover': 'cdp("Input.dispatchMouseEvent", type="mouseMoved", x=200, y=300)',
	'python': '# the CLI runs Python directly now — pipe it on stdin as shown below',
	'run': _AGENT_HINT,
	'-p': _AGENT_HINT,
	'--prompt': _AGENT_HINT,
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


CORE_HELPERS = """Core helpers: new_tab(url), goto_url(url), page_info(), capture_screenshot(),
  click_at_xy(x, y), type_text(text), fill_input(selector, text), press_key(key),
  scroll(x, y), js(code), cdp(method, ...), wait_for_load(), wait_for_element(selector),
  list_tabs(), switch_tab(target), close_tab(target)"""

_CLI3_GUIDE = f"""{CORE_HELPERS}

Read the full interface now:   browser-use skill show
Install the skill (replaces any pre-existing browser-use skill):
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
	return f"""The browser-use CLI changed in 1.0, and '{command}' was removed.

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

  Install browser-use with `uv tool install browser-use=={version}`, run `browser-use skill install`
  to register the skill, and connect it to my browser. If setup or connection fails,
  run `browser-use --doctor` and follow its output and the error message.

More:
  browser-use login        sign in once for cloud browsers and the default model
  browser-use --doctor     check install, daemon, and browser health
  browser-use --help       full command list
  docs: https://docs.browser-use.com/open-source/browser-use-cli"""

_EMPTY_STDIN_MESSAGE = """browser-use received empty stdin. This CLI executes Python piped on stdin:
  browser-use <<'PY'
  print(page_info())
  PY"""


HELP = """Browser Use CLI: your coding agent drives a browser with Python piped on stdin.

  browser-use <<'PY'
  new_tab("https://example.com")
  print(page_info())
  PY

Helpers are pre-imported; the daemon starts and attaches to your running Chrome by itself, or to a Chromium of its own
where it cannot (no display, remote debugging off).

Commands:
  browser-use login [--device-code | --api-key-stdin]   sign in to Browser Use Cloud (cloud browsers, default model)
  browser-use logout                  remove the stored key
  browser-use auth status             show the sign-in state
  browser-use --doctor                check install, daemon and browser
  browser-use doctor --fix-snap       how to fix Snap Chromium blocking CDP (Linux)
  browser-use mac-approve             approve Chrome's macOS remote-debugging prompt
  browser-use --reload                restart the daemon and close its own Chromium
  browser-use install                 install Chromium for the library's Browser('chromium') (Playwright's build)
  browser-use skill [show | install [--target NAME] [--path DIR] [--install-cli]]
                                      print or install the agent skill
  browser-use feedback "what happened" [--category bug|docs|missing|other]
                                      tell the Browser Use team what went wrong with browser-use
  browser-use --cli-mcp               run the MCP server (browser_exec, browser_screenshot, browser_login, browser_feedback)
  browser-use --version               print the versions
Update: uv tool upgrade browser-use (or pip install -U browser-use).
Library: from browser_use import Agent, see https://github.com/browser-use/browser-use"""


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


def _stdin_is_terminal() -> bool:
	"""On Windows isatty() is True for every character device, NUL too: `browser-use < NUL` and a subprocess started
	with stdin=DEVNULL got the quickstart and exit 0, not the empty-stdin error (win-cli-8). Only a console is a terminal."""
	if not sys.stdin.isatty():
		return False
	if sys.platform != 'win32':
		return True
	import ctypes
	import msvcrt

	try:
		handle = msvcrt.get_osfhandle(sys.stdin.fileno())
	except (OSError, ValueError):  # no file descriptor: trust isatty()
		return True
	console = ctypes.c_void_p(handle)  # a HANDLE is pointer-sized; ctypes passes a bare int as a 32-bit C int
	return bool(ctypes.windll.kernel32.GetConsoleMode(console, ctypes.byref(ctypes.c_ulong())))


def _dispatch(args: list[str]) -> tuple[int | None, str]:
	if args in (['--help'], ['-h'], ['help']):  # browser-harness's own help named its commands and flags, not ours
		print(HELP)
		return 0, 'help'
	if args and args[0] == '--update':  # browser-harness's self-update would update it, not browser-use
		print('browser-use does not update itself: uv tool upgrade browser-use (or pip install -U browser-use).', file=sys.stderr)
		return 2, 'update'
	if args in (['--version'], ['-V']):
		from importlib.metadata import version as package_version

		print(f'browser-use {_browser_use_version()} (browser-harness {package_version("browser-harness")})')
		return 0, 'version'
	from browser_use.utils import install_tls_opener  # after --version: importing it costs ~12 ms on macOS (proxy lookup)

	install_tls_opener()  # browser-harness's own requests here (cloud browsers, login) verify as the OS does
	if args and args[0] == 'install':
		return _run_install_command(args[1:]), 'install'
	if args and args[0] == 'init':
		return _run_init_command(args[1:]), 'init'
	if '--template' in args or '-t' in args:
		return _run_init_command(args), 'init'
	if args and args[0] == 'skill':
		from browser_use.skills.install import handle as handle_skill_command

		return handle_skill_command(args[1:]), 'skill'
	if args and args[0] == 'feedback':
		return _run_feedback_command(args[1:]), 'feedback'

	legacy = _legacy_command(args)
	if legacy is not None:
		print(_legacy_migration_message(legacy), file=sys.stderr)
		return 2, f'legacy:{legacy}'

	from browser_use.browser.browser import require_harness_dirs
	from browser_use.exceptions import BrowserConfigError

	try:  # every command below imports browser-harness
		require_harness_dirs()
	except BrowserConfigError as e:
		print(e, file=sys.stderr)
		if mcp := next((a for a in args if a in ('--cli-mcp', '--mcp')), None):
			_run_mcp_error_server(str(e))  # the agent reads it as the tool's error
			return 1, mcp.removeprefix('--')
		return 1, _command_name(args)
	if '--cli-mcp' in args:
		_run_cli_mcp_server()
		return 0, 'cli-mcp'
	if '--mcp' in args:
		return _run_mcp_server(), 'mcp'
	if args in (['--doctor'], ['doctor']):  # browser-harness's doctor: its name, its version, FAIL for a stopped daemon
		return _run_doctor(), 'doctor'
	if args[:1] in (['login'], ['logout']) or args[:2] in (['auth', 'login'], ['auth', 'logout']):
		# `auth login` is browser-harness's spelling (the skill teaches it): the same checks as `login`
		command, rest = (args[1], args[2:]) if args[0] == 'auth' else (args[0], args[1:])
		return (_run_login_command if command == 'login' else _run_logout_command)(rest), command

	if isinstance(sys.stdin, TextIOWrapper) and not sys.stdin.isatty():
		# Windows decoded a pipe with the ANSI code page (cp1252, cp932): piped 'Zürich' ran as 'ZÃ¼rich', or raised
		sys.stdin.reconfigure(encoding='utf-8-sig', errors='replace')  # -sig: PowerShell's UTF-8 starts with a BOM
	code = None
	if not args:
		if _stdin_is_terminal():
			print(_QUICKSTART.replace('{version}', _browser_use_version()))
			return 0, 'quickstart'
		code = sys.stdin.read()
		if not code.strip():
			print(_EMPTY_STDIN_MESSAGE, file=sys.stderr)
			return 1, 'run'
		sys.stdin = StringIO(code)

	from browser_harness.auth import CloudAuthRequired

	from browser_use.harness_cloud import CloudBrowserError

	try:
		return _run_browser_harness(code), args[0] if args else 'run'
	except CloudAuthRequired:  # its message names `browser-harness auth login`, not on PATH for `uv tool install browser-use`
		print('Not signed in to Browser Use Cloud. Run `browser-use login`, then retry.', file=sys.stderr)
		return 1, args[0] if args else 'run'
	except CloudBrowserError as e:
		print(e, file=sys.stderr)
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


if not TYPE_CHECKING:  # pyright would accept any name imported from here
	from browser_use.legacy import removed_names

	__getattr__ = removed_names(__name__)  # a 0.x name raises the removed error naming its 1.0 answer


if __name__ == '__main__':
	result = main()
	if result is not None:
		sys.exit(result)
