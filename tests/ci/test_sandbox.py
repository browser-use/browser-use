"""Agent(sandbox=True): the REPL worker is confined to its workspace (repl/sandbox.py). Real workers, real headless
Chrome; skipped where the OS cannot sandbox (Windows, a kernel without Landlock)."""

import json
import os
import sys
from pathlib import Path

import pytest
from conftest import script

from browser_use import Agent, Browser
from browser_use.repl import Repl, sandbox

MARKER = 'sk-parent-only-7f3e9c'


def _supported() -> bool:
	try:
		sandbox.check()
	except ValueError:
		return False
	return True


needs_sandbox = pytest.mark.skipif(not _supported(), reason='this OS cannot sandbox the worker (Landlock / sandbox-exec)')


@pytest.fixture
def outside(tmp_path):
	"""A home-like dir outside the workspace holding what an injected page wants: an ssh key, the browser-harness key
	file, a project .env. (HOME itself stays: browser-harness reads its dirs from it once per process.)"""
	home = tmp_path / 'home'
	(home / '.ssh').mkdir(parents=True)
	(home / '.ssh' / 'id_ed25519').write_text('PRIVATE KEY')
	(home / '.config' / 'browser-harness').mkdir(parents=True)
	(home / '.config' / 'browser-harness' / 'auth.json').write_text('{"api_key": "bu_secret"}')
	(home / 'project').mkdir()
	(home / 'project' / '.env').write_text(f'OPENAI_API_KEY={MARKER}')
	return home


def _probe(home: Path) -> str:
	"""A cell trying each way out; prints one 'name: ok|denied' line each."""
	reads = {
		'ssh': home / '.ssh' / 'id_ed25519',
		'auth': home / '.config' / 'browser-harness' / 'auth.json',
		'dotenv': home / 'project' / '.env',
	}
	code = [
		'import os, subprocess',
		'def t(name, fn):',
		'\ttry:',
		'\t\tfn()',
		'\t\tprint(name + ": ok")',
		'\texcept PermissionError:',
		'\t\tprint(name + ": denied")',
		'def cat(path):',  # a cell's subprocess is confined too
		'\tif subprocess.run(["cat", path], capture_output=True).returncode:',
		'\t\traise PermissionError(path)',
	]
	code += [f't({k!r}, lambda: open({str(v)!r}).read())' for k, v in reads.items()]
	code.append(f't("list_home", lambda: os.listdir({str(home)!r}))')
	code.append(f't("subprocess", lambda: cat({str(reads["ssh"])!r}))')
	if sys.platform == 'darwin':  # ps -E reads it (sandboxed, ps does not start)
		code.append(
			't("parent_env", lambda: subprocess.run(["ps", "-E", "-ww", "-p", str(os.getppid())], check=True, capture_output=True))'
		)
	else:
		code.append('t("parent_env", lambda: open(f"/proc/{os.getppid()}/environ", "rb").read())')
	return '\n'.join(code)


def _results(output: str) -> dict[str, str]:
	return dict(line.split(': ', 1) for line in output.splitlines() if line.endswith((': ok', ': denied')))


@needs_sandbox
@pytest.mark.parametrize('confined', [True, False])
async def test_sandboxed_worker_cannot_read_outside_its_workspace(tmp_path, outside, confined):
	"""MIGRATING.md trust model: the worker read ~/.ssh, the browser-harness key file, a project .env and the parent's
	environment (/proc/<pid>/environ, ps -E). sandbox=True denies each; sandbox=False keeps 1.0's behavior."""
	ws = tmp_path / 'ws'
	ws.mkdir()
	repl = Repl(ws, sandbox=confined)
	try:
		r = await repl.call('exec', _probe(outside), 60)
		assert r['error'] is None, r
		got = _results(r['output'])
		assert got.keys() == {'ssh', 'auth', 'dotenv', 'list_home', 'subprocess', 'parent_env'}, r['output']
		assert set(got.values()) == {'denied' if confined else 'ok'}, got
		# the workspace, its temp dir and checkpoints still work
		r = await repl.call(
			'exec',
			"open('notes.txt', 'w').write('hi'); import tempfile, json\n"
			"with tempfile.NamedTemporaryFile('w', delete=False) as f: f.write('t')\n"
			"print(open('notes.txt').read(), f.name.startswith(os.getcwd()) or not "
			+ str(confined)
			+ ", checkpoint('c.json', {'a': 1}))",
			60,
		)
		assert r['error'] is None and r['output'].startswith('hi True'), r
		assert (ws / 'c.json').read_text().replace(' ', '').replace('\n', '') == '{"a":1}'
		assert (ws / 'notes.txt').read_text() == 'hi'
	finally:
		await repl.close()


@needs_sandbox
async def test_sandboxed_worker_still_drives_the_browser(daemon, tmp_path, outside):
	"""Browser actions, screenshots, checkpoints and upload_file from the workspace work in the sandbox; uploading a
	file from outside it (which a local browser would read for the page) raises."""
	ws = tmp_path / 'ws'
	ws.mkdir()
	(ws / 'cv.txt').write_text('hello local')
	repl = Repl(ws, daemon, sandbox=True)
	secret = outside / '.ssh' / 'id_ed25519'
	try:
		r = await repl.call(
			'exec',
			"new_tab('data:text/html,<title>t</title><input type=file id=f>'); wait_for_load(); print(page_info()['title'])\n"
			"shot = screenshot(); print(os.path.getsize(shot) > 0, checkpoint('p.json', {'ok': 1}))\n"
			"upload_file('#f', 'cv.txt'); print(js(\"document.getElementById('f').files[0].size\"))\n"
			'print(capture_screenshot().startswith(os.getcwd()))',
			60,
		)
		assert r['error'] is None, r
		lines = r['output'].splitlines()
		assert lines[0] == 't' and lines[1].startswith('True') and lines[2] == '11' and lines[3] == 'True', r['output']
		assert len(r['images']) == 2  # screenshot() and capture_screenshot()
		for code in (
			f'upload_file("#f", {str(secret)!r})',
			"node = cdp('DOM.getDocument')['root']['nodeId']; n = cdp('DOM.querySelector', nodeId=node, selector='#f')['nodeId']\n"
			f"cdp('DOM.setFileInputFiles', nodeId=n, files=[{str(secret)!r}])",
		):
			r = await repl.call('exec', code, 60)
			assert r['error'] and 'PermissionError: upload_file:' in r['error'] and 'workspace' in r['error'], r
	finally:
		await repl.close()


@needs_sandbox
@pytest.mark.parametrize('mode', ['default', 'ultrafast'])
async def test_sandboxed_agent_run_completes(chrome_binary, tmp_path, outside, mode):
	"""End to end: a scripted Agent(sandbox=True) on a local headless Chromium browses, is denied the ssh key, and
	finishes."""
	model, seen = script(
		(
			'python',
			{
				'code': "new_tab('data:text/html,<h1>hi</h1>'); wait_for_load()\n"
				f'try: open({str(outside / ".ssh" / "id_ed25519")!r}).read()\n'
				'except PermissionError as e: print("denied", type(e).__name__)\n'
				'print(js(\'document.querySelector("h1").textContent\'))'
			},
		),
		('finish', {'success': True, 'result': 'ok'}),
	)
	browser = Browser('chromium', headless=True, executable_path=chrome_binary)
	result = await Agent('t', model, browser=browser, workspace=tmp_path / 'ws', mode=mode, sandbox=True).run()
	assert result.status == 'completed' and result.final_result() == 'ok', result.error
	output = str(seen[1][-1])
	assert 'denied PermissionError' in output and 'hi' in output, output


def test_sandbox_fails_closed_where_the_os_cannot_confine_the_worker(monkeypatch):
	"""Never silently unsandboxed: Windows and a kernel without Landlock raise before any browser starts, as does a
	workspace that holds the home dir (read-write in the sandbox)."""
	model, _ = script()
	with pytest.raises(TypeError, match='sandbox must be True or False'):
		Agent('t', model, browser=Browser('chromium'), sandbox='yes')  # type: ignore[arg-type]
	if _supported():
		with pytest.raises(ValueError, match='must not contain your home dir'):
			Agent('t', model, browser=Browser('chromium'), workspace=Path.home(), sandbox=True)
	monkeypatch.setattr(sys, 'platform', 'win32')
	with pytest.raises(ValueError, match='not available on Windows'):
		Agent('t', model, browser=Browser('chromium'), sandbox=True)
	monkeypatch.setattr(sys, 'platform', 'linux')
	monkeypatch.setattr(sandbox, '_SYS_CREATE_RULESET', 444)  # Windows CI: no os.uname
	monkeypatch.setattr(sandbox, 'landlock_abi', lambda: 0)
	with pytest.raises(ValueError, match='needs Landlock'):
		Agent('t', model, browser=Browser('chromium'), sandbox=True)


@needs_sandbox
async def test_a_worker_that_reports_no_sandbox_is_refused(tmp_path, monkeypatch):
	"""The parent checks the worker's ready message: a worker that did not confine itself never runs a cell."""
	monkeypatch.setattr(Repl, '_sandboxed', lambda self, env: [])  # BU_SANDBOX never reaches the worker
	repl = Repl(tmp_path, sandbox=True)
	try:
		with pytest.raises(RuntimeError, match='without its sandbox'):
			await repl.start()
	finally:
		await repl.close()


def test_seatbelt_profile_denies_by_default_and_names_only_the_policy_paths():
	"""The macOS profile is generated per run: deny by default, contents readable only under the policy's paths,
	process info only for the sandbox itself. (A string test: it runs on every OS.)"""
	p = sandbox.Policy(write=('/private/tmp/ws', '/dev/null'), read=('/usr',), list=('/repo',), sockets=('/run/bu.sock',))
	text = sandbox.profile(p)
	assert '(deny default)' in text and '(allow process-info* (target same-sandbox))' in text
	assert '(allow file-read* file-write* (subpath "/private/tmp/ws"))' in text
	assert '(allow file-read* (subpath "/usr"))' in text and '(allow file-read-data (literal "/repo"))' in text
	assert '(remote unix-socket (path-literal "/run/bu.sock"))' in text
	assert sandbox.profile(sandbox.Policy(write=('/a"b',), read=())).count('(subpath "/a\\"b")') == 1  # quotes escaped


def test_policy_never_grants_home_or_an_editable_checkouts_root(tmp_path):
	"""The policy reads the interpreter and the packages, not the user's home or the checkout holding its .env."""
	import browser_use

	p = sandbox.policy(tmp_path, {})
	root = str(Path(browser_use.__file__).resolve().parent.parent)
	home = os.path.realpath(Path.home())
	assert root not in p.read and home not in p.read and home not in p.write
	assert str(Path(browser_use.__file__).resolve().parent) in p.read or any(
		str(Path(browser_use.__file__).resolve()).startswith(r + '/') for r in p.read
	)


@needs_sandbox
@pytest.mark.skipif(sys.platform == 'win32', reason='no ptys')
async def test_sandboxed_worker_cannot_open_your_other_terminals(tmp_path):
	"""macOS: the profile allowed every /dev/ttys*, so a cell could open another terminal of yours and read what you
	type there (a sudo password). Now only ptys the sandbox itself opened (Linux: no ptys at all)."""
	parent, child = os.openpty()  # stands in for another Terminal tab
	repl = Repl(tmp_path, sandbox=True)
	try:
		code = (
			f'try: open({os.ttyname(child)!r}, "rb", buffering=0); print("other: ok")\n'
			'except PermissionError: print("other: denied")\n'
		)
		if sys.platform == 'darwin':  # openpty() in a cell still works there
			code += 'm, s = os.openpty(); os.write(m, b"hi\\n"); print("own:", os.read(s, 3) == b"hi\\n")'
		r = await repl.call('exec', code, 60)
		assert r['error'] is None, r
		assert r['output'].splitlines() == ['other: denied', *(['own: True'] if sys.platform == 'darwin' else [])], r
	finally:
		await repl.close()
		os.close(parent)
		os.close(child)


@needs_sandbox
async def test_a_module_a_cell_writes_never_runs_before_the_next_worker_confines_itself(tmp_path, outside):
	"""A relative or empty PYTHONPATH entry (PYTHONPATH=":/x" from export PYTHONPATH=$PYTHONPATH:/x) put the worker's
	cwd, the workspace, on sys.path: a cell wrote idna.py there, and the next worker imported it before Landlock."""
	ws = tmp_path / 'ws'
	ws.mkdir()
	marker = outside / 'project' / 'pwned'
	repl = Repl(ws, env={'PYTHONPATH': os.pathsep + str(tmp_path / 'nonexistent')}, sandbox=True)
	try:
		module = 'open(%r, "w").close()' % str(marker)
		plant = f"open('idna.py', 'w').write({module!r}); os._exit(1)"
		r = await repl.call('exec', plant, 30)
		assert r['error_type'] == 'WorkerExited', r
		r = await repl.call('exec', "print('ok')", 30)
		assert r['output'] == 'ok\n', r
		assert not marker.exists()
	finally:
		await repl.close()


@needs_sandbox
async def test_a_workspace_that_holds_the_workers_python_is_refused(tmp_path, monkeypatch):
	"""Agent(workspace='.') in a project with its .venv (or PYTHONPATH) made the packages writable in the sandbox: a cell
	wrote a module there, and the next worker imported it before confining itself. Refused at Agent() and at start."""
	ws = tmp_path / 'ws'
	(ws / 'lib').mkdir(parents=True)
	model, _ = script()
	monkeypatch.setenv('PYTHONPATH', str(ws / 'lib'))
	with pytest.raises(ValueError, match='loads Python from'):
		Agent('t', model, browser=Browser('chromium'), workspace=ws, sandbox=True)
	monkeypatch.delenv('PYTHONPATH')
	Agent('t', model, browser=Browser('chromium'), workspace=ws, sandbox=True)  # the same dir without it is fine
	repl = Repl(ws, env={'PYTHONPATH': str(ws / 'lib')}, sandbox=True)
	try:
		with pytest.raises(ValueError, match='loads Python from'):
			await repl.start()
		assert repl.proc is None or repl.proc.poll() is not None
	finally:
		await repl.close()


@needs_sandbox
@pytest.mark.parametrize('link', ['worker.log', 'state dir'])
async def test_the_parent_never_follows_a_link_the_sandboxed_worker_planted(tmp_path, outside, link):
	"""The parent runs unconfined and opens files in the workspace: a cell swapped its own output file for a link to the
	ssh key and hung, and the timed-out cell's output (read by the parent) was the key; it swapped worker.log (or the
	whole .browser-use dir) for a link, and the next worker's output (opened by the parent) went to that file."""
	ws = tmp_path / 'ws'
	ws.mkdir()
	key = outside / '.ssh' / 'id_ed25519'
	target = outside / 'project'
	(target / 'worker.log').write_text('mine')
	repl = Repl(ws, sandbox=True)
	try:
		r = await repl.call(
			'exec',
			"import glob, time\nout = sorted(glob.glob('.browser-use/cells/*.txt'))[-1]\n"
			f'os.unlink(out); os.symlink({str(key)!r}, out); time.sleep(30)',
			3,
		)
		assert r['error_type'] == 'CellTimeout' and 'PRIVATE KEY' not in r['output'], r
		swap = (
			f"os.unlink('.browser-use/worker.log'); os.symlink({str(target / 'worker.log')!r}, '.browser-use/worker.log')"
			if link == 'worker.log'
			else f"os.rename('.browser-use', 'old'); os.symlink({str(target)!r}, '.browser-use')"
		)
		r = await repl.call('exec', f'{swap}; os._exit(1)', 30)
		assert r['error_type'] == 'WorkerExited', r
		with pytest.raises(OSError):  # fails closed: no worker starts with its output going there
			await repl.call('exec', "print('restarted')", 30)
		assert (target / 'worker.log').read_text() == 'mine'
	finally:
		await repl.close()


@needs_sandbox
@pytest.mark.parametrize('swap', [True, False])
async def test_cloud_downloads_never_land_outside_the_workspace(tmp_path, outside, monkeypatch, swap):
	"""The parent copies a cloud browser's downloads into workspace/downloads after the run: a cell swapped that dir for
	a link to ~/.ssh, and the page's download (named authorized_keys) was written there by the unconfined parent."""
	import threading
	from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

	from browser_harness import admin

	from browser_use.browser import browser as browser_mod

	class Key(BaseHTTPRequestHandler):
		def do_GET(self):
			self.send_response(200)
			self.send_header('Content-Length', '4')
			self.end_headers()
			self.wfile.write(b'evil')

		def log_message(self, *a):
			pass

	server = ThreadingHTTPServer(('127.0.0.1', 0), Key)
	threading.Thread(target=server.serve_forever, daemon=True).start()

	def fake_cloud(path, method='GET', body=None):
		if method == 'POST' and path == '/browsers':
			return {'id': 'b1', 'cdpUrl': 'https://cdp.example.test', 'liveUrl': 'https://live.example.test/x'}
		if 'downloads' in path:
			url = f'http://127.0.0.1:{server.server_port}/k'
			return {'files': [{'path': '/dl/authorized_keys', 'url': url, 'size': 4}], 'hasMore': False}
		return {}

	monkeypatch.setenv('BROWSER_USE_API_KEY', 'fake-test-key')
	monkeypatch.setattr(browser_mod, '_cloud', fake_cloud)
	monkeypatch.setattr(browser_mod, '_ws_url', lambda url: 'ws://fake.test/devtools/browser/x')
	monkeypatch.setattr(admin, 'ensure_daemon', lambda *a, **k: None)
	monkeypatch.setattr(admin, 'restart_daemon', lambda name=None, **k: None)
	ssh = outside / '.ssh'
	model, seen = script(
		(
			'python',
			{'code': f"import shutil; shutil.rmtree('downloads'); os.symlink({str(ssh)!r}, 'downloads')" if swap else '1'},
		),
		('finish', {'success': True, 'result': 'ok'}),
	)
	try:
		result = await Agent('t', model, browser=Browser(), workspace=tmp_path / 'ws', sandbox=True, judge=False).run()
	finally:
		server.shutdown()
		browser_mod._LIVE.clear()
	assert result.status == 'completed' and 'Error' not in str(seen[1][-1]), (result.error, seen)
	assert not (ssh / 'authorized_keys').exists()
	assert (tmp_path / 'ws' / 'downloads' / 'authorized_keys').exists() is not swap  # and without the link, it lands


def test_policy_reads_only_the_code_of_another_editable_install(tmp_path, monkeypatch):
	"""Only browser_use's and browser_harness's editable checkouts were narrowed to their package: a flat-layout editable
	install of your own project (hatchling's .pth names the project root) made that root, .env included, readable."""
	import site

	project = tmp_path / 'myproject'
	(project / 'mypkg').mkdir(parents=True)
	(project / 'mypkg' / '__init__.py').write_text('')
	(project / 'tool.py').write_text('')
	(project / '.env').write_text(f'OPENAI_API_KEY={MARKER}')
	sitedir = tmp_path / 'site-packages'
	sitedir.mkdir()
	(sitedir / '_myproject.pth').write_text(f'{project}\n')
	monkeypatch.setattr(site, 'getsitepackages', lambda: [str(sitedir)])
	p = sandbox.policy(tmp_path / 'ws', {})
	real = Path(os.path.realpath(project))
	assert str(real) in p.list and str(real) not in p.read
	assert {str(real / 'mypkg'), str(real / 'tool.py')} <= set(p.read)
	assert not any(str(real / '.env').startswith(r) for r in p.read)


@pytest.mark.skipif(sys.platform == 'win32', reason='no sandbox on Windows, so open_own follows links there')
def test_the_parent_reads_no_partial_result_or_download_log_through_a_link(tmp_path, outside):
	"""The parent read partial.json and downloads.jsonl through links a sandboxed cell could plant: a JSON file outside
	the workspace with a 'value' key became the run's partial result, and any file the user can read fed the downloads."""
	from types import SimpleNamespace

	from browser_use.agent.loop import Session

	ws = tmp_path / 'ws'
	(ws / '.browser-use').mkdir(parents=True)
	secret = outside / 'creds.json'
	secret.write_text(json.dumps({'value': 'outside-secret'}))
	(ws / '.browser-use' / 'partial.json').symlink_to(secret)
	(ws / '.browser-use' / 'downloads.jsonl').symlink_to(secret)
	session = Session(repl=SimpleNamespace(workspace=ws, state=ws / '.browser-use', secrets=[]))  # type: ignore[arg-type]
	assert session.partial() is None
	browser = Browser('chromium')
	browser.note_downloads(ws / '.browser-use' / 'downloads.jsonl')
	assert browser._download_records == []
