from __future__ import annotations

import ast
import asyncio
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from browser_use.integrations.anthropic.bash import run_bash
from browser_use.integrations.anthropic.tab_state import (
	consume_pinned_tabs,
	converged_active_tab,
)

ROOT = Path(__file__).parents[3]
DRIVER_PATH = ROOT / 'browser_use/integrations/anthropic/browser_use.py'
QUICKSTART_PATH = ROOT / 'examples/integrations/toolsets-for-claude/quickstart.py'


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
	env['PYTHONPATH'] = os.pathsep.join(filter(None, (str(ROOT), env.get('PYTHONPATH'))))
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
	from browser_use.integrations.toolsets_for_claude import Bash as ClaudeBash
	from browser_use.integrations.toolsets_for_claude import BrowserUse as ClaudeBrowserUse

	assert ClaudeBash is Bash
	assert ClaudeBrowserUse is BrowserUse
	browser = BrowserUse()
	bash = Bash(output_dir='outputs')
	configs = browser.to_dict().get('configs') or {}
	file_upload = configs.get('file_upload') or {}
	assert file_upload.get('enabled') is False
	assert bash.to_dict()['name'] == 'bash'


def test_browser_use_can_own_a_cloud_browser() -> None:
	pytest.importorskip('anthropic.tools.browser')
	from browser_use.integrations.anthropic import BrowserUse

	browser = BrowserUse(use_cloud=True)
	assert browser._manages_browser is True
	assert browser.browser.browser_profile.use_cloud is True


def test_browser_use_rejects_a_borrowed_browser_with_cloud_selection() -> None:
	pytest.importorskip('anthropic.tools.browser')
	from browser_use import BrowserSession
	from browser_use.integrations.anthropic import BrowserUse

	with pytest.raises(ValueError, match='either a BrowserSession or use_cloud=True'):
		BrowserUse(BrowserSession(), use_cloud=True)


async def test_reference_document_identity_survives_cdp_session_rotation() -> None:
	pytest.importorskip('anthropic.tools.browser')
	from browser_use.integrations.anthropic import BrowserUse

	class FakeCDP:
		def __init__(self):
			self.send = SimpleNamespace(DOM=SimpleNamespace(getDocument=self.get_document))

		async def get_document(self, **kwargs):
			return {'root': {'backendNodeId': 999}}

	class FakePage:
		_target_id = 'tab-a'

		@property
		async def session_id(self):
			return 'rotating-session'

	driver = BrowserUse()
	driver.browser = cast(Any, SimpleNamespace(cdp_client=FakeCDP()))
	page = FakePage()
	document = await driver._document(page)
	ref = driver._reference(page, document, 42)
	assert ref in driver._refs

	assert await driver._document(page) == document
	assert ref in driver._refs

	driver._invalidate_refs('tab-a')
	assert await driver._document(page) != document
	assert ref not in driver._refs


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
	resolved_tmp_path = await asyncio.to_thread(tmp_path.resolve)
	result = json.loads(
		await run_bash(
			'printf "%s\\n%s\\n" "$HOME" "${ANTHROPIC_API_KEY-unset}"; pwd; printf ok > result.txt',
			output_dir=tmp_path,
		)
	)
	lines = result['output'].splitlines()
	assert lines == [str(resolved_tmp_path), 'unset', str(resolved_tmp_path)]
	assert await asyncio.to_thread((tmp_path / 'result.txt').read_text) == 'ok'
	assert result['exit_code'] == 0
	assert result['timed_out'] is False


async def test_bash_bounds_output_and_kills_on_timeout(tmp_path: Path) -> None:
	truncated = json.loads(await run_bash('yes x | head -c 10000', output_dir=tmp_path, max_output_bytes=100))
	assert len(truncated['output'].encode()) == 100
	assert truncated['truncated'] is True

	timed_out = json.loads(await run_bash('sleep 10', output_dir=tmp_path, timeout_seconds=0.05))
	assert timed_out['timed_out'] is True
	assert timed_out['exit_code'] < 0


async def test_bash_deadline_closes_inherited_output_pipes(tmp_path: Path) -> None:
	# setsid escapes the shell's process group while retaining stdout.
	import shlex
	import signal

	pid_path = tmp_path / 'descendant.pid'
	child = "import os,time; os.setsid(); open('descendant.pid','w').write(str(os.getpid())); print('started',flush=True); time.sleep(10)"
	command = f'{shlex.quote(sys.executable)} -c {shlex.quote(child)} & wait'
	try:
		result = json.loads(await asyncio.wait_for(run_bash(command, output_dir=tmp_path, timeout_seconds=1), timeout=3))
		assert result['timed_out'] is True
		assert 'started' in result['output']
	finally:
		if pid_path.exists():
			try:
				os.kill(int(pid_path.read_text()), signal.SIGKILL)
			except ProcessLookupError:
				pass


async def test_bash_cancellation_closes_inherited_output_pipes(tmp_path: Path, monkeypatch) -> None:
	import shlex
	import signal

	import browser_use.integrations.anthropic.bash as bash_module

	started = asyncio.Event()
	original = bash_module._BashOutput.pipe_data_received

	def observe_output(protocol, fd, data):
		original(protocol, fd, data)
		if b'started' in protocol.output:
			started.set()

	monkeypatch.setattr(bash_module._BashOutput, 'pipe_data_received', observe_output)
	pid_path = tmp_path / 'descendant.pid'
	child = "import os,time; os.setsid(); open('descendant.pid','w').write(str(os.getpid())); print('started',flush=True); time.sleep(10)"
	task = asyncio.create_task(run_bash(f'{shlex.quote(sys.executable)} -c {shlex.quote(child)} & wait', output_dir=tmp_path))
	try:
		await asyncio.wait_for(started.wait(), timeout=2)
		task.cancel()
		with pytest.raises(asyncio.CancelledError):
			await asyncio.wait_for(task, timeout=2)
	finally:
		if pid_path.exists():
			try:
				os.kill(int(pid_path.read_text()), signal.SIGKILL)
			except ProcessLookupError:
				pass
		if not task.done():
			task.cancel()


def test_quickstart_uses_peer_browser_use_and_bash_tools() -> None:
	source = QUICKSTART_PATH.read_text()
	tree = ast.parse(source)
	assert tree is not None
	driver = next(
		node
		for node in ast.walk(tree)
		if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'BrowserUse'
	)
	configs = ast.literal_eval(next(option.value for option in driver.keywords if option.arg == 'configs'))
	for action in ('javascript_exec', 'file_upload', 'read_console', 'read_network'):
		assert configs[action]['enabled'] is True
	confirmation = next(option.value for option in driver.keywords if option.arg == 'confirm')
	assert isinstance(confirmation, ast.Lambda)
	assert isinstance(confirmation.body, ast.Constant) and confirmation.body.value is True
	assert not any(
		isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'input' for node in ast.walk(tree)
	)
	assert "bash = Bash(output_dir=Path('outputs'))" in source
	assert 'tools=[driver, bash]' in source
	assert 'ActorUse' not in source
	assert 'owns_browser' not in source
	assert 'until_done()' in source
