"""Client-side compaction (bu-pi src/context.ts) for models without server-side compaction: scripted model, fake REPL."""

import base64
import json
import logging

import pytest
from pydantic_ai import BinaryContent
from pydantic_ai.messages import (
	ModelRequest,
	ModelResponse,
	TextPart,
	ThinkingPart,
	ToolCallPart,
	ToolReturnPart,
	UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage

from browser_use.agent.loop import Session, build_agent, run
from browser_use.repl.session import scoped_secrets

PNG = base64.b64encode(b'\x89PNG-fake-image-bytes').decode()


class FakeRepl:
	def __init__(self, workspace, secrets=None, pad=2000):
		self.workspace = self.state = workspace
		self.secrets, self.search, self.pad = scoped_secrets(secrets), None, pad

	async def call(self, op, code, timeout):
		images = [{'data': PNG, 'media_type': 'image/png'}] if code.startswith('step1 ') else []  # one: never pruned
		return {'output': f'ran {code} {"." * self.pad}', 'error': None, 'images': images}


def scripted(big: set[int], steps: int = 5, fail: bool = False, code=lambda i: f'step{i} hunter2-secret'):
	"""Agent requests call python `steps` times, then finish. Requests in `big` report 5000 input tokens, others 100.
	The summarizer (a request without tools) answers SUMMARY or raises; fn.settings has its model settings."""
	agent_requests, summarizer_requests = [], []

	def fn(messages, info: AgentInfo):
		if not info.function_tools:
			summarizer_requests.append(messages)
			fn.settings.append(info.model_settings)
			if fail:
				raise RuntimeError('summarizer down')
			return ModelResponse(parts=[TextPart('SUMMARY')], usage=RequestUsage(input_tokens=7, output_tokens=3))
		agent_requests.append(messages)
		i = len(agent_requests)
		call = ToolCallPart('python', {'code': code(i)}, tool_call_id=f'c{i}')
		if i > steps:
			call = ToolCallPart('finish', {'result': 'done', 'success': True}, tool_call_id=f'c{i}')
		return ModelResponse(parts=[call], usage=RequestUsage(input_tokens=5000 if i in big else 100, output_tokens=1))

	fn.settings = []
	return fn, agent_requests, summarizer_requests


async def go(tmp_path, fn, *, window=None, pad=2000, **kw):
	agent = build_agent(FunctionModel(fn, profile={'context_window': window}), **kw)
	session = Session(repl=FakeRepl(tmp_path, {'pw': 'hunter2-secret'}, pad))
	return await run(agent, 'TASK-TEXT', session, 'function:x')


def checkpoint_text(request) -> str | None:
	first = request[0].parts[0]
	return first.content if isinstance(first, UserPromptPart) and first.content.startswith('Conversation checkpoint') else None


@pytest.mark.parametrize('kw', [{'compact_at_tokens': 4500}, {'window': 8000}])  # 0.65 * 8000 = 5200 tokens
async def test_compacts_past_the_threshold_keeping_tool_pairs_and_user_messages(tmp_path, kw):
	fn, agent_requests, summarizer_requests = scripted(big={3})
	result = await go(tmp_path, fn, **kw)
	assert result.status == 'completed' and result.output == 'done', result.error
	assert len(summarizer_requests) == 1  # once: the usage that crossed the threshold is not counted again
	assert [checkpoint_text(r) is not None for r in agent_requests] == [False] * 3 + [True] * 3  # not before request 4
	compacted = agent_requests[3]
	text = checkpoint_text(compacted)
	assert '"SUMMARY"' in text and '["TASK-TEXT"]' in text  # the user's request pinned verbatim
	# the last two assistant/tool groups follow the checkpoint whole: every tool result has its call
	assert isinstance(compacted[1], ModelResponse) and len(compacted) == 5
	calls = {p.tool_call_id for m in compacted if isinstance(m, ModelResponse) for p in m.parts}
	assert all(
		p.tool_call_id in calls
		for m in compacted
		if isinstance(m, ModelRequest)
		for p in m.parts
		if isinstance(p, ToolReturnPart)
	)
	assert 'step1' in summarizer_requests[0][0].parts[0].content and 'step1' not in repr(compacted[1:])
	# the transcript stays whole; the summarizer's request is counted in usage
	assert result.steps == 6 and result.usage['requests'] == 7
	assert result.usage['input'] == 5 * 100 + 5000 + 7 and result.usage['output'] == 6 + 3


async def test_compacts_past_bu_pi_character_budget_without_a_token_trigger(tmp_path):
	fn, agent_requests, summarizer_requests = scripted(big=set())  # usage stays at 100 tokens; no context window
	result = await go(tmp_path, fn, pad=70_000)  # unknown window: 240k; 3 tool results pass 0.75 of it from the 4th request
	assert result.status == 'completed' and result.output == 'done', result.error
	assert [checkpoint_text(r) is not None for r in agent_requests] == [False] * 3 + [True] * 3


@pytest.mark.parametrize('kw', [{'window': 1_000_000}, {'max_context_chars': 1_000_000}])
async def test_character_budget_is_bu_pi_default_or_the_agent_setting(tmp_path, kw):
	"""matrix 1107: a fixed 240k budget compacted at 180k characters, 3-6x earlier than bu-pi (4 per token of the window,
	800k in the eval). The same 210k characters as above stay whole under the window default or max_context_chars."""
	fn, agent_requests, summarizer_requests = scripted(big=set())
	result = await go(tmp_path, fn, pad=70_000, **kw)
	assert result.status == 'completed' and result.output == 'done', result.error
	assert not summarizer_requests and not any(map(checkpoint_text, agent_requests))


def test_size_counts_like_bu_pi_json_stringify():
	"""Kimi bub2-019 (adidas.jp) compacted every 8 steps: json.dumps escaped each Japanese character to 6 (\\uXXXX) and
	put a space after every ':' and ','. JSON.stringify does neither."""
	from browser_use.agent.loop import _chars

	text = 'アディダス' * 1000
	frame = '[{"kind":"request","parts":[{"part_kind":"user-prompt","content":""}]}]'
	assert _chars([ModelRequest(parts=[UserPromptPart(text)])]) == len(frame) + len(text)


def test_agent_passes_max_context_chars_to_compaction():
	from browser_use import Agent, Browser
	from browser_use.agent.loop import Compaction

	agent = Agent(
		'task', FunctionModel(lambda m, i: ModelResponse(parts=[])), browser=Browser(local=True), max_context_chars=800_000
	)
	agent._build()
	assert any(isinstance(c, Compaction) and c.max_chars == 800_000 for c in agent._agent._root_capability.capabilities)
	with pytest.raises(ValueError, match='max_context_chars'):
		Agent('task', max_context_chars=0)


async def test_early_threshold_waits_until_a_tool_group_can_be_compacted(tmp_path):
	fn, agent_requests, summarizer_requests = scripted(big=set())
	result = await go(tmp_path, fn, window=8000, pad=10_000)
	assert result.status == 'completed' and result.output == 'done', result.error
	# With only two groups, the prefix is just the pinned user task: summarizing it cannot reduce the context.
	# Wait for a third group rather than permanently disabling compaction after that non-reduction.
	assert [checkpoint_text(r) is not None for r in agent_requests] == [False] * 3 + [True] * 3
	assert 'step1' in summarizer_requests[0][0].parts[0].content


async def test_archive_is_written_redacted_and_without_images(tmp_path):
	fn, agent_requests, _ = scripted(big={3})
	await go(tmp_path, fn, compact_at_tokens=4500)
	(archive,) = (tmp_path / '.browser-use' / 'context').glob('*.json')
	assert json.dumps(str(archive)) in checkpoint_text(agent_requests[3])
	raw = archive.read_text()
	data = json.loads(raw)
	assert data['summary'] == 'SUMMARY' and data['covered_messages'] == 3
	assert 'TASK-TEXT' in raw and 'step1' in raw and 'step2' not in raw  # messages before the kept groups
	assert 'hunter2-secret' not in raw and '<secret:pw>' in raw
	assert PNG not in raw and '[Image omitted from text archive]' in raw


async def test_summarizer_failure_keeps_the_history_and_warns_once(tmp_path, caplog, monkeypatch):
	monkeypatch.setattr(logging.getLogger('browser_use'), 'propagate', True)  # caplog listens on the root logger
	fn, agent_requests, summarizer_requests = scripted(big={3, 4, 5}, fail=True)  # past the threshold from request 3 on
	with caplog.at_level(logging.WARNING, logger='browser_use.agent.loop'):
		result = await go(tmp_path, fn, compact_at_tokens=4500)
	assert result.status == 'completed' and result.output == 'done', result.error
	assert len(summarizer_requests) == 1 and not any(map(checkpoint_text, agent_requests))
	assert len(agent_requests[3]) == 7 and agent_requests[3][0].parts[-1].content == 'TASK-TEXT'  # full history
	assert [r.message for r in caplog.records].count(
		'Compaction failed, continuing with the full history: RuntimeError: summarizer down'
	) == 1


def test_every_model_without_server_side_compaction_compacts():
	from browser_use.agent.loop import Compaction

	for model in ('openai-chat:deepseek-chat', 'anthropic:claude-sonnet-4-5', 'google-gla:gemini-2.5-flash'):
		capabilities = build_agent(model)._root_capability.capabilities
		assert any(isinstance(c, Compaction) and c.token_threshold is None for c in capabilities), model


def test_size_and_archive_count_only_message_content():
	"""bu-pi's archive keeps role, tool name and call id, content or arguments: no usage, ids, timestamps or provider
	details. Only real images become the note; tool data that looks like one, or has an instructions key, stays."""
	from browser_use.agent.loop import _plain

	messages = [
		ModelRequest(parts=[UserPromptPart(['look', BinaryContent(b'png', media_type='image/png')])], instructions='SYSTEM'),
		ModelResponse(
			parts=[ThinkingPart('hmm'), ToolCallPart('python', {'code': 'x', 'instructions': 'kept'}, tool_call_id='c1')],
			usage=RequestUsage(input_tokens=9),
			provider_details={'p': 1},
			provider_response_id='r1',
		),
		ModelRequest(parts=[ToolReturnPart('python', {'kind': 'binary', 'data': 'tool data'}, tool_call_id='c1')]),
	]
	call, ret = {'tool_name': 'python', 'tool_call_id': 'c1'}, {'kind': 'binary', 'data': 'tool data'}
	assert _plain(messages) == [
		{'kind': 'request', 'parts': [{'part_kind': 'user-prompt', 'content': ['look', '[Image omitted from text archive]']}]},
		{'kind': 'response', 'parts': [{'part_kind': 'tool-call', **call, 'args': {'code': 'x', 'instructions': 'kept'}}]},
		{'kind': 'request', 'parts': [{'part_kind': 'tool-return', **call, 'content': ret}]},
	]


async def test_summarizer_runs_at_low_effort_with_bu_pi_limits_and_no_cache_write(tmp_path):
	fn, _, _ = scripted(big={3})
	settings = {'cache': True, 'openai_reasoning_effort': 'high', 'temperature': 0.3}
	await go(tmp_path, fn, compact_at_tokens=4500, model_settings=settings)
	(seen,) = fn.settings
	assert 'cache' not in seen and 'tool_choice' not in seen
	assert {k: seen.get(k) for k in ('openai_reasoning_effort', 'max_tokens', 'request_timeout', 'temperature')} == {
		'openai_reasoning_effort': 'low',
		'max_tokens': 12_000,
		'request_timeout': 120,
		'temperature': 0.3,
	}


async def test_follow_up_run_keeps_sending_the_checkpoint(tmp_path, monkeypatch):
	"""Agent.add_new_task: the next run's Session got the raw transcript without the checkpoint, so it re-sent
	everything the first run had compacted (bu-pi saves the projected history)."""
	from functools import partial

	import browser_use.agent.service as service
	from browser_use import Agent, Browser

	async def start(self):
		return {}

	async def stop(self, downloads_dir=None):
		return []

	monkeypatch.setattr(Browser, 'start', start)
	monkeypatch.setattr(Browser, 'stop', stop)
	monkeypatch.setattr(service, 'build_agent', partial(build_agent, compact_at_tokens=4500))
	fn, agent_requests, summarizer_requests = scripted(big={3}, code=lambda i: f'print("step{i}", "." * 2000)')
	agent = Agent('TASK-1', FunctionModel(fn), browser=Browser(local=True, keep_alive=True), workspace=tmp_path)
	try:
		assert (await agent.run()).final_result() == 'done'
		assert len(summarizer_requests) == 1 and checkpoint_text(agent_requests[-1])
		agent.add_new_task('TASK-2')
		assert (await agent.run()).final_result() == 'done'
	finally:
		await agent.close()
	assert len(agent_requests) == 7 and len(summarizer_requests) == 1
	assert checkpoint_text(agent_requests[-1]) and agent_requests[-1][-1].parts[-1].content == 'TASK-2'
