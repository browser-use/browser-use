"""Agent(approve=..., approve_on=...): effects (an upload, typing a secret, a new origin) wait for the parent's decision;
a denial raises PermissionError in the cell and the effect never happens."""

import asyncio
import time

import pytest
from conftest import script
from test_agent import serve
from test_hooks import tool_returns

from browser_use import Agent, ApprovalRequest, Browser
from browser_use.agent import hooks
from browser_use.agent.hooks import Approvals
from browser_use.repl.session import Repl

FORM = '<input type=file id=f><input id=pw>'


def texts(seen) -> list[str]:
	"""What the model read back from each tool call, as text."""
	return [' '.join(map(str, r)) if isinstance(r, list) else str(r) for r in tool_returns(seen[-1])]


async def test_a_denied_upload_sets_no_file_through_any_helper_and_an_approved_one_does(chrome, tmp_path):
	server, port = serve({'/form': FORM})
	(tmp_path / 'secret.txt').write_text('payroll')
	(tmp_path / 'ok.txt').write_text('cv')
	asked: list[ApprovalRequest] = []

	def approve(request: ApprovalRequest):
		asked.append(request)
		return 'no secrets leave' if any(f.endswith('secret.txt') for f in request.detail['files']) else True

	raw = (
		"o = cdp('Runtime.evaluate', expression='document.querySelector(\"#f\")')['result']['objectId']\n"
		'try:\n'
		"\tcdp('DOM.setFileInputFiles', objectId=o, files=['secret.txt'])\n"
		'except PermissionError as e:\n'
		"\tprint('raw denied')\n"
		"print('files', js('document.querySelector(\"#f\").files.length'))"
	)
	model, seen = script(
		('python', {'code': f"goto_url('http://127.0.0.1:{port}/form'); wait_for_load(); upload_file('#f', 'secret.txt')"}),
		('python', {'code': raw}),
		('python', {'code': "upload_file('#f', 'ok.txt'); print('name', js('document.querySelector(\"#f\").files[0].name'))"}),
		('finish', {'success': True, 'result': 'done'}),
	)
	try:
		await Agent('Apply', model, browser=Browser(cdp_url=chrome['http']), workspace=tmp_path, approve=approve).run()
	finally:
		server.shutdown()
	returns = texts(seen)
	assert 'PermissionError: Not allowed: upload of secret.txt to http://127.0.0.1' in returns[0], returns[0]
	assert '(no secrets leave). Nothing was done.' in returns[0]
	assert 'raw denied' in returns[1] and 'files 0' in returns[1], returns[1]  # cdp() is gated too: nothing was set
	assert 'name ok.txt' in returns[2], returns[2]
	assert [(r.kind, r.detail['origin']) for r in asked] == [('upload', f'http://127.0.0.1:{port}')] * 3
	assert asked[0].detail['files'] == [str(tmp_path / 'secret.txt')] and asked[0].task == 'Apply'
	assert asked[0].message == f'Allow upload of secret.txt to http://127.0.0.1:{port}?'
	assert [r.step for r in asked] == [1, 2, 3]


async def test_type_secret_types_nothing_when_approve_raises(chrome, tmp_path):
	"""Fail closed: a broken approver denies; the request names the secret, never its value."""
	server, port = serve({'/form': FORM})
	asked: list[ApprovalRequest] = []

	async def broken(request: ApprovalRequest):
		asked.append(request)
		raise ConnectionError('approval service down')

	model, seen = script(
		('python', {'code': f"goto_url('http://127.0.0.1:{port}/form'); wait_for_load(); js('document.querySelector(\"#pw\").focus()'); type_secret('pw')"}),
		('python', {'code': "print('value', repr(js('document.querySelector(\"#pw\").value')))"}),
		('finish', {'success': True, 'result': 'done'}),
	)  # fmt: skip
	try:
		agent = Agent('Log in', model, browser=Browser(cdp_url=chrome['http']), workspace=tmp_path,
					  sensitive_data={'pw': 'hunter2-Zq9'}, approve=broken)  # fmt: skip
		await agent.run()
	finally:
		server.shutdown()
	returns = texts(seen)
	assert "typing the secret 'pw' into http://127.0.0.1" in returns[0], returns[0]
	assert 'approve raised ConnectionError: approval service down' in returns[0]
	assert "value ''" in returns[1], returns[1]
	assert [(r.kind, r.detail) for r in asked] == [('type_secret', {'secret': 'pw', 'origin': f'http://127.0.0.1:{port}'})]
	assert 'hunter2' not in repr(asked)


async def test_new_origin_asks_once_per_origin_and_a_denied_one_is_never_opened(chrome, tmp_path):
	server, port = serve({'/a': '<title>A</title>', '/b': '<title>B</title>'})
	asked: list[str] = []

	def approve(request: ApprovalRequest):  # a plain function may block: it runs in a thread
		asked.append(request.detail['origin'])
		return request.detail['origin'] == f'http://127.0.0.1:{port}' or 'not on the list'

	model, seen = script(
		('python', {'code': f"goto_url('http://127.0.0.1:{port}/a'); goto_url('http://127.0.0.1:{port}/b'); wait_for_load(); print(page_info()['url'])"}),
		('python', {'code': f"n, here = len(list_tabs()), current_tab()['targetId']; new_tab('http://localhost:{port}/a')"}),
		('python', {'code': "print('tabs', [t['url'] for t in list_tabs()], len(list_tabs()) - n, current_tab()['targetId'] == here)"}),
		('finish', {'success': True, 'result': 'done'}),
	)  # fmt: skip
	try:
		agent = Agent('Browse', model, browser=Browser(cdp_url=chrome['http']), workspace=tmp_path, approve=approve,
					  approve_on={'new_origin'})  # fmt: skip
		await agent.run()
	finally:
		server.shutdown()
	returns = texts(seen)
	assert f'http://127.0.0.1:{port}/b' in returns[0], returns[0]
	assert f'Not allowed: access to http://localhost:{port} was denied (not on the list)' in returns[1], returns[1]
	assert f'localhost:{port}' not in returns[2] and returns[2].strip().endswith(' 0 True'), returns[2]  # no blank tab either
	assert asked == [f'http://127.0.0.1:{port}', f'http://localhost:{port}']  # the approved origin is remembered


async def test_the_cell_deadline_waits_for_a_slow_human(daemon, tmp_path):
	server, port = serve({'/a': '<title>A</title>'})

	async def human(kind: str, detail: dict) -> str | None:
		await asyncio.sleep(3)
		return None

	repl = Repl(tmp_path, daemon, approve=human, approve_on={'new_origin'})
	try:
		r = await repl.call('exec', f"goto_url('http://127.0.0.1:{port}/a'); print('went')", 2)
	finally:
		await repl.close()
		server.shutdown()
	assert r['error'] is None and 'went' in r['output'], r


async def test_approvals_fail_closed_and_remember_only_what_was_allowed(monkeypatch):
	monkeypatch.setattr(hooks, 'APPROVE_TIMEOUT_S', 0.2)
	calls: list[str] = []

	def answer(request: ApprovalRequest):
		calls.append(request.detail['origin'])
		if request.detail['origin'] == 'https://slow.example':
			time.sleep(1)
		return {'https://ok.example': True, 'https://none.example': None}.get(request.detail['origin'], False)

	approvals = Approvals(answer, 'task')
	assert await approvals.ask('new_origin', {'origin': 'https://ok.example'}) is None
	assert await approvals.ask('new_origin', {'origin': 'https://ok.example'}) is None  # remembered: not asked again
	assert 'was denied (no answer within 0.2 s)' in str(await approvals.ask('new_origin', {'origin': 'https://slow.example'}))
	assert '(denied)' in str(await approvals.ask('new_origin', {'origin': 'https://none.example'}))  # only True allows
	assert await approvals.ask('new_origin', {'origin': 'https://none.example'}) is not None  # a denial asks again
	assert calls == ['https://ok.example', 'https://slow.example', 'https://none.example', 'https://none.example']


def test_approve_options_are_checked_before_any_browser_starts():
	with pytest.raises(TypeError, match='approve must be a function'):
		Agent('t', 'test', approve='yes')  # type: ignore[arg-type]
	with pytest.raises(TypeError, match='approve_on needs approve='):
		Agent('t', 'test', approve_on={'upload'})
	with pytest.raises(ValueError, match="unknown kind 'click'"):
		Agent('t', 'test', approve=lambda r: True, approve_on={'click'})
	assert Agent('t', 'test', approve=lambda r: True).approve_on == {'upload', 'type_secret'}


async def test_type_secret_after_a_slow_approval_types_only_into_the_frame_that_was_approved(daemon, tmp_path):
	"""The page had minutes to move focus while a human decided: keys must not reach another origin."""
	focus = '<input id=pw><script>pw.focus()</script>'
	away = "location.href = location.href.replace('127.0.0.1', 'localhost').replace('/a', '/b')"
	pages = {
		'/a': focus + f"<script>setInterval(async () => (await (await fetch('/go')).text()) && ({away}), 100)</script>",
		'/b': focus,
	}
	server, port = serve(pages)
	asked: list[dict] = []

	async def slow_yes(kind: str, detail: dict) -> str | None:
		asked.append(detail)
		pages['/go'] = 'yes'  # while the human decides, the page navigates to another origin
		await asyncio.sleep(3)
		return None

	repl = Repl(tmp_path, daemon, secrets={'pw': 'hunter2-Zq9'}, approve=slow_yes, approve_on={'type_secret'})
	try:
		r = await repl.call('exec', f"goto_url('http://127.0.0.1:{port}/a'); wait_for_load(); type_secret('pw')", 30)
		after = await repl.call('exec', "print(page_info()['url'], repr(js('document.querySelector(\"#pw\").value')))", 30)
	finally:
		await repl.close()
		server.shutdown()
	assert asked == [{'secret': 'pw', 'origin': f'http://127.0.0.1:{port}'}]
	assert 'PermissionError' in (r['error'] or ''), r
	assert f'localhost:{port}/b' in after['output'] and "''" in after['output'], after


async def test_a_denied_upload_drops_no_file_through_a_drag_event(daemon, tmp_path):
	"""Input.dispatchDragEvent(data={'files': [...]}) hands local files to a drop zone: an upload like setFileInputFiles."""
	zone = (
		'<div id=z style="width:300px;height:300px" ondragenter="event.preventDefault()" ondragover="event.preventDefault()" '
		'ondrop="event.preventDefault(); window.got = [...event.dataTransfer.files].map(f => f.name)"></div>'
	)
	server, port = serve({'/z': zone})
	(tmp_path / 'secret.txt').write_text('payroll')
	asked: list[tuple[str, dict]] = []

	async def no(kind: str, detail: dict) -> str | None:
		asked.append((kind, detail))
		return 'Not allowed: no'

	drag = (
		"data = {'items': [], 'files': [str(Path('secret.txt').resolve())], 'dragOperationsMask': 1}\n"
		"for t in ('dragEnter', 'dragOver', 'drop'):\n"
		'\ttry:\n'
		"\t\tcdp('Input.dispatchDragEvent', type=t, x=100, y=100, data=data)\n"
		'\texcept PermissionError:\n'
		"\t\tprint('denied', t)\n"
		"print('got', js('window.got || []'))"
	)
	repl = Repl(tmp_path, daemon, approve=no, approve_on={'upload'})
	try:
		await repl.call('exec', f"goto_url('http://127.0.0.1:{port}/z'); wait_for_load()", 30)
		r = await repl.call('exec', 'from pathlib import Path\n' + drag, 30)
	finally:
		await repl.close()
		server.shutdown()
	assert 'got []' in r['output'], r
	assert asked and asked[0][0] == 'upload' and asked[0][1]['files'] == [str((tmp_path / 'secret.txt').resolve())], asked


async def test_an_approved_upload_or_unknown_origin_does_not_approve_the_next_one():
	"""The human approved these files on this page; a different file, or a page nobody could name, asks again."""
	calls: list[dict] = []

	def yes(request: ApprovalRequest):
		calls.append(request.detail)
		return True

	approvals = Approvals(yes, 'task')
	cv, key = (
		{'files': ['/home/me/cv.pdf'], 'origin': 'https://jobs.example'},
		{'files': ['/home/me/.ssh/id_rsa'], 'origin': 'https://jobs.example'},
	)
	assert await approvals.ask('upload', cv) is None
	assert await approvals.ask('upload', cv) is None  # the same files to the same origin: remembered
	assert await approvals.ask('upload', key) is None
	unknown = {'secret': 'pw', 'origin': None}
	assert await approvals.ask('type_secret', unknown) is None
	assert await approvals.ask('type_secret', unknown) is None
	assert calls == [cv, key, unknown, unknown]
