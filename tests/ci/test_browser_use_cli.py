import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _run_browser_use_cli(
	*args: str,
	module: str = 'browser_use.cli',
	env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
	env = os.environ.copy()
	env['PYTHONPATH'] = os.pathsep.join(part for part in (str(ROOT), env.get('PYTHONPATH', '')) if part)
	if env_overrides:
		env.update(env_overrides)
	return subprocess.run(
		[sys.executable, '-m', module, *args],
		cwd=ROOT,
		env=env,
		capture_output=True,
		text=True,
		timeout=20,
	)


def test_browser_use_doctor_help_prints_browser_use_usage():
	result = _run_browser_use_cli('doctor', '--help')

	assert result.returncode == 0
	assert result.stdout == 'usage: browser-use doctor [--fix-snap]\n'
	assert result.stderr == ''


def test_browser_use_module_entrypoint_matches_cli_entrypoint():
	cli_result = _run_browser_use_cli('doctor', '--help')
	module_result = _run_browser_use_cli('doctor', '--help', module='browser_use')

	assert module_result.returncode == cli_result.returncode == 0
	assert module_result.stdout == cli_result.stdout
	assert module_result.stderr == cli_result.stderr == ''


def test_normalize_captured_cli_output_handles_string_system_exit(capsys):
	from browser_use.cli import _normalize_captured_cli_output

	def exits_with_string(_argv):
		raise SystemExit('browser-harness failed')

	assert _normalize_captured_cli_output(exits_with_string, []) == 1
	captured = capsys.readouterr()
	assert captured.out == ''
	assert captured.err == 'browser-use failed\n'


def test_browser_use_tui_is_deprecated_alias(monkeypatch, capsys):
	import browser_use.cli as browser_use_cli

	monkeypatch.setattr(browser_use_cli, 'main', lambda: 0)

	assert browser_use_cli.browser_use_tui_main() == 0
	assert capsys.readouterr().err == 'browser-use-tui is deprecated; use browser-use instead.\n'


def test_orcarouter_cli_help_is_available() -> None:
	result = _run_browser_use_cli('orcarouter', '--help')

	assert result.returncode == 0
	assert 'login' in result.stdout
	assert 'status' in result.stdout
	assert 'logout' in result.stdout
	assert result.stderr == ''


def test_main_cli_help_mentions_orcarouter_login() -> None:
	result = _run_browser_use_cli('--help')

	assert result.returncode == 0
	assert 'browser-use orcarouter login' in result.stdout


def test_orcarouter_status_and_logout_never_print_the_stored_key(tmp_path: Path) -> None:
	from browser_use.llm.orcarouter.auth import OrcaRouterCredentialStore

	key = 'sk-orca-' + ('a' * 48)
	store = OrcaRouterCredentialStore(tmp_path / 'config.json')
	store.save(key=key, user_id='user-123')
	env = {'BROWSER_USE_CONFIG_DIR': str(tmp_path)}

	status_result = _run_browser_use_cli('orcarouter', 'status', env_overrides=env)
	assert status_result.returncode == 0
	assert 'connected' in status_result.stdout.lower()
	assert key not in status_result.stdout + status_result.stderr

	logout_result = _run_browser_use_cli('orcarouter', 'logout', env_overrides=env)
	assert logout_result.returncode == 0
	assert key not in logout_result.stdout + logout_result.stderr
	assert store.load() is None
