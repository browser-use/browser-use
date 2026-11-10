"""Public API (Agent, Browser) against a real isolated headless Chrome, scripted model (no provider calls)."""

import asyncio
import json
import os
import re
import sys
import time

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


async def test_secret_the_model_quotes_is_redacted_in_result_messages_but_not_the_follow_up(chrome, tmp_path):
	"""C43: the model read a secret off a screenshot and quoted it in thinking, text and finish args; every channel was
	redacted except result.messages. The follow-up still gets the raw transcript: providers reject edited signed thinking."""
	from pydantic_ai.messages import ModelResponse, TextPart, ThinkingPart, ToolCallPart
	from pydantic_ai.models.function import FunctionModel

	secret, seen = 'hunter2-Zq9', []

	def fn(messages, info):
		seen.append(messages)
		if len(seen) == 1:
			return ModelResponse(
				parts=[
					ThinkingPart(f'the screenshot shows {secret}', signature='sig'),
					TextPart(f'Password is {secret}'),
					ToolCallPart('finish', {'success': True, 'result': f'pw {secret}'}),
				]
			)
		return ModelResponse(parts=[ToolCallPart('finish', {'success': True, 'result': 'second'})])

	agent = Agent('t', FunctionModel(fn), browser=Browser(cdp_url=chrome['http']), workspace=tmp_path,
				  sensitive_data={'pw': secret})  # fmt: skip
	first = await agent.run()
	assert first.final_result() == 'pw <secret:pw>'
	assert secret not in str(first.messages) and str(first.messages).count('<secret:pw>') == 3, first.messages
	agent.add_new_task('again')
	second = await agent.run()
	assert second.final_result() == 'second' and secret not in str(second.messages)
	assert f'the screenshot shows {secret}' in str(seen[1])  # the provider gets its own unedited parts back


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


async def test_a_keep_alive_browser_whose_daemon_died_between_runs_starts_in_the_agents_tab(chrome, tmp_path):
	"""browser-1 follow-up: the daemon of a Browser(keep_alive=True) died between runs; start() started it again, its new
	blank tab became the attached one, and the next run (the same Agent's follow-up, or a new Agent) saw about:blank:
	the agent's page and form state out of reach. The Browser remembers the agent's tab and attaches it again."""
	import signal

	from browser_harness import _ipc as ipc

	where = 'f"{page_info()[\'title\']} {len(list_tabs())}"'
	model, _ = script(
		('python', {'code': "new_tab('data:text/html,<title>kept</title>'); wait_for_load()"}),
		('finish_from_repl', {'success': True, 'expression': where}),
		('finish_from_repl', {'success': True, 'expression': where}),
		('finish_from_repl', {'success': True, 'expression': where}),
	)
	browser = Browser(cdp_url=chrome['http'], keep_alive=True)
	agent = Agent('t', model, browser=browser, workspace=tmp_path)
	try:
		first = (await agent.run()).final_result()
		assert first and first.startswith('kept '), first
		os.kill(ipc.identify(browser.name), signal.SIGKILL)
		agent.add_new_task('again')
		assert (await agent.run()).final_result() == first  # the same Agent's follow-up
		await agent.close()
		os.kill(ipc.identify(browser.name), signal.SIGKILL)
		agent = Agent('t', model, browser=browser, workspace=tmp_path / 'b')
		assert (await agent.run()).final_result() == first  # a new Agent on the same Browser
	finally:
		await agent.close()
		await browser.stop()


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


async def test_a_run_logs_task_each_step_and_the_end(chrome, tmp_path, monkeypatch, caplog):
	"""C08: a run printed nothing at INFO or DEBUG, and the 0.x step callbacks have no live replacement."""
	import logging

	monkeypatch.setattr(logging.getLogger('browser_use'), 'propagate', True)  # caplog listens on the root logger
	model, _ = script(
		('python', {'code': '\npw = "hunter22"\n1 / 0'}),
		('finish', {'success': True, 'result': 'done'}),
	)
	agent = Agent('Log in with hunter22', model, browser=Browser(cdp_url=chrome['http']), workspace=tmp_path,
				  sensitive_data={'pw': 'hunter22'})  # fmt: skip
	with caplog.at_level('INFO', logger='browser_use'):
		assert (await agent.run()).final_result() == 'done'
	lines = [r.getMessage() for r in caplog.records if r.name.startswith('browser_use.agent')]
	assert lines[:2] == [
		f'Task: Log in with <secret:pw> (workspace {tmp_path.resolve()})',
		'step 1: pw = "<secret:pw>" -> ZeroDivisionError: division by zero',
	], lines
	assert re.fullmatch(r'completed in 2 steps, \d+s', lines[2]) and len(lines) == 3, lines


async def test_a_page_exception_in_the_step_log_cannot_drive_the_terminal(chrome, tmp_path, monkeypatch, caplog):
	"""INJ-1: a page's JS exception text reached the step log line raw, so ESC sequences in it erased or faked terminal
	lines, set the window title or (OSC 52) wrote the clipboard. Control characters are shown escaped instead."""
	import logging

	root = logging.getLogger('browser_use')
	monkeypatch.setattr(root, 'propagate', True)  # caplog listens on the root logger
	# what a page's own script throws (any DOM method the agent calls can be overridden to): ESC ]0; sets the title,
	# ESC [2K erases the line. The model's code holds no escape: the page builds it.
	esc = "String.fromCharCode(27) + ']0;PWNED' + String.fromCharCode(7) + String.fromCharCode(27) + '[2KFAKE'"
	model, _ = script(
		('python', {'code': f'new_tab("about:blank")\njs("throw {esc}")'}), ('finish', {'success': True, 'result': 'done'})
	)
	agent = Agent('t', model, browser=Browser(cdp_url=chrome['http']), workspace=tmp_path)
	with caplog.at_level('INFO', logger='browser_use'):
		await agent.run()
	(record,) = (r for r in caplog.records if r.getMessage().startswith('step 1:'))
	assert '\\x1b]0;PWNED\\x07\\x1b[2KFAKE' in record.getMessage() and '\x1b' not in record.getMessage(), record.getMessage()
	(handler,) = (h for h in root.handlers if isinstance(h, logging.StreamHandler) and h is not caplog.handler)
	raw = logging.makeLogRecord({'name': 'browser_use.x', 'levelname': 'INFO', 'msg': 'page said \x1b]52;c;ZWNobw==\x07\x9b2K'})
	assert handler.format(raw).endswith('page said \\x1b]52;c;ZWNobw==\\x07\\x9b2K')  # any browser_use line, C1 too


async def test_your_chrome_reads_titles_unmarked_on_a_daemon_that_marks_them(chrome, tmp_path, monkeypatch):
	"""Retest round 2: after `browser-use` (CLI) or an older wheel started the shared daemon with browser-harness's
	default BH_TAB_MARKER, Browser('chrome') reused it (it cannot change a running daemon's env) and answered 'What is
	the title of https://example.com?' with '🐴 Example Domain'. The daemon re-marks the attached tab after every load."""
	from browser_harness import admin

	name = f'butestmarked{os.getpid()}'
	monkeypatch.setenv('BU_NAME', name)
	monkeypatch.setattr(admin, 'NAME', name)
	monkeypatch.setenv('BU_CDP_WS', chrome['ws'])
	from browser_use.browser.browser import _daemon_cdp, _daemon_request, _shutdown_daemon

	admin.ensure_daemon(name=name, env={'BH_TAB_MARKER': '1'})  # what the CLI / MCP / browser-harness itself start
	# The tab that daemon already drives and marked (a CLI call left it there): the agent starts on it.
	tab = _daemon_cdp(name, 'Target.createTarget', url='data:text/html,<title>Before</title><h1>ok</h1>')['targetId']
	sid = _daemon_cdp(name, 'Target.attachToTarget', targetId=tab, flatten=True)['sessionId']
	_daemon_request(name, {'meta': 'set_session', 'session_id': sid, 'target_id': tab})
	deadline = time.time() + 5
	while not _daemon_cdp(name, 'Runtime.evaluate', expression='document.title')['result']['value'].startswith('\U0001f434'):
		assert time.time() < deadline, 'the daemon never marked the tab'
		await asyncio.sleep(0.05)
	# The daemon marks fire-and-forget after each load event: poll 2 s for a mark that, before the fix, always came.
	code = (
		"titles = [page_info()['title'], js('document.title')]\n"  # the page it started on
		"new_tab('data:text/html,<title>Local</title><h1>ok</h1>'); wait_for_load()\n"
		'import time\n'
		'deadline = time.time() + 2\n'
		"while time.time() < deadline and not js('document.title').startswith('\\U0001F434'):\n"
		'    time.sleep(0.05)\n'
		"goto_url('data:text/html,<title>Next</title><h1>ok</h1>'); wait_for_load()\n"  # a later load in the same tab
		'deadline = time.time() + 2\n'
		"while time.time() < deadline and not js('document.title').startswith('\\U0001F434'):\n"
		'    time.sleep(0.05)\n'
		"tab = current_tab()['targetId']\n"
		"titles += [page_info()['title'], js('document.title'), current_tab()['title'],\n"
		"           [t['title'] for t in list_tabs() if t['targetId'] == tab][0]]"
	)
	model, _ = script(('python', {'code': code}), ('finish_from_repl', {'success': True, 'expression': 'titles'}))
	try:
		result = await Agent('Read the title', model, browser=Browser('chrome'), workspace=tmp_path).run()
		assert (result.status, json.loads(result.final_result() or '')) == ('completed', ['Before'] * 2 + ['Next'] * 4)
	finally:
		_shutdown_daemon(name)


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


async def test_your_chrome_reads_page_titles_unmarked(chrome, tmp_path, monkeypatch):
	"""Retest2 clean install: Browser('chrome') answered 'What is the title of https://example.com?' with '🐴 Example
	Domain'. The shared daemon it started inherited browser-harness's default BH_TAB_MARKER, so every page load got the
	horse prefix in document.title, page_info() and js(). This user environment has no BH_TAB_MARKER (conftest sets 0)."""
	from browser_harness import admin

	name = f'butestmark{os.getpid()}'
	monkeypatch.setenv('BU_NAME', name)
	monkeypatch.setattr(admin, 'NAME', name)
	monkeypatch.setenv('BU_CDP_WS', chrome['ws'])
	monkeypatch.delenv('BH_TAB_MARKER')
	# The daemon marks a tab fire-and-forget after its load event: poll 2 s for a mark that, before the fix, always came.
	code = (
		"new_tab('data:text/html,<title>Local</title><h1>ok</h1>'); wait_for_load()\n"
		'import time\n'
		'deadline = time.time() + 2\n'
		"while time.time() < deadline and not js('document.title').startswith('\\U0001F434'):\n"
		'    time.sleep(0.05)\n'
		"titles = [page_info()['title'], js('document.title')]"
	)
	model, _ = script(('python', {'code': code}), ('finish_from_repl', {'success': True, 'expression': 'titles'}))
	try:
		result = await Agent('Read the title', model, browser=Browser('chrome'), workspace=tmp_path).run()
		assert (result.status, result.final_result()) == ('completed', '["Local", "Local"]')
	finally:
		from browser_use.browser.browser import _shutdown_daemon

		_shutdown_daemon(name)


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
		'openai_store': False,
		'openai_reasoning_effort': 'medium',
		'openai_reasoning_summary': 'auto',
		'openai_reasoning_context': 'auto',
		'max_tokens': 32_768,
	}
	assert build_agent('openai:gpt-4.1').model_settings == build_agent('openai:gpt-4o').model_settings == {'openai_store': False}


def test_an_agent_that_never_runs_leaves_no_temp_workspace(monkeypatch, tmp_path):
	"""C59: every Agent() made a browser-use-* dir in $TMPDIR at construction, so scripts that only build agents (or
	reject a schema) left thousands of empty dirs. The default workspace is now made on first use, once."""
	import tempfile

	from browser_use import ChatOpenAI

	monkeypatch.setattr(tempfile, 'tempdir', str(tmp_path))
	llm = ChatOpenAI('gpt-6-luna', api_key='x')
	for _ in range(3):
		Agent('t', llm)
	assert list(tmp_path.iterdir()) == []
	agent = Agent('t', llm)
	assert agent.workspace == agent.workspace and agent.workspace.is_dir() and agent.workspace.parent == tmp_path
	assert len(list(tmp_path.iterdir())) == 1
	custom = tmp_path / 'mine'
	assert Agent('t', llm, workspace=custom).workspace == custom and not custom.exists()  # made by run()


def test_the_workspace_keeps_the_path_as_given(tmp_path, monkeypatch):
	"""Examples run: on macOS tempfile.mkdtemp() returns /var/... (a symlink to /private/var), Agent resolved it, and
	result.downloads[0].relative_to(workspace) raised ValueError. The workspace is the path as given, made absolute."""
	import tempfile

	from browser_use import ChatOpenAI

	(tmp_path / 'real').mkdir()
	(tmp_path / 'link').symlink_to(tmp_path / 'real', target_is_directory=True)
	llm = ChatOpenAI('gpt-6-luna', api_key='x')
	assert Agent('t', llm, workspace=tmp_path / 'link' / 'ws').workspace == tmp_path / 'link' / 'ws'
	monkeypatch.setattr(tempfile, 'tempdir', str(tmp_path / 'link'))
	assert Agent('t', llm).workspace.parent == tmp_path / 'link'


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


@pytest.fixture
def remote_host(chrome):
	"""A CDP endpoint that rejects local file paths as Browser Use cloud does: the browser runs on another host."""
	import contextlib
	import threading

	from websockets.sync.client import connect
	from websockets.sync.server import serve

	def relay(client):
		with connect(chrome['ws'], max_size=None) as upstream:

			def down():
				with contextlib.suppress(Exception):  # either side closed
					for message in upstream:
						client.send(message)

			threading.Thread(target=down, daemon=True).start()
			for message in client:
				msg = json.loads(message)
				if msg.get('method') == 'DOM.setFileInputFiles' and msg.get('params', {}).get('files'):
					error = {'code': -32602, 'message': 'Files must exist in the downloads directory'}
					client.send(
						json.dumps(
							{'id': msg['id'], 'error': error, **({'sessionId': msg['sessionId']} if 'sessionId' in msg else {})}
						)
					)
				else:
					upstream.send(message)

	server = serve(relay, '127.0.0.1', 0, max_size=None)
	threading.Thread(target=server.serve_forever, daemon=True).start()
	yield f'ws://127.0.0.1:{server.socket.getsockname()[1]}/devtools/browser/remote'
	server.shutdown()


@pytest.mark.parametrize('cloud', [False, True])
async def test_local_paths_upload_on_a_browser_on_another_host(remote_host, tmp_path, cloud):
	"""Browser(cdp_url=<remote>) used DOM.setFileInputFiles with the local path, which the host rejects: upload_file
	failed. On the cloud default, bu's recipe cdp('DOM.setFileInputFiles', backendNodeId=...) failed the same way.
	Both now send the bytes through the page."""
	browser = Browser(cdp_url=remote_host)
	env = await browser.start()
	repl = Repl(tmp_path, {**env, 'BU_REMOTE_BROWSER': '1'} if cloud else env)
	size = "js(\"[...document.getElementById('f').files].map(f => f.name + ':' + f.size).join()\")"
	try:
		(tmp_path / 'cv.txt').write_text('hello remote')
		r = await repl.call(
			'exec',
			"import os\nnew_tab('data:text/html,<input type=file id=f multiple>'); wait_for_load()\n"
			f"print(upload_file('#f', 'cv.txt'), {size})\n"
			"node = cdp('DOM.getDocument')['root']['nodeId']\n"
			"node = cdp('DOM.querySelector', nodeId=node, selector='#f')['nodeId']\n"
			"backend = cdp('DOM.describeNode', nodeId=node)['node']['backendNodeId']\n"
			"cdp('DOM.setFileInputFiles', backendNodeId=backend, files=[os.path.abspath('cv.txt'), 'cv.txt'])\n"
			f'print({size})',
			60,
		)
		assert r['error'] is None and r['output'].split() == ['1', 'cv.txt:12', 'cv.txt:12,cv.txt:12'], r
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


async def test_remote_upload_has_no_size_cap(chrome, tmp_path):
	"""C29: files over 10MB raised ValueError, so the model hand-rolled the same page upload one js() per turn (758
	calls, 147s for 25MB). The parts already go 8 at a time, so any size goes through upload_file."""
	browser = Browser(cdp_url=chrome['http'])
	repl = Repl(tmp_path, {**await browser.start(), 'BU_REMOTE_BROWSER': '1'})
	try:
		(tmp_path / 'big.bin').write_bytes(b'\x00' * 10_000_000 + b'end')
		r = await repl.call(
			'exec',
			"new_tab('data:text/html,<input type=file id=f>'); wait_for_load()\n"
			"print(upload_file('#f', 'big.bin'), js(\"document.getElementById('f').files[0].size\"))",
			120,
		)
		assert r['error'] is None and '1 10000003' in r['output'], r
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
	started again on the same browser, and the next cell works in the agent's tab (the new daemon's own blank tab is
	closed): it was on about:blank, the agent's page and form state out of reach."""
	import os
	import signal

	from browser_harness import _ipc as ipc

	browser = Browser(cdp_url=chrome['http'])
	env = await browser.start()
	repl = Repl(tmp_path, env, reattach=browser.start)
	try:
		r = await repl.call('exec', "new_tab('data:text/html,<title>kept</title>'); wait_for_load(); print(len(list_tabs()))", 60)
		assert r['error'] is None, r
		tabs = r['output'].strip()
		assert browser.name
		pid = ipc.identify(browser.name)
		assert pid
		os.kill(pid, signal.SIGKILL)
		r = await repl.call('exec', 'page_info()', 60)
		assert r['error'].startswith('BrowserConnectionLost: browser connection lost'), r
		assert 'Traceback' not in r['error'] and 'started the daemon again' in r['error'], r
		assert ipc.identify(browser.name) not in (None, pid)
		r = await repl.call('exec', "print(page_info()['title'], len(list_tabs()))", 60)
		assert r['error'] is None and r['output'].strip() == f'kept {tabs}', r  # the agent's tab, no extra blank tab
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


async def test_type_secret_by_id_replaces_the_fields_text(daemon, tmp_path):
	"""C15: ultrafast teaches bu.type(id, text) but type_secret took no id, so the model wrote bu.type(8, 'pw') and
	submitted the secret's name as the password. type_secret(name, id) is Pi's fillSecret(name, backendNodeId)."""
	page = 'data:text/html,<input id=user><input id=pw value=junk>'
	repl = Repl(tmp_path, daemon, secrets={'pw': 'Hunter2-Zq9!'}, mode='ultrafast')
	try:
		node = "cdp('DOM.querySelector', nodeId=cdp('DOM.getDocument')['root']['nodeId'], selector='#pw')['nodeId']"
		code = (
			f'new_tab({page!r}); wait_for_load(); js(\'document.getElementById("user").focus()\')\n'
			f"type_secret('pw', cdp('DOM.describeNode', nodeId={node})['node']['backendNodeId'])"
		)
		r = await repl.call('exec', code, 30)
		state = await repl.call('exec', 'print(js(\'[document.getElementById("pw").value === "Hunter2-Zq9!"]\'))', 30)
	finally:
		await repl.close()
	assert r['error'] is None, r
	assert state['output'].strip() == '[True]', state


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


def serve_slow(pages, slow_s):
	"""serve(), plus /slow answering after slow_s seconds and .js paths as JavaScript. Returns (server, port, answered):
	answered gets the time.time() each /slow answer was sent."""
	import threading
	import time
	from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

	answered = []

	class Handler(BaseHTTPRequestHandler):
		def do_GET(self):
			if self.path == '/slow':
				time.sleep(slow_s)
			body = pages.get(self.path, 'done').format(port=self.server.server_address[1]).encode()
			self.send_response(200)
			self.send_header('Content-Type', 'text/javascript' if self.path.endswith('.js') else 'text/html')
			self.send_header('Content-Length', str(len(body)))
			self.end_headers()
			self.wfile.write(body)
			if self.path == '/slow':
				answered.append(time.time())

		def log_message(self, *a):
			pass

	server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
	threading.Thread(target=server.serve_forever, daemon=True).start()
	return server, server.server_address[1], answered


@pytest.mark.parametrize('mode', ['default', 'ultrafast'])
async def test_network_idle_ignores_workers_and_cross_site_iframes_but_waits_for_requests(daemon, tmp_path, mode):
	"""browser-4: browser-harness 0.1.13's wait_for_network_idle() waited for a worker's script and an out-of-process
	iframe's document, which start on the tab but finish on their own target: it ran to its 10 s cap on any page with a
	Web Worker or a cross-site (ad, captcha, chat) iframe. A real request still holds it until it finishes, also one of
	an iframe that came back in process."""
	blob = "URL.createObjectURL(new Blob(['1'], {{type: 'text/javascript'}}))"
	pages = {  # localhost is another site than 127.0.0.1: Chrome loads that iframe in its own process
		'/page': f"<h1>page</h1><iframe src='http://localhost:{{port}}/child'></iframe><script>new Worker({blob}); "
		"new Worker('/w.js'); new SharedWorker(" + blob + ')</script>',
		'/child': '<p>child</p>',
		'/w.js': '1',
		# the iframe starts out of process, then comes back in process and loads a slow image
		'/swap': "<iframe src='http://localhost:{port}/child' onload=\"this.onload = null; this.src = '/slow-image'\"></iframe>",
		'/slow-image': '<img src="/slow">',
	}
	server, port, answered = serve_slow(pages, 3)
	repl = Repl(tmp_path, daemon, mode=mode)
	# a busy machine slows the requests themselves: the cap is raised, and the slow request's answer time is compared
	timed = (
		'import time\nt = time.monotonic(); ok = wait_for_network_idle(timeout=30); print(ok, time.monotonic() - t, time.time())'
	)
	try:
		r = await repl.call('exec', f"new_tab('http://127.0.0.1:{port}/page'); wait_for_load()\n{timed}", 90)
		ok, s, _ = r['output'].split()
		assert r['error'] is None and ok == 'True' and float(s) < 5, r  # 0.5 s; the 0.13 helper: its 10 s cap
		for code in ('js("void fetch(\'/slow\')")', f"goto_url('http://127.0.0.1:{port}/swap')"):
			answered.clear()
			r = await repl.call('exec', f'{code}\n{timed}', 90)
			ok, _, idle_at = r['output'].split()
			assert r['error'] is None and ok == 'True' and len(answered) == 1 and float(idle_at) > answered[0], (code, r)
		await repl.call('exec', 'close_tab()', 30)
	finally:
		await repl.close()
		server.shutdown()


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

	# focus the <iframe> element (a page without OS focus never runs the frame's focus handler) or, for a secret
	# that may type, the frame's own input
	async def attempt(path, name, read, focus='js(\'window.focusFrame ? focusFrame() : document.getElementById("i").focus()\')'):
		code = f"new_tab('{allowed}{path}'); wait_for_load(); import time; time.sleep(1)\n{focus}; time.sleep(0.3)\ntype_secret({name!r})"
		error = (await repl.call('exec', code, 30))['error'] or ''
		value = (await repl.call('exec', f'print(repr({read})); close_tab()', 30))['output'].strip()  # one frame per URL
		return 'PermissionError' in error, value

	cross = f"js('document.getElementById(\"f\").value', target_id=iframe_target('localhost:{op}'))"
	try:
		assert await attempt('/cross-site', 'pw', cross) == (True, "''")  # the attacker frame gets nothing
		# same site, other origin: one process, so read it through the frame tree
		same_site = await attempt('/same-site', 'pw', "'(cross-origin)'")
		inner = 'document.getElementById("i").contentDocument.getElementById("f")'
		same_origin = await attempt('/same-origin', 'pw', f"js('{inner}.value')", focus=f"js('{inner}.focus()')")
		assert await attempt('/shadow', 'pw', cross) == (True, "''")
		# the frame's own secret, on an unrelated top page
		focus_frame_input = cross.replace('.value', '.focus()')
		allowed_frame = await attempt('/cross-site', 'tok', cross, focus=focus_frame_input)
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
		# C27: focus inside an iframe skipped both checks, so a focused frame without a field "typed" and the form posted
		# empty; a field inside the frame still types
		page = 'data:text/html,<iframe id=f srcdoc="<input id=i>"></iframe><iframe id=e srcdoc="<p>no field</p>"></iframe>'
		field = 'document.getElementById("f").contentDocument.getElementById("i")'
		r = await repl.call('exec', f"new_tab({page!r}); wait_for_load(); js('{field}.focus()'); type_secret('pw')", 60)
		assert r['error'] is None, r
		assert '11' in (await repl.call('exec', f"print(len(js('{field}.value')))", 60))['output']
		r = await repl.call('exec', "js('document.getElementById(\"e\").focus()'); type_secret('pw')", 60)
		assert "type_secret('pw'): no field is focused (the page <body> is)" in (r['error'] or ''), r
	finally:
		await repl.close()


async def test_a_secret_placeholder_typed_into_the_page_raises_and_names_type_secret(daemon, tmp_path):
	"""Live (0.x sensitive-data template, gpt-4.1-mini, 2 of 3 runs): the model typed the literal '<secret:x_user>' into
	the form, read the field back (redacted output shows the real value the same way) and reported "Wrong credentials".
	0.x replaced <secret>name</secret> with the value; 1.0 sent the placeholder to the page as the password."""
	page = 'data:text/html,<input id=u><input id=p type=password>'
	repl = Repl(tmp_path, daemon, secrets={'x_user': 'alice@example.com', 'x_pass': 'hunter2-Secret!'})
	try:
		await repl.call('exec', f'new_tab({page!r}); wait_for_load(); js(\'document.getElementById("u").focus()\')', 60)
		for code in (
			"cdp('Input.insertText', text='<secret:x_user>')",
			"type_text('<secret>x_pass</secret>')",
			'js(\'document.getElementById("p").value = "<secret:x_pass>"\')',
		):
			r = await repl.call('exec', code, 60)
			assert "is not replaced with the secret: type it with type_secret('x_" in (r['error'] or ''), (code, r)
		typed = await repl.call(
			'exec', 'print(js(\'[document.getElementById("u").value, document.getElementById("p").value]\'))', 60
		)
		assert typed['output'].strip() == "['', '']", typed
		r = await repl.call(
			'exec', "type_text('<secret:other> stays literal'); print(js('document.getElementById(\"u\").value'))", 60
		)
		assert r['error'] is None and '<secret:other> stays literal' in r['output'], r  # not a secret name: plain text
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


@pytest.mark.parametrize('remote', [False, True])
async def test_upload_reaches_inputs_in_frames_and_shadow_roots(chrome, tmp_path, remote):
	"""C28: upload_file searched only the top document, so an uploader in a same-origin iframe or an open shadow root
	raised 'no element for ...' and the agent hand-wrote DataTransfer js for 3-6 steps."""
	browser = Browser(cdp_url=chrome['http'])
	repl = Repl(tmp_path, {**await browser.start(), **({'BU_REMOTE_BROWSER': '1'} if remote else {})})
	page = (
		'<iframe id=fr srcdoc="<input type=file id=f onchange=top.changed=1>"></iframe><div id=h></div><script>'
		'document.getElementById(`h`).attachShadow({mode:`open`}).innerHTML=`<input type=file id=s>`</script>'
	)
	try:
		(tmp_path / 'cv.txt').write_text('hello')
		r = await repl.call(
			'exec',
			f'new_tab({"data:text/html," + page!r}); wait_for_load(); upload_file("#f", "cv.txt"); upload_file("#s", "cv.txt")\n'
			"print(js(\"[fr.contentDocument.getElementById('f').files[0].size, window.changed, "
			"h.shadowRoot.getElementById('s').files[0].name].join()\"))",
			60,
		)
		assert r['error'] is None and '5,1,cv.txt' in r['output'], r
	finally:
		await repl.close()
		await browser.stop()


@pytest.mark.skipif(sys.platform == 'win32' or os.geteuid() == 0, reason='needs a directory this user cannot write')
async def test_an_unwritable_workspace_fails_before_a_browser_starts(tmp_path, monkeypatch):
	"""Only workspace.mkdir ran before browser.start(), and it passes on an existing read-only directory: a cloud browser
	was created and billed for a run that could not work (local raised after Chrome launched, cloud returned error)."""
	started = []

	async def start(self):
		started.append(self)
		raise AssertionError('browser started')

	monkeypatch.setattr(Browser, 'start', start)
	workspace = tmp_path / 'ro'
	workspace.mkdir()
	workspace.chmod(0o555)
	try:
		agent = Agent('t', script(('finish', {'result': 'ok', 'success': True}))[0], browser=Browser(), workspace=workspace)
		with pytest.raises(PermissionError):
			await agent.run()
	finally:
		workspace.chmod(0o755)
	assert started == []


FD_LIMIT_CHILD = """
import asyncio, os, resource, sys
from conftest import script
from browser_use import Agent, Browser

soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
resource.setrlimit(resource.RLIMIT_NOFILE, (256, hard))  # macOS's default (launchctl limit maxfiles)


async def start(self):
	raise RuntimeError('no browser in this test')


Browser.start = start
model, _ = script(('finish', {'success': True, 'result': 'ok'}))
asyncio.run(Agent('t', model, browser=Browser(local=True), workspace=sys.argv[1]).run())
fds = []
try:
	for _ in range(400):  # ~3 per live Agent: what 100+ concurrent Agents hold
		fds.append(os.open(os.devnull, os.O_RDONLY))
except OSError as e:
	print(f'{len(fds)} {e}')
else:
	print(len(fds))
"""


@pytest.mark.skipif(sys.platform == 'win32', reason='no RLIMIT_NOFILE on Windows')
def test_agent_raises_a_low_open_file_limit(tmp_path):
	"""gwscale F1: 100 concurrent Agents in one process on macOS (soft limit 256) need ~300 fds; 27-33 of 100 failed
	with EMFILE, failed binds, or 'ModelConnectionError: Connection error.' (DNS without a free fd)."""
	import subprocess
	from pathlib import Path

	r = subprocess.run(
		[sys.executable, '-c', FD_LIMIT_CHILD, str(tmp_path)],
		capture_output=True,
		text=True,
		timeout=120,
		cwd=Path(__file__).parent,
	)
	assert r.returncode == 0, r.stderr[-3000:]
	assert r.stdout.strip().splitlines()[-1] == '400', r.stdout[-500:]


async def test_a_connection_error_names_its_cause(tmp_path):
	"""gwscale F1: out of file descriptors, a model call failed with only 'ModelConnectionError: Connection error.' (the
	OpenAI SDK's text for any transport failure). The run's error now names the transport cause."""
	from pydantic_ai.exceptions import ModelConnectionError
	from pydantic_ai.models.function import FunctionModel

	from browser_use.agent.loop import Session, run

	def provider(messages, info):
		try:
			raise OSError(24, 'Too many open files')
		except OSError as e:
			raise ModelConnectionError('m', 'Connection error.', phase='connect') from e

	r = await run(build_agent(FunctionModel(provider)), 'task', Session(repl=Repl(tmp_path)), 'm')
	assert (r.status, r.error) == ('error', 'ModelConnectionError: Connection error. (OSError: [Errno 24] Too many open files)')
