"""Model resolution. A local stub server stands in for OpenAI-compatible backends; no provider calls."""

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast

import pytest
from pydantic_ai.exceptions import UserError
from pydantic_ai.models.openai import OpenAIChatModel, OpenAICompaction, OpenAIResponsesModel

from browser_use import Agent, Browser, ChatAnthropic, ChatBrowserUse, ChatGoogle, ChatOpenAI
from browser_use.agent.loop import Session, build_agent, run
from browser_use.llm import GATEWAY_URL, model_ref, resolve_model
from browser_use.repl import Repl


def compaction(agent) -> bool:
	return any(isinstance(c, OpenAICompaction) for c in agent._root_capability.capabilities)


FINISH_OK = {
	'role': 'assistant',
	'content': None,
	'tool_calls': [
		{'id': 't1', 'type': 'function', 'function': {'name': 'finish', 'arguments': '{"result": "ok", "success": true}'}}
	],
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


GATEWAY_ITEMS = {
	'message',
	'function_call',
	'function_call_output',
	'custom_tool_call',
	'custom_tool_call_output',
	'reasoning',
	'compaction',
}


def gateway_violations(body: dict) -> list[str]:
	"""What the gateway's /responses (cloud pigateway/responses.go) rejects or silently drops: it stores nothing."""
	bad = [f for f in ('previous_response_id', 'conversation', 'prompt') if body.get(f) is not None]
	bad += [f for f in ('store', 'background') if body.get(f) is True]
	bad += [f'tool {t.get("type")}' for t in body.get('tools', []) if t.get('type') not in ('function', 'custom')]
	bad += [
		f'include {i}'
		for i in body.get('include', [])
		if i not in ('reasoning.encrypted_content', 'message.output_text.logprobs')
	]
	if isinstance(choice := body.get('tool_choice'), dict) and choice.get('type') not in ('function', 'custom', 'allowed_tools'):
		bad.append(f'tool_choice {choice.get("type")}')
	for item in body['input'] if isinstance(body['input'], list) else []:
		kind = item.get('type') or ('message' if 'role' in item else None)
		if kind not in GATEWAY_ITEMS:
			bad.append(f'input {kind}')  # item_reference, input_file, hosted tool calls
		elif kind in ('reasoning', 'compaction') and not item.get('encrypted_content'):
			bad.append(f'{kind} without encrypted_content')  # dropped (reasoning) or rejected (compaction)
		parts = item.get('output' if kind in ('function_call_output', 'custom_tool_call_output') else 'content')
		for part in parts if isinstance(parts, list) else []:
			if part.get('type') not in ('input_text', 'output_text', 'refusal', 'input_image') or 'file_id' in part:
				bad.append(f'content {part.get("type")}')
	return bad


def call(name: str, arguments: dict, n: int) -> dict:
	return {
		'type': 'function_call',
		'id': f'fc_{n}',
		'call_id': f'call_{n}',
		'name': name,
		'arguments': json.dumps(arguments),
		'status': 'completed',
	}


def reasoning(n: int) -> dict:
	return {'type': 'reasoning', 'id': f'rs_{n}', 'summary': [], 'encrypted_content': f'sealed-reasoning-{n}'}


@pytest.fixture
def responses_server():
	"""The gateway's POST /responses: 400 on what it rejects, else the queued `replies` (output item lists), then a
	finish call. The response carries browser_use{resolved_model, service_tier, charge_usd} as the gateway's does."""
	requests, replies = [], []

	class Handler(BaseHTTPRequestHandler):
		def do_POST(self):
			body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
			requests.append((self.path, body))
			bad = gateway_violations(body) if self.path == '/v1/responses' else ['path']
			if bad:
				status, reply = 400, {'error': {'code': 'stateful_request', 'message': '; '.join(bad)}}
			else:
				n = len(requests)
				output = replies.pop(0) if replies else [reasoning(n), call('finish', {'success': True, 'result': 'ok'}, n)]
				usage = {'input_tokens': 10, 'output_tokens': 2, 'total_tokens': 12,
						 'input_tokens_details': {'cached_tokens': 0}, 'output_tokens_details': {'reasoning_tokens': 1}}  # fmt: skip
				status, reply = 200, {
					'id': f'resp_{n}', 'object': 'response', 'created_at': 0, 'model': body['model'], 'status': 'completed',
					'output': output, 'usage': usage, 'parallel_tool_calls': True, 'tool_choice': 'auto', 'tools': [],
					'browser_use': {'resolved_model': 'gpt-6-luna', 'service_tier': 'priority', 'charge_usd': '0.00020000'},
				}  # fmt: skip
			data = json.dumps(reply).encode()
			self.send_response(status)
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


async def test_gateway_models_run_stateless_responses_with_compaction(responses_server, tmp_path):
	"""The gateway path was chat completions (no compaction, reasoning dropped every turn). Now: /responses as the
	gateway requires it, encrypted reasoning and compaction items sent back, no previous_response_id, the alias's own
	effort, cost = what the gateway charged."""
	url, requests, replies = responses_server
	replies += [
		[reasoning(1), call('python', {'code': 'print(6 * 7)'}, 1)],
		[
			{'type': 'compaction', 'id': 'cmp_2', 'encrypted_content': 'sealed-compaction-2'},
			reasoning(2),
			call('python', {'code': 'print(1)'}, 2),
		],
		[
			{
				'type': 'message',
				'id': 'msg_3',
				'role': 'assistant',
				'status': 'completed',
				'content': [{'type': 'output_text', 'text': 'Done.', 'annotations': []}],
			}
		],
	]  # the text reply is the answer (str result): no delivery repair request
	model, settings = resolve_model(ChatBrowserUse(api_key='fake-test-key', base_url=url))
	assert isinstance(model, OpenAIResponsesModel)
	# what Agent() passes for the gateway; threshold = the stub's 10 input tokens: compaction is requested from the 2nd call
	agent = build_agent(model, model_settings=settings, reasoning_effort=None, compact_at_tokens=10)
	assert compaction(agent)
	result = await run(agent, 'TASK-TEXT', Session(repl=Repl(tmp_path)), model.model_name)
	assert (result.status, result.output, result.error) == ('completed', 'Done.', None)
	assert [path for path, _ in requests] == ['/v1/responses'] * 3
	for i, (_, body) in enumerate(requests):
		assert body['model'] == 'bu-fast' and body['store'] is False and 'reasoning.encrypted_content' in body['include']
		# only once the last request reached the threshold: on every request it cost ~0.8 s per call
		assert body.get('context_management') == ([{'type': 'compaction', 'compact_threshold': 10}] if i else None)
		assert 'effort' not in body.get('reasoning', {})  # the gateway applies bu-fast's medium
	second, third = requests[1][1]['input'], requests[2][1]['input']  # after reply 1, after reply 2 (compaction)
	assert {'type': 'reasoning', 'encrypted_content': 'sealed-reasoning-1'}.items() <= next(
		i for i in second if i.get('type') == 'reasoning'
	).items()
	assert 'TASK-TEXT' in json.dumps(second) and 'TASK-TEXT' not in json.dumps(third)  # compacted away
	assert any(i.get('type') == 'compaction' and i['encrypted_content'] == 'sealed-compaction-2' for i in third)
	assert result.cost_usd == pytest.approx(3 * 0.0002)


async def test_responses_compaction_threshold_fits_the_model_window(responses_server, tmp_path):
	"""gpt-4o (128k window) never compacted: the fixed 150k threshold was above its window, so the run ended on the
	context-window error. The default is now capped at 65% of the window (here 15 tokens -> 9; the stub reports 10)."""
	from pydantic_ai.profiles.openai import openai_model_profile
	from pydantic_ai.providers.openai import OpenAIProvider

	url, requests, replies = responses_server
	replies += [[call('python', {'code': 'print(1)'}, 1)]]
	profile = {**openai_model_profile('gpt-4o'), 'context_window': 15}
	model = OpenAIResponsesModel('gpt-4o', provider=OpenAIProvider(base_url=url, api_key='x'), profile=cast(Any, profile))
	result = await run(build_agent(model), 'TASK-TEXT', Session(repl=Repl(tmp_path)), 'openai:gpt-4o')
	assert result.status == 'completed'
	assert [body.get('context_management') for _, body in requests] == [None, [{'type': 'compaction', 'compact_threshold': 9}]]


async def test_openai_responses_requests_are_not_stored(responses_server, tmp_path):
	"""bu-pi sends store=false; 1.0 sent none, so OpenAI stored every response, and the first byte came 168 ms later at
	39k tokens, 324 ms at 83k (live A/B on api.openai.com, same body). Nothing reads a stored response back: reasoning
	round-trips encrypted and no previous_response_id is sent (gateway_violations)."""
	from pydantic_ai.providers.openai import OpenAIProvider

	url, requests, replies = responses_server
	replies.append([reasoning(1), call('python', {'code': 'print(6 * 7)'}, 1)])
	model = OpenAIResponsesModel('gpt-6.1-sol', provider=OpenAIProvider(base_url=url, api_key='fake-test-key'))
	result = await run(build_agent(model), 'TASK-TEXT', Session(repl=Repl(tmp_path)), model.model_name)
	assert (result.status, result.output) == ('completed', 'ok'), result.error
	assert [body['store'] for _, body in requests] == [False, False]
	assert 'reasoning.encrypted_content' in requests[1][1]['include'] and 'sealed-reasoning-1' in json.dumps(requests[1][1])


async def test_responses_bodies_skip_the_sdk_transform(responses_server, tmp_path, monkeypatch):
	"""openai-python rewrote every Responses body against its TypedDicts before sending it: ~20k calls at 50k tokens,
	~30 ms per request on an M5 Pro, growing with the history (bu-pi's Node SDK sends the body as is). The create params
	carry no alias or format, so the pass could not change a byte; an openai that adds one keeps its own pass."""
	from typing import Annotated

	from openai._utils import PropertyInfo, _transform
	from openai.types.responses import response_create_params as params
	from typing_extensions import TypedDict

	from browser_use.llm import responses_params_rewrite

	class Aliased(TypedDict, total=False):
		card_id: Annotated[str, PropertyInfo(alias='cardID')]

	assert responses_params_rewrite(params.ResponseCreateParamsNonStreaming, list[Aliased])
	assert not responses_params_rewrite(params.ResponseCreateParamsNonStreaming, params.ResponseCreateParamsStreaming)

	calls, real = [], _transform._async_transform_recursive

	async def counted(*args, **kwargs):
		calls.append(1)
		return await real(*args, **kwargs)

	monkeypatch.setattr(_transform, '_async_transform_recursive', counted)
	url, requests, replies = responses_server
	replies.append([reasoning(1), call('python', {'code': 'print(6 * 7)'}, 1)])
	model, settings = resolve_model(ChatBrowserUse(api_key='fake-test-key', base_url=url))
	agent = build_agent(model, model_settings=settings, reasoning_effort=None)
	result = await run(agent, 'TASK-TEXT', Session(repl=Repl(tmp_path)), model.model_name)
	assert (result.status, result.output, len(requests)) == ('completed', 'ok', 2)
	assert '42' in json.dumps(requests[1][1]['input']) and calls == []


async def test_text_answer_reaches_the_repair_turn_when_a_compaction_item_ends_the_response(responses_server, tmp_path):
	"""agent-llm F2: the model answered in text, the response ended with a compaction item, and the delivery repair
	request was [compaction, retry]: the answer was gone, and the model then said it could not verify anything.
	Only a structured result gets the repair turn (C33)."""
	url, requests, replies = responses_server
	answer = 'There are 120 books; the cheapest is Patience at 10.16.'
	replies.append(
		[
			reasoning(1),
			{'type': 'message', 'id': 'msg_1', 'role': 'assistant', 'status': 'completed',
			 'content': [{'type': 'output_text', 'text': answer, 'annotations': []}]},
			{'type': 'compaction', 'id': 'cmp_1', 'encrypted_content': 'sealed-compaction-1'},
		]
	)  # fmt: skip
	replies.append([reasoning(2), call('finish', {'success': True, 'result': {'books': 120}}, 2)])
	model, settings = resolve_model(ChatBrowserUse(api_key='fake-test-key', base_url=url))
	agent = build_agent(model, model_settings=settings, reasoning_effort=None, output_type=dict[str, int])
	result = await run(agent, 'TASK-TEXT', Session(repl=Repl(tmp_path)), model.model_name)
	assert (result.status, result.output) == ('completed', {'books': 120})
	repair = requests[1][1]['input']
	assert repair[0]['type'] == 'compaction' and 'TASK-TEXT' not in json.dumps(repair)  # compacted as before
	assert answer in json.dumps(repair)  # but the answer to deliver is in the repair request itself


@pytest.fixture
def models_server():
	"""The gateway's GET /models: answers with `reply` = [status, body, content type]."""
	reply, seen = (
		[200, {'data': [{'id': 'bu-ultrafast'}, {'id': 'bu-fast'}, {'id': 'bu-auto'}, {'id': 'gpt-6-luna'}]}, 'application/json'],
		[],
	)

	class Handler(BaseHTTPRequestHandler):
		def do_GET(self):
			seen.append((self.path, self.headers.get('Authorization')))
			status, body, kind = reply
			data = (json.dumps(body) if kind == 'application/json' else body).encode()
			self.send_response(status)
			self.send_header('Content-Type', kind)
			self.send_header('Content-Length', str(len(data)))
			self.end_headers()
			self.wfile.write(data)

		def log_message(self, *args):
			pass

	server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
	threading.Thread(target=server.serve_forever, daemon=True).start()
	yield f'http://127.0.0.1:{server.server_address[1]}/v1', reply, seen
	server.shutdown()


def error(code: str, message: str) -> dict:
	return {'error': {'code': code, 'message': message, 'type': code}}


def test_preflight_checks_the_gateway_key_and_model_before_anything_starts(models_server):
	"""agent-llm F4/F6: a gateway that is not deployed, a rejected key or a model the gateway does not serve failed only
	after a cloud browser had been created and billed."""
	url, reply, seen = models_server
	assert ChatBrowserUse(api_key='fake-test-key', base_url=url).preflight() is None
	assert ChatBrowserUse('openai/gpt-6-luna', api_key='fake-test-key', base_url=url).preflight() is None
	assert seen[0] == ('/v1/models', 'Bearer fake-test-key')
	missing = ChatBrowserUse('bu-nonexistent-xyz', api_key='fake-test-key', base_url=url).preflight()
	assert missing == 'bu-nonexistent-xyz is not on the Browser Use gateway. Listed: bu-auto, bu-fast, bu-ultrafast, gpt-6-luna.'
	for legacy in ('bu-2-0', 'bu-latest', 'bu-2-0-mini-preview'):  # M4: refused locally, the gateway 404s them
		with pytest.raises(ValueError, match=r"needs browser-use<1\.0 \(pip install 'browser-use<1\.0'\), or use bu-fast"):
			ChatBrowserUse(legacy, api_key='fake-test-key', base_url=url)
		with pytest.raises(ValueError, match='needs browser-use<1.0'):
			Agent('t', legacy)
	assert not any(path for path, _ in seen[1:] if 'legacy' in path)
	reply[:] = [404, '404 page not found', 'text/plain']  # the route itself is missing (Go's default 404)
	dead = ChatBrowserUse(api_key='fake-test-key', base_url=url).preflight()
	assert dead and f'gateway is not deployed at {url} (404)' in dead and 'region' not in dead  # H1: no region claim
	assert 'model id' not in dead
	reply[:] = [401, error('invalid_api_key', 'Invalid API key.'), 'application/json']
	rejected = ChatBrowserUse(api_key='bad', base_url=url).preflight() or ''
	assert 'API key rejected (401): check api_key=..., or BROWSER_USE_API_KEY' in rejected  # C38: may be either key
	reply[:] = [403, error('insufficient_scope', 'This API key requires v4:runs:create permission.'), 'application/json']
	assert 'requires v4:runs:create permission. Run `browser-use login`' in (
		ChatBrowserUse(api_key='x', base_url=url).preflight() or ''
	)
	with socket.socket() as s:  # a port nothing listens on
		s.bind(('127.0.0.1', 0))
		closed = f'http://127.0.0.1:{s.getsockname()[1]}/v1'
	assert 'is not reachable' in (ChatBrowserUse(api_key='x', base_url=closed).preflight() or '')


async def test_agent_preflight_failure_never_starts_a_browser(models_server, monkeypatch, tmp_path):
	from browser_use import Browser

	url, reply, _ = models_server
	reply[:] = [404, '404 page not found', 'text/plain']
	started = []

	async def start(self):
		started.append(self)
		return {}

	monkeypatch.setattr(Browser, 'start', start)
	agent = Agent('t', ChatBrowserUse(api_key='fake-test-key', base_url=url), browser=Browser(local=True), workspace=tmp_path)
	result = await agent.run()
	assert (result.status, result.steps, result.is_successful()) == ('error', 0, None)
	assert 'gateway is not deployed at' in (result.error or '') and started == []
	# C38: a provider key is checked on a local browser too, not only before a billed cloud browser
	monkeypatch.setattr('browser_use.agent.service.provider_preflight', lambda model: 'openai rejected the API key (401)')
	result = await Agent('t', ChatOpenAI('gpt-6-luna', api_key='bad'), browser=Browser(local=True), workspace=tmp_path).run()
	assert result.error == 'openai rejected the API key (401)' and started == []


def test_missing_provider_key_names_the_env_var_not_pydantic_ai_internals(monkeypatch):
	"""C38: Pydantic AI's text named OpenAIProvider(api_key=...) and suggested Agent('test'), a task named 'test' here."""
	monkeypatch.delenv('OPENAI_API_KEY', raising=False)
	for llm in (ChatOpenAI('gpt-6-luna'), 'openai:gpt-6-luna'):
		with pytest.raises(UserError) as e:
			resolve_model(llm)
		assert str(e.value) == 'OPENAI_API_KEY is not set: export it, put it in .env, or pass api_key=... to the model.'


def test_gateway_400s_are_one_line_with_the_gateway_message():
	"""agent-llm F5: 400s came back as 'ModelRequestRejectedError: status_code: 400, model_name: ..., body: {...}'."""
	from pydantic_ai.exceptions import ModelHTTPError

	legacy = {'code': 'legacy_model', 'message': 'This model requires browser-use<1.0. Use bu-auto with the new library.'}
	llm = ChatBrowserUse(api_key='x')
	llm.model = 'bu-2-0'  # refused at construction (M4); the gateway's own legacy_model answer still reads the same
	line = llm.explain_error(ModelHTTPError(400, 'bu-2-0', legacy))
	assert line == "bu-2-0 needs browser-use<1.0 (pip install 'browser-use<1.0'), or use bu-fast with browser-use 1.0."
	for code in ('invalid_model', 'model_not_on_gateway'):
		body = {'code': code, 'message': 'Use bu-auto, bu-ultrafast, bu-smart, or a listed OpenAI model.'}
		line = ChatBrowserUse('kimi-k3', api_key='x').explain_error(ModelHTTPError(400, 'kimi-k3', body))
		assert line == f'kimi-k3 is not on the Browser Use gateway (400): {body["message"]}'
	other = {'code': 'invalid_request', 'message': 'n must be 1'}
	assert ChatBrowserUse(api_key='x').explain_error(ModelHTTPError(400, 'bu-ultrafast', other)) is None


def test_every_gateway_model_and_the_gateway_url_use_responses(monkeypatch):
	monkeypatch.setenv('BROWSER_USE_API_KEY', 'fake-test-key')
	for name in ('bu-ultrafast', 'bu-auto', 'bu-smart', 'gpt-6.1-sol'):
		model, _ = resolve_model(ChatBrowserUse(name))
		assert isinstance(model, OpenAIResponsesModel) and model.model_name == name  # never renamed
		assert model.profile['openai_responses_requires_store_false'] and model.profile['openai_supports_reasoning']
	model, _ = resolve_model(ChatOpenAI('bu-auto', base_url=GATEWAY_URL))
	assert isinstance(model, OpenAIResponsesModel) and model.profile['openai_responses_requires_store_false']
	agent = Agent('t', ChatBrowserUse(), browser=None)
	agent._build()
	assert 'openai_reasoning_effort' not in agent._agent.model_settings  # the alias decides
	agent = Agent('t', ChatBrowserUse(), browser=None, reasoning='high')
	agent._build()
	assert agent._agent.model_settings['openai_reasoning_effort'] == 'high'


async def test_gateway_tool_revealed_mid_run_sends_no_additional_tools_item(responses_server, tmp_path):
	"""Roast: a tool hidden on turn 1 and shown on turn 2 went out as an `additional_tools` input item, which the
	gateway rejects (400 unsupported_input). Now the reveal is a plain tools-list change."""
	from pydantic_ai import Tool

	url, requests, replies = responses_server
	replies += [[reasoning(1), call('python', {'code': 'print(1)'}, 1)]]

	def lookup(q: str) -> str:
		return q

	async def later(ctx, tool_def):
		return tool_def if ctx.run_step > 1 else None

	model, settings = resolve_model(ChatBrowserUse(api_key='fake-test-key', base_url=url))
	agent = build_agent(model, model_settings=settings, reasoning_effort=None, tools=[Tool(lookup, prepare=later)])
	result = await run(agent, 'TASK-TEXT', Session(repl=Repl(tmp_path)), model.model_name)
	assert (result.status, result.error) == ('completed', None)
	first, second = requests[0][1], requests[1][1]
	assert 'lookup' not in json.dumps(first['tools']) and 'lookup' in json.dumps(second['tools'])
	assert 'additional_tools' not in json.dumps([body for _, body in requests])


def test_gateway_detection_https_only_and_openai_key_precedence(monkeypatch):
	"""Roast: http:// (or another port) on the gateway host got the Browser Use key attached in clear text; with
	OPENAI_BASE_URL=gateway, a Browser Use key in OPENAI_API_KEY (the 0.x setup) was ignored."""
	monkeypatch.delenv('OPENAI_BASE_URL', raising=False)
	monkeypatch.setenv('BROWSER_USE_API_KEY', 'bu-env-key')
	for url in ('http://api.browser-use.com/api/v4/llm/v1', 'https://api.browser-use.com:8443/api/v4/llm/v1'):
		assert not ChatOpenAI('bu-auto', api_key='x', base_url=url).is_gateway
	assert ChatOpenAI('bu-auto', base_url=GATEWAY_URL + '/').is_gateway
	monkeypatch.setenv('OPENAI_BASE_URL', GATEWAY_URL)
	monkeypatch.setenv('OPENAI_API_KEY', 'bu_openai_env')
	model, _ = resolve_model(ChatOpenAI('bu-auto'))
	assert isinstance(model, OpenAIResponsesModel) and model.client.api_key == 'bu_openai_env'
	agent = Agent('t', ChatOpenAI('bu-auto'), browser=None)
	agent._build()  # the preflight checks the key the model sends, not the Browser Use key
	assert agent._gateway and agent._gateway.api_key == 'bu_openai_env'
	monkeypatch.setenv('OPENAI_API_KEY', 'sk-not-a-gateway-key')  # an OpenAI key never works there
	model, _ = resolve_model(ChatOpenAI('bu-auto'))
	assert model.client.api_key == 'bu-env-key'
	assert resolve_model(ChatOpenAI('bu-auto', api_key='explicit'))[0].client.api_key == 'explicit'


def test_agent_treats_every_gateway_model_form_alike(monkeypatch):
	"""Roast: ChatOpenAI(base_url=gateway) lost the actionable 401/402 lines, and an already-resolved gateway model
	(ChatBrowserUse(...).pydantic_model()) got 'medium' instead of the alias's own effort."""
	from pydantic_ai.exceptions import ModelHTTPError

	monkeypatch.setenv('BROWSER_USE_API_KEY', 'fake-test-key')
	for llm in (
		ChatBrowserUse('bu-smart'),
		ChatOpenAI('bu-smart', base_url=GATEWAY_URL),
		ChatBrowserUse('bu-smart').pydantic_model(),
	):
		agent = Agent('t', llm, browser=None)
		agent._build()
		assert 'openai_reasoning_effort' not in agent._agent.model_settings
		assert agent._gateway and 'tab=billing' in agent._gateway.explain_error(ModelHTTPError(402, 'bu-smart'))
		assert agent._model_ref == 'browser-use:bu-smart'
	agent = Agent('t', ChatOpenAI('gpt-6-luna', api_key='sk-test'), browser=None)
	agent._build()
	assert agent._agent.model_settings['openai_reasoning_effort'] == 'medium' and agent._gateway is None


def test_gateway_cost_is_the_charge_or_none_never_a_retail_estimate():
	"""Roast: a gateway response without charge_usd (e.g. a listed gpt-4.1) was priced at OpenAI retail and summed
	with real charges into one authoritative-looking total."""
	from pydantic_ai.messages import ModelResponse, TextPart
	from pydantic_ai.usage import RequestUsage

	from browser_use.agent.loop import usage_and_cost

	u = RequestUsage(input_tokens=1000, output_tokens=100)

	def reply(charge):
		details = None if charge is None else {'browser_use': {'charge_usd': charge}}
		return ModelResponse(parts=[TextPart('x')], usage=u, provider_details=details)

	assert usage_and_cost([reply('0.0002'), reply('0.0003')], 'browser-use:gpt-4.1')[1] == pytest.approx(0.0005)
	assert usage_and_cost([reply('0.0002'), reply(None)], 'browser-use:gpt-4.1')[1] is None
	assert usage_and_cost([reply('nan')], 'browser-use:gpt-4.1')[1] is None
	assert usage_and_cost([reply(None)], 'openai:gpt-4.1')[1]  # non-gateway: still priced


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


def test_default_llm_is_bu_fast_on_the_gateway(monkeypatch):
	monkeypatch.setenv('BROWSER_USE_API_KEY', 'fake-test-key')
	agent = Agent('t', browser=None)
	assert isinstance(agent.llm, ChatBrowserUse) and agent.llm.model == 'bu-fast'
	assert ChatBrowserUse().model == 'bu-fast'
	model, _ = resolve_model(agent.llm)
	assert isinstance(model, OpenAIResponsesModel) and model.model_name == 'bu-fast'
	assert str(model.client.base_url).rstrip('/') == GATEWAY_URL
	assert Agent('t', 'bu-auto').llm.model == 'bu-auto'  # still available; ids are passed through, never renamed
	assert Agent('t', 'bu-smart').llm.model == 'bu-smart'


async def test_gateway_errors_are_one_actionable_line():
	from pydantic_ai.exceptions import ModelHTTPError

	llm = ChatBrowserUse(api_key='fake-test-key')
	assert 'cloud.browser-use.com/settings?tab=billing' in llm.explain_error(ModelHTTPError(402, 'bu-ultrafast'))
	assert 'browser-use login' in llm.explain_error(ModelHTTPError(401, 'bu-ultrafast'))
	not_found = llm.explain_error(ModelHTTPError(404, 'bu-ultrafast'))
	assert f'gateway is not deployed at {GATEWAY_URL} (404)' in not_found and 'model id' not in not_found
	assert llm.explain_error(ModelHTTPError(500, 'bu-ultrafast')) is None
	# 403 has several causes: the gateway's own message (body as the OpenAI SDK passes it) names the actual one
	policy = {'message': 'This project policy does not permit the new Browser Use LLM gateway.', 'code': 'project_policy'}
	error = ModelHTTPError(403, 'bu-ultrafast', policy, provider_error_code='project_policy')
	assert llm.explain_error(error) == f'bu-fast is not available for this key (403): {policy["message"]}'
	scope = {'message': 'This API key requires v4:runs:create permission.', 'code': 'insufficient_scope'}
	error = ModelHTTPError(403, 'bu-ultrafast', scope, provider_error_code='insufficient_scope')
	assert llm.explain_error(error) == f'{scope["message"]} Run `browser-use login` again for a new key.'
	assert 'ChatOpenAI' in llm.explain_error(ModelHTTPError(403, 'bu-ultrafast'))  # no body: a generic hint


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


def test_langchain_llm_raises_in_agent_init_with_qualified_name():
	"""A LangChain ChatOpenAI shares browser_use.ChatOpenAI's class name: the error names its module, at Agent()."""
	LangChainChatOpenAI = type('ChatOpenAI', (), {'__module__': 'langchain_openai.chat_models.base'})
	with pytest.raises(TypeError, match=r'llm=langchain_openai\.chat_models\.base\.ChatOpenAI is not supported'):
		Agent('t', llm=LangChainChatOpenAI(), browser=Browser('chromium'))


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
		[{'type': 'tool_use', 'id': 'tu_1', 'name': 'finish', 'input': {'result': 42, 'success': True}}],
	)
	model = AnthropicModel(name, provider=AnthropicProvider(anthropic_client=client))
	agent = build_agent(model, output_type=int)  # a str result takes the text reply as the answer (C33)
	result = await run(agent, 'task', Session(repl=Repl(tmp_path)), f'anthropic:{name}')
	assert (result.status, result.output, result.error) == ('completed', 42, None)
	first, repair = bodies
	assert 'python' in {t['name'] for t in first['tools']}
	assert {t['name'] for t in repair['tools']} == {'finish', 'finish_from_repl'}  # python withheld
	assert repair.get('tool_choice', {'type': 'auto'})['type'] == 'auto' and repair.get('thinking')


async def test_claude_returns_its_thinking_text_as_bu_pi_asks_for_it(tmp_path):
	"""Matrix v2: Haiku 5.5 compacted 0 times (bu-pi 17). Claude models with adaptive thinking default to display
	'omitted': all 124 thinking blocks of Haiku bub2-001 came back empty, so the history lacked the reasoning text
	bu-pi's context size counts (112k of its 582k characters there). bu-pi's pi-ai asks for 'summarized'. The effort
	still applies, and a caller who turns thinking off keeps it off."""
	from pydantic_ai.models.anthropic import AnthropicModel
	from pydantic_ai.providers.anthropic import AnthropicProvider

	async def first_body(name, **kwargs):
		client, bodies = anthropic_mock([{'type': 'text', 'text': 'done'}])
		model = AnthropicModel(name, provider=AnthropicProvider(anthropic_client=client))
		result = await run(build_agent(model, **kwargs), 'task', Session(repl=Repl(tmp_path)), f'anthropic:{name}')
		assert (result.status, result.output) == ('completed', 'done'), result.error
		return bodies[0]

	body = await first_body('claude-haiku-5-5', reasoning_effort='high')
	assert body['thinking'] == {'type': 'adaptive', 'display': 'summarized'} and body['output_config']['effort'] == 'high'
	assert (await first_body('claude-haiku-5-5', model_settings={'thinking': False}))['thinking'] == {'type': 'disabled'}
	assert body['thinking'] == (await first_body('claude-opus-5-5'))['thinking']
	assert (await first_body('claude-sonnet-4-5'))['thinking']['type'] == 'enabled'  # summarized is its API default


async def test_compatible_backends_get_plain_required_on_the_delivery_turn(chat_server, tmp_path):
	"""Fable r2-4: chat backends got OpenAI's allowed_tools tool_choice, which vLLM/DeepSeek reject and Ollama ignores."""
	url, requests, replies = chat_server
	for llm in (ChatOpenAI('my-vllm-model', api_key='x', base_url=url),):
		requests.clear()
		replies.append({'role': 'assistant', 'content': 'Done, it is ok.'})
		model, settings = resolve_model(llm)
		session = Session(repl=Repl(tmp_path))
		agent = build_agent(model, model_settings=settings, output_type=list[str])  # str takes the text reply (C33)
		replies.append(
			{'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'c1', 'type': 'function',
			 'function': {'name': 'finish', 'arguments': json.dumps({'result': ['ok'], 'success': True})}}]}
		)  # fmt: skip
		result = await run(agent, 'task', session, model.model_name)
		assert (result.status, result.output) == ('completed', ['ok'])
		repair = requests[1][1]
		assert repair['tool_choice'] == 'required'
		assert {t['function']['name'] for t in repair['tools']} == {'finish', 'finish_from_repl'}


async def test_compatible_backends_get_no_strict_tool_definitions(chat_server, tmp_path):
	"""Fable r4-2: the chat path sent "strict": true on tools; Ollama and other compatible servers do not support it
	(Pydantic AI's own Ollama profile turns it off)."""
	url, requests, _ = chat_server
	for llm in (ChatOpenAI('my-ollama-model', api_key='x', base_url=url),):
		requests.clear()
		model, settings = resolve_model(llm)
		result = await run(build_agent(model, model_settings=settings), 'task', Session(repl=Repl(tmp_path)), model.model_name)
		assert result.status == 'completed'
		assert [t['function'].get('strict') for t in requests[0][1]['tools'] if 'strict' in t['function']] == []


def test_openai_non_reasoning_models_get_no_reasoning_params():
	"""Fable r2-2: ChatOpenAI('gpt-4.1'/'gpt-4o') got reasoning params and max_output_tokens=32768: OpenAI 400s both."""
	for name in ('gpt-4.1', 'gpt-4o', 'gpt-4.1-mini'):
		model, settings = resolve_model(ChatOpenAI(name, api_key='sk-test'))
		assert build_agent(model, model_settings=settings).model_settings == {'openai_store': False}, name
	model, _ = resolve_model(ChatOpenAI('gpt-6-luna', api_key='sk-test'))
	assert build_agent(model).model_settings['openai_reasoning_effort'] == 'medium'


def test_openai_reasoning_models_on_chat_completions_get_reasoning_off(monkeypatch):
	"""M1: 'openai-chat:gpt-6-luna' 400ed on the first request ("Function tools with reasoning_effort are not supported
	... set reasoning_effort to 'none'"): OpenAI turns reasoning on by default there. ChatOpenAI('gpt-6-luna',
	base_url=proxy) still 400ed 5/5 on step 1: 'none' went to api.openai.com only. It is decided by the model name now;
	models OpenAI's profile does not know (DeepSeek, Grok, OpenRouter names) get nothing on any host."""
	from pydantic_ai.models.openai import OpenAIChatModel
	from pydantic_ai.providers.openai import OpenAIProvider

	from browser_use.agent.loop import build_agent

	monkeypatch.setenv('OPENAI_API_KEY', 'sk-test')
	assert build_agent('openai-chat:gpt-6-luna').model_settings == {'openai_reasoning_effort': 'none'}
	official = OpenAIChatModel('gpt-6-luna', provider=OpenAIProvider(api_key='k'))
	assert build_agent(official).model_settings == {'openai_reasoning_effort': 'none'}
	assert build_agent('openai-chat:gpt-4.1').model_settings == {}
	for older in ('o1', 'o3', 'o4-mini', 'gpt-5'):  # review: they reject 'none' (400) and take tools with reasoning on
		assert build_agent(f'openai-chat:{older}').model_settings == {}, older
	proxy = ChatOpenAI('gpt-6-luna', base_url='http://127.0.0.1:1/v1', api_key='k').pydantic_model()
	assert build_agent(proxy).model_settings == {'openai_reasoning_effort': 'none'}
	for name, url in (
		('deepseek-reasoner', 'https://api.deepseek.com/v1'),
		('grok-4', 'https://api.x.ai/v1'),
		('openai/gpt-6-luna', 'https://openrouter.ai/api/v1'),
		('gpt-oss-120b', 'http://127.0.0.1:1/v1'),
		('gpt-5', 'http://127.0.0.1:1/v1'),
	):
		other = ChatOpenAI(name, base_url=url, api_key='k').pydantic_model()
		assert build_agent(other).model_settings == {}, name


async def test_gpt_6_luna_behind_a_proxy_is_sent_reasoning_none(chat_server, tmp_path):
	"""ChatOpenAI('gpt-6-luna', base_url=proxy) failed 5/5 on step 1 (400: function tools need reasoning_effort
	'none'): the request carried no effort. A model the proxy serves under another name gets none."""
	url, requests, _ = chat_server
	for name, effort in (('gpt-6-luna', 'none'), ('my-vllm-model', None)):
		requests.clear()
		model, settings = resolve_model(ChatOpenAI(name, api_key='x', base_url=url))
		result = await run(build_agent(model, model_settings=settings), 'task', Session(repl=Repl(tmp_path)), name)
		assert result.status == 'completed', result.error
		assert requests[0][1].get('reasoning_effort') == effort, name


def test_anthropic_models_use_prompt_caching():
	"""M6: no Anthropic prompt caching: cache_read and cache_write were 0 in every Claude run. Review: the explicit
	settings it added overrode a caller's anthropic_cache=False, and with anthropic_cache_messages=True every request
	raised UserError (the two cannot be combined)."""
	from pydantic_ai.models import ModelRequestParameters
	from pydantic_ai.models.anthropic import AnthropicModel
	from pydantic_ai.providers.anthropic import AnthropicProvider
	from pydantic_ai.settings import merge_model_settings

	from browser_use.agent.loop import build_agent

	def sent(model):  # what Pydantic AI prepares for the request: the model's own settings under the agent's
		agent_settings = build_agent(model).model_settings
		prepared = model.prepare_request(merge_model_settings(model.settings, agent_settings), ModelRequestParameters())[0]
		return {k: v for k, v in (prepared or {}).items() if 'cache' in k}

	cache = {'anthropic_cache_instructions': '5m', 'anthropic_cache_tool_definitions': '5m', 'anthropic_cache': '5m'}
	adaptive = {'type': 'adaptive', 'display': 'summarized'}
	assert build_agent('anthropic:claude-haiku-5-5').model_settings == {
		'thinking': 'medium',
		'cache': True,
		'anthropic_thinking': adaptive,
	}
	assert sent(ChatAnthropic('claude-haiku-5-5', api_key='k').pydantic_model()) == cache
	for own in ({'anthropic_cache': False}, {'anthropic_cache_messages': True}):
		model = AnthropicModel('claude-haiku-5-5', provider=AnthropicProvider(api_key='k'), settings=own)
		assert sent(model) == own, own
	model = AnthropicModel('claude-haiku-5-5', provider=AnthropicProvider(api_key='k'), settings={'cache': False})
	assert sent(model) == {}
	assert 'cache' not in build_agent(ChatGoogle('gemini-2.5-pro', api_key='k').pydantic_model()).model_settings


def test_base_url_accepts_url_objects():
	"""Roast r2-13: ChatOpenAI(base_url=httpx.URL(...)) crashed with AttributeError; 0.x accepted it."""
	import httpx

	model, _ = resolve_model(ChatOpenAI('m', api_key='x', base_url=httpx.URL('http://localhost:11434/v1')))
	assert isinstance(model, OpenAIChatModel) and str(model.client.base_url).rstrip('/') == 'http://localhost:11434/v1'


def test_secretstr_api_keys_are_sent_as_the_plain_key():
	"""C16: LangChain-era code passes SecretStr; the SDKs str() it, so '**********' went out as the key."""
	from pydantic import SecretStr

	assert resolve_model(ChatOpenAI('m', api_key=SecretStr('k')))[0].client.api_key == 'k'
	assert resolve_model(ChatOpenAI('m', api_key=SecretStr('k'), base_url='http://localhost:1/v1'))[0].client.api_key == 'k'
	assert resolve_model(ChatAnthropic('claude-opus-5-5', api_key=SecretStr('k')))[0].client.api_key == 'k'
	assert ChatGoogle('gemini-3-flash', api_key=SecretStr('k')).api_key == 'k'
	assert resolve_model(ChatGoogle('gemini-3-flash', api_key=SecretStr('k')))[0].model_name == 'gemini-3-flash'
	assert ChatBrowserUse(api_key=SecretStr(' bu_k\n')).api_key == 'bu_k'


async def test_gemini_requests_are_retried_by_the_client_like_openai_and_anthropic(tmp_path):
	"""google-genai retries nothing unless asked (OpenAI and Anthropic SDKs retry twice), so two 503 'overloaded' in a
	run ended a Gemini run: BrowserLoop's one retry per run was all it had. Two 503s in a row now pass."""
	from google.genai.types import HttpRetryOptions
	from pydantic_ai.models.google import GoogleModel
	from pydantic_ai.providers.google import GoogleProvider

	calls = []

	class Gemini(BaseHTTPRequestHandler):
		def do_POST(self):
			self.rfile.read(int(self.headers['Content-Length']))
			calls.append(self.path)
			if len(calls) <= 2:
				status, reply = 503, {'error': {'code': 503, 'message': 'The model is overloaded.', 'status': 'UNAVAILABLE'}}
			else:
				part = {'functionCall': {'name': 'finish', 'args': {'result': 'ok', 'success': True}}}
				status, reply = (
					200,
					{
						'candidates': [{'content': {'role': 'model', 'parts': [part]}, 'finishReason': 'STOP'}],
						'usageMetadata': {'promptTokenCount': 10, 'candidatesTokenCount': 2, 'totalTokenCount': 12},
					},
				)
			data = json.dumps(reply).encode()
			self.send_response(status)
			self.send_header('Content-Type', 'application/json')
			self.send_header('Content-Length', str(len(data)))
			self.end_headers()
			self.wfile.write(data)

		def log_message(self, *args):
			pass

	server = ThreadingHTTPServer(('127.0.0.1', 0), Gemini)
	threading.Thread(target=server.serve_forever, daemon=True).start()
	# attempts=1: google-genai's default (no retry); its delays are kept, shortened here
	fast = HttpRetryOptions(attempts=1, initial_delay=0.01, max_delay=0.02, jitter=0)
	provider = GoogleProvider(api_key='x', base_url=f'http://127.0.0.1:{server.server_address[1]}', retry_options=fast)
	try:
		agent = build_agent(GoogleModel('gemini-3.5-flash', provider=provider))
		result = await run(agent, 'task', Session(repl=Repl(tmp_path)), 'google-gla:gemini-3.5-flash')
	finally:
		server.shutdown()
	assert (result.status, result.output, result.error) == ('completed', 'ok', None)
	assert len(calls) == 3


async def test_a_models_own_settings_win_over_the_agent_defaults(tmp_path, monkeypatch):
	"""AnthropicModel/GoogleModel(settings={'thinking': False}) still sent thinking='medium': Pydantic AI puts a Model's
	settings below the Agent's, and build_agent's defaults went in the Agent's."""
	from pydantic_ai.messages import ModelResponse, ToolCallPart
	from pydantic_ai.models.anthropic import AnthropicModel
	from pydantic_ai.models.google import GoogleModel
	from pydantic_ai.providers.anthropic import AnthropicProvider
	from pydantic_ai.providers.google import GoogleProvider

	sent = []

	async def request(self, messages, model_settings, params):
		sent.append(dict(model_settings or {}))
		return ModelResponse(parts=[ToolCallPart('finish', {'result': 'ok', 'success': True})])

	monkeypatch.setattr(AnthropicModel, 'request', request)
	monkeypatch.setattr(GoogleModel, 'request', request)
	off = {'thinking': False, 'max_retries': 0}
	models = [
		AnthropicModel('claude-haiku-5-5', provider=AnthropicProvider(api_key='x'), settings=off),
		GoogleModel('gemini-3.5-flash', provider=GoogleProvider(api_key='x'), settings=off),
		GoogleModel('gemini-3.5-flash', provider=GoogleProvider(api_key='x')),
	]
	for m in models:
		await run(build_agent(m), 'task', Session(repl=Repl(tmp_path)), 'x:y')
	assert [(s.get('thinking'), s.get('max_retries')) for s in sent] == [(False, 0), (False, 0), ('medium', 2)]


def test_openai_compatible_backends_are_priced_as_the_provider_at_their_url():
	"""ChatOpenAI(model, base_url=...) on DeepSeek, OpenRouter or xAI reported cost_usd=None: the model reports
	system='openai', and OpenAI has no price for 'deepseek-chat'. genai-prices knows them by their API URL."""
	from pydantic_ai.messages import ModelResponse
	from pydantic_ai.usage import RequestUsage

	from browser_use.agent.loop import usage_and_cost

	for name, url in (
		('deepseek-chat', 'https://api.deepseek.com/v1'),
		('anthropic/claude-sonnet-4.5', 'https://openrouter.ai/api/v1'),
		('grok-4', 'https://api.x.ai/v1'),
	):
		agent = Agent('t', ChatOpenAI(name, api_key='x', base_url=url))
		agent._build()
		reply = ModelResponse(parts=[], usage=RequestUsage(input_tokens=100_000, output_tokens=1_000), model_name=name)
		assert usage_and_cost([reply], agent._model_ref)[1], (name, agent._model_ref)
	agent = Agent('t', ChatOpenAI('my-model', api_key='x', base_url='http://localhost:11434/v1'))
	agent._build()
	assert agent._model_ref == 'openai:my-model'  # unknown backend: unchanged, no made-up price
