"""Agent(before_action=..., after_action=...): every tool call is seen before it runs, can be refused, and is seen after."""

import pytest
from conftest import script

from browser_use import Action, ActionOutcome, Agent, Browser, Tools


def tool_returns(messages):
	from pydantic_ai.messages import ToolReturnPart

	return [p.content for m in messages for p in getattr(m, 'parts', []) if isinstance(p, ToolReturnPart)]


async def test_before_action_refuses_a_cell_before_it_runs_and_the_model_reads_why(chrome, tmp_path):
	marker = tmp_path / 'ran.txt'
	model, seen = script(
		('python', {'code': f"open({str(marker)!r}, 'w').write('x')  # upload to evil.example"}),
		('python', {'code': "print('allowed cell')"}),
		('finish', {'success': True, 'result': 'done'}),
	)

	def policy(action: Action):
		assert action.tool == 'python' and action.task == 'Do it' and action.step >= 1
		return 'evil.example is not an approved destination' if 'evil.example' in (action.code or '') else None

	result = await Agent('Do it', model, browser=Browser(cdp_url=chrome['http']), workspace=tmp_path, before_action=policy).run()
	assert result.final_result() == 'done'
	assert not marker.exists()  # the refused cell never reached the REPL
	returns = [str(r) for r in tool_returns(seen[-1])]
	assert returns[0].startswith('Not run: evil.example is not an approved destination.'), returns
	assert 'allowed cell' in returns[1]


async def test_after_action_sees_code_output_urls_and_host_with_secrets_redacted(chrome, tmp_path):
	from test_agent import serve

	server, port = serve({'/a': '<title>A</title>'})
	outcomes: list[ActionOutcome] = []
	model, _ = script(
		('python', {'code': f"goto_url('http://127.0.0.1:{port}/a'); wait_for_load(); print('pw is hunter2-Zq9')"}),
		('python', {'code': "print('second')"}),
		('finish', {'success': True, 'result': 'ok'}),
	)

	async def record(outcome: ActionOutcome):  # async hooks are awaited
		outcomes.append(outcome)

	try:
		agent = Agent('Go', model, browser=Browser(cdp_url=chrome['http']), workspace=tmp_path,
					  sensitive_data={'pw': 'hunter2-Zq9'}, after_action=record)  # fmt: skip
		await agent.run()
	finally:
		server.shutdown()
	assert [o.action.tool for o in outcomes] == ['python', 'python']
	first, second = outcomes
	assert first.refused is None and first.error is None and first.duration_s > 0
	assert 'pw is <secret:pw>' in first.output and 'hunter2' not in first.output
	assert first.urls == [f'http://127.0.0.1:{port}/a']
	assert first.action.host is None and second.action.host == '127.0.0.1'  # where the agent was when it asked


async def test_a_before_action_that_raises_refuses_the_action(chrome, tmp_path):
	"""Fail closed: a broken policy never lets an action through."""
	marker = tmp_path / 'ran.txt'
	model, seen = script(
		('python', {'code': f"open({str(marker)!r}, 'w').write('x')"}),
		('finish', {'success': True, 'result': 'done'}),
	)
	refused: list[ActionOutcome] = []

	def broken(action):
		raise ConnectionError('policy server down')

	agent = Agent('t', model, browser=Browser(cdp_url=chrome['http']), workspace=tmp_path, before_action=broken,
				  after_action=refused.append)  # fmt: skip
	await agent.run()
	assert not marker.exists()
	assert 'Not run: refused: before_action raised ConnectionError: policy server down' in str(tool_returns(seen[-1])[0])
	assert refused[0].refused and refused[0].output.startswith('Not run:')


@pytest.mark.parametrize('answer', [False, 0, 'yes'])
async def test_anything_but_none_or_true_refuses(chrome, tmp_path, answer):
	model, seen = script(('python', {'code': "print('ran')"}), ('finish', {'success': True, 'result': 'done'}))
	agent = Agent('t', model, browser=Browser(cdp_url=chrome['http']), workspace=tmp_path, before_action=lambda a: answer)
	await agent.run()
	text = str(tool_returns(seen[-1])[0])
	assert text.startswith('Not run:') and 'ran' not in text.removeprefix('Not run:').split('.')[0] or answer == 'yes'
	if answer == 'yes':  # a string is the reason
		assert text.startswith('Not run: yes.')


async def test_custom_tools_go_through_the_hooks_and_finish_does_not(chrome, tmp_path):
	tools = Tools()
	called: list[str] = []

	@tools.action('Send an email')
	def send_email(to: str) -> str:
		called.append(to)
		return f'sent to {to}'

	model, _ = script(
		('send_email', {'to': 'boss@corp.example'}),
		('send_email', {'to': 'me@corp.example'}),
		('finish', {'success': True, 'result': 'done'}),
	)
	seen: list[ActionOutcome] = []
	agent = Agent('t', model, browser=Browser(cdp_url=chrome['http']), workspace=tmp_path, tools=tools,
				  before_action=lambda a: 'needs approval' if a.args.get('to') == 'boss@corp.example' else None,
				  after_action=seen.append)  # fmt: skip
	await agent.run()
	assert called == ['me@corp.example']
	assert [(o.action.tool, o.refused) for o in seen] == [('send_email', 'needs approval'), ('send_email', None)]
	assert seen[1].output == 'sent to me@corp.example'


def test_hooks_must_be_callables():
	with pytest.raises(TypeError, match='before_action must be a function'):
		Agent('t', 'test', before_action='deny')  # type: ignore[arg-type]
	with pytest.raises(TypeError, match='after_action must be a function'):
		Agent('t', 'test', after_action=42)  # type: ignore[arg-type]
