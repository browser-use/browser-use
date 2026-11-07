"""Public API (Agent, Browser) against a real isolated headless Chrome, scripted model (no provider calls)."""

import os

import pytest
from conftest import script
from pydantic import BaseModel

from browser_use import Agent, Browser
from browser_use.agent.loop import build_agent
from browser_use.repl import Repl


def prompts(messages):
	from pydantic_ai.messages import UserPromptPart

	return [p.content for m in messages for p in getattr(m, 'parts', []) if isinstance(p, UserPromptPart)]


async def test_run_stops_browser_then_follow_up_restarts_it(chrome, tmp_path):
	model, seen = script(
		('python', {'code': "new_tab('data:text/html,<title>Hi there</title>'); wait_for_load(); title = page_info()['title']"}),
		('finish_from_repl', {'success': True, 'expression': 'title'}),
		('finish', {'success': True, 'result': 'second answer'}),
	)
	browser = Browser(cdp_url=chrome['http'])
	async with Agent('Read the title', model, browser=browser, workspace=tmp_path) as agent:
		first = await agent.run()
		assert first.final_result() == 'Hi there' and first.is_done() and first.structured_output is None
		assert browser.name is None and agent._repl is None  # 0.x: run() stops the browser unless keep_alive
		agent.add_new_task('Now something else')
		second = await agent.run()
		assert second.final_result() == 'second answer' and second.steps == 1  # this run's steps only
		assert prompts(seen[-1]) == ['Read the title', 'Now something else']  # same transcript
	assert browser.name is None


async def test_keep_alive_keeps_browser_and_repl_between_runs(chrome, tmp_path):
	from browser_harness import admin

	model, _ = script(
		('python', {'code': 'x = 41'}),
		('finish', {'success': True, 'result': 'one'}),
		('finish_from_repl', {'success': True, 'expression': 'str(x + 1)'}),
	)
	browser = Browser(cdp_url=chrome['http'], keep_alive=True)
	agent = Agent('t', model, browser=browser, workspace=tmp_path)
	assert (await agent.run()).final_result() == 'one'
	name = browser.name
	assert name and admin.daemon_alive(name)
	agent.add_new_task('again')
	assert (await agent.run()).final_result() == '42'  # same REPL: variables survived
	await agent.close()
	assert admin.daemon_alive(name)  # keep_alive: the caller stops it
	await browser.stop()
	assert browser.name is None and not admin.daemon_alive(name)


async def test_structured_output(chrome, tmp_path):
	class Story(BaseModel):
		title: str
		points: int

	model, _ = script(('finish', {'success': True, 'result': {'title': 'x', 'points': 3}}))
	r = await Agent('t', model, browser=Browser(cdp_url=chrome['http']), output_model_schema=Story, workspace=tmp_path).run()
	assert r.structured_output == Story(title='x', points=3) and r.is_successful()


async def test_unfinished_run_has_no_final_result(chrome, tmp_path):
	model, _ = script(*[('python', {'code': '1'})] * 4)
	r = await Agent('t', model, browser=Browser(cdp_url=chrome['http']), workspace=tmp_path).run(max_steps=3)
	assert r.final_result() is None and not r.is_done() and r.is_successful() is None


async def test_your_chrome_end_to_end(chrome, tmp_path, monkeypatch):
	"""Browser('chrome') = the shared browser-harness daemon path; isolated here with its own name and Chrome."""
	from browser_harness import admin

	name = f'butestlocal{os.getpid()}'
	monkeypatch.setenv('BU_NAME', name)
	monkeypatch.setattr(admin, 'NAME', name)
	monkeypatch.setenv('BU_CDP_WS', chrome['ws'])
	model, _ = script(
		('python', {'code': "new_tab('data:text/html,<title>Local</title><h1>ok</h1>'); wait_for_load(); info = page_info()"}),
		('finish_from_repl', {'success': True, 'expression': "info['title']"}),
	)
	try:
		result = await Agent('Read the title', model, browser=Browser('chrome'), workspace=tmp_path).run()
		assert (result.status, result.final_result()) == ('completed', 'Local')
	finally:
		from browser_use.browser.browser import _shutdown_daemon

		_shutdown_daemon(name)  # Browser('chrome') never stops the shared local daemon itself


async def test_type_secret_types_value_and_output_is_redacted(chrome, tmp_path):
	model, seen = script(
		(
			'python',
			{
				'code': "new_tab('data:text/html,<input id=pw>'); wait_for_load(); js('document.getElementById(\"pw\").focus()'); "
				"type_secret('password'); print(secret_names(), js('document.getElementById(\"pw\").value'))"
			},
		),
		('finish', {'success': True, 'result': 'typed'}),
	)
	secret = 'hunter2-Zq9'
	agent = Agent(
		'Log in', model, browser=Browser(cdp_url=chrome['http']), sensitive_data={'password': secret}, workspace=tmp_path
	)
	result = await agent.run()
	from pydantic_ai.messages import ToolReturnPart

	out = [p for p in seen[1][-1].parts if isinstance(p, ToolReturnPart)][0].content[0]
	assert "['password'] <secret:password>" in out  # typed into the page, hidden from text output
	assert secret not in str(result.messages)
	assert 'type_secret' in str(seen[0])  # the prompt tells the model about it


def test_openai_settings_unchanged():
	"""The evaluated configuration must not drift. Non-reasoning OpenAI models get none of it (Fable r2-2: OpenAI 400s
	reasoning params on gpt-4.1/gpt-4o, and 32768 is above their output cap)."""
	agent = build_agent('openai-responses:gpt-6-luna', reasoning_effort='medium')
	assert agent.model_settings == {
		'openai_reasoning_effort': 'medium',
		'openai_reasoning_summary': 'auto',
		'openai_reasoning_context': 'auto',
		'max_tokens': 32_768,
	}
	assert build_agent('openai:gpt-4.1').model_settings == build_agent('openai:gpt-4o').model_settings == {}


def test_reasoning_on_a_chat_backend_warns_instead_of_silently_doing_nothing(monkeypatch, caplog):
	"""Fable r2-5: Agent(reasoning='high') with bu-auto or a base_url model changed nothing, without a word."""
	import logging

	from browser_use import ChatOpenAI

	monkeypatch.setenv('BROWSER_USE_API_KEY', 'fake-test-key')
	monkeypatch.setattr(logging.getLogger('browser_use'), 'propagate', True)  # caplog listens on the root logger
	llm = ChatOpenAI('m', api_key='x', base_url='http://localhost:11434/v1')
	Agent('t', llm, reasoning='high')._build()
	assert "reasoning='high' is ignored" in caplog.text
	caplog.clear()
	Agent('t', llm)._build()  # the default says nothing
	Agent('t', ChatOpenAI('gpt-6-luna', api_key='x'), reasoning='high')._build()
	assert 'ignored' not in caplog.text


async def test_remote_upload_sends_bytes(chrome, tmp_path):
	"""Cloud browsers can't read local paths: upload_file sends the file's bytes through the page."""
	browser = Browser(cdp_url=chrome['http'])
	repl = Repl(tmp_path, {**await browser.start(), 'BU_REMOTE_BROWSER': '1'})
	try:
		(tmp_path / 'cv.txt').write_text('hello cloud')
		r = await repl.call(
			'exec',
			"new_tab('data:text/html,<input type=file id=f>'); wait_for_load(); "
			"print(upload_file('#f', 'cv.txt'), js(\"document.getElementById('f').files[0].name + ':' "
			"+ document.getElementById('f').files[0].size\"))",
			60,
		)
		assert r['error'] is None and '1 cv.txt:11' in r['output'], r
	finally:
		await repl.close()
		await browser.stop()


async def test_local_upload_takes_relative_paths_and_refuses_what_is_not_a_file(chrome, tmp_path):
	"""H9: on a local browser upload_file passed the path to DOM.setFileInputFiles as is, so a relative, missing, ~ or
	directory path silently set a 0-byte file. Now a relative path is resolved from the workspace, the rest raise."""
	browser = Browser(cdp_url=chrome['http'])
	repl = Repl(tmp_path, await browser.start())
	try:
		(tmp_path / 'cv.txt').write_text('hello local')
		r = await repl.call(
			'exec',
			"new_tab('data:text/html,<input type=file id=f>'); wait_for_load(); upload_file('#f', 'cv.txt'); "
			"print(js(\"document.getElementById('f').files[0].name + ':' + document.getElementById('f').files[0].size\"))",
			60,
		)
		assert r['error'] is None and 'cv.txt:11' in r['output'], r
		for bad in ('missing.txt', '~/browser-use-no-such-file.txt', '.'):
			r = await repl.call('exec', f'upload_file("#f", {bad!r})', 60)
			assert r['error'] and 'FileNotFoundError: upload_file:' in r['error'] and 'is not a file' in r['error'], r
	finally:
		await repl.close()
		await browser.stop()


async def test_remote_upload_of_a_large_file_arrives_intact(chrome, tmp_path):
	"""browser-features #1 (P1): the whole file went to the daemon in one js() request, and the daemon reads at most
	64 KiB per request: every upload over about 48 KB failed with BrokenPipeError. Now it goes in parts."""
	import os

	def fnv1a(data: bytes) -> int:
		h = 0x811C9DC5
		for b in data:
			h = ((h ^ b) * 0x01000193) & 0xFFFFFFFF
		return h

	browser = Browser(cdp_url=chrome['http'])
	repl = Repl(tmp_path, {**await browser.start(), 'BU_REMOTE_BROWSER': '1'})
	try:
		data = os.urandom(1_000_003)
		(tmp_path / 'big.bin').write_bytes(data)
		(tmp_path / 'small.txt').write_text('hi')
		check = (
			"(async () => { const f = document.getElementById('f').files; const b = new Uint8Array(await "
			'f[0].arrayBuffer()); let h = 0x811c9dc5; for (const x of b) h = Math.imul(h ^ x, 0x01000193) >>> 0; '
			'return [f[0].name, f[0].size, h, f[1].name, f[1].size] })()'
		)
		r = await repl.call(
			'exec',
			"new_tab('data:text/html,<input type=file id=f multiple>'); wait_for_load()\n"
			"n = upload_file('#f', ['big.bin', 'small.txt'])\n"
			f'print(n, js({check!r}), js("Object.keys(window).filter(k => k.startsWith(\'__buUpload\')).length"))',
			120,
		)
		assert r['error'] is None, r
		assert f"2 ['big.bin', 1000003, {fnv1a(data)}, 'small.txt', 2] 0" in r['output'], r
	finally:
		await repl.close()
		await browser.stop()


async def test_a_request_too_large_for_the_daemon_raises_one_clear_error(chrome, tmp_path):
	"""browser-features #1: a js() expression over 64 KiB broke the daemon connection (BrokenPipeError, or 'Separator
	is found, but chunk is longer than limit')."""
	browser = Browser(cdp_url=chrome['http'])
	repl = Repl(tmp_path, await browser.start())
	try:
		r = await repl.call('exec', "print(js('1+' * 32_000 + '1'))", 60)  # 64,000 characters: works
		assert r['error'] is None and '32001' in r['output'], r
		r = await repl.call('exec', "js('1+' * 40_000 + '1')", 60)
		assert r['error_type'] == 'ValueError' and 'at most 64 KiB per request' in r['error'], r
		r = await repl.call('exec', 'print(js("1+1"))', 60)  # the daemon is fine afterwards
		assert r['output'].strip() == '2', r
	finally:
		await repl.close()
		await browser.stop()


async def test_a_dead_daemon_is_started_again_on_the_same_browser(chrome, tmp_path):
	"""Lifecycle F2: once the daemon died every cell failed with a raw ipc.connect traceback, start() handed back the
	dead daemon's env, and a keep_alive cloud browser kept billing. Now the cell says so in one line, the daemon is
	started again on the same browser, and the next cell works."""
	import os
	import signal

	from browser_harness import _ipc as ipc

	browser = Browser(cdp_url=chrome['http'])
	env = await browser.start()
	repl = Repl(tmp_path, env, reattach=browser.start)
	try:
		r = await repl.call('exec', "new_tab('data:text/html,<title>kept</title>'); wait_for_load(); print('ok')", 60)
		assert r['error'] is None, r
		assert browser.name
		pid = ipc.identify(browser.name)
		assert pid
		os.kill(pid, signal.SIGKILL)
		r = await repl.call('exec', 'page_info()', 60)
		assert r['error'].startswith('BrowserConnectionLost: browser connection lost'), r
		assert 'Traceback' not in r['error'] and 'started the daemon again' in r['error'], r
		assert ipc.identify(browser.name) not in (None, pid)
		r = await repl.call('exec', "print([t['title'] for t in list_tabs()])", 60)
		assert r['error'] is None and 'kept' in r['output'], r  # the same browser
		os.kill(ipc.identify(browser.name), signal.SIGKILL)
		assert await browser.start() == env and ipc.ping(browser.name)  # a follow-up run's start() too
	finally:
		await repl.close()
		await browser.stop()


async def test_a_browser_stopped_mid_run_is_never_replaced_or_retried_forever(chrome_binary, tmp_path):
	"""H6: once another Agent (or browser.stop()) stopped the Browser, every cell said "started the daemon again: retry"
	while the REPL kept the dead daemon's env, forever. Agent's reattach refuses (a new browser would bill and lose the
	tabs); a reattach that does hand back a new browser's env (Browser.start) moves the REPL to it."""
	browser = Browser('chromium', executable_path=chrome_binary, headless=True)
	env = await browser.start()
	repl = Repl(tmp_path, env, reattach=browser.reattach)
	try:
		assert (await repl.call('exec', 'print(1)', 60))['error'] is None
		await browser.stop()
		r = await repl.call('exec', "print(page_info()['url'])", 60)
		assert 'The browser was stopped while the agent ran' in r['error'] and 'Finish with what you have' in r['error'], r
		assert browser.name is None  # nothing started again
		repl.reattach = browser.start  # a caller that does want a new browser
		r = await repl.call('exec', "print(page_info()['url'])", 60)
		assert 'a new one started' in r['error'] and repl.env['BU_NAME'] == browser.name, r
		r = await repl.call('exec', "new_tab('about:blank'); print(page_info()['url'])", 60)
		assert r['error'] is None and 'about:blank' in r['output'], r
	finally:
		await repl.close()
		await browser.stop()


@pytest.mark.skipif(__import__('sys').platform == 'win32', reason='kills the process group')
async def test_a_chrome_we_launched_that_dies_mid_run_is_launched_again(chrome_binary, tmp_path):
	"""M13: Chrome crashing mid-run gave the model a raw RuntimeError ("no close frame received or sent"). C05: then the
	reattach dialed the dead Chrome, the model finished over http_get as status=completed (even success=True), and a
	keep_alive follow-up run's start() raised a raw RuntimeError. The Chrome this Browser launched is launched again."""
	import os
	import signal

	browser = Browser('chromium', executable_path=chrome_binary, headless=True)
	repl = Repl(tmp_path, await browser.start(), reattach=browser.reattach)
	try:
		assert (await repl.call('exec', "new_tab('about:blank')", 60))['error'] is None
		for _ in range(2):  # mid-run (the REPL's reattach), and again on the relaunched Chrome
			assert browser._local and browser._local.proc
			os.killpg(browser._local.proc.pid, signal.SIGKILL)  # Chrome crashes
			browser._local.proc.wait(10)
			r = await repl.call('exec', "print(page_info()['url'])", 60)
			assert r['error'].startswith('BrowserConnectionLost: browser connection lost: the browser ended'), r
			assert 'Traceback' not in r['error'] and 'a new one started' in r['error'] and not r.get('browser_gone'), r
			r = await repl.call('exec', "new_tab('data:text/html,<title>new</title>'); wait_for_load(); print(page_info())", 60)
			assert r['error'] is None and "'new'" in r['output'], r
		os.killpg(browser._local.proc.pid, signal.SIGKILL)  # between runs: a keep_alive follow-up run's start()
		browser._local.proc.wait(10)
		assert (await browser.start())['BU_NAME'] == browser.name and browser._local.proc.poll() is None
	finally:
		await repl.close()
		await browser.stop()


class _StallingProxy:
	"""TCP relay to the test Chrome. stall() freezes the connections open now (a stuck browser connection: the browser
	is fine); connections made later pass."""

	def __init__(self, port: int):
		import socket
		import threading

		self.target, self.stalled = port, []
		self.server = socket.create_server(('127.0.0.1', 0))
		self.port = self.server.getsockname()[1]
		threading.Thread(target=self._accept, daemon=True).start()

	def _accept(self) -> None:
		import socket
		import threading

		while True:
			try:
				client, _ = self.server.accept()
			except OSError:
				return
			upstream = socket.create_connection(('127.0.0.1', self.target))
			stall = threading.Event()
			self.stalled.append(stall)
			for a, b in ((client, upstream), (upstream, client)):
				threading.Thread(target=self._pipe, args=(a, b, stall), daemon=True).start()

	@staticmethod
	def _pipe(a, b, stall) -> None:
		import time

		try:
			while data := a.recv(65536):
				while stall.is_set():
					time.sleep(0.05)
				b.sendall(data)
		except OSError:
			pass

	def stall(self) -> None:
		for s in self.stalled:
			s.set()


async def test_a_stuck_cloud_daemon_is_replaced_without_stopping_its_cloud_browser(chrome, monkeypatch):
	"""Astra r1-1: a cloud daemon (BU_BROWSER_ID) whose browser connection got stuck. start() reattached through
	browser-harness's ensure_daemon, which shuts such a daemon down, and its shutdown stops the cloud browser that is
	still alive: the next run failed with "The browser is gone" and the user's browser was gone too."""
	import asyncio

	from browser_harness import _ipc as ipc
	from browser_harness import admin

	from browser_use.browser import browser as browser_mod
	from browser_use.harness_cloud import daemon_healthy

	monkeypatch.delenv('BROWSER_USE_API_KEY', raising=False)  # a cloud stop then fails on "no key", before any request
	port = chrome['http'].rsplit(':', 1)[1]
	proxy = _StallingProxy(int(port))
	browser = Browser(cdp_url=chrome['http'])
	browser.name = f'bustuck{os.getpid()}'
	browser._daemon_env = {
		'BU_CDP_WS': chrome['ws'].replace(f':{port}/', f':{proxy.port}/'),
		'BU_BROWSER_ID': 'no-such-browser',  # the daemon reports itself as cloud, as the library's cloud daemons do
		'BH_TAB_MARKER': '0',
	}
	admin.ensure_daemon(name=browser.name, env=browser._daemon_env)
	try:
		pid = ipc.identify(browser.name)
		assert pid and daemon_healthy(browser.name)
		proxy.stall()
		assert not daemon_healthy(browser.name)
		await asyncio.to_thread(browser._reattach)
		assert ipc.identify(browser.name) not in (None, pid) and daemon_healthy(browser.name)
		assert 'stop_remote' not in ipc.log_path(browser.name).read_text()
	finally:
		browser_mod._kill_daemon(browser.name)
		try:
			admin.restart_daemon(browser.name)
		except Exception:
			pass
		proxy.server.close()


RUNTIME_DIR_CHILD = """
import asyncio, json, os, sys, tempfile
from pathlib import Path
os.environ['BH_RUNTIME_DIR'] = sys.argv[2]
os.environ.pop('BH_RUNTIME_DIR_SHARED', None)
from browser_harness import _ipc as ipc
from browser_use import Browser
from browser_use.repl import Repl

async def main():
	a, b = Browser(cdp_url=sys.argv[1]), Browser(cdp_url=sys.argv[1])
	ea, eb = await a.start(), await b.start()
	out = {'pids': [ipc.identify(a.name), ipc.identify(b.name)], 'errors': []}
	ra, rb = Repl(Path(tempfile.mkdtemp()), ea), Repl(Path(tempfile.mkdtemp()), eb)
	try:
		for r, code in ((ra, "js('window.who = 1')"), (rb, "js('window.who = 2')")):
			out['errors'].append((await r.call('exec', code, 60))['error'])
		for r, key in ((ra, 'a_sees'), (rb, 'b_sees')):
			res = await r.call('exec', "print(js('window.who'))", 60)
			out[key] = res['output'].strip()
			out['errors'].append(res['error'])
	finally:
		await ra.close(); await rb.close(); await a.stop(); await b.stop()
	print(json.dumps(out))

asyncio.run(main())
"""


def test_parallel_browsers_with_bh_runtime_dir_never_share_a_daemon(chrome):
	"""browser-features #2: with BH_RUNTIME_DIR set (a short path for AF_UNIX) and no BH_RUNTIME_DIR_SHARED, every
	daemon listened on <dir>/bu.sock: parallel Browser()s drove the last one's browser."""
	import json
	import subprocess
	import sys
	import tempfile

	with tempfile.TemporaryDirectory(dir='/tmp' if sys.platform != 'win32' else None) as rt:
		r = subprocess.run(
			[sys.executable, '-c', RUNTIME_DIR_CHILD, chrome['http'], rt], capture_output=True, text=True, timeout=180
		)
	assert r.returncode == 0, r.stderr[-3000:]
	out = json.loads(r.stdout.strip().splitlines()[-1])
	assert None not in out['pids'] and out['pids'][0] != out['pids'][1], out
	assert (out['a_sees'], out['b_sees'], out['errors']) == ('1', '2', [None] * 4), out


@pytest.mark.parametrize('mode', ['ultrafast'])
async def test_ultrafast_agent_runs(chrome, tmp_path, mode):
	model, _ = script(
		('python', {'code': "new_tab('data:text/html,<button>Go</button>'); bu.state()"}),
		('finish', {'success': True, 'result': 'ok'}),
	)
	r = await Agent('t', model, browser=Browser(cdp_url=chrome['http']), mode=mode, workspace=tmp_path).run()
	assert r.final_result() == 'ok'


async def test_domain_check_ignores_what_page_js_reports(daemon, tmp_path):
	"""Roast r3-1: type_secret read the URL with page_info(), which runs the page's JSON.stringify; a page that
	overrides it reported an allowed URL and got the credential typed into its own field."""
	page = (
		'data:text/html,<input id=pw><script>const real = JSON.stringify; JSON.stringify = (v, ...a) => '
		"v && v.url !== undefined ? real({...v, url: 'https://site.test/login'}) : real(v, ...a)</script>"
	)
	repl = Repl(tmp_path, daemon, secrets={'https://site.test': {'pw': 'hunter2-Zq9'}})
	try:
		code = (
			f'new_tab({page!r}); wait_for_load(); js(\'document.getElementById("pw").focus()\')\n'
			"print(page_info()['url'])\ntype_secret('pw')"
		)
		r = await repl.call('exec', code, 30)
		typed = (await repl.call('exec', 'print(repr(js(\'document.getElementById("pw").value\')))', 30))['output']
	finally:
		await repl.close()
	assert 'https://site.test/login' in r['output'], r  # the page lies to page JS
	assert 'PermissionError' in (r['error'] or ''), r
	assert typed.strip() == "''"


async def test_type_secret_sends_key_events_so_key_driven_forms_see_it(daemon, tmp_path):
	"""Fable r4-3: type_secret used Input.insertText only (no key events); a login form that enables its submit button
	on keyup stayed disabled, and the model had no value to type another way. 0.x typed secrets with key events."""
	page = (
		'data:text/html,<input id=pw onkeyup="document.getElementById(\'go\').disabled = this.value.length < 8">'
		'<button id=go disabled>Log in</button>'
	)
	repl = Repl(tmp_path, daemon, secrets={'pw': 'Hunter2-Zq9!'})
	try:
		code = f"new_tab({page!r}); wait_for_load(); js('document.getElementById(\"pw\").focus()'); type_secret('pw')"
		r = await repl.call('exec', code, 30)
		state = await repl.call(
			'exec',
			'print(js(\'[document.getElementById("pw").value === "Hunter2-Zq9!", document.getElementById("go").disabled]\'))',
			30,
		)
	finally:
		await repl.close()
	assert r['error'] is None, r
	assert state['output'].strip() == '[True, False]', state


async def test_type_secret_types_tabs_newlines_and_non_ascii_exactly(daemon, tmp_path):
	"""Verify r4: per-character key events turned a tab in a secret into a Tab key (focus moved on and the rest of the
	secret landed in the next field, visible) and lost a newline and everything after it."""
	value = 'päss\tw€\U0001f600rd\nZq9'
	page = 'data:text/html,<textarea id=ta></textarea><input id=next>'
	repl = Repl(tmp_path, daemon, secrets={'pw': value})
	try:
		code = f"new_tab({page!r}); wait_for_load(); js('document.getElementById(\"ta\").focus()'); type_secret('pw')"
		r = await repl.call('exec', code, 30)
		read = f'print(js(\'document.getElementById("ta").value\') == {value!r}, repr(js(\'document.getElementById("next").value\')))'
		state = await repl.call('exec', read + '; close_tab()', 30)
	finally:
		await repl.close()
	assert r['error'] is None, r
	assert state['output'].strip() == "True ''", state


def serve(pages):
	"""A local HTTP server answering path -> HTML. Returns (server, port)."""
	import threading
	from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

	class Handler(BaseHTTPRequestHandler):
		def do_GET(self):
			body = pages.get(self.path, '').encode()
			self.send_response(200)
			self.send_header('Content-Type', 'text/html')
			self.send_header('Content-Length', str(len(body)))
			self.end_headers()
			self.wfile.write(body)

		def log_message(self, *a):
			pass

	server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
	threading.Thread(target=server.serve_forever, daemon=True).start()
	return server, server.server_address[1]


async def test_domain_scoped_secret_checks_the_frame_that_receives_it(daemon, tmp_path):
	"""Roast r4-3: type_secret checked the top page's URL, but the text goes to the focused frame: an allowed page with a
	focused attacker iframe (cross-site: its own process; or same-site, other port) received the credential."""
	# the frame moves focus into its input whenever it gets focus, as an attacker frame would
	frame = '<input id=f autofocus><script>addEventListener("focus", () => document.getElementById("f").focus())</script>'
	other, op = serve({'/frame': frame})
	pages = {
		'/cross-site': f'<input id=top><iframe id=i src="http://localhost:{op}/frame"></iframe>',
		'/same-site': f'<input id=top><iframe id=i src="http://127.0.0.1:{op}/frame"></iframe>',
		'/same-origin': '<input id=top><iframe id=i src="/frame"></iframe>',
		# the attacker iframe inside a closed shadow root: document.activeElement stops at the host
		'/shadow': (
			f'<div id=h></div><script>const r = document.getElementById("h").attachShadow({{mode: "closed"}}); '
			f'r.innerHTML = \'<iframe src="http://localhost:{op}/frame"></iframe>\'; '
			'window.focusFrame = () => r.querySelector("iframe").focus()</script>'
		),
		'/frame': frame,
	}
	site, sp = serve(pages)
	allowed, attacker = f'http://127.0.0.1:{sp}', f'http://localhost:{op}'
	repl = Repl(tmp_path, daemon, secrets={allowed: {'pw': 'hunter2-Zq9'}, attacker: {'tok': 'tok-Zq9'}})

	async def attempt(path, name, read):
		code = (
			f"new_tab('{allowed}{path}'); wait_for_load(); import time; time.sleep(1)\n"
			'js(\'window.focusFrame ? focusFrame() : document.getElementById("i").focus()\'); time.sleep(0.3)\n'
			f'type_secret({name!r})'
		)
		error = (await repl.call('exec', code, 30))['error'] or ''
		value = (await repl.call('exec', f'print(repr({read})); close_tab()', 30))['output'].strip()  # one frame per URL
		return 'PermissionError' in error, value

	cross = f"js('document.getElementById(\"f\").value', target_id=iframe_target('localhost:{op}'))"
	try:
		assert await attempt('/cross-site', 'pw', cross) == (True, "''")  # the attacker frame gets nothing
		# same site, other origin: one process, so read it through the frame tree
		same_site = await attempt('/same-site', 'pw', "'(cross-origin)'")
		same_origin = await attempt(
			'/same-origin', 'pw', 'js(\'document.getElementById("i").contentDocument.getElementById("f").value\')'
		)
		assert await attempt('/shadow', 'pw', cross) == (True, "''")
		allowed_frame = await attempt('/cross-site', 'tok', cross)  # the frame's own secret, on an unrelated top page
	finally:
		await repl.close()
		other.shutdown()
		site.shutdown()
	assert same_site[0] is True, same_site
	assert same_origin == (False, "'<secret:pw>'"), same_origin
	assert allowed_frame == (False, "'<secret:tok>'"), allowed_frame


async def test_type_secret_with_no_focused_field_raises(daemon, tmp_path):
	"""M35: type_secret() with nothing focused typed the value into <body> and returned None, so the agent believed the
	field was filled."""
	repl = Repl(tmp_path, daemon, secrets={'pw': 'hunter2-Zq9'})
	try:
		r = await repl.call('exec', "new_tab('data:text/html,<input id=pw>'); wait_for_load(); type_secret('pw')", 60)
		assert "type_secret('pw'): no field is focused (the page <body> is)" in (r['error'] or ''), r
		code = "js('document.getElementById(\"pw\").focus()'); type_secret('pw'); print(len(js('document.getElementById(\"pw\").value')))"
		r = await repl.call('exec', code, 60)
		assert r['error'] is None and '11' in r['output'], r
		# review: a focused button, read-only or disabled-looking input, or contenteditable="false" took the keys too
		page = (
			'data:text/html,<button id=b>b</button><input id=ro readonly><div id=no contenteditable=false tabindex=0>x</div>'
			'<input id=chk type=checkbox><div id=ce contenteditable></div><textarea id=ta></textarea>'
		)
		r = await repl.call('exec', f'new_tab({page!r}); wait_for_load()', 60)
		for el, tag in (('b', 'button'), ('ro', 'input'), ('no', 'div'), ('chk', 'input')):
			r = await repl.call('exec', f"js('document.getElementById(\"{el}\").focus()'); type_secret('pw')", 60)
			assert f"type_secret('pw'): the focused <{tag}> is not an editable field" in (r['error'] or ''), (el, r)
		for el, prop in (('ce', 'textContent'), ('ta', 'value')):
			code = f"js('document.getElementById(\"{el}\").focus()'); type_secret('pw'); print(len(js('document.getElementById(\"{el}\").{prop}')))"
			r = await repl.call('exec', code, 60)
			assert r['error'] is None and '11' in r['output'], (el, r)
	finally:
		await repl.close()


async def test_bu_2fa_code_secret_types_the_current_totp_code_not_the_seed(daemon, tmp_path):
	"""Roast r6-1: 0.x turned sensitive_data={'bu_2fa_code': seed} into a 6-digit TOTP code; 1.0 typed the raw seed, so
	login failed and the page received the reusable 2FA secret."""
	import re

	seed = 'JBSWY3DPEHPK3PXP'
	page = 'data:text/html,<input id=otp>'
	repl = Repl(tmp_path, daemon, secrets={'bu_2fa_code': seed})
	try:
		code = f"new_tab({page!r}); wait_for_load(); js('document.getElementById(\"otp\").focus()'); type_secret('bu_2fa_code')"
		r = await repl.call('exec', code, 30)
		typed = await repl.call('exec', 'print(js(\'document.getElementById("otp").value\'))', 30)
	finally:
		await repl.close()
	assert r['error'] is None, r
	value = typed['output'].strip()
	assert seed not in value and re.fullmatch(r'\d{6}', value), typed


def test_totp_matches_rfc6238():
	from browser_use.repl.worker import totp

	seed = 'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ'  # RFC 6238 SHA-1 key '12345678901234567890'
	assert [totp(seed, now=t) for t in (59, 1111111109, 1234567890)] == ['287082', '081804', '005924']


def test_localhost_task_with_a_cloud_browser_warns_instead_of_refusing(monkeypatch, caplog):
	"""A cloud browser cannot reach localhost, but the task may only mention it (docs, a version number): a hint only."""
	import logging

	monkeypatch.setenv('BROWSER_USE_API_KEY', 'fake-test-key')
	monkeypatch.setattr(logging.getLogger('browser_use'), 'propagate', True)  # caplog listens on the root logger
	agent = Agent('Test the signup form on http://localhost:3000', 'test', browser=Browser())
	with caplog.at_level('WARNING', logger='browser_use.agent.service'):
		agent._check_task()
	assert "'localhost'" in caplog.text and "Browser('chromium')" in caplog.text
