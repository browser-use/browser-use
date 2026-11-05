"""REPL worker transport, env allowlist and secret redaction. No browser needed (runs on Windows/macOS/Linux)."""

import ast
import asyncio
from pathlib import Path

import pytest

import browser_use
from browser_use.repl import Repl, redact, worker_env

PACKAGE = Path(browser_use.__file__).parent


async def test_worker_runs_cells_over_loopback(tmp_path):
	repl = Repl(tmp_path)
	try:
		r = await repl.call('exec', 'x = 20\nx + 1', 30)
		assert (r['output'].strip(), r['error']) == ('21', None)
		r = await repl.call('eval', 'x * 2', 30)
		assert r['value'] == '40'
	finally:
		await repl.close()


async def test_worker_is_spawned_without_pass_fds(tmp_path, monkeypatch):
	calls = []
	real = asyncio.create_subprocess_exec

	async def spy(*args, **kwargs):
		calls.append(kwargs)
		return await real(*args, **kwargs)

	monkeypatch.setattr(asyncio, 'create_subprocess_exec', spy)
	repl = Repl(tmp_path)
	try:
		assert (await repl.call('exec', 'print("hi")', 30))['output'].strip() == 'hi'
	finally:
		await repl.close()
	assert calls and all('pass_fds' not in kw for kw in calls)


def test_no_pass_fds_or_socketpair_anywhere_in_the_package():
	"""POSIX-only fd passing broke Windows (P0). Look at real code, not comments."""
	for path in PACKAGE.rglob('*.py'):
		names = {n.attr if isinstance(n, ast.Attribute) else n.arg if isinstance(n, ast.keyword) else getattr(n, 'id', None)
				 for n in ast.walk(ast.parse(path.read_text(encoding='utf-8')))}  # fmt: skip
		assert not {'pass_fds', 'socketpair'} & names, path


async def test_worker_after_timeout_restarts(tmp_path):
	repl = Repl(tmp_path)
	try:
		r = await repl.call('exec', 'import time\nprint("started", flush=True)\ntime.sleep(30)', 2)
		assert 'timed out' in r['error'] and 'started' in r['output']
		assert (await repl.call('exec', 'print(1 + 1)', 30))['output'].strip() == '2'
	finally:
		await repl.close()


async def test_worker_env_has_no_credentials(tmp_path, monkeypatch):
	monkeypatch.setenv('FAKE_API_KEY', 'planted-fake-value-1')
	monkeypatch.setenv('OPENAI_API_KEY', 'planted-fake-value-2')
	monkeypatch.setenv('BROWSER_USE_API_KEY', 'planted-fake-value-3')
	monkeypatch.setenv('GITHUB_TOKEN', 'planted-fake-value-4')
	monkeypatch.setenv('BU_CDP_WS', 'ws://example.invalid/?token=planted-fake-value-5')
	monkeypatch.setenv('BH_RUNTIME_DIR_SHARED', '0')
	repl = Repl(tmp_path)
	try:
		r = await repl.call('exec', 'import os\nprint(sorted(os.environ.items()))', 30)
	finally:
		await repl.close()
	assert r['error'] is None
	assert 'planted-fake-value' not in r['output']
	assert 'BH_RUNTIME_DIR_SHARED' in r['output'] and "'PATH'" in r['output']  # what the harness needs survives


def test_worker_env_allowlist():
	env = worker_env({'BU_NAME': 'x'})
	assert env['BU_NAME'] == 'x'
	assert not [k for k in env if any(s in k.upper() for s in ('KEY', 'TOKEN', 'SECRET', 'PASSW'))]


async def test_secret_values_are_redacted_from_everything_returned(tmp_path):
	repl = Repl(tmp_path, secrets={'pw': 'hunter2-Zq9', 'pin': '4711'})
	try:
		# A prompt-injected cell digging the value out of type_secret's closure still only shows the placeholder.
		code = (
			'v = [c.cell_contents for c in type_secret.__closure__ if isinstance(c.cell_contents, dict)][0]\n'
			"print('leak', v['pw'], v['pin'], secret_names())\n"
			"raise ValueError(v['pw'])"
		)
		r = await repl.call('exec', code, 30)
		assert "leak <secret:pw> <secret:pin> ['pin', 'pw']" in r['output']
		assert 'ValueError: <secret:pw>' in r['error'] and 'hunter2' not in r['error']
		assert (await repl.call('eval', "v['pw']", 30))['value'] == '<secret:pw>'
		assert 'KeyError' in (await repl.call('exec', "type_secret('nope')", 30))['error']
	finally:
		await repl.close()


def test_redact_longest_first():
	assert redact('abcdef abc', {'short': 'abc', 'long': 'abcdef'}) == '<secret:long> <secret:short>'
	assert redact(None, {'a': 'b'}) is None


@pytest.mark.parametrize('mode', ['bad'])
def test_bad_mode_raises(tmp_path, mode):
	with pytest.raises(ValueError):
		Repl(tmp_path, mode=mode)
