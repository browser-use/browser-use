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
		assert 'hunter2' not in Path(r['output_file']).read_text()  # the captured output file in the workspace too
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


async def test_cancelled_call_resets_the_worker(tmp_path):
	"""Roast C5: a whole-run timeout cancelled the call but left its cell running; the next call got its stale answer."""
	repl = Repl(tmp_path)
	try:
		await repl.call('exec', 'pass', 30)
		with pytest.raises(TimeoutError):
			await asyncio.wait_for(repl.call('exec', 'import time\ntime.sleep(2)\nprint("stale")', 30), 0.5)
		await asyncio.sleep(2.5)  # the old cell would have answered by now
		assert (await repl.call('exec', 'print("fresh")', 30))['output'].strip() == 'fresh'
	finally:
		await repl.close()


async def test_reset_kills_the_cells_subprocesses(tmp_path):
	"""Roast C11: a timeout killed only the worker; a subprocess the cell started kept running (and driving the browser)."""
	marker = tmp_path / 'child-survived'
	code = (
		'import subprocess, sys, time\n'
		f'subprocess.Popen([sys.executable, "-c", "import time; time.sleep(3); open({str(marker)!r}, \\"w\\").close()"])\n'
		'time.sleep(30)'
	)
	repl = Repl(tmp_path)
	try:
		assert 'timed out' in (await repl.call('exec', code, 1))['error']
	finally:
		await repl.close()
	await asyncio.sleep(4)
	assert not marker.exists()


async def test_harness_dotenv_cannot_reintroduce_credentials(tmp_path, monkeypatch):
	"""Roast C7: browser-harness loads its workspace .env on import; DATABASE_URL-style credentials came back."""
	harness_ws = tmp_path / 'harness-ws'
	harness_ws.mkdir()
	(harness_ws / '.env').write_text('DATABASE_URL=postgres://u:planted-fake-value@db/x\n', encoding='utf-8')
	monkeypatch.setenv('BH_AGENT_WORKSPACE', str(harness_ws))
	repl = Repl(tmp_path / 'ws')
	try:
		r = await repl.call('exec', 'import os, browser_harness.helpers\nprint(sorted(os.environ))', 30)
	finally:
		await repl.close()
	assert r['error'] is None and 'DATABASE_URL' not in r['output'] and 'BH_AGENT_WORKSPACE' in r['output']


def test_worker_env_keeps_proxy_and_ca_settings(monkeypatch):
	for name in ('HTTPS_PROXY', 'no_proxy', 'SSL_CERT_FILE', 'REQUESTS_CA_BUNDLE', 'CURL_CA_BUNDLE'):
		monkeypatch.setenv(name, 'x')
	assert {'HTTPS_PROXY', 'no_proxy', 'SSL_CERT_FILE', 'REQUESTS_CA_BUNDLE', 'CURL_CA_BUNDLE'} <= set(worker_env())


async def test_cells_print_unicode_whatever_the_parent_locale(tmp_path, monkeypatch):
	"""Roast C17: on Windows (cp1252) a cell printing page text like CJK or emoji raised UnicodeEncodeError."""
	monkeypatch.setenv('PYTHONIOENCODING', 'ascii')  # stands in for a cp1252 console
	monkeypatch.setenv('PYTHONUTF8', '0')
	repl = Repl(tmp_path)
	try:
		r = await repl.call(
			'exec', "print('日本語 🙂')\nimport subprocess, sys\nsubprocess.run([sys.executable, '-c', 'print(\"é\")'])", 30
		)
	finally:
		await repl.close()
	assert r['error'] is None and '日本語 🙂' in r['output'] and 'é' in r['output']


async def test_interrupted_cell_never_writes_a_secret_to_disk(tmp_path):
	"""Roast C8: output reached the workspace file before redaction; a killed cell left the plaintext there."""
	repl = Repl(tmp_path, secrets={'pw': 'hunter2-Zq9'})
	try:
		code = (
			'v = [c.cell_contents for c in type_secret.__closure__ if isinstance(c.cell_contents, dict)][0]\n'
			"print('got', v['pw'], flush=True)\nimport time\ntime.sleep(30)"
		)
		r = await repl.call('exec', code, 2)
	finally:
		await repl.close()
	assert 'timed out' in r['error']
	text = Path(r['output_file']).read_text(encoding='utf-8')
	assert 'got <secret:pw>' in text and 'hunter2' not in text


async def test_common_encodings_of_a_secret_are_redacted(tmp_path):
	"""Fable: btoa(value), value[::-1], hex and URL-encoding walked the value past plain-text redaction."""
	repl = Repl(tmp_path, secrets={'pw': 'hunter2 Zq9/'})
	try:
		code = (
			'import base64, urllib.parse\n'
			'v = [c.cell_contents for c in type_secret.__closure__ if isinstance(c.cell_contents, dict)][0]["pw"]\n'
			'print(base64.b64encode(v.encode()).decode(), v[::-1], v.encode().hex(), urllib.parse.quote(v, safe=""))'
		)
		r = await repl.call('exec', code, 30)
	finally:
		await repl.close()
	assert r['output'].split() == ['<secret:pw>'] * 4


async def test_checkpoints_and_partial_results_are_redacted(tmp_path):
	"""Roast C13: checkpointed data holding a secret was saved raw and returned through .partial / timeout text."""
	from browser_use.agent.loop import Session

	repl = Repl(tmp_path, secrets={'pw': 'hunter2-Zq9'})
	try:
		code = (
			'v = [c.cell_contents for c in type_secret.__closure__ if isinstance(c.cell_contents, dict)][0]\n'
			"checkpoint('rows.json', [{'note': 'pw is ' + v['pw']}], partial=True)"
		)
		assert (await repl.call('exec', code, 30))['error'] is None
	finally:
		await repl.close()
	for f in (tmp_path / 'rows.json', repl.state / 'partial.json'):
		assert 'hunter2' not in f.read_text(encoding='utf-8') and '<secret:pw>' in f.read_text(encoding='utf-8')
	assert Session(repl=repl).partial() == [{'note': 'pw is <secret:pw>'}]


def test_corrupt_partial_json_is_ignored(tmp_path):
	"""Roast C12: a partial.json truncated by a kill made the timeout path raise instead of returning."""
	from browser_use.agent.loop import Session

	repl = Repl(tmp_path)
	repl.state.mkdir(parents=True)
	(repl.state / 'partial.json').write_text('{"file": "rows.json", "val', encoding='utf-8')
	assert Session(repl=repl).partial() is None


async def test_worker_cuts_huge_output_before_sending(tmp_path):
	"""Fable: the worker sent a cell's whole output over the channel; past 256 MB the read failed the run."""
	repl = Repl(tmp_path)
	try:
		r = await repl.call('exec', "print('x' * 50_000)", 30)
	finally:
		await repl.close()
	assert len(r['output']) < 13_000 and 'Truncated. Full captured output' in r['output']
	assert len(Path(r['output_file']).read_text(encoding='utf-8')) > 50_000
