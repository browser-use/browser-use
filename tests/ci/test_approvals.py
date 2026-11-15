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
		('python', {'code': f"new_tab('http://localhost:{port}/a')"}),
		('python', {'code': "print('tabs', [t['url'] for t in list_tabs()])"}),
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
	assert f'localhost:{port}' not in returns[2], returns[2]
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
