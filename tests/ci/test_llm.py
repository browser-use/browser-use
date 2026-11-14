"""Model resolution. A local stub server stands in for OpenAI-compatible backends; no provider calls."""

import json
import socket
import threading
import time
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


def sse(response: dict) -> list[bytes]:
	"""The response as OpenAI and the gateway stream it, one frame per event: created, each output item (added,
	deltas, done), then response.completed (or response.failed) carrying the whole response, usage and browser_use."""
	events: list[dict] = []

	def emit(kind: str, **data: Any) -> None:
		events.append({'type': kind, 'sequence_number': len(events), **data})

	# An item's 'streamed' encrypted_content is what its own added/done events carry where response.completed differs
	streamed = {item['id']: item['streamed'] for item in response['output'] if 'streamed' in item}
	response = {**response, 'output': [{k: v for k, v in item.items() if k != 'streamed'} for item in response['output']]}
	emit('response.created', response={**response, 'status': 'in_progress', 'output': [], 'usage': None})
	if response['status'] == 'error':  # the gateway's frame for an upstream that failed mid-stream (openaistream ErrorSSE)
		events.append({'type': 'error', 'sequence_number': 0, 'error': response['error']})
		return [f'event: {e["type"]}\ndata: {json.dumps(e)}\n\n'.encode() for e in events]
	for i, item in enumerate(response['output']):
		if item['type'] == 'message':
			emit('response.output_item.added', output_index=i, item={**item, 'status': 'in_progress', 'content': []})
			for j, part in enumerate(item['content']):
				where = {'item_id': item['id'], 'output_index': i, 'content_index': j, 'logprobs': []}
				emit('response.output_text.delta', **where, delta=part['text'])
				emit('response.output_text.done', **where, text=part['text'])
		elif item['type'] == 'function_call':
			emit('response.output_item.added', output_index=i, item={**item, 'status': 'in_progress', 'arguments': ''})
			where = {'item_id': item['id'], 'output_index': i}
			emit('response.function_call_arguments.delta', **where, delta=item['arguments'])
			emit('response.function_call_arguments.done', **where, arguments=item['arguments'], name=item['name'])
		elif seen := streamed.get(item['id']):  # gpt-6-luna live: added has a provisional token, then compacting
			emit('response.output_item.added', output_index=i, item={**item, 'encrypted_content': seen['added']})
			emit('response.compaction.compacting', item_id=item['id'], output_index=i)
			emit('response.output_item.done', output_index=i, item={**item, 'encrypted_content': seen['done']})
			continue
		else:
			emit('response.output_item.added', output_index=i, item=item)
		emit('response.output_item.done', output_index=i, item=item)
	if response['status'] not in ('cut', 'drop'):  # the stream ends before its terminal event (cut: cleanly)
		emit('response.failed' if response['status'] == 'failed' else 'response.completed', response=response)
	return [f'event: {e["type"]}\ndata: {json.dumps(e)}\n\n'.encode() for e in events]


@pytest.fixture
def responses_server():
	"""The gateway's POST /responses: 400 on what it rejects, else the queued `replies` (output item lists, a dict of
	response fields such as a failure, or an (HTTP status, body) error), then a finish call; streamed when the request asks for it,
	slowly with pace=(s after response.created, s after each later event). The response
	carries browser_use{resolved_model, service_tier, charge_usd} as the gateway's does. A non-streamed request gets
	what the gateway answers one past its 300 s window: HTTP 200, status failed, request_timeout. A compaction item sent
	back must be one a response carried (encrypted_content included), its id without 'unreadable', else OpenAI's 400; a
	reasoning item too."""
	requests, replies, issued = [], [], {}

	class Handler(BaseHTTPRequestHandler):
		def do_POST(self):
			body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
			requests.append((self.path, body))
			bad = gateway_violations(body) if self.path == '/v1/responses' else ['path']
			sealed = [i for i in body['input'] if isinstance(body['input'], list) and i.get('type') == 'compaction']
			rejected = [i['id'] for i in sealed if issued.get(i['id']) != i['encrypted_content'] or 'unreadable' in i['id']]
			items = body['input'] if isinstance(body['input'], list) else []
			rejected += [i['id'] for i in items if i.get('type') == 'reasoning' and 'unreadable' in i['id']]
			if bad:
				status, reply = 400, {'error': {'code': 'stateful_request', 'message': '; '.join(bad)}}
			elif rejected:
				status, reply = 400, {'error': {'code': 'invalid_encrypted_content', 'type': 'invalid_request_error', 'param': None,
					'message': f'The encrypted content for item {rejected[0]} could not be verified. Reason: Encrypted '
					'content could not be decrypted or parsed.'}}  # fmt: skip
			elif replies and isinstance(replies[0], tuple):  # (HTTP status, error body)
				status, reply = replies.pop(0)
			else:
				n = len(requests)
				queued = replies.pop(0) if replies else [reasoning(n), call('finish', {'success': True, 'result': 'ok'}, n)]
				fields = queued if isinstance(queued, dict) else {'output': queued}
				if not body.get('stream'):
					fields = {
						'output': [],
						'status': 'failed',
						'error': {'code': 'request_timeout', 'message': 'The request timed out.'},
					}
				usage = {'input_tokens': 10, 'output_tokens': 2, 'total_tokens': 12,
						 'input_tokens_details': {'cached_tokens': 0}, 'output_tokens_details': {'reasoning_tokens': 1}}  # fmt: skip
				status, reply = 200, {
					'id': f'resp_{n}', 'object': 'response', 'created_at': 0, 'model': body['model'], 'status': 'completed',
					'output': [], 'usage': usage, 'parallel_tool_calls': True, 'tool_choice': 'auto', 'tools': [],
					'browser_use': {'resolved_model': 'gpt-6-luna', 'service_tier': 'priority', 'charge_usd': '0.00020000'},
					**fields,
				}  # fmt: skip
				issued.update((i['id'], i['encrypted_content']) for i in reply['output'] if i['type'] == 'compaction')
			streamed = status == 200 and body.get('stream')
			head, gap = reply.pop('pace', (0, 0))
			frames = sse(reply) if streamed else [json.dumps(reply).encode()]
			self.send_response(status)
			self.send_header('Content-Type', 'text/event-stream' if streamed else 'application/json')
			dropped = reply.get('status') == 'drop'  # the connection breaks: the body is shorter than its Content-Length
			self.send_header('Content-Length', str(sum(map(len, frames)) + (1000 if dropped else 0)))
			self.end_headers()
			try:
				for i, frame in enumerate(frames):
					self.wfile.write(frame)
					self.wfile.flush()
					time.sleep(head if i == 0 else gap)
			except (BrokenPipeError, ConnectionResetError):  # the client gave up on a slow stream
				pass

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


async def test_responses_requests_stream_so_the_gateway_never_cuts_a_long_turn(responses_server, tmp_path, monkeypatch):
	"""C5: the gateway cuts a non-streamed request at 300 s with HTTP 200 status=failed request_timeout (the stub
	answers every non-streamed request that way) and a long bu-smart turn, often the delivery, ended the run. Gateway
	and OpenAI Responses models (a Model, or a model string) now stream every request; usage, the gateway's charge
	and encrypted reasoning come through as from a body."""
	from pydantic_ai.providers.openai import OpenAIProvider

	url, requests, replies = responses_server
	monkeypatch.setenv('OPENAI_BASE_URL', url)
	monkeypatch.setenv('OPENAI_API_KEY', 'fake-test-key')
	gateway, _ = resolve_model(ChatBrowserUse('bu-smart', api_key='fake-test-key', base_url=url))
	direct = OpenAIResponsesModel('gpt-6-luna', provider=OpenAIProvider(base_url=url, api_key='fake-test-key'))
	for model, ref in ((gateway, 'browser-use:bu-smart'), (direct, 'openai:gpt-6-luna'), ('openai-responses:gpt-6-luna', 'x')):
		requests.clear()
		replies.append([reasoning(1), call('python', {'code': 'print(6 * 7)'}, 1)])
		result = await run(build_agent(model, reasoning_effort=None), 'TASK-TEXT', Session(repl=Repl(tmp_path)), ref)
		assert (result.status, result.output) == ('completed', 'ok'), (model, result.error)
		assert [body['stream'] for _, body in requests] == [True, True], model
		assert (result.usage['input'], result.usage['output'], result.usage['requests']) == (20, 4, 2)
		assert 'sealed-reasoning-1' in json.dumps(requests[1][1]['input']) and '42' in json.dumps(requests[1][1]['input'])
		if model is gateway:
			assert result.cost_usd == pytest.approx(2 * 0.0002)


@pytest.mark.parametrize('code', ['server_error', 'overloaded', 'request_timeout'])
async def test_a_responses_failure_inside_http_200_is_retried_once(responses_server, tmp_path, code):
	"""C5 stopgap: a Responses failure the gateway reports inside HTTP 200 (status=failed: server_error, overloaded,
	request_timeout) ended the run: the OpenAI client retries HTTP errors only, and BrowserLoop skipped it because that
	client has max_retries. It now gets the one transient retry per run like a 5xx."""
	url, requests, replies = responses_server
	failed = {'status': 'failed', 'error': {'code': code, 'message': 'The request failed. Retry the request.'}}
	model, _ = resolve_model(ChatBrowserUse('bu-smart', api_key='fake-test-key', base_url=url))
	replies.append(failed)
	result = await run(build_agent(model, reasoning_effort=None), 'TASK-TEXT', Session(repl=Repl(tmp_path)), 'x')
	assert (result.status, result.output, len(requests)) == ('completed', 'ok', 2), result.error
	requests.clear()
	replies += [failed, failed]  # once per run, as every transient error
	result = await run(build_agent(model, reasoning_effort=None), 'TASK-TEXT', Session(repl=Repl(tmp_path)), 'x')
	assert (result.status, len(requests)) == ('error', 2) and code in (result.error or '')


async def test_streamed_requests_record_time_to_first_event_and_each_failed_attempt(responses_server, tmp_path):
	"""Telemetry v3: a streamed request's time to its first event, the failed attempt before it (class and provider code,
	never the message) and the retry's cause, from the real Responses path."""
	from browser_use.telemetry.recorder import RunRecorder
	from browser_use.telemetry.stats import RunStats

	url, requests, replies = responses_server
	model, _ = resolve_model(ChatBrowserUse('bu-fast', api_key='fake-test-key', base_url=url))
	replies.append({'status': 'failed', 'error': {'code': 'server_error', 'message': 'Zq-provider-message'}})
	session = Session(repl=Repl(tmp_path), rec=RunRecorder(model='bu-fast', gateway=True))
	result = await run(build_agent(model, reasoning_effort=None), 'TASK-TEXT', session, 'browser-use:bu-fast')
	assert result.status == 'completed', result.error
	rec = session.rec
	(step,) = rec.steps
	assert 0 <= step.ttft <= step.model_ms and step.ev & 4 and (step.inp, step.out, step.reason) == (10, 2, 1)
	assert (dict(rec.retries), rec.attempts, rec.ms['ttft'] > 0) == ({'provider_transient': 1}, 2, True)
	out = rec.build(RunStats(), 1000)
	(fail,) = out['model_fails']
	assert fail[0] == 1 and fail[2] == 'ModelServerError' and fail[3] == 'server_error'
	assert out['response_models'] == {'bu-fast': 1} and out['s_ttft_ms'][0] >= 0 and 'Zq-provider' not in json.dumps(out)


@pytest.mark.parametrize('code', ['upstream_stream_failed', 'model_request_failed'])
async def test_a_gateway_stream_error_before_any_output_is_retried_once(responses_server, tmp_path, code):
	"""gw3 (live, prod gateway, 4 of 8 streamed compactions): the gateway gave up on OpenAI ~32 s in, before its first
	keepalive at 30 s, and sent an error frame (upstream_error / upstream_stream_failed: 'The model request timed out.
	Retry the request.') that ended the run. It now gets the one transient retry per run; the failed request has no
	charge (the gateway bills a Responses stream only after its terminal event), so the run costs one charge."""
	url, requests, replies = responses_server
	frame = {
		'status': 'error',
		'error': {'type': 'upstream_error', 'code': code, 'message': 'The model request timed out. Retry the request.'},
	}
	model, _ = resolve_model(ChatBrowserUse('bu-fast', api_key='fake-test-key', base_url=url))
	replies.append(frame)
	ref = 'browser-use:bu-fast'
	result = await run(build_agent(model, reasoning_effort=None), 'TASK-TEXT', Session(repl=Repl(tmp_path)), ref)
	assert (result.status, result.output, len(requests)) == ('completed', 'ok', 2), result.error
	assert result.cost_usd == pytest.approx(0.0002) and result.usage['requests'] == 1
	requests.clear()
	replies += [frame, frame]  # once per run, as every transient error
	result = await run(build_agent(model, reasoning_effort=None), 'TASK-TEXT', Session(repl=Repl(tmp_path)), ref)
	assert (result.status, len(requests)) == ('error', 2) and 'timed out' in (result.error or ''), result


def text(content: str, n: int) -> dict:
	return {'type': 'message', 'id': f'msg_{n}', 'role': 'assistant', 'status': 'completed',
			'content': [{'type': 'output_text', 'text': content, 'annotations': []}]}  # fmt: skip


@pytest.mark.parametrize(('end', 'error'), [('cut', 'stream ended'), ('drop', 'ModelConnectionError')])
async def test_a_responses_stream_that_ends_early_is_retried_once(responses_server, tmp_path, end, error):
	"""Review: a stream that closed cleanly before response.completed (a proxy or the gateway ending it) was taken as a
	whole response: its half text the run's answer with status completed, and cost_usd None (no charge). A stream whose
	connection broke was never retried: BrowserLoop counted it as retried by the OpenAI client, which retries a request
	only until its stream opens. A non-streamed body cut short was a connection error the client retried; both now get
	the one transient retry per run."""
	url, requests, replies = responses_server
	cut = {'status': end, 'output': [text('The answer is 4', 1)]}
	model, _ = resolve_model(ChatBrowserUse('bu-smart', api_key='fake-test-key', base_url=url))
	replies += [cut, [text('The answer is 42', 2)]]
	ref = 'browser-use:bu-smart'
	result = await run(build_agent(model, reasoning_effort=None), 'TASK-TEXT', Session(repl=Repl(tmp_path)), ref)
	assert (result.status, result.output, len(requests)) == ('completed', 'The answer is 42', 2), result.error
	assert result.cost_usd == pytest.approx(0.0002)
	requests.clear()
	replies += [cut, cut]
	result = await run(build_agent(model, reasoning_effort=None), 'TASK-TEXT', Session(repl=Repl(tmp_path)), ref)
	assert (result.status, len(requests)) == ('error', 2) and error in (result.error or ''), result


async def test_a_streamed_turn_past_the_model_timeout_runs_while_events_flow(responses_server, tmp_path, monkeypatch):
	"""L1 (gateway scale test): a streamed request had 300 s in all, as a non-streamed one. A bu-smart turn still
	streaming at 300 s was cut and asked again; the gateway billed every cut attempt in full and cost_usd counted none
	(staging: 5 cuts, $1.84 billed, cost_usd $0.0074). A streamed request now has the 300 s for its first event and runs
	on while events flow. One that sends nothing is still cut at 300 s and asked again."""
	from browser_use.agent import loop

	monkeypatch.setattr(loop, 'MODEL_TIMEOUT_S', 1.0)  # stands in for 300 s
	url, requests, replies = responses_server
	model, _ = resolve_model(ChatBrowserUse('bu-smart', api_key='fake-test-key', base_url=url))
	ref = 'browser-use:bu-smart'
	replies.append({'output': [text('The answer is 42', 1)], 'pace': (0, 0.5)})  # first output at 0.5 s, done at 2 s
	result = await run(build_agent(model, reasoning_effort=None), 'TASK-TEXT', Session(repl=Repl(tmp_path)), ref)
	assert (result.status, result.output, len(requests)) == ('completed', 'The answer is 42', 1), result.error
	assert result.cost_usd == pytest.approx(0.0002)
	requests.clear()
	replies.append({'output': [text('late', 1)], 'pace': (3, 0)})  # nothing after response.created for 3 s
	result = await run(build_agent(model, reasoning_effort=None), 'TASK-TEXT', Session(repl=Repl(tmp_path)), ref)
	assert (result.status, result.output, len(requests)) == ('completed', 'ok', 2), result.error


async def test_a_responses_request_over_the_context_window_compacts_once_and_is_sent_again(responses_server, tmp_path):
	"""rrt-fail t3_context gw_overflow: a gateway/Responses request over the context window ended the run (3/3): server
	compaction runs only on requests the model accepts (an over-window input is a 400 with or without
	context_management, live gpt-5-nano). As on chat models, the 400 now gets one checkpoint (summary by the same
	model, evidence archive, user messages) and the same request again; a second 400 in that step ends the run."""
	url, requests, replies = responses_server
	over = (400, {'error': {'message': 'Your input exceeds the context window of this model.', 'type': 'invalid_request_error',
				  'code': 'context_length_exceeded', 'param': 'input'}})  # fmt: skip
	steps = [[reasoning(i), call('python', {'code': f"print('row{100 + i} ' * 500)"}, i)] for i in (1, 2, 3)]
	model, _ = resolve_model(ChatBrowserUse('bu-fast', api_key='fake-test-key', base_url=url))
	replies += [*steps, over, [text('## Goal\nSUMMARY-TEXT', 5)]]
	result = await run(build_agent(model, reasoning_effort=None), 'TASK-TEXT', Session(repl=Repl(tmp_path)), 'x')
	assert (result.status, result.output, len(requests)) == ('completed', 'ok', 6), result.error
	summarizer, retried = json.dumps(requests[4][1]), json.dumps(requests[5][1]['input'])
	assert '<conversation>' in summarizer and 'row101' in summarizer and requests[4][1]['stream'] is True
	assert 'SUMMARY-TEXT' in retried and 'TASK-TEXT' in retried  # the checkpoint: summary and the user's words
	assert 'row101' not in retried and 'row103' in retried  # older steps replaced, the last two kept
	assert result.cost_usd == pytest.approx(5 * 0.0002)  # the summary is charged too; the 400 was not

	requests.clear()
	replies += [*steps, over, [text('## Goal\nSUMMARY-TEXT', 5)], over]
	result = await run(build_agent(model, reasoning_effort=None), 'TASK-TEXT', Session(repl=Repl(tmp_path)), 'x')
	assert (result.status, len(requests)) == ('error', 6) and 'context window' in (result.error or '')


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


def sealed(n: int | str, **fields: Any) -> dict:
	return {'type': 'compaction', 'id': f'cmp_{n}', 'encrypted_content': f'sealed-compaction-{n}', **fields}


async def test_a_streamed_compaction_item_goes_back_as_response_completed_carries_it(responses_server, tmp_path):
	"""bub2-010 (eval run 42535262389, gpt-6-luna): a streamed response compacted with response.compaction.compacting,
	the next request got 400 invalid_encrypted_content on that compaction item and the run ended. A compaction item's
	own stream events can carry another token than the response (output_item.added a provisional one, live; done in the
	compacting path, unobserved): the item sent back is the one response.completed carries, as in a non-streamed body."""
	url, requests, replies = responses_server
	stale = {'added': 'provisional-2', 'done': 'sampled-so-far-2'}
	replies += [
		[reasoning(1), call('python', {'code': 'print(6 * 7)'}, 1)],
		[sealed(2, streamed=stale), reasoning(2), call('python', {'code': 'print(1)'}, 2)],
	]
	model, settings = resolve_model(ChatBrowserUse(api_key='fake-test-key', base_url=url))
	agent = build_agent(model, model_settings=settings, reasoning_effort=None, compact_at_tokens=10)
	result = await run(agent, 'TASK-TEXT', Session(repl=Repl(tmp_path)), model.model_name)
	assert (result.status, result.output, len(requests)) == ('completed', 'ok', 3), result.error
	third = requests[2][1]['input']
	assert [i['encrypted_content'] for i in third if i.get('type') == 'compaction'] == ['sealed-compaction-2']
	assert 'TASK-TEXT' not in json.dumps(third)  # still compacted


async def test_a_compaction_item_the_provider_cannot_read_is_dropped_and_the_history_compacted_again(responses_server, tmp_path):
	"""bub2-010: a compaction item the provider then could not read (400 invalid_encrypted_content naming it) ended the
	run. The history it replaced is still there: the request goes out again without the item, the server compacts that
	history again, and the run goes on from the new item; at most once per such item."""
	url, requests, replies = responses_server
	steps = [
		[reasoning(1), call('python', {'code': 'print(6 * 7)'}, 1)],
		[sealed('unreadable_2'), reasoning(2), call('python', {'code': 'print(1)'}, 2)],
	]
	replies += [*steps, [sealed(4), reasoning(4), call('python', {'code': 'print(2)'}, 4)]]
	model, settings = resolve_model(ChatBrowserUse(api_key='fake-test-key', base_url=url))
	agent = build_agent(model, model_settings=settings, reasoning_effort=None, compact_at_tokens=10)
	result = await run(agent, 'TASK-TEXT', Session(repl=Repl(tmp_path)), model.model_name)
	assert (result.status, result.output, len(requests)) == ('completed', 'ok', 5), result.error
	rejected, again, after = (json.dumps(requests[i][1]['input']) for i in (2, 3, 4))
	assert 'cmp_unreadable_2' in rejected and 'cmp_unreadable_2' not in again
	assert 'TASK-TEXT' in again and requests[3][1]['context_management']  # the replaced history, to compact again
	assert 'cmp_4' in after and 'TASK-TEXT' not in after and 'cmp_unreadable_2' not in after
	assert result.usage['requests'] == 4 and result.cost_usd == pytest.approx(4 * 0.0002)  # the 400 is not charged

	requests.clear()
	replies += [*steps, [sealed('unreadable_4'), reasoning(4), call('python', {'code': 'print(2)'}, 4)]]
	result = await run(
		build_agent(model, model_settings=settings, reasoning_effort=None, compact_at_tokens=10),
		'TASK-TEXT',
		Session(repl=Repl(tmp_path)),
		model.model_name,
	)
	assert (result.status, result.output, len(requests)) == ('completed', 'ok', 7), result.error
	retries = [json.dumps(body['input']) for _, body in requests[5:7]]  # each unreadable item dropped once, newest first
	assert 'cmp_unreadable_4' not in retries[0] and 'cmp_unreadable_2' in retries[0]
	assert 'cmp_unreadable' not in retries[1] and 'TASK-TEXT' in retries[1]


async def test_a_reasoning_item_the_provider_cannot_read_is_left_out_of_every_later_request(responses_server, tmp_path):
	"""Live (longrun b3, api.openai.com): one changed character in a reasoning item's encrypted_content got 400
	invalid_encrypted_content naming the rs_ item, and the run ended at step 2. The request goes out again without that
	item (only its reasoning is lost), and so does every later one: one 400 per unreadable item, not per step."""
	url, requests, replies = responses_server
	replies += [
		[reasoning('unreadable_1'), call('python', {'code': 'print(1)'}, 1)],
		[reasoning(2), call('python', {'code': 'print(2)'}, 2)],
	]
	from pydantic_ai.providers.openai import OpenAIProvider

	model = OpenAIResponsesModel('gpt-6-luna', provider=OpenAIProvider(base_url=url, api_key='fake-test-key'))
	result = await run(build_agent(model, reasoning_effort=None), 'TASK-TEXT', Session(repl=Repl(tmp_path)), 'openai:gpt-6-luna')
	assert (result.status, result.output, len(requests)) == ('completed', 'ok', 4), result.error
	sent = [json.dumps(body['input']) for _, body in requests]
	assert 'rs_unreadable_1' in sent[1] and not any('rs_unreadable_1' in b for b in sent[2:])
	assert 'call_1' in sent[3] and 'rs_2' in sent[3]  # the rest of the history is kept


GATEWAY_REJECTED = (400, {'error': {'message': 'The model rejected this request. Check the input, tools and output limits.',
	'type': 'invalid_request', 'code': 'invalid_request'}})  # fmt: skip


async def test_the_gateways_400_on_a_compacted_request_resends_it_once_without_the_compaction_item(responses_server, tmp_path):
	"""bub2-010 through the gateway: it answers OpenAI's 400 invalid_encrypted_content as invalid_request, without the
	code or the item id (cloud llmgateway publicError), and the run ended. The item a compacted request carries is the
	newest: the request goes out once more without it; a second 400 is not the item's, and ends the run."""
	url, requests, replies = responses_server
	replies += [
		[reasoning(1), call('python', {'code': 'print(6 * 7)'}, 1)],
		[sealed(2), reasoning(2), call('python', {'code': 'print(1)'}, 2)],
		GATEWAY_REJECTED,
		[sealed(4), reasoning(4), call('python', {'code': 'print(2)'}, 4)],
	]
	model, settings = resolve_model(ChatBrowserUse(api_key='fake-test-key', base_url=url))
	agent = build_agent(model, model_settings=settings, reasoning_effort=None, compact_at_tokens=10)
	result = await run(agent, 'TASK-TEXT', Session(repl=Repl(tmp_path)), model.model_name)
	assert (result.status, result.output, len(requests)) == ('completed', 'ok', 5), result.error
	rejected, again, after = (json.dumps(requests[i][1]['input']) for i in (2, 3, 4))
	assert 'cmp_2' in rejected and 'cmp_2' not in again and 'TASK-TEXT' in again and requests[3][1]['context_management']
	assert 'cmp_4' in after and 'TASK-TEXT' not in after

	requests.clear()
	replies += [
		[sealed(1), reasoning(1), call('python', {'code': 'print(6 * 7)'}, 1)],
		[sealed(2), reasoning(2), call('python', {'code': 'print(1)'}, 2)],
		GATEWAY_REJECTED,
		GATEWAY_REJECTED,
	]
	agent = build_agent(model, model_settings=settings, reasoning_effort=None, compact_at_tokens=10)
	result = await run(agent, 'TASK-TEXT', Session(repl=Repl(tmp_path)), model.model_name)
	assert (result.status, len(requests)) == ('error', 4)  # cmp_1 is still sent: one resend, not one per item
	assert 'cmp_1' in json.dumps(requests[3][1]['input']) and 'invalid_request' in (result.error or '')


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


def test_an_openai_prefixed_gateway_model_is_sent_without_the_prefix():
	"""Live (0.13 README: ChatBrowserUse(model='openai/gpt-5.5')): the preflight accepted the prefixed name, then the
	gateway answered 400 "not on the Browser Use gateway" to the first request, after the browser had started."""
	llm = ChatBrowserUse('openai/gpt-5.5', api_key='fake-test-key')
	assert llm.model == 'gpt-5.5' and llm.pydantic_model().model_name == 'gpt-5.5'


def test_preflight_checks_the_gateway_key_and_model_before_anything_starts(models_server):
	"""agent-llm F4/F6: a gateway that is not deployed, a rejected key or a model the gateway does not serve failed only
	after a cloud browser had been created and billed."""
	url, reply, seen = models_server
	assert ChatBrowserUse(api_key='fake-test-key', base_url=url).preflight() is None
	assert ChatBrowserUse('openai/gpt-6-luna', api_key='fake-test-key', base_url=url).preflight() is None
	assert seen[0] == ('/v1/models', 'Bearer fake-test-key')
	missing = ChatBrowserUse('bu-nonexistent-xyz', api_key='fake-test-key', base_url=url).preflight()
	assert missing == 'bu-nonexistent-xyz is not on the Browser Use gateway. Listed: bu-auto, bu-fast, bu-ultrafast, gpt-6-luna.'
	# the 0.13 README's ChatBrowserUse('anthropic/claude-sonnet-4-6'): the 0.x gateway served it, the error named no class
	vendor = ChatBrowserUse('anthropic/claude-sonnet-4-6', api_key='fake-test-key', base_url=url).preflight()
	assert vendor and "in 1.0 use ChatAnthropic('claude-sonnet-4-6') with your own anthropic key" in vendor, vendor
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


def test_a_listed_openai_model_on_the_gateway_gets_medium_like_on_openai(monkeypatch):
	"""Live: ChatBrowserUse('gpt-6-luna') sent no effort and ran at 'high', ChatBrowserUse('gpt-6.1-sol') at 'xhigh' (the
	upstream default), while ChatOpenAI('gpt-6-luna') runs at the documented 'medium'. Only a bu-* alias has an effort of
	its own; Agent(reasoning=...) still wins."""
	monkeypatch.setenv('BROWSER_USE_API_KEY', 'fake-test-key')
	for llm in (
		ChatBrowserUse('gpt-6-luna'),
		ChatOpenAI('gpt-6.1-sol', base_url=GATEWAY_URL),
		ChatBrowserUse('gpt-6.1-sol').pydantic_model(),
	):
		agent = Agent('t', llm, browser=None)
		agent._build()
		assert agent._gateway and agent._agent.model_settings['openai_reasoning_effort'] == 'medium'
	agent = Agent('t', ChatBrowserUse('gpt-6.1-sol'), browser=None, reasoning='low')
	agent._build()
	assert agent._agent.model_settings['openai_reasoning_effort'] == 'low'
	for alias in ('bu-fast', 'bu-ultrafast', 'bu-smart', 'bu-auto'):
		agent = Agent('t', alias, browser=None)
		agent._build()
		assert 'openai_reasoning_effort' not in agent._agent.model_settings, alias


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


@pytest.mark.parametrize(
	('name', 'hint'),
	[
		('gpt-6-luna', "llm=ChatOpenAI('gpt-6-luna') or llm='openai:gpt-6-luna'"),
		('o4-mini', "llm=ChatOpenAI('o4-mini') or llm='openai:o4-mini'"),
		('claude-haiku-5-5', "llm=ChatAnthropic('claude-haiku-5-5') or llm='anthropic:claude-haiku-5-5'"),
		('gemini-3.5-flash', "llm=ChatGoogle('gemini-3.5-flash') or llm='google:gemini-3.5-flash'"),
	],
)
def test_a_bare_model_name_names_the_1_0_form_not_a_degraded_one(name, hint):
	"""Live: Pydantic AI answered llm='gpt-6-luna' with "Did you mean 'openai-chat:gpt-6-luna'?" (chat completions:
	reasoning sent as 'none', not the evaluated Responses setup) and llm='gemini-3.5-flash' with 'google-cloud:...'
	(Vertex: a GOOGLE_API_KEY got 403 API_KEY_SERVICE_BLOCKED after the browser had started)."""
	with pytest.raises(UserError) as e:
		resolve_model(name)
	assert str(e.value) == f'Unknown model {name!r}: a model string names its provider. Use {hint}.'
	assert 'openai-chat:' not in str(e.value) and 'google-cloud:' not in str(e.value)


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


def test_google_models_call_the_gemini_api_version_that_has_function_calling(monkeypatch):
	"""Live retry check 11-08: google-genai 3.0.0 (2026-11-06) moved the Gemini API default from v1beta to v1, which
	rejects tools (400 "Function calling is not enabled for api version v1"). Fresh installs resolved it, so every
	ChatGoogle or 'google:' run failed on its first request. pyproject.toml caps google-genai<3."""
	monkeypatch.delenv('GOOGLE_GENAI_API_VERSION', raising=False)
	monkeypatch.setenv('GOOGLE_API_KEY', 'x')
	for llm in (ChatGoogle('gemini-2.5-flash', api_key='x'), 'google:gemini-2.5-flash'):
		api = resolve_model(llm)[0].client._api_client
		assert api._http_options.api_version == 'v1beta', llm


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


def test_a_provider_key_with_whitespace_never_reaches_an_error_message(monkeypatch):
	"""Live: ChatOpenAI/ChatGoogle/ChatAnthropic keys with a line break went to the SDK, httpx rejected the header with
	the whole key in its error, and result.error and the ERROR log line printed it. Surrounding whitespace is stripped;
	whitespace inside raises before any browser starts, without the key."""
	for var in ('OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'GOOGLE_API_KEY', 'GEMINI_API_KEY'):
		monkeypatch.delenv(var, raising=False)
	assert resolve_model(ChatOpenAI('m', api_key=' sk-k\n'))[0].client.api_key == 'sk-k'
	assert resolve_model(ChatAnthropic('claude-opus-5-5', api_key='sk-ant-k\n'))[0].client.api_key == 'sk-ant-k'
	assert resolve_model(ChatGoogle('gemini-3-flash', api_key='AIza-k\n'))[0].client._api_client.api_key == 'AIza-k'
	monkeypatch.setenv('OPENAI_API_KEY', 'sk-env\n')
	monkeypatch.setenv('GEMINI_API_KEY', ' AIza-env ')
	assert resolve_model(ChatOpenAI('m'))[0].client.api_key == 'sk-env'
	assert resolve_model(ChatOpenAI('m', base_url='http://localhost:1/v1'))[0].client.api_key == 'sk-env'
	assert resolve_model(ChatGoogle('gemini-3-flash'))[0].client._api_client.api_key == 'AIza-env'
	monkeypatch.setenv('OPENAI_API_KEY', 'sk-proj-abc\nSECRETPART')
	for llm in (
		ChatOpenAI('m', api_key='sk-proj-abc SECRETPART'),
		ChatGoogle('g', api_key='AIza\tSECRETPART'),
		'openai:gpt-5-mini',
	):
		with pytest.raises(ValueError, match='line break') as e:
			resolve_model(llm)
		assert 'SECRETPART' not in str(e.value)
	with pytest.raises(ValueError, match='line break'):  # in run(), before the browser starts
		Agent('t', llm='openai:gpt-5-mini', browser=Browser('chromium')).run_sync()


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
