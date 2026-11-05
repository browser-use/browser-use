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


async def test_local_browser_end_to_end(chrome, tmp_path, monkeypatch):
	"""Browser(local=True) = the browser-harness daemon path; isolated here with its own name and Chrome."""
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
		result = await Agent('Read the title', model, browser=Browser(local=True), workspace=tmp_path).run()
		assert (result.status, result.final_result()) == ('completed', 'Local')
	finally:
		from browser_use.browser.browser import _shutdown_daemon

		_shutdown_daemon(name)  # Browser(local=True) never stops the shared local daemon itself


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
		state = await repl.call('exec', "print(js('[document.getElementById(\"pw\").value === \"Hunter2-Zq9!\", document.getElementById(\"go\").disabled]'))", 30)
	finally:
		await repl.close()
	assert r['error'] is None, r
	assert state['output'].strip() == '[True, False]', state

