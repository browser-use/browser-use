from __future__ import annotations

import ast
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from browser_use.integrations.anthropic.bash import run_bash
from browser_use.integrations.anthropic.tab_state import (
	consume_pinned_tabs,
	converged_active_tab,
)

ROOT = Path(__file__).parents[3]
DRIVER_PATH = ROOT / 'browser_use/integrations/anthropic/browser_use.py'
QUICKSTART_PATH = ROOT / 'examples/integrations/anthropic/quickstart.py'


def test_browser_use_implements_all_31_browser_actions() -> None:
	expected = {
		'navigate',
		'screenshot',
		'zoom',
		'left_click',
		'right_click',
		'middle_click',
		'double_click',
		'triple_click',
		'hover',
		'mouse_move',
		'left_mouse_down',
		'left_mouse_up',
		'left_click_drag',
		'scroll',
		'scroll_to',
		'type',
		'key',
		'hold_key',
		'form_input',
		'read_page',
		'find',
		'get_page_text',
		'wait',
		'file_upload',
		'read_console',
		'read_network',
		'javascript_exec',
		'new_tab',
		'list_tabs',
		'switch_tab',
		'close_tab',
	}
	tree = ast.parse(DRIVER_PATH.read_text())
	toolset = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'BrowserUse')
	implemented = {
		node.name for node in toolset.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in expected
	}
	assert len(expected) == 31
	assert implemented == expected


def test_missing_browser_toolset_sdk_has_an_actionable_error() -> None:
	try:
		sdk_available = importlib.util.find_spec('anthropic.tools.browser') is not None
	except ModuleNotFoundError:
		sdk_available = False
	if sdk_available:
		pytest.skip('The installed Anthropic SDK already includes browser tools.')
	env = os.environ.copy()
	env['PYTHONPATH'] = str(ROOT)
	result = subprocess.run(
		[
			sys.executable,
			'-c',
			'from browser_use.integrations.anthropic import BrowserUse',
		],
		env=env,
		text=True,
		capture_output=True,
	)
	assert result.returncode != 0
	assert 'requires an Anthropic Python SDK release' in result.stderr


def test_browser_use_and_bash_construct_with_a_compatible_sdk() -> None:
	pytest.importorskip('anthropic.tools.browser')
	from browser_use.integrations.anthropic import Bash, BrowserUse

	browser = BrowserUse()
	bash = Bash(output_dir='outputs')
	configs = browser.to_dict().get('configs') or {}
	file_upload = configs.get('file_upload') or {}
	assert file_upload.get('enabled') is False
	assert bash.to_dict()['name'] == 'bash'


def _tabs(active: str) -> list[dict]:
	return [
		{'tab_id': 'tab-a', 'url': 'https://a.example', 'title': 'A', 'active': active == 'tab-a'},
		{'tab_id': 'tab-b', 'url': 'about:blank', 'title': '', 'active': active == 'tab-b'},
	]


def test_tab_result_and_browser_state_share_a_stable_snapshot() -> None:
	context = object()
	current = _tabs('tab-b')
	result = converged_active_tab(context, current, 'tab-b', 'tab-b')
	assert result is not None
	opened, snapshot = result
	current[1]['tab_id'] = 'changed'
	assert opened['tab_id'] == 'tab-b'
	assert consume_pinned_tabs(snapshot, context) == _tabs('tab-b')


async def test_bash_strips_environment_and_writes_in_output_dir(tmp_path: Path, monkeypatch) -> None:
	monkeypatch.setenv('ANTHROPIC_API_KEY', 'must-not-leak')
	result = json.loads(
		await run_bash(
			'printf "%s\\n%s\\n" "$HOME" "${ANTHROPIC_API_KEY-unset}"; pwd; printf ok > result.txt',
			output_dir=tmp_path,
		)
	)
	lines = result['output'].splitlines()
	assert lines == [str(tmp_path.resolve()), 'unset', str(tmp_path.resolve())]
	assert (tmp_path / 'result.txt').read_text() == 'ok'
	assert result['exit_code'] == 0
	assert result['timed_out'] is False


async def test_bash_bounds_output_and_kills_on_timeout(tmp_path: Path) -> None:
	truncated = json.loads(await run_bash('yes x | head -c 10000', output_dir=tmp_path, max_output_bytes=100))
	assert len(truncated['output'].encode()) == 100
	assert truncated['truncated'] is True

	timed_out = json.loads(await run_bash('sleep 10', output_dir=tmp_path, timeout_seconds=0.05))
	assert timed_out['timed_out'] is True
	assert timed_out['exit_code'] < 0


def test_quickstart_uses_peer_browser_use_and_bash_tools() -> None:
	source = QUICKSTART_PATH.read_text()
	tree = ast.parse(source)
	assert tree is not None
	assert 'browser = BrowserUse()' in source
	assert "bash = Bash(output_dir=Path('outputs'))" in source
	assert 'tools=[browser, bash]' in source
	assert 'ActorUse' not in source
	assert 'owns_browser' not in source
	assert 'until_done()' in source
