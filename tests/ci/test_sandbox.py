"""Agent(sandbox=True): the REPL worker is confined to its workspace (repl/sandbox.py). Real workers, real headless
Chrome; skipped where the OS cannot sandbox (Windows, a kernel without Landlock)."""

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


def test_seatbelt_profile_denies_by_default_and_names_only_the_policy_paths(tmp_path):
	"""The macOS profile is generated per run: deny by default, contents readable only under the policy's paths,
	process info only for the sandbox itself."""
	p = sandbox.Policy(write=(str(tmp_path), '/dev/null'), read=('/usr',), list=('/repo',), sockets=('/run/bu.sock',))
	text = sandbox.profile(p)
	assert '(deny default)' in text and '(allow process-info* (target same-sandbox))' in text
	assert f'(allow file-read* file-write* (subpath "{tmp_path}"))' in text
	assert '(allow file-read* (subpath "/usr"))' in text and '(allow file-read-data (literal "/repo"))' in text
	assert '(remote unix-socket (path-literal "/run/bu.sock"))' in text
	assert str(Path.home()) not in text or str(tmp_path).startswith(str(Path.home()))


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
