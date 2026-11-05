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


@pytest.fixture
def chat_server():
	"""OpenAI-compatible /chat/completions that answers every request with a finish tool call."""
	requests = []

	class Handler(BaseHTTPRequestHandler):
		def do_POST(self):
			body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
			requests.append((self.path, body))
			reply = {
				'id': 'c1',
				'object': 'chat.completion',
				'created': 0,
				'model': body['model'],
				'choices': [
					{
						'index': 0,
						'finish_reason': 'tool_calls',
						'message': {
							'role': 'assistant',
							'content': None,
							'tool_calls': [
								{'id': 't1', 'type': 'function', 'function': {'name': 'finish', 'arguments': '{"result": "ok"}'}}
							],
						},
					}
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
	yield f'http://127.0.0.1:{server.server_address[1]}/v1', requests
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
	url, requests = chat_server
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


async def test_gateway_errors_are_one_actionable_line(chat_server, tmp_path):
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
