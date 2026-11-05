"""Model resolution. A local stub server stands in for OpenAI-compatible backends; no provider calls."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from pydantic_ai.models.openai import OpenAIChatModel, OpenAICompaction, OpenAIResponsesModel

from browser_use import Agent, ChatAnthropic, ChatBrowserUse, ChatGoogle, ChatOpenAI
from browser_use.agent.loop import Session, build_agent, run
from browser_use.llm import GATEWAY_URL, model_ref, resolve_model
from browser_use.repl import Repl


def compaction(agent) -> bool:
	return any(isinstance(c, OpenAICompaction) for c in agent._root_capability.capabilities)


FINISH_OK = {
	'role': 'assistant',
	'content': None,
	'tool_calls': [{'id': 't1', 'type': 'function', 'function': {'name': 'finish', 'arguments': '{"result": "ok"}'}}],
}


@pytest.fixture
def chat_server():
	"""OpenAI-compatible /chat/completions. Answers with the messages queued in `replies`, then with a finish call."""
	requests, replies = [], []

	class Handler(BaseHTTPRequestHandler):
		def do_POST(self):
			body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
			requests.append((self.path, body))
			message = replies.pop(0) if replies else FINISH_OK
			reply = {
				'id': 'c1',
				'object': 'chat.completion',
				'created': 0,
				'model': body['model'],
				'choices': [
					{'index': 0, 'finish_reason': 'tool_calls' if message.get('tool_calls') else 'stop', 'message': message}
				],
				'usage': {'prompt_tokens': 10, 'completion_tokens': 2, 'total_tokens': 12},
			}
			data = json.dumps(reply).encode()
			self.send_response(200)
			self.send_header('Content-Type', 'application/json')
			self.send_header('Content-Length', str(len(data)))
			self.end_headers()
			self.wfile.write(data)

		def log_message(self, *args):
			pass

	server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
	threading.Thread(target=server.serve_forever, daemon=True).start()
	yield f'http://127.0.0.1:{server.server_address[1]}/v1', requests, replies
	server.shutdown()


def test_official_openai_uses_responses_with_compaction():
	model, settings = resolve_model(ChatOpenAI('gpt-6-luna', api_key='sk-test'))
	assert isinstance(model, OpenAIResponsesModel) and settings == {}
	agent = build_agent(model)
	assert compaction(agent) and agent.model_settings['openai_reasoning_effort'] == 'medium'


def test_custom_base_url_is_plain_chat_completions():
	"""ChatOpenAI(base_url=...) crashed BUP: 'OpenAICompaction requires OpenAIResponsesModel'."""
	model, settings = resolve_model(ChatOpenAI('deepseek-chat', api_key='x', base_url='https://api.deepseek.com/v1'))
	assert isinstance(model, OpenAIChatModel) and not isinstance(model, OpenAIResponsesModel)
	agent = build_agent(model, model_settings=settings)
	assert not compaction(agent)
	assert agent.model_settings == {}  # no openai_reasoning_*, no max_tokens a small backend may reject


async def test_custom_base_url_runs_end_to_end(chat_server, tmp_path):
	url, requests, _ = chat_server
	model, settings = resolve_model(ChatOpenAI('my-vllm-model', api_key='x', base_url=url, temperature=0.3))
	session = Session(repl=Repl(tmp_path))
	result = await run(build_agent(model, model_settings=settings), 'task', session, model.model_name)
	assert (result.status, result.output, result.error) == ('completed', 'ok', None)
	path, body = requests[0]
	assert path == '/v1/chat/completions' and body['model'] == 'my-vllm-model' and body['temperature'] == 0.3
	assert 'reasoning_effort' not in body and 'max_tokens' not in body and 'max_completion_tokens' not in body
	assert result.usage['input'] == 10 and result.cost_usd is None  # unknown price is not $0


def test_default_llm_is_bu_auto_on_the_gateway(monkeypatch):
	monkeypatch.setenv('BROWSER_USE_API_KEY', 'fake-test-key')
	agent = Agent('t', browser=None)
	assert isinstance(agent.llm, ChatBrowserUse) and agent.llm.model == 'bu-auto'
	model, _ = resolve_model(agent.llm)
	assert isinstance(model, OpenAIChatModel) and model.model_name == 'bu-auto'
	assert str(model.client.base_url).rstrip('/') == GATEWAY_URL
	assert Agent('t', 'bu-smart').llm.model == 'bu-smart'  # ids are passed through, never renamed


async def test_gateway_errors_are_one_actionable_line():
	from pydantic_ai.exceptions import ModelHTTPError

	llm = ChatBrowserUse(api_key='fake-test-key')
	assert 'cloud.browser-use.com/billing' in llm.explain_error(ModelHTTPError(402, 'bu-auto'))
	assert 'US-only' in llm.explain_error(ModelHTTPError(403, 'bu-auto'))
	assert 'browser-use auth login' in llm.explain_error(ModelHTTPError(401, 'bu-auto'))
	assert '404' in llm.explain_error(ModelHTTPError(404, 'bu-auto'))
	assert llm.explain_error(ModelHTTPError(500, 'bu-auto')) is None


def test_model_strings_pass_through(monkeypatch):
	monkeypatch.setenv('OPENAI_API_KEY', 'sk-test')
	assert model_ref('openai/gpt-5.6-luna') == 'openai-responses:gpt-5.6-luna'
	assert model_ref('anthropic/claude-opus-5-5') == 'anthropic:claude-opus-5-5'
	assert model_ref('openrouter/openai/gpt-5.6-luna') == 'openrouter:openai/gpt-5.6-luna'
	assert model_ref('openai-responses:gpt-6-luna') == 'openai-responses:gpt-6-luna'
	model, _ = resolve_model('openai:gpt-6-luna')
	assert isinstance(model, OpenAIResponsesModel) and model.model_name == 'gpt-6-luna'


def test_missing_extra_gives_install_hint(monkeypatch):
	import pydantic_ai.models

	def no_sdk(ref):
		raise ImportError('No module named anthropic')

	monkeypatch.setattr(pydantic_ai.models, 'infer_model', no_sdk)
	with pytest.raises(ImportError, match=r'browser-use\[anthropic\]'):
		resolve_model('anthropic:claude-opus-5-5')


@pytest.mark.parametrize(
	('base_url', 'env', 'official'),
	[
		(None, None, True),
		('https://api.openai.com/v1', None, True),
		(None, 'http://localhost:11434/v1', False),  # Ollama via OPENAI_BASE_URL
		('https://api.openai.com.evil.test/v1', None, False),
		('https://proxy.test/api.openai.com/v1', None, False),
	],
)
def test_openai_vs_compatible_by_effective_hostname(monkeypatch, base_url, env, official):
	"""Roast C15: OPENAI_BASE_URL servers got the Responses API; any URL containing 'api.openai.com' counted as OpenAI."""
	if env:
		monkeypatch.setenv('OPENAI_BASE_URL', env)
	else:
		monkeypatch.delenv('OPENAI_BASE_URL', raising=False)
	model, _ = resolve_model(ChatOpenAI('m', api_key='x', base_url=base_url))
	assert isinstance(model, OpenAIResponsesModel if official else OpenAIChatModel)


def test_missing_provider_sdk_never_suggests_a_nonexistent_extra(monkeypatch):
	"""Roast C20: groq suggested browser-use[groq], which does not exist."""
	import pydantic_ai.models

	def no_sdk(ref):
		raise ImportError('No module named groq')

	monkeypatch.setattr(pydantic_ai.models, 'infer_model', no_sdk)
	with pytest.raises(ImportError, match=r'pydantic-ai-slim\[groq\]'):
		resolve_model('groq:llama-3.3-70b')


def test_anthropic_and_google_wrappers_build_models():
	assert resolve_model(ChatAnthropic('claude-opus-5-5', api_key='x'))[0].model_name == 'claude-opus-5-5'
	assert resolve_model(ChatGoogle('gemini-3-flash', api_key='x'))[0].model_name == 'gemini-3-flash'


def test_unsupported_llm_object_raises():
	with pytest.raises(TypeError, match='Pydantic AI model string'):
		resolve_model(object())


def anthropic_mock(*replies):
	"""An Anthropic client on a mock transport: answers with `replies` (content blocks) in order, streamed when asked
	(Pydantic AI streams when its default max_tokens is large). Records request bodies."""
	import httpx2
	from anthropic import AsyncAnthropic

	bodies = []

	def handler(request):
		body = json.loads(request.content)
		bodies.append(body)
		content = replies[len(bodies) - 1]
		stop = 'tool_use' if any(b['type'] == 'tool_use' for b in content) else 'end_turn'
		message = {'id': f'msg_{len(bodies)}', 'type': 'message', 'role': 'assistant', 'model': body['model'],
				   'stop_sequence': None, 'usage': {'input_tokens': 10, 'output_tokens': 2}}  # fmt: skip
		if not body.get('stream'):
			return httpx2.Response(200, json={**message, 'content': content, 'stop_reason': stop})
		events = [('message_start', {'message': {**message, 'content': [], 'stop_reason': None}})]
		for i, b in enumerate(content):
			if b['type'] == 'text':
				start, delta = {'type': 'text', 'text': ''}, {'type': 'text_delta', 'text': b['text']}
			else:
				start = {'type': 'tool_use', 'id': b['id'], 'name': b['name'], 'input': {}}
				delta = {'type': 'input_json_delta', 'partial_json': json.dumps(b['input'])}
			events += [('content_block_start', {'index': i, 'content_block': start}),
					   ('content_block_delta', {'index': i, 'delta': delta}), ('content_block_stop', {'index': i})]  # fmt: skip
		events += [('message_delta', {'delta': {'stop_reason': stop, 'stop_sequence': None}, 'usage': {'output_tokens': 2}}),
				   ('message_stop', {})]  # fmt: skip
		sse = ''.join(f'event: {e}\ndata: {json.dumps({"type": e, **d})}\n\n' for e, d in events)
		return httpx2.Response(200, text=sse, headers={'content-type': 'text/event-stream'})

	client = AsyncAnthropic(api_key='fake-test-key', http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))
	return client, bodies


@pytest.mark.parametrize('name', ['claude-sonnet-4-5', 'claude-opus-5-5'])
async def test_anthropic_text_reply_reaches_delivery_repair_and_finishes(tmp_path, name):
	"""Roast r2 (both): the delivery turn forced tool_choice; Claude with thinking (and Opus 5.5 always) rejects that,
	so every Anthropic run that replied in text or hit the budget ended status='error'."""
	from pydantic_ai.models.anthropic import AnthropicModel
	from pydantic_ai.providers.anthropic import AnthropicProvider

	client, bodies = anthropic_mock(
		[{'type': 'text', 'text': 'I found it: 42.'}],
		[{'type': 'tool_use', 'id': 'tu_1', 'name': 'finish', 'input': {'result': '42'}}],
	)
	model = AnthropicModel(name, provider=AnthropicProvider(anthropic_client=client))
	result = await run(build_agent(model), 'task', Session(repl=Repl(tmp_path)), f'anthropic:{name}')
	assert (result.status, result.output, result.error) == ('completed', '42', None)
	first, repair = bodies
	assert 'python' in {t['name'] for t in first['tools']}
	assert {t['name'] for t in repair['tools']} == {'finish', 'finish_from_repl'}  # python withheld
	assert repair.get('tool_choice', {'type': 'auto'})['type'] == 'auto' and repair.get('thinking')


async def test_compatible_backends_get_plain_required_on_the_delivery_turn(chat_server, tmp_path):
	"""Fable r2-4: chat backends got OpenAI's allowed_tools tool_choice, which vLLM/DeepSeek reject and Ollama ignores."""
	url, requests, replies = chat_server
	for llm in (ChatOpenAI('my-vllm-model', api_key='x', base_url=url), ChatBrowserUse(api_key='fake-test-key', base_url=url)):
		requests.clear()
		replies.append({'role': 'assistant', 'content': 'Done, it is ok.'})
		model, settings = resolve_model(llm)
		session = Session(repl=Repl(tmp_path))
		result = await run(build_agent(model, model_settings=settings), 'task', session, model.model_name)
		assert (result.status, result.output) == ('completed', 'ok')
		repair = requests[1][1]
		assert repair['tool_choice'] == 'required'
		assert {t['function']['name'] for t in repair['tools']} == {'finish', 'finish_from_repl'}


async def test_compatible_backends_get_no_strict_tool_definitions(chat_server, tmp_path):
	"""Fable r4-2: the chat path sent "strict": true on tools; Ollama and other compatible servers do not support it
	(Pydantic AI's own Ollama profile turns it off)."""
	url, requests, _ = chat_server
	for llm in (ChatOpenAI('my-ollama-model', api_key='x', base_url=url), ChatBrowserUse(api_key='fake-test-key', base_url=url)):
		requests.clear()
		model, settings = resolve_model(llm)
		result = await run(build_agent(model, model_settings=settings), 'task', Session(repl=Repl(tmp_path)), model.model_name)
		assert result.status == 'completed'
		assert [t['function'].get('strict') for t in requests[0][1]['tools'] if 'strict' in t['function']] == []


def test_openai_non_reasoning_models_get_no_reasoning_params():
	"""Fable r2-2: ChatOpenAI('gpt-4.1'/'gpt-4o') got reasoning params and max_output_tokens=32768: OpenAI 400s both."""
	for name in ('gpt-4.1', 'gpt-4o', 'gpt-4.1-mini'):
		model, settings = resolve_model(ChatOpenAI(name, api_key='sk-test'))
		assert build_agent(model, model_settings=settings).model_settings == {}, name
	model, _ = resolve_model(ChatOpenAI('gpt-6-luna', api_key='sk-test'))
	assert build_agent(model).model_settings['openai_reasoning_effort'] == 'medium'


def test_base_url_accepts_url_objects():
	"""Roast r2-13: ChatOpenAI(base_url=httpx.URL(...)) crashed with AttributeError; 0.x accepted it."""
	import httpx

	model, _ = resolve_model(ChatOpenAI('m', api_key='x', base_url=httpx.URL('http://localhost:11434/v1')))
	assert isinstance(model, OpenAIChatModel) and str(model.client.base_url).rstrip('/') == 'http://localhost:11434/v1'
