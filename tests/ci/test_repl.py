"""REPL worker transport, env allowlist and secret redaction. No browser needed (runs on Windows/macOS/Linux)."""

import ast
import asyncio
import gc
import os
import sys
import time
from pathlib import Path

import pytest

import browser_use
from browser_use.repl import Repl, redact, worker_env

PACKAGE = Path(browser_use.__file__).parent
# A prompt-injected cell digging the values out of type_secret's closure.
DIG = (  # helpers are wrapped for telemetry counts (worker._counted); an injected cell can unwrap them too
	'import inspect\nv = {n: x for n, x, _ in [c.cell_contents for c in inspect.unwrap(type_secret).__closure__ '
	'if isinstance(c.cell_contents, list)][0]}\n'
)


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
	import subprocess

	calls = []
	real = subprocess.Popen

	def spy(*args, **kwargs):
		calls.append(kwargs)
		return real(*args, **kwargs)

	monkeypatch.setattr(subprocess, 'Popen', spy)
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


@pytest.mark.skipif(sys.platform == 'win32', reason='counts open file descriptors in /dev/fd')
async def test_close_and_a_timeout_restart_release_the_worker_socket(tmp_path):
	"""live/scale: close() left this process's end of the worker connection open (CLOSE_WAIT) until a garbage
	collection freed it: 20 concurrent Agents left 20 sockets, and every cell timeout restart one more."""
	gc.disable()  # a collection would free the socket and hide the leak
	try:
		before = len(os.listdir('/dev/fd'))
		repl = Repl(tmp_path)
		r = await repl.call('exec', 'import time\ntime.sleep(30)', 1)
		assert r['error_type'] == 'CellTimeout'  # the restart closes the first worker
		assert (await repl.call('exec', 'print(2)', 30))['output'].strip() == '2'
		await repl.close()
		for _ in range(3):  # the transport closes its socket on a later loop iteration
			await asyncio.sleep(0)
		assert len(os.listdir('/dev/fd')) == before
	finally:
		gc.enable()


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


async def test_a_browser_harness_call_from_a_cell_fails_closed(tmp_path):
	"""Night swarm 11-07: after the local browser died, a model called browser_harness.admin.ensure_daemon(), which
	found no BU_CDP_WS, discovered the user's own Chrome and raised its "Allow remote debugging?" sheet. A daemon or
	CLI a cell starts now dials a dead port (and the CLI only reuses this run's daemon) instead of discovering a
	local Chrome. A determined model can still undo this (same user); the agent ends cells once the browser is gone."""
	repl = Repl(tmp_path)
	try:
		r = await repl.call('exec', 'import os\nprint(os.environ["BH_REQUIRE_EXISTING_DAEMON"], os.environ["BU_CDP_WS"])', 30)
	finally:
		await repl.close()
	assert r['error'] is None and '1 ws://127.0.0.1:9/' in r['output'], r


def test_trust_model_says_the_worker_can_still_reach_the_parents_keys():
	"""H3: model code read every provider key through the parent's environment (ps -E -p $PPID) and its .env while the
	trust model said keys "never reach" the worker. Same-user processes cannot be walled off here: the docs say so."""
	trust = (Path(__file__).resolve().parents[2] / 'MIGRATING.md').read_text(encoding='utf-8').split('## Trust model')[1]
	assert 'never reach it' not in trust
	assert 'ps -E -p <pid>' in trust and '/proc/<pid>/environ' in trust and '`.env`' in trust


def test_worker_env_allowlist():
	env = worker_env({'BU_NAME': 'x'})
	assert env['BU_NAME'] == 'x'
	assert not [k for k in env if any(s in k.upper() for s in ('KEY', 'TOKEN', 'SECRET', 'PASSW'))]


async def test_secret_values_are_redacted_from_everything_returned(tmp_path):
	repl = Repl(tmp_path, secrets={'pw': 'hunter2-Zq9', 'pin': '4711'})
	try:
		# A prompt-injected cell digging the value out of type_secret's closure still only shows the placeholder.
		code = DIG + "print('leak', v['pw'], v['pin'], secret_names())\nraise ValueError(v['pw'])"
		r = await repl.call('exec', code, 30)
		assert "leak <secret:pw> <secret:pin> ['pin', 'pw']" in r['output']
		assert 'hunter2' not in Path(r['output_file']).read_text()  # the captured output file in the workspace too
		assert 'ValueError: <secret:pw>' in r['error'] and 'hunter2' not in r['error']
		assert (await repl.call('eval', "v['pw']", 30))['value'] == '<secret:pw>'
		assert 'KeyError' in (await repl.call('exec', "type_secret('nope')", 30))['error']
	finally:
		await repl.close()


def test_a_short_secret_is_redacted_only_where_it_stands_alone():
	"""M23: a 1-character pin '9' turned 'year 2019, 9 days, version 1.9.9' into 'year 201<secret:pin>, ...'."""
	text = 'year 2019, 9 days, version 1.9.9, pin=9, x9y, _9_'
	assert redact(text, {'pin': '9'}) == (
		'year 2019, <secret:pin> days, version 1.<secret:pin>.<secret:pin>, pin=<secret:pin>, x9y, _<secret:pin>_'
	)
	assert redact('ab12 1234 a1234', {'pin': '1234'}) == 'ab12 <secret:pin> a<secret:pin>'  # 4+: everywhere, as before


def test_redact_longest_first():
	assert redact('abcdef abc', {'short': 'abc', 'long': 'abcdef'}) == '<secret:long> <secret:short>'
	assert redact(None, {'a': 'b'}) is None


@pytest.mark.parametrize('mode', ['bad'])
def test_bad_mode_raises(tmp_path, mode):
	with pytest.raises(ValueError):
		Repl(tmp_path, mode=mode)


async def test_cancelled_call_resets_the_worker(tmp_path):
	"""Roast C5: a whole-run timeout cancelled the call but left its cell running (still acting on the browser)."""
	marker = tmp_path / 'cell-kept-running'
	repl = Repl(tmp_path)
	try:
		await repl.call('exec', 'pass', 30)
		code = f'import time\ntime.sleep(2)\nopen({str(marker)!r}, "w").close()\nprint("stale")'
		with pytest.raises(TimeoutError):
			await asyncio.wait_for(repl.call('exec', code, 30), 0.5)
		await asyncio.sleep(2.5)  # the old cell would have finished by now
		assert not marker.exists()
		assert (await repl.call('exec', 'print("fresh")', 30))['output'].strip() == 'fresh'
	finally:
		await repl.close()


async def test_a_call_never_takes_an_earlier_calls_answer(tmp_path, monkeypatch):
	"""Roast C5: when a cancelled cell survives (cancelled before the reset, or the kill failed), its late answer
	was returned as the next call's result."""
	repl = Repl(tmp_path)
	try:
		await repl.call('exec', 'pass', 30)
		close = repl.close
		monkeypatch.setattr(repl, 'close', lambda: asyncio.sleep(0))  # the reset does not happen
		with pytest.raises(TimeoutError):
			await asyncio.wait_for(repl.call('exec', 'import time\ntime.sleep(1)\nprint("stale")', 30), 0.3)
		monkeypatch.setattr(repl, 'close', close)
		assert (await repl.call('exec', 'print("fresh")', 30))['output'].strip() == 'fresh'
	finally:
		await repl.close()


async def test_repl_without_a_daemon_never_reaches_the_default_one(tmp_path):
	"""A test REPL with no daemon env attached to the developer's default browser-harness daemon (their own Chrome):
	a broken type_secret check typed the test value into it. conftest pins BU_NAME to a daemon that never exists."""
	repl = Repl(tmp_path)
	try:
		r = await repl.call('exec', 'page_info()', 30)
	finally:
		await repl.close()
	assert r['error'], r  # no daemon: page_info() fails instead of reading the developer's tab


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


async def test_worker_never_loads_dotenv(tmp_path):
	"""Roast C16: .env is read in the parent only; the worker must not import the modules that load it."""
	(tmp_path / '.env').write_text('DOTENV_PROBE=planted\n', encoding='utf-8')
	repl = Repl(tmp_path)
	try:
		code = (
			"import os, sys\nmods = ('browser_use.agent.service', 'browser_use.browser.browser', 'browser_use.telemetry.service')\n"
			"print([m for m in mods if m in sys.modules], os.environ.get('DOTENV_PROBE'))"
		)
		r = await repl.call('exec', code, 30)
	finally:
		await repl.close()
	assert r['output'].strip() == '[] None', r


def test_worker_env_keeps_proxy_and_ca_settings(monkeypatch):
	names = ('HTTPS_PROXY', 'no_proxy', 'SSL_CERT_FILE', 'REQUESTS_CA_BUNDLE', 'CURL_CA_BUNDLE')
	for name in names:
		monkeypatch.setenv(name, 'x')
	assert {n.upper() for n in names} <= {k.upper() for k in worker_env()}  # Windows env keys are uppercase


async def test_cell_output_file_keeps_the_bytes_the_cell_wrote(tmp_path):
	"""Fable r2-3a: on Windows the text-mode cell file turned the cell's \\r\\n into \\r\\r\\n, so the model saw a blank
	line after every line."""
	repl = Repl(tmp_path)
	try:
		r = await repl.call('exec', "import os\n_ = os.write(1, b'a\\r\\nb\\n')", 30)
	finally:
		await repl.close()
	assert Path(r['output_file']).read_bytes() == b'a\r\nb\n' and r['output'] == 'a\nb\n', r


async def test_cells_print_unicode_whatever_the_parent_locale(tmp_path, monkeypatch):
	"""Roast C17: on Windows (cp1252) a cell printing page text like CJK or emoji raised UnicodeEncodeError."""
	monkeypatch.setenv('PYTHONIOENCODING', 'ascii')  # stands in for a cp1252 console
	monkeypatch.setenv('PYTHONUTF8', '0')
	monkeypatch.setenv('LC_ALL', 'en_US.ISO8859-1')  # a non-UTF-8 locale reaches the worker (LC_* pass) on macOS/Linux
	repl = Repl(tmp_path)
	try:
		r = await repl.call(
			'exec',
			"print('日本語 🙂')\nimport subprocess, sys\n_ = subprocess.run([sys.executable, '-c', 'print(\"é 日本\")'])",
			30,
		)
	finally:
		await repl.close()
	assert r['error'] is None and r['output'].splitlines()[:2] == ['日本語 🙂', 'é 日本'], r  # the child printed it


async def test_interrupted_cell_never_writes_a_secret_to_disk(tmp_path):
	"""Roast C8: output reached the workspace file before redaction; a killed cell left the plaintext there."""
	repl = Repl(tmp_path, secrets={'pw': 'hunter2-Zq9'})
	try:
		code = DIG + "print('got', v['pw'], flush=True)\nimport time\ntime.sleep(30)"
		r = await repl.call('exec', code, 2)
	finally:
		await repl.close()
	assert 'timed out' in r['error']
	text = Path(r['output_file']).read_text(encoding='utf-8')
	assert 'got <secret:pw>' in text and 'hunter2' not in text


async def test_output_between_cells_never_writes_a_secret_to_disk(tmp_path):
	"""Live: a thread a cell left running printed the value after the cell ended; fd 1 was worker.log again, raw."""
	repl = Repl(tmp_path, secrets={'pw': 'hunter2-Zq9'})
	log = tmp_path / '.browser-use' / 'worker.log'
	try:
		code = DIG + (
			'import os, threading, time, warnings\n'
			'def later():\n'
			"\twhile not os.path.exists('go'):  # created once the cell's result arrived: the cell is over\n"
			'\t\ttime.sleep(0.01)\n'
			"\tprint('thread', v['pw'], flush=True)\n"
			"\twarnings.warn('warn ' + v['pw'])\n"
			'threading.Thread(target=later, daemon=True).start()'
		)
		r = await repl.call('exec', code, 30)
		assert r['error'] is None, r
		(tmp_path / 'go').touch()

		def logged() -> None:  # the thread's lines reach worker.log (a 10 s deadline)
			deadline = time.monotonic() + 10
			while 'warn' not in log.read_text(encoding='utf-8') and time.monotonic() < deadline:
				time.sleep(0.05)

		await asyncio.to_thread(logged)
	finally:
		await repl.close()
	text = log.read_text(encoding='utf-8')
	assert 'thread <secret:pw>' in text and 'warn <secret:pw>' in text and 'hunter2' not in text, text


async def test_common_encodings_of_a_secret_are_redacted(tmp_path):
	"""Fable: btoa(value), value[::-1], hex and URL-encoding walked the value past plain-text redaction."""
	repl = Repl(tmp_path, secrets={'pw': 'hunter2 Zq9/'})
	try:
		code = (
			DIG + 'import base64, urllib.parse\n'
			'v = v["pw"]\n'
			'print(base64.b64encode(v.encode()).decode(), v[::-1], v.encode().hex(), urllib.parse.quote(v, safe=""))'
		)
		r = await repl.call('exec', code, 30)
	finally:
		await repl.close()
	assert r['output'].split() == ['<secret:pw>'] * 4


async def test_a_secret_as_the_page_shows_it_is_redacted(tmp_path):
	"""Live run: a login page showed the email lowercased, outerHTML showed the password HTML-escaped, and base64 of
	'user:' + password (Basic auth) or of a JSON blob holding it started mid-group: all four reached result.messages."""
	pw, email = 'P@ss&w0rd<Zq9>!x"', 'Jane.Doe-Q7@Example.COM'
	repl = Repl(tmp_path, secrets={'pw': pw, 'email': email})
	try:
		code = (
			'import base64, html, json\n'
			f'pw, email = {pw!r}, {email!r}\n'
			'b64 = lambda s: base64.b64encode(s.encode()).decode()\n'
			'print(email.lower(), email.upper())\n'
			"print(js_text := pw.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))\n"
			"print(js_text.replace('\"', '&quot;'), pw.replace('&', '&amp;').replace('\"', '&quot;'), html.escape(pw))\n"
			"for prefix in ('', 'a', 'a:', 'ab:'):\n\tprint('Basic', b64(prefix + pw), b64(prefix + pw + '\\n'))\n"
			"print(b64(json.dumps({'password': pw})), base64.urlsafe_b64encode(json.dumps({'pw': pw}).encode()).decode())\n"
		)
		r = await repl.call('exec', code, 30)
	finally:
		await repl.close()
	lines = r['output'].strip().splitlines()
	assert r['error'] is None and len(lines) == 8, r
	assert lines[0] == '<secret:email> <secret:email>'
	for line in lines[1:3]:
		assert set(line.split()) == {'<secret:pw>'}, line
	for line in lines[3:]:
		assert all('<secret:pw>' in word for word in line.split() if word != 'Basic'), line
	assert 'w0rd' not in r['output'] and 'Example' not in r['output']


async def test_ordinary_base64_is_not_redacted_by_a_short_secret(tmp_path):
	"""The base64 cores of a 4-5 character value are 4-6 characters long and would match by chance in any blob."""
	blob = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk'
	assert redact(blob, {'pin': '4821', 'code': 'x9Kq2'}) == blob


async def test_checkpoints_and_partial_results_are_redacted(tmp_path):
	"""Roast C13: checkpointed data holding a secret was saved raw and returned through .partial / timeout text."""
	from browser_use.agent.loop import Session

	repl = Repl(tmp_path, secrets={'pw': 'hunter2-Zq9'})
	try:
		code = DIG + "checkpoint('rows.json', [{'note': 'pw is ' + v['pw']}], partial=True)"
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


async def test_domain_scoped_secret_is_refused_on_another_origin(tmp_path):
	"""Fable: a prompt-injected page could have the model open evil.test and type the secret there (0.x scoped it)."""
	repl = Repl(tmp_path, secrets={'https://*.site.test': {'pw': 'hunter2-Zq9'}, 'pin': '4711'})
	try:
		code = (
			'import browser_harness.helpers as h\n'
			"h.cdp = lambda method, *a, **k: {'frameTree': {'frame': {'url': 'https://evil.test/login'}}}\n"
			"print(secret_names())\ntype_secret('pw')"
		)
		r = await repl.call('exec', code, 30)
	finally:
		await repl.close()
	assert "['pin', 'pw']" in r['output']
	assert 'PermissionError' in r['error'] and '*.site.test' in r['error'] and 'hunter2' not in r['error']


async def test_cell_traceback_keeps_cell_and_workspace_frames_but_no_installed_paths(tmp_path):
	"""C60: stdlib and site-packages frames reached the model with absolute paths (the user's home, the venv) and
	~4k characters for one urlopen error."""
	(tmp_path / 'mymod.py').write_text(
		'import urllib.request\ndef go():\n\turllib.request.urlopen("http://127.0.0.1:9/", timeout=5)\n'
	)
	repl = Repl(tmp_path)
	try:
		r = await repl.call('exec', 'import mymod\nmymod.go()', 30)
	finally:
		await repl.close()
	error = r['error']
	assert error.startswith('Traceback') and '<cell' in error and 'mymod.py' in error, error
	assert '/urllib/' not in error and '/http/' not in error and 'browser_use' not in error, error
	assert error.splitlines()[-1].startswith('urllib.error.URLError'), error


@pytest.mark.parametrize(
	('url', 'pattern', 'ok'),
	[
		('https://site.test/x', 'site.test', True),
		('http://site.test/x', 'site.test', False),  # no scheme means https only, as in 0.x
		('http://site.test/x', 'http*://site.test', True),
		('https://a.site.test/', '*.site.test', True),
		('https://site.test/', '*.site.test', True),
		('https://evilsite.test/', '*.site.test', False),
		('https://site.test.evil/', 'https://site.test', False),
		('https://site.test:8443/', 'https://site.test:8443', True),
		('about:blank', 'site.test', False),
	],
)
def test_domain_matches(url, pattern, ok):
	from browser_use.repl.session import domain_matches

	assert domain_matches(url, pattern) is ok


async def test_close_kills_cell_processes_after_the_worker_died(tmp_path):
	"""Roast r2-4: close() killed the process tree only while the worker was alive; after a worker crash a process a
	cell started kept running (and could keep driving the browser)."""
	beat = tmp_path / 'beat.txt'
	# Bounded (30 s), so a regression never leaves a process running forever on the test machine.
	child = f"import time\nfor _ in range(600):\n    open({str(beat)!r}, 'a').write('.')\n    time.sleep(0.05)"
	repl = Repl(tmp_path)
	try:
		code = f'import subprocess, sys\n_ = subprocess.Popen([sys.executable, "-c", {child!r}])'
		assert (await repl.call('exec', code, 30))['error'] is None
		for _ in range(100):
			if beat.exists():
				break
			await asyncio.sleep(0.05)
		assert repl.proc is not None
		repl.proc.kill()  # the worker dies; its cell's process does not
		repl.proc.wait()
	finally:
		await repl.close()
	await asyncio.sleep(0.3)
	size = beat.stat().st_size
	await asyncio.sleep(0.5)
	assert beat.stat().st_size == size  # the heartbeat stopped


async def test_restart_after_the_worker_died_kills_its_cell_processes(tmp_path):
	"""Roast r3-3: when the worker died between calls, the next call started a new one and dropped the old process
	group/job without killing it; a process the old cell started kept running (and driving the browser)."""
	beat = tmp_path / 'beat.txt'
	child = f"import time\nfor _ in range(600):\n    open({str(beat)!r}, 'a').write('.')\n    time.sleep(0.05)"
	repl = Repl(tmp_path)
	try:
		code = f'import subprocess, sys\n_ = subprocess.Popen([sys.executable, "-c", {child!r}])'
		assert (await repl.call('exec', code, 30))['error'] is None
		for _ in range(100):
			if beat.exists():
				break
			await asyncio.sleep(0.05)
		assert repl.proc is not None
		repl.proc.kill()  # the worker dies between calls; its cell's process does not
		repl.proc.wait()
		assert (await repl.call('exec', 'print("fresh")', 30))['output'].strip() == 'fresh'  # restart
		await asyncio.sleep(0.3)
		size = beat.stat().st_size
		await asyncio.sleep(0.5)
		assert beat.stat().st_size == size  # the old cell's heartbeat stopped at the restart, not at close()
	finally:
		await repl.close()


async def test_cancel_during_worker_startup_leaves_a_usable_repl(tmp_path, monkeypatch):
	"""Roast r3-5: a cancel while the worker was starting left a half-started worker (no channel); with
	Browser(keep_alive=True) the next call failed on the missing writer."""
	site, flag = tmp_path / 'site', tmp_path / 'slow-start'
	site.mkdir()
	(site / 'sitecustomize.py').write_text(  # the first interpreter that sees the flag starts slowly
		'import os, time\np = os.environ.get("BU_TEST_SLOW_START", "")\n'
		'if p and os.path.exists(p):\n    os.remove(p)\n    time.sleep(2)\n',
		encoding='utf-8',
	)
	flag.touch()
	monkeypatch.setenv('PYTHONPATH', str(site))
	monkeypatch.setenv('BU_TEST_SLOW_START', str(flag))
	repl = Repl(tmp_path / 'ws')
	try:
		with pytest.raises(TimeoutError):
			await asyncio.wait_for(repl.call('exec', 'pass', 30), 0.5)  # cancelled while the worker starts
		assert not flag.exists()  # the cancel landed during startup
		assert (await repl.call('exec', 'print("fresh")', 30))['output'].strip() == 'fresh'
	finally:
		await repl.close()


async def test_a_new_repl_in_the_same_workspace_never_overwrites_earlier_cell_files(tmp_path):
	"""Roast r3-7: a follow-up run starts a fresh REPL; its numbering restarted at 0001 and overwrote the earlier
	cell's file, which the retained conversation still linked to."""
	files = []
	for text in ('first', 'second'):
		repl = Repl(tmp_path)
		try:
			files.append((await repl.call('exec', f'print({text!r})', 30))['output_file'])
		finally:
			await repl.close()
	assert files[0] != files[1] and Path(files[0]).read_text(encoding='utf-8') == 'first\n'


async def test_timed_out_cell_reads_only_the_start_of_a_huge_output(tmp_path):
	"""Fable r3-4: on a cell timeout the parent read the cell's whole output file into memory before clipping it."""
	import tracemalloc

	repl = Repl(tmp_path)
	try:
		await repl.call('exec', 'pass', 30)
		code = "import sys, time\nsys.stdout.write('x' * 20_000_000)\nsys.stdout.flush()\ntime.sleep(30)"
		tracemalloc.start()
		try:
			r = await repl.call('exec', code, 4)
			peak = tracemalloc.get_traced_memory()[1]
		finally:
			tracemalloc.stop()
	finally:
		await repl.close()
	assert 'timed out' in r['error'] and Path(r['output_file']).stat().st_size >= 20_000_000, r['error']
	assert 'Truncated' in r['output'] and peak < 10_000_000, peak


async def test_workspace_file_named_like_a_stdlib_module_never_breaks_the_worker(tmp_path):
	"""Fable r3-1: the workspace was sys.path[0] of the worker, so a json.py there (the user's project, or one the
	model wrote before a restart) shadowed the stdlib and every cell failed with 'REPL worker failed to start'."""
	(tmp_path / 'json.py').write_text('loads = None\n', encoding='utf-8')
	(tmp_path / 'mymod.py').write_text('X = 7\n', encoding='utf-8')
	repl = Repl(tmp_path)
	try:
		r = await repl.call('exec', 'import mymod\nprint(mymod.X)', 30)
	finally:
		await repl.close()
	assert (r['output'].strip(), r['error']) == ('7', None)  # the agent's own modules still import


async def test_finish_from_repl_delivers_a_pydantic_model_as_json(tmp_path):
	"""Fable r3-3: eval serialized non-JSON values with str(); a pydantic model came back as "title='x' points=3",
	which failed the result schema and burned a retry."""
	import json

	repl = Repl(tmp_path)
	try:
		code = 'from pydantic import BaseModel\nclass Story(BaseModel):\n    title: str\n    points: int\ns = Story(title="x", points=3)'
		assert (await repl.call('exec', code, 30))['error'] is None
		r = await repl.call('eval', '[s]', 30)
	finally:
		await repl.close()
	assert json.loads(r['value']) == [{'title': 'x', 'points': 3}], r


async def test_checkpoint_saves_a_pydantic_model_as_json(tmp_path):
	"""Same root as Fable r3-3: checkpoint() serialized non-JSON values with str(), so a checkpointed model became
	the string "title='x' points=3" in the file and in result.partial."""
	import json

	repl = Repl(tmp_path)
	try:
		code = (
			'from pydantic import BaseModel\nclass Story(BaseModel):\n    title: str\n    points: int\n'
			'checkpoint("rows.json", [Story(title="x", points=3)], partial=True)'
		)
		assert (await repl.call('exec', code, 30))['error'] is None
	finally:
		await repl.close()
	assert json.loads((tmp_path / 'rows.json').read_text(encoding='utf-8')) == [{'title': 'x', 'points': 3}]


ESCAPED = 'pa"ss\\wo\nrd-Zq9'  # quotes, a backslash and a newline: JSON and repr() escape all three


async def test_escaped_forms_of_a_secret_are_redacted(tmp_path):
	"""Roast r4-2: json.dumps / repr() escape quotes, backslashes and newlines, so the serialized value no longer matched
	the plain secret; json.loads(final_result()) recovered the password."""
	import json

	repl = Repl(tmp_path, secrets={'pw': ESCAPED})
	try:
		code = DIG + "import json\nprint({'pw': v['pw']})\nprint(json.dumps({'pw': v['pw']}), json.dumps(v['pw'] + 'é'))"
		r = await repl.call('exec', code, 30)
		value = (await repl.call('eval', "json.dumps({'pw': v['pw']})", 30))['value']
	finally:
		await repl.close()
	assert r['output'].count('<secret:pw>') == 3 and 'Zq9' not in r['output'], r
	assert json.loads(value) == {'pw': '<secret:pw>'}


@pytest.mark.parametrize('deliver', ['finish', 'finish_from_repl'])
async def test_structured_result_never_holds_a_secret(tmp_path, deliver):
	"""Fable r4-5 + roast r4-2: only the result text was redacted; result.output / structured_output returned the raw
	model instance, and the text was redacted after JSON escaping."""
	import json

	from conftest import script
	from pydantic import BaseModel

	from browser_use.agent.loop import Session, build_agent, run

	class Creds(BaseModel):
		note: str
		n: int

	call = (
		('finish', {'success': True, 'result': {'note': f'pw {ESCAPED}', 'n': 1}})
		if deliver == 'finish'
		else ('finish_from_repl', {'success': True, 'expression': "{'note': 'pw ' + v['pw'], 'n': 1}"})
	)
	model, _ = script(('python', {'code': DIG}), call)
	session = Session(repl=Repl(tmp_path, secrets={'pw': ESCAPED}))
	try:
		r = await run(build_agent(model, output_type=Creds), 'task', session, 'test')
	finally:
		await session.repl.close()
	assert r.structured_output == Creds(note='pw <secret:pw>', n=1), r
	assert json.loads(r.final_result()) == {'note': 'pw <secret:pw>', 'n': 1}


def test_repl_reused_from_a_new_event_loop_restarts_its_worker(tmp_path):
	"""Fable r4-1: Browser(keep_alive=True) + asyncio.run(agent.run()) twice: the second run's cells failed with "attached
	to a different loop" (the worker's pipes and the lock belong to the first loop)."""
	repl = Repl(tmp_path)

	async def two_cells():  # parallel calls contend for the lock, which binds it to this loop
		return await asyncio.gather(repl.call('exec', 'x = 1', 30), repl.call('exec', 'print(2)', 30))

	try:
		assert [r['error'] for r in asyncio.run(two_cells())] == [None, None]
		second = asyncio.run(two_cells())
	finally:
		asyncio.run(repl.close())
	assert [r['error'] for r in second] == [None, None], second
	assert 'Python variables are lost' in second[0]['output'] and second[1]['output'].strip() == '2'


@pytest.mark.skipif(sys.platform == 'win32', reason='reads the process state with ps')
def test_a_worker_whose_event_loop_closed_is_reaped_without_asyncio_warnings(tmp_path, caplog):
	"""live/scale: Browser(keep_alive=True) with asyncio.run(agent.run()) then asyncio.run(agent.close()) (and every REPL
	restart for a new loop) killed a worker its finished loop had started. asyncio's child watcher belongs to that loop:
	macOS logged "Loop ... that handles pid ... is closed" for each, Linux (pidfd watcher) never reaped it and kept its
	pidfd open."""
	import subprocess

	repl = Repl(tmp_path)
	pids = []

	async def cell():
		r = await repl.call('exec', 'print(1)', 30)
		assert repl.proc is not None
		pids.append(repl.proc.pid)
		return r

	assert asyncio.run(cell())['error'] is None
	assert asyncio.run(cell())['error'] is None  # a new loop: the first worker is replaced
	asyncio.run(repl.close())
	time.sleep(0.5)
	for pid in pids:
		state = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)], capture_output=True, text=True).stdout.strip()
		assert state == '', (pid, state)  # gone: not running, not a zombie
	assert not [r for r in caplog.records if r.name == 'asyncio' and 'that handles pid' in r.getMessage()]


def _tab(capture_hangs: bool):
	"""A stub browser-harness cdp for one hidden attached tab; records (method, response timeout) per call."""
	from browser_harness.helpers import _IPCResponseTimeout

	state, calls = {'visibility': 'hidden'}, []

	def raw_cdp(method, session_id=None, _response_timeout=5.0, **params):
		calls.append((method, _response_timeout))
		if method == 'Runtime.evaluate':
			return {'result': {'type': 'string', 'value': state['visibility']}}
		if method == 'Target.activateTarget':
			state['visibility'] = 'visible'
			return {}
		if capture_hangs and state['visibility'] == 'hidden':
			raise _IPCResponseTimeout(f'{method} timed out after {_response_timeout:g}s waiting for the daemon')
		return {'data': 'AAAA'}

	return raw_cdp, calls, state


def test_hidden_tab_that_captures_is_never_activated():
	"""Roast r7 F1: screenshot() activated every hidden tab, switching the user's visible tab in local mode, although
	only Linux headless needs it (a hidden tab captures fine on macOS and in headful Chrome)."""
	from browser_use.repl.capture import capture

	raw_cdp, calls, state = _tab(capture_hangs=False)
	assert capture(raw_cdp, lambda: {'targetId': 'T'}, format='jpeg')['data']
	assert state['visibility'] == 'hidden'
	assert [m for m, _ in calls] == ['Runtime.evaluate', 'Page.captureScreenshot']


def test_hidden_tab_is_activated_only_after_its_capture_times_out():
	"""Linux headless renders no frames for a hidden tab: its capture hung 60s. A short try first, then activate."""
	from browser_use.repl.capture import HIDDEN_CAPTURE_TRY_S, SCREENSHOT_TIMEOUT_S, capture

	raw_cdp, calls, state = _tab(capture_hangs=True)
	activated = []
	assert capture(raw_cdp, lambda: activated.append(1) or {'targetId': 'T'}, format='jpeg')['data']
	assert calls == [
		('Runtime.evaluate', 5),
		('Page.captureScreenshot', HIDDEN_CAPTURE_TRY_S),
		('Target.activateTarget', 5.0),
		('Page.captureScreenshot', SCREENSHOT_TIMEOUT_S),
	]
	assert state['visibility'] == 'visible' and activated == [1]


def test_hidden_cloud_tab_is_activated_before_its_capture():
	"""browser-features #3: a cloud browser never answers a hidden tab's capture, so every first screenshot and every
	one after switch_tab() waited the full 10 s first try. Ours and hidden: activate, then capture."""
	from browser_use.repl.capture import SCREENSHOT_TIMEOUT_S, capture

	raw_cdp, calls, state = _tab(capture_hangs=True)
	assert capture(raw_cdp, lambda: {'targetId': 'T'}, activate=True, format='jpeg')['data']
	assert calls == [('Runtime.evaluate', 5), ('Target.activateTarget', 5.0), ('Page.captureScreenshot', SCREENSHOT_TIMEOUT_S)]
	calls.clear()
	assert capture(raw_cdp, lambda: {'targetId': 'T'}, activate=True, format='jpeg')['data']  # visible now: no activate
	assert [m for m, _ in calls] == ['Runtime.evaluate', 'Page.captureScreenshot']


@pytest.mark.parametrize('kind', ['cdp', 'cloud'])
def test_cli_mcp_screenshot_activates_a_hidden_tab_whose_capture_hangs(monkeypatch, tmp_path, kind):
	"""win-cli-5: the CLI and --cli-mcp called browser-harness's bare capture_screenshot(): a background tab of a
	headless Chromium stalled 10 s or timed out at 60 s, where the Agent's screenshot() activates it after a short try.
	A cloud browser's hidden tab is activated without the 10 s try, as the Agent's is (cloud CLI: 10.6 s -> 0.4 s)."""
	from browser_harness import admin, helpers

	from browser_use.mcp import cli_mcp

	raw_cdp, calls, state = _tab(capture_hangs=True)
	monkeypatch.setattr(helpers, 'cdp', raw_cdp)
	monkeypatch.setattr(helpers, 'current_tab', lambda: {'targetId': 'T'})
	monkeypatch.setattr(admin, 'daemon_browser_kind', lambda name=None: kind)
	ns = cli_mcp.CLIMCPServer()._ensure_namespace()
	path = ns['capture_screenshot'](str(tmp_path / 'shot.png'))
	assert Path(path).read_bytes() == b'\x00\x00\x00'  # base64 'AAAA'
	assert state['visibility'] == 'visible'
	first_try = ['Page.captureScreenshot'] if kind != 'cloud' else []
	assert [m for m, _ in calls] == ['Runtime.evaluate', *first_try, 'Target.activateTarget', 'Page.captureScreenshot']


PARENT = """
import asyncio, sys
from pathlib import Path
from browser_use.repl import Repl

ws = Path(sys.argv[1])
beat = "import time\\nfor _ in range(600):\\n    open({!r}, 'a').write('.')\\n    time.sleep(0.05)"
code = (
    "import subprocess, sys\\n"
    f"_ = subprocess.Popen([sys.executable, '-c', {beat.format(str(ws / 'child.txt'))!r}])\\n"
    + beat.format(str(ws / 'cell.txt'))
)
asyncio.run(Repl(ws).call('exec', code, 120))
"""


@pytest.mark.parametrize('how', ['terminate', 'kill'])
def test_worker_dies_with_its_parent_mid_cell(tmp_path, how):
	"""Roast r7 Codex P1: a parent killed during a cell (SIGTERM, SIGKILL, a crash) left the worker running the cell,
	and the processes it started, with no timeout: the agent's code could keep driving the browser. Heartbeats are
	bounded (30 s), so a regression never leaves a process running forever on the test machine."""
	import subprocess
	import sys
	import time

	parent = subprocess.Popen([sys.executable, '-c', PARENT, str(tmp_path)])
	try:
		beats = [tmp_path / 'cell.txt', tmp_path / 'child.txt']
		for _ in range(300):
			if all(b.exists() for b in beats):
				break
			time.sleep(0.05)
		assert all(b.exists() for b in beats), (tmp_path / '.browser-use' / 'worker.log').read_text()
	finally:
		getattr(parent, how)()  # POSIX: SIGTERM / SIGKILL; Windows: TerminateProcess
		parent.wait()
	time.sleep(3)  # the watchdog polls every second
	sizes = [b.stat().st_size for b in beats]
	time.sleep(0.5)
	assert [b.stat().st_size for b in beats] == sizes  # both heartbeats stopped


async def test_http_get_returns_bytes_for_binary_and_text_for_text(tmp_path):
	"""C31: browser-harness's http_get ended in data.decode(), so a zip or PDF raised UnicodeDecodeError and the model fell
	back to raw urllib. Binary comes back as the exact bytes; text (gzip too) as str."""
	import gzip
	import threading
	from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

	zip_bytes = b'PK\x03\x04\x14\x00\xd9\x9c\xff\x00binary'
	bodies = {'/a.zip': (zip_bytes, {}), '/t': (gzip.compress('héllo'.encode()), {'Content-Encoding': 'gzip'})}

	class Handler(BaseHTTPRequestHandler):
		def do_GET(self):
			body, headers = bodies[self.path]
			self.send_response(200)
			for k, v in headers.items():
				self.send_header(k, v)
			self.send_header('Content-Length', str(len(body)))
			self.end_headers()
			self.wfile.write(body)

		def log_message(self, *args):
			pass

	server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
	threading.Thread(target=server.serve_forever, daemon=True).start()
	base = f'http://127.0.0.1:{server.server_address[1]}'
	repl = Repl(tmp_path)
	try:
		r = await repl.call('exec', f'z = http_get({base + "/a.zip"!r}); t = http_get({base + "/t"!r}); (z, t)', 30)
		assert r['error'] is None, r['error']
		assert r['output'].strip() == repr((zip_bytes, 'héllo'))
	finally:
		await repl.close()
		server.shutdown()


async def test_gif_and_palette_images_reach_the_model_as_plain_png(tmp_path):
	"""grok bub2-008: show_image('epc/94017744.png') sent a palette (P) image as image/png and xAI 400'd the run
	("not a valid JPG, PNG, WebP, or ICO image"). A GIF named .png, a palette PNG and a JPEG named .png all arrive as
	what their media type says, RGB(A)."""
	import base64
	import io

	from PIL import Image

	code = (
		"from PIL import Image\nImage.new('RGB', (40, 20), 'red').save('graph.png', 'GIF')\n"
		"Image.new('P', (40, 20)).save('palette.png')\nImage.new('RGB', (40, 20)).save('photo.png', 'JPEG')\n"
		"print(show_image('graph.png'), show_image('palette.png'), show_image('photo.png'))"
	)
	repl = Repl(tmp_path)
	try:
		r = await repl.call('exec', code, 30)
	finally:
		await repl.close()
	assert r['error'] is None and r['output'].strip() == 'True True True', r
	decoded = [(i['media_type'], Image.open(io.BytesIO(base64.b64decode(i['data'])))) for i in r['images']]
	assert [(t, img.format, img.mode) for t, img in decoded] == [
		('image/png', 'PNG', 'RGB'),
		('image/png', 'PNG', 'RGB'),
		('image/jpeg', 'JPEG', 'RGB'),
	]


async def test_images_providers_take_are_sent_as_is_and_conversions_fit_the_limits(tmp_path):
	"""Review of the palette fix: a 16-bit gray PNG came out white and a camera JPEG (Pillow: MPO) grew 4-5x as PNG; both
	are sent unchanged. A noisy GIF grew past Anthropic's 5 MB as PNG, and a transparent PNG over 2048 px came out black:
	the first is sized after conversion, the second goes on white."""
	import base64
	import io

	from PIL import Image

	code = (
		'import os\nfrom PIL import Image, ImageDraw\n'
		"Image.new('I;16', (40, 20), 30000).save('depth.png')\n"
		"a = Image.new('RGB', (40, 20), 'red')\na.save('camera.jpg', 'MPO', save_all=True, append_images=[a])\n"
		"noise = Image.frombytes('P', (1500, 1500), os.urandom(1500 * 1500))\nnoise.putpalette(os.urandom(768))\n"
		"noise.save('noise.gif')\n"
		"logo = Image.new('RGBA', (3000, 100))\nImageDraw.Draw(logo).text((10, 10), 'ACME', fill='black')\nlogo.save('logo.png')\n"
		"print(*(show_image(f) for f in ['depth.png', 'camera.jpg', 'noise.gif', 'logo.png']))"
	)
	repl = Repl(tmp_path)
	try:
		r = await repl.call('exec', code, 60)
	finally:
		await repl.close()
	assert r['error'] is None and r['output'].strip() == 'True True True True', r
	sent = [base64.b64decode(i['data']) for i in r['images']]
	assert sent[:2] == [(tmp_path / 'depth.png').read_bytes(), (tmp_path / 'camera.jpg').read_bytes()]
	assert [i['media_type'] for i in r['images']] == ['image/png', 'image/jpeg', 'image/jpeg', 'image/jpeg']
	assert len(sent[2]) < 5_000_000
	logo = Image.open(io.BytesIO(sent[3]))
	assert logo.size == (2048, 68) and logo.getpixel((1000, 50)) == (255, 255, 255)
	assert logo.convert('L').crop((0, 0, 60, 30)).getextrema()[0] < 100  # the black text stays
