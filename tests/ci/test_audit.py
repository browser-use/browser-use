"""Agent(audit_log=...): one hash-chained JSON line per run_start, action, outcome and run_end; verify() finds edits."""

import base64
import hashlib
import json

import pytest
from conftest import script
from test_hooks import tool_returns

from browser_use import ActionOutcome, Agent, Browser
from browser_use.audit import verify

SECRET = 'hunter2-Zq9x'


def read(path):
	return [json.loads(line) for line in path.read_text().splitlines()]


async def test_audit_log_records_each_event_without_secrets_or_page_text_and_verifies(chrome, tmp_path):
	from test_agent import serve

	server, port = serve({'/a': '<title>A</title><p>PAGE-TEXT-7731 jane@patient.example</p>'})
	log = tmp_path / 'logs' / 'audit.jsonl'
	model, seen = script(
		('python', {'code': f"goto_url('http://127.0.0.1:{port}/a'); wait_for_load(); print(js('document.body.innerText'))"}),
		('python', {'code': f"print('typing {SECRET}'); raise ValueError('bad {SECRET}')"}),
		('python', {'code': "print('wire money')"}),
		('finish_from_repl', {'expression': "'done'", 'success': True}),  # it runs Python in the REPL: an action too
	)
	mine: list[ActionOutcome] = []
	try:
		agent = Agent(f'Log in with {SECRET}', model, browser=Browser(cdp_url=chrome['http']), workspace=tmp_path,
					  sensitive_data={'pw': SECRET},
					  before_action=lambda a: 'needs a human' if 'wire money' in (a.code or '') else None,
					  after_action=mine.append, audit_log=log,
					  audit_metadata={'run_by': 'svc-reports', 'on_behalf_of': 'alice@corp.example'})  # fmt: skip
		result = await agent.run()
	finally:
		server.shutdown()
	assert result.final_result() == 'done'
	assert str(tool_returns(seen[-1])[2]).startswith('Not run: needs a human.')  # the user's hook still decides
	assert len(mine) == 4  # and the user's after_action still sees every action

	raw = log.read_bytes()
	assert verify(log) == []
	for leak in (SECRET, base64.b64encode(SECRET.encode()).decode(), 'PAGE-TEXT-7731', 'jane@patient.example'):
		assert leak not in raw.decode(), leak
	events = read(log)
	types = ['run_start', 'action', 'outcome', 'action', 'outcome', 'action', 'action', 'outcome', 'run_end']
	assert [e['type'] for e in events] == types
	assert [e['seq'] for e in events] == list(range(9)) and len({e['run_id'] for e in events}) == 1
	start, nav, nav_out, bad, bad_out, refused, deliver, deliver_out, end = events
	assert start['prev'] == hashlib.sha256(start['run_id'].encode()).hexdigest()
	assert start['task'] == 'Log in with <secret:pw>' and start['browser'] == 'cdp' and start['model']
	assert start['metadata'] == {'run_by': 'svc-reports', 'on_behalf_of': 'alice@corp.example'}
	assert start['ts'].endswith('Z') and start['version']
	assert nav['decision'] == 'allowed' and nav['tool'] == 'python' and nav['host'] is None and 'goto_url' in nav['args']['code']
	assert nav_out['urls'] == [f'http://127.0.0.1:{port}/a'] and nav_out['error'] is None
	assert nav_out['output_sha256'] == hashlib.sha256(mine[0].output.encode()).hexdigest()  # proves what was seen
	assert nav_out['output_chars'] == len(mine[0].output) and 'output' not in nav_out
	assert bad['args']['code'].startswith("print('typing <secret:pw>')") and '<secret:pw>' in bad_out['error']
	assert refused['decision'] == 'refused' and refused['reason'] == 'needs a human' and refused['host'] == '127.0.0.1'
	assert deliver['tool'] == 'finish_from_repl' and deliver['args'] == {'expression': "'done'"}
	assert deliver_out['output_sha256'] == hashlib.sha256(b'done').hexdigest()
	assert end['status'] == 'completed' and end['steps'] == 4 and end['success'] is True and end['error'] is None

	# A second Agent appends its own chain to the same file
	model2, _ = script(('finish', {'success': True, 'result': 'again'}))
	await Agent('t2', model2, browser=Browser(cdp_url=chrome['http']), workspace=tmp_path, audit_log=str(log)).run()
	assert verify(log) == [] and len({e['run_id'] for e in read(log)}) == 2

	# Tampering: each edit is found
	lines = raw.split(b'\n')[:-1]

	def problems(new_lines, tail=b'\n'):
		forged = tmp_path / 'forged.jsonl'
		forged.write_bytes(b'\n'.join(new_lines) + tail)
		return verify(forged)

	edited = lines.copy()
	edited[5] = edited[5].replace(b'"refused"', b'"allowed"')  # hide the refusal
	assert any('line 7' in p and 'prev does not match' in p for p in problems(edited))
	assert any('seq 3' in p and 'expected seq 2' in p for p in problems(lines[:2] + lines[3:]))  # a line deleted
	assert any('no run_end' in p for p in problems(lines[:-1]))  # the tail cut
	assert any('cut off' in p for p in problems(lines, tail=b''))  # killed mid-write
	assert any('reordered' in p for p in problems([lines[0], lines[2], lines[1], *lines[3:]]))


async def test_a_function_sink_gets_each_event_and_an_unwritable_one_refuses_the_action(chrome, tmp_path):
	"""Fail closed: an action that cannot be recorded does not run."""
	marker = tmp_path / 'ran.txt'
	shipped = tmp_path / 'shipped.jsonl'
	events: list[dict] = []

	async def siem(event: dict):  # async sinks are awaited
		if event['type'] == 'action' and 'ran.txt' in event['args']['code']:
			raise ConnectionError('SIEM down')
		events.append(event)
		with shipped.open('a') as f:  # the documented way to keep a verifiable copy
			f.write(json.dumps(event, separators=(',', ':')) + '\n')

	model, seen = script(
		('python', {'code': f"open({str(marker)!r}, 'w').write('x')"}),
		('python', {'code': "print('fine')"}),
		('finish', {'success': True, 'result': 'done'}),
	)
	await Agent('t', model, browser=Browser(cdp_url=chrome['http']), workspace=tmp_path, audit_log=siem).run()
	assert not marker.exists()
	assert str(tool_returns(seen[-1])[0]).startswith('Not run: the audit log could not be written (ConnectionError).')
	assert [e['type'] for e in events] == ['run_start', 'action', 'outcome', 'run_end']
	assert [e['seq'] for e in events] == [0, 1, 2, 3]  # the failed line took no seq
	assert verify(shipped) == []


async def test_an_unwritable_audit_log_fails_the_run_before_the_browser_starts(tmp_path):
	(tmp_path / 'file').write_text('')
	model, seen = script(('finish', {'success': True, 'result': 'done'}))
	agent = Agent('t', model, browser=Browser(cdp_url='http://127.0.0.1:9'), workspace=tmp_path,
				  audit_log=tmp_path / 'file' / 'audit.jsonl')  # fmt: skip
	with pytest.raises(OSError):
		await agent.run()
	assert seen == []


def test_audit_options_are_checked_up_front():
	with pytest.raises(TypeError, match='audit_log must be'):
		Agent('t', 'test', audit_log=42)  # type: ignore[arg-type]
	with pytest.raises(ValueError, match='pass audit_log'):
		Agent('t', 'test', audit_metadata={'run_by': 'x'})
	with pytest.raises(TypeError, match='JSON-serializable'):
		Agent('t', 'test', audit_log='a.jsonl', audit_metadata={'when': object()})


async def test_parallel_tool_calls_with_a_slow_async_sink_keep_one_chain(tmp_path):
	"""An async sink yields mid-line: without the lock, two parallel calls wrote the same seq and prev."""
	import asyncio

	from browser_use.audit import AuditRun

	lines: list[str] = []

	async def slow(event: dict):
		await asyncio.sleep(0.01)
		lines.append(json.dumps(event, separators=(',', ':')))

	run = AuditRun(slow, 'r1', [])
	await run.write('run_start')
	await asyncio.gather(*(run.write('action', step=1, n=i) for i in range(3)))
	await run.end(None, None)
	(tmp_path / 'a.jsonl').write_bytes(('\n'.join(lines) + '\n').encode())  # bytes: text mode on Windows writes \r\n
	assert [json.loads(line)['seq'] for line in lines] == [0, 1, 2, 3, 4]
	assert verify(tmp_path / 'a.jsonl') == []


def test_a_secret_in_any_json_shape_is_redacted_and_lines_end_in_a_bare_newline(tmp_path):
	"""A tuple or an object's str() holding a secret was written as is; text mode on Windows wrote \\r\\n, which
	verify() reads as an edit."""
	from browser_use.audit import AuditRun
	from browser_use.repl.session import secret_forms

	class Principal:
		def __str__(self):
			return f'svc:{SECRET}'

	log = tmp_path / 'audit.jsonl'
	run = AuditRun(log, 'r1', secret_forms({'pw': SECRET}))

	async def write():
		await run.write('run_start', metadata={'ids': (SECRET, 1)}, who=Principal())
		await run.end(None, None)

	import asyncio

	asyncio.run(write())
	raw = log.read_bytes()
	assert SECRET.encode() not in raw and b'\r' not in raw
	assert read(log)[0]['metadata'] == {'ids': ['<secret:pw>', 1]} and read(log)[0]['who'] == 'svc:<secret:pw>'
	assert verify(log) == []
