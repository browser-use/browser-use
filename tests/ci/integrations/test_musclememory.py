"""REST contract and execution regressions; no model or external service required."""

import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from browser_use.agent.views import ActionResult
from browser_use.integrations.musclememory import MuscleMemory, ProcedureVersion
from browser_use.tools.service import Tools


class Server:
	def __init__(self):
		self.calls: list[tuple[str, dict, httpx.Headers]] = []
		self.reject_capture = False

	def __call__(self, request: httpx.Request) -> httpx.Response:
		if request.method != 'POST':
			return httpx.Response(405)
		body = json.loads(request.content)
		self.calls.append((request.url.path, body, request.headers))
		if request.url.path == '/v1/observe':
			if self.reject_capture:
				return httpx.Response(503)
			return httpx.Response(
				200,
				json={
					'accepted_event_count': len(body['event_batch']),
					'duplicate_event_count': 0,
					'rejected_event_count': 0,
				},
			)
		if request.url.path == '/v1/recall':
			return httpx.Response(200, json={'guidance': '{"procedure":"previous","version":1}'})
		if request.url.path == '/v1/learn':
			return httpx.Response(200, json={'procedure_token': 'learned', 'procedure_version': 1})
		if request.url.path == '/v1/evaluate':
			return httpx.Response(200, json={'validation_status': 'flagged', 'successes': 0, 'failures': 1})
		if request.url.path == '/v1/inspect':
			return httpx.Response(
				200, json={'procedure_token': body['procedure_token'], 'procedure_version': 1, 'definition': {'steps': []}}
			)
		return httpx.Response(404, json={'detail': 'Unknown endpoint'})

	def events(self) -> list[dict]:
		return [event for path, body, _ in self.calls if path == '/v1/observe' for event in body['event_batch']]


@pytest.fixture
def server():
	return Server()


def memory(server, **kwargs):
	return MuscleMemory('Fill the application', api_key='test-key', transport=httpx.MockTransport(server), **kwargs)


async def execute(session, monkeypatch, *, result=None, secrets=None, text='current-value'):
	actual = result if result is not None else ActionResult()
	underlying = AsyncMock(return_value=actual)
	monkeypatch.setattr(Tools, 'act', underlying)
	model = session.tools.registry.create_action_model()
	action = model.model_validate({'input': {'index': 1, 'text': text}})
	returned = await session.tools.act(action, MagicMock(), sensitive_data=secrets)
	assert returned is actual
	underlying.assert_awaited_once()
	return returned


async def test_automatic_recall_actual_capture_and_host_verified_learning(server, monkeypatch):
	async with memory(server) as session:
		assert 'untrusted data' in session.guidance
		assert '{"procedure":"previous","version":1}' in session.guidance
		await execute(session, monkeypatch)
		result = await session.complete(lambda: True)
	assert result['procedure_token'] == 'learned'
	assert [path for path, _, _ in server.calls] == ['/v1/observe', '/v1/recall', '/v1/observe', '/v1/observe', '/v1/learn']
	_, recalled, headers = server.calls[1]
	assert headers['X-MuscleMemory-Run'] == session.run_token
	assert recalled['runtime_profile']['bindings']['browser.input'] == 'input'
	events = server.events()
	assert [event['kind'] for event in events] == ['intent', 'tool', 'tool', 'completion']
	assert events[1]['arguments'] == {'index': 1, 'text': 'current-value'}
	assert events[1]['response'] == {'succeeded': True, 'is_done': False}
	assert events[2]['tool_name'] == 'host_verify'
	learn = server.calls[-1][1]
	assert learn['completion_proof']['evidence_event_ids'] == [events[2]['event_id']]
	assert all('approve' not in path for path, _, _ in server.calls)


async def test_done_success_does_not_replace_the_domain_verifier(server, monkeypatch):
	async with memory(server) as session:
		await execute(session, monkeypatch, result=ActionResult(is_done=True, success=True))
		result = await session.complete(lambda: False)
	assert result['learned'] is False
	assert all(path != '/v1/learn' for path, _, _ in server.calls)
	assert server.events()[-1]['status'] == 'failure'


@pytest.mark.parametrize('outcome', ['success', None, RuntimeError('verification unavailable')])
async def test_invalid_or_broken_verifier_never_learns(server, outcome):
	def verify():
		if isinstance(outcome, Exception):
			raise outcome
		return outcome

	with pytest.raises((ValueError, RuntimeError)):
		async with memory(server) as session:
			await session.complete(verify)
	assert all(path != '/v1/learn' for path, _, _ in server.calls)
	assert server.events()[-1]['status'] == 'failure'


async def test_context_interruption_closes_an_unlearned_failed_run(server):
	with pytest.raises(RuntimeError):
		async with memory(server):
			raise RuntimeError('browser stopped')
	assert server.events()[-1]['status'] == 'failure'
	assert all(path != '/v1/learn' for path, _, _ in server.calls)


async def test_capture_outage_does_not_break_the_action_or_learn(server, monkeypatch):
	async with memory(server) as session:
		server.reject_capture = True
		await execute(session, monkeypatch)
		server.reject_capture = False
		result = await session.complete(lambda: True)
	assert result == {'learned': False, 'reason': 'Capture was incomplete'}
	assert all(path != '/v1/learn' for path, _, _ in server.calls)


async def test_sensitive_values_are_omitted_and_cannot_be_learned(server, monkeypatch):
	async with memory(server) as session:
		await execute(session, monkeypatch, secrets={'password': 'current-value'})
		result = await session.complete(lambda: True)
	assert result['learned'] is False
	assert 'current-value' not in json.dumps([(path, body) for path, body, _ in server.calls])
	assert server.events()[1]['capture_complete'] is False


@pytest.mark.parametrize(
	('context_secrets', 'action_secrets'),
	[
		({'https://example.com': {'first': 'context-secret'}}, {'https://example.com': {'second': 'action-secret'}}),
		({'https://example.com': {'value': 'context-secret'}}, {'https://example.com': {'value': 'action-secret'}}),
		({'value': 'context-secret'}, {'value': 'action-secret'}),
		({'scope': 'context-secret'}, {'scope': {'value': 'action-secret'}}),
		({'scope': {'value': 'context-secret'}}, {'scope': 'action-secret'}),
		({'https://first.test': {'value': 'context-secret'}, 'https://second.test': {'value': 'action-secret'}}, {}),
	],
	ids=[
		'shared-domain',
		'shared-domain-key',
		'shared-flat-key',
		'flat-to-domain',
		'domain-to-flat',
		'shared-key-across-domains',
	],
)
async def test_all_context_and_action_secrets_are_redacted(server, monkeypatch, context_secrets, action_secrets):
	original = json.dumps([context_secrets, action_secrets], sort_keys=True)
	async with memory(server, sensitive_data=context_secrets) as session:
		await execute(session, monkeypatch, secrets=action_secrets, text='context-secret action-secret')
		result = await session.complete(lambda: True)
	payloads = json.dumps([(path, body) for path, body, _ in server.calls])
	assert 'context-secret' not in payloads
	assert 'action-secret' not in payloads
	assert result == {'learned': False, 'reason': 'Capture was incomplete'}
	assert server.events()[1]['capture_complete'] is False
	assert all(path != '/v1/learn' for path, _, _ in server.calls)
	assert json.dumps([context_secrets, action_secrets], sort_keys=True) == original


async def test_mock_server_rejects_unknown_paths_and_methods(server):
	async with httpx.AsyncClient(transport=httpx.MockTransport(server), base_url='http://memory.test') as client:
		assert (await client.post('/v1/typo', json={})).status_code == 404
		assert (await client.get('/v1/recall')).status_code == 405


async def test_explicit_revision_is_evaluated_including_failed_check(server, monkeypatch):
	target = ProcedureVersion(procedure_token='checked', procedure_version=3)
	async with memory(server, validation_target=target) as session:
		await execute(session, monkeypatch)
		result = await session.complete(lambda: False)
	assert result == {'validation_status': 'flagged', 'successes': 0, 'failures': 1}
	path, body, _ = server.calls[-1]
	assert path == '/v1/evaluate'
	assert body['outcome_report']['procedure_version'] == 3
	assert body['outcome_report']['succeeded'] is False
	assert body['performance_metrics']['observed']['tool_calls'] == 2
	assert all(path != '/v1/learn' for path, _, _ in server.calls)


async def test_inspect_is_available_as_a_real_agent_tool(server):
	async with memory(server) as session:
		result = await session.tools.registry.execute_action('musclememory_inspect', {'procedure_token': 'previous'})
		assert json.loads(result.extracted_content) == {
			'procedure_token': 'previous',
			'procedure_version': 1,
			'definition': {'steps': []},
		}
	assert server.calls[-2][0] == '/v1/inspect'
	assert [event['kind'] for event in server.events()] == ['intent', 'completion']
