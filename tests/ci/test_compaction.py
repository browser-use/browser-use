"""Client-side compaction (bu-pi src/context.ts) for models without server-side compaction: scripted model, fake REPL."""

import base64
import json
import logging

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage

from browser_use.agent.loop import Session, build_agent, run
from browser_use.repl.session import scoped_secrets

PNG = base64.b64encode(b'\x89PNG-fake-image-bytes').decode()


class FakeRepl:
	def __init__(self, workspace, secrets=None):
		self.workspace = self.state = workspace
		self.secrets, self.search = scoped_secrets(secrets), None

	async def call(self, op, code, timeout):
		images = [{'data': PNG, 'media_type': 'image/png'}] if code.startswith('step1') else []  # one: never pruned
		return {'output': f'ran {code}', 'error': None, 'images': images}


def scripted(big: set[int], steps: int = 5, fail: bool = False):
	"""Agent requests call python `steps` times, then finish. Requests in `big` report 5000 input tokens, others 100.
	The summarizer (a request without tools) answers SUMMARY or raises."""
	agent_requests, summarizer_requests = [], []

	def fn(messages, info: AgentInfo):
		if not info.function_tools:
			summarizer_requests.append(messages)
			if fail:
				raise RuntimeError('summarizer down')
			return ModelResponse(parts=[TextPart('SUMMARY')], usage=RequestUsage(input_tokens=7, output_tokens=3))
		agent_requests.append(messages)
		i = len(agent_requests)
		call = ToolCallPart('python', {'code': f'step{i} hunter2-secret'}, tool_call_id=f'c{i}')
		if i > steps:
			call = ToolCallPart('finish', {'result': 'done', 'success': True}, tool_call_id=f'c{i}')
		return ModelResponse(parts=[call], usage=RequestUsage(input_tokens=5000 if i in big else 100, output_tokens=1))

	return fn, agent_requests, summarizer_requests


async def go(tmp_path, fn, *, window=None, **kw):
	agent = build_agent(FunctionModel(fn, profile={'context_window': window}), **kw)
	session = Session(repl=FakeRepl(tmp_path, {'pw': 'hunter2-secret'}))
	return await run(agent, 'TASK-TEXT', session, 'function:x')


def checkpoint_text(request) -> str | None:
	first = request[0].parts[0]
	return first.content if isinstance(first, UserPromptPart) and first.content.startswith('Conversation checkpoint') else None


@pytest.mark.parametrize('kw', [{'compact_at_tokens': 4000}, {'window': 6000}])  # 0.65 * 6000 = 3900 < the default 150k
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


async def test_archive_is_written_redacted_and_without_images(tmp_path):
	fn, agent_requests, _ = scripted(big={3})
	await go(tmp_path, fn, compact_at_tokens=4000)
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
		result = await go(tmp_path, fn, compact_at_tokens=4000)
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
		assert any(isinstance(c, Compaction) and c.token_threshold == 150_000 for c in capabilities), model
