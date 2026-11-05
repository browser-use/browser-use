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
		('finish_from_repl', {'expression': 'title'}),
		('finish', {'result': 'second answer'}),
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
		('finish', {'result': 'one'}),
		('finish_from_repl', {'expression': 'str(x + 1)'}),
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

	model, _ = script(('finish', {'result': {'title': 'x', 'points': 3}}))
	r = await Agent('t', model, browser=Browser(cdp_url=chrome['http']), output_model_schema=Story, workspace=tmp_path).run()
	assert r.structured_output == Story(title='x', points=3) and r.is_successful()


async def test_unfinished_run_has_no_final_result(chrome, tmp_path):
	model, _ = script(*[('python', {'code': '1'})] * 3)
	r = await Agent('t', model, browser=Browser(cdp_url=chrome['http']), workspace=tmp_path).run(max_steps=2)
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
		('finish_from_repl', {'expression': "info['title']"}),
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
		('finish', {'result': 'typed'}),
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


@pytest.mark.parametrize('mode', ['ultrafast'])
async def test_ultrafast_agent_runs(chrome, tmp_path, mode):
	model, _ = script(
		('python', {'code': "new_tab('data:text/html,<button>Go</button>'); bu.state()"}),
		('finish', {'result': 'ok'}),
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
