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


def _first_env_value(names: tuple[str, ...]) -> str | None:
	import os

	for name in names:
		value = os.environ.get(name)
		if value:
			return value
	return None


def _detect_agent_client() -> str | None:
	return _first_env_value(('BROWSER_USE_AGENT_CLIENT',))


def _detect_model() -> tuple[str | None, str | None]:
	return _first_env_value(('BROWSER_USE_AGENT_MODEL',)), _first_env_value(('BROWSER_USE_MODEL_PROVIDER',))


def _redacted_task(task: str | None) -> str | None:
	if task is None:
		return None
	return '[redacted]'


def _capture_cli_event(
	*,
	action: str,
	mode: str,
	command: str,
	start_time: float,
	task: str | None = None,
	result: int | str | None = None,
	error_message: str | None = None,
) -> None:
	try:
		import logging

		from browser_use.telemetry import CLITelemetryEvent, ProductTelemetry

		model, model_provider = _detect_model()
		telemetry_logger = logging.getLogger('browser_use.telemetry.service')
		telemetry_logger_disabled = telemetry_logger.disabled
		telemetry_logger.disabled = True
		try:
			telemetry = ProductTelemetry()
			telemetry.capture(
				CLITelemetryEvent(
					version=_browser_use_version(),
					action=action,
					mode=mode,
					command=command,
					task=_redacted_task(task),
					task_length=len(task) if task is not None else None,
					agent_client=_detect_agent_client(),
					model=model,
					model_provider=model_provider,
					duration_seconds=time.monotonic() - start_time,
					exit_code=_exit_code(result),
					error_message=error_message,
				)
			)
			telemetry.flush()
		finally:
			telemetry_logger.disabled = telemetry_logger_disabled
	except Exception:
		pass


def _run_mcp_server() -> None:
	import asyncio
	import logging
	import os

	os.environ['BROWSER_USE_LOGGING_LEVEL'] = 'critical'
	os.environ['BROWSER_USE_SETUP_LOGGING'] = 'false'
	logging.disable(logging.CRITICAL)

	from browser_use.mcp.server import main as mcp_main

	asyncio.run(mcp_main())


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


def _run_init_command(argv: list[str]) -> int | None:
	from browser_use.init_cmd import main as init_main

	original_argv = sys.argv
	try:
		sys.argv = [original_argv[0], *argv]
		init_main()
	except SystemExit as exc:
		if exc.code is None:
			return 0
		if isinstance(exc.code, int):
			return exc.code
		print(exc.code, file=sys.stderr)
		return 1
	finally:
		sys.argv = original_argv
	return 0


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


def _run_browser_harness() -> int | None:
	import os

	from browser_harness import run

	os.environ['BH_CLIENT'] = 'browser-use-cli'
	_patch_browser_harness_cli_text()
	args = sys.argv[1:]
	if args and args[0] == 'doctor' and args[1:]:
		if args[1:] in (['--help'], ['-h']):
			print('usage: browser-use doctor [--fix-snap]')
			return 0
		if args[1:] != ['--fix-snap']:
			print('usage: browser-use doctor [--fix-snap]', file=sys.stderr)
			sys.exit(2)
	run.main()
	return None


def _read_harness_task(args: list[str]) -> str | None:
	for flag in ('-c', '--code'):
		if flag in args:
			index = args.index(flag)
			if index + 1 < len(args):
				return args[index + 1]
	if args or sys.stdin.isatty():
		return None
	code = sys.stdin.read()
	sys.stdin = StringIO(code)
	return code


def _command_context(args: list[str]) -> tuple[str, str]:
	if '--mcp' in args:
		return 'mcp_server', 'mcp'
	if args and args[0] == 'install':
		return 'install', 'install'
	if args and args[0] == 'init':
		return 'init', 'init'
	if '--template' in args or '-t' in args:
		return 'init', 'init'
	if args and args[0] == 'skill':
		return 'skill', 'skill'
	return 'browser_harness', args[0] if args else 'run'


def _dispatch(args: list[str]) -> tuple[int | None, str, str, str | None]:
	if '--mcp' in args:
		_run_mcp_server()
		return 0, 'mcp_server', 'mcp', None
	if args and args[0] == 'install':
		return _run_install_command(args[1:]), 'install', 'install', None
	if args and args[0] == 'init':
		return _run_init_command(args[1:]), 'init', 'init', None
	if '--template' in args or '-t' in args:
		return _run_init_command(args), 'init', 'init', None
	if args and args[0] == 'skill':
		from browser_use.skills.install import handle as handle_skill_command

		return handle_skill_command(args[1:]), 'skill', 'skill', None

	task = _read_harness_task(args)
	return _run_browser_harness(), 'browser_harness', args[0] if args else 'run', task


def browser_use_tui_main() -> int | None:
	print('browser-use-tui is deprecated; use browser-use instead.', file=sys.stderr)
	return main()


def main() -> int | None:
	args = sys.argv[1:]
	start_time = time.monotonic()
	mode, command = _command_context(args)
	task = None
	try:
		result, mode, command, task = _dispatch(args)
	except SystemExit as exc:
		result = exc.code
		_capture_cli_event(
			action='error' if _exit_code(result) else 'completed',
			mode=mode,
			command=command,
			start_time=start_time,
			task=task,
			result=result,
			error_message=str(result) if isinstance(result, str) else None,
		)
		raise
	except Exception as exc:
		_capture_cli_event(
			action='error',
			mode=mode,
			command=command,
			start_time=start_time,
			task=task,
			result=1,
			error_message=str(exc),
		)
		raise

	_capture_cli_event(
		action='error' if _exit_code(result) else 'completed',
		mode=mode,
		command=command,
		start_time=start_time,
		task=task,
		result=result,
	)
	return result


if __name__ == '__main__':
	result = main()
	if result is not None:
		sys.exit(result)
