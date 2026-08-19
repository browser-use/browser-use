import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]


def _run_browser_use_cli(*args: str) -> subprocess.CompletedProcess[str]:
	env = os.environ.copy()
	env['PYTHONPATH'] = os.pathsep.join(part for part in (str(ROOT), env.get('PYTHONPATH', '')) if part)
	return subprocess.run(
		[sys.executable, '-m', 'browser_use.cli', *args],
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


def test_normalize_captured_cli_output_handles_string_system_exit(capsys):
	from browser_use.cli import _normalize_captured_cli_output

	def exits_with_string(_argv):
		raise SystemExit('browser-harness failed')

	assert _normalize_captured_cli_output(exits_with_string, []) == 1
	captured = capsys.readouterr()
	assert captured.out == ''
	assert captured.err == 'browser-use failed\n'


def test_page_info_with_tab_context_infers_current_tab():
	from browser_use.cli import _page_info_with_tab_context

	tabs = [
		{'target_id': 'tab-1', 'url': 'https://example.com/old', 'title': 'Old tab'},
		{'target_id': 'tab-2', 'url': 'https://example.com/new', 'title': 'New tab'},
	]

	page_info = _page_info_with_tab_context(
		{'url': 'https://example.com/new', 'title': 'New tab', 'w': 1280, 'h': 720},
		tabs=tabs,
		current_tab=None,
	)

	assert page_info['tab_count'] == 2
	assert page_info['tabs'] == tabs
	assert page_info['current_tab'] == tabs[1]


def test_patch_browser_harness_page_info_adds_tabs_and_is_idempotent():
	import browser_use.cli as browser_use_cli

	tabs = [
		{'target_id': 'tab-1', 'url': 'https://example.com/old', 'title': 'Old tab'},
		{'target_id': 'tab-2', 'url': 'https://example.com/new', 'title': 'New tab'},
	]
	run = SimpleNamespace(
		page_info=lambda: {'url': 'https://example.com/new', 'title': 'New tab'},
		list_tabs=lambda: tabs,
		current_tab=lambda: tabs[1],
	)

	browser_use_cli._patch_browser_harness_page_info(run)
	patched_page_info = run.page_info
	browser_use_cli._patch_browser_harness_page_info(run)

	assert run.page_info is patched_page_info
	assert run.page_info() == {
		'url': 'https://example.com/new',
		'title': 'New tab',
		'tabs': tabs,
		'tab_count': 2,
		'current_tab': tabs[1],
	}


def test_patch_browser_harness_page_info_preserves_state_when_tab_queries_fail():
	import browser_use.cli as browser_use_cli

	def fail():
		raise RuntimeError('browser disconnected')

	run = SimpleNamespace(
		page_info=lambda: {'url': 'https://example.com', 'title': 'Example'},
		list_tabs=fail,
		current_tab=fail,
	)

	browser_use_cli._patch_browser_harness_page_info(run)

	assert run.page_info() == {'url': 'https://example.com', 'title': 'Example'}


def test_browser_use_tui_is_deprecated_alias(monkeypatch, capsys):
	import browser_use.cli as browser_use_cli

	monkeypatch.setattr(browser_use_cli, 'main', lambda: 0)

	assert browser_use_cli.browser_use_tui_main() == 0
	assert capsys.readouterr().err == 'browser-use-tui is deprecated; use browser-use instead.\n'
