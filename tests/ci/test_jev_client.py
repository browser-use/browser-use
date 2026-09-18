"""Jev request validity and failure accounting, with no live model calls."""

import asyncio
import json

import httpx
import pytest

from browser_use.agent.jev_client import JevClient

QUESTION = {'q': {'type': 'choice', 'criteria': {'yes': 'Yes', 'no': 'No'}, 'instructions': 'Choose'}}
ANSWER = {'q': {'choice': 'yes', 'confidence': 0.9, 'probabilities': {'yes': 0.9, 'no': 0.1}}}


@pytest.mark.asyncio
async def test_real_payload_cost_and_ledger(tmp_path):
	def handle(request):
		body = json.loads(request.content)
		assert body['model'] == 'jev-1.13.0'
		assert body['questions'] == QUESTION
		return httpx.Response(200, json={'answers': ANSWER, 'usage': {'input_tokens': 1000}, 'model': 'jev-1.13.0'})

	client = JevClient(api_key='test', log_path=str(tmp_path / 'calls.jsonl'))
	client._http = httpx.AsyncClient(transport=httpx.MockTransport(handle))
	assert await client.ask(state={'text': 'observed'}, questions=QUESTION, purpose='test') == ANSWER
	assert client.summary()['known_cost_usd'] == pytest.approx(0.000042)
	assert client.summary()['unknown_cost_calls'] == 0
	assert 'test' not in (tmp_path / 'calls.jsonl').read_text().replace('"purpose": "test"', '')
	assert [json.loads(line)['event'] for line in (tmp_path / 'calls.jsonl').read_text().splitlines()] == [
		'request_started',
		'request_finished',
	]
	await client.close()


@pytest.mark.asyncio
async def test_invalid_answer_still_counts_known_charge():
	client = JevClient(api_key='test')
	client._http = httpx.AsyncClient(
		transport=httpx.MockTransport(lambda r: httpx.Response(200, json={'answers': {}, 'usage': {'input_tokens': 10}}))
	)
	with pytest.raises(ValueError):
		await client.ask(state={}, questions=QUESTION, purpose='test')
	assert client.summary()['calls'] == 1
	assert client.summary()['known_cost_usd'] > 0
	await client.close()


@pytest.mark.asyncio
async def test_cancellation_propagates_and_keeps_unknown_charge():
	async def handle(request):
		raise asyncio.CancelledError()

	client = JevClient(api_key='test')
	client._http = httpx.AsyncClient(transport=httpx.MockTransport(handle))
	with pytest.raises(asyncio.CancelledError):
		await client.ask(state={}, questions=QUESTION, purpose='test')
	assert client.summary()['unknown_cost_calls'] == 1
	assert client.calls[0]['error'] == 'CancelledError'
	await client.close()


@pytest.mark.asyncio
async def test_response_unknown_choice_is_never_accepted():
	client = JevClient(api_key='test')
	client._http = httpx.AsyncClient(
		transport=httpx.MockTransport(
			lambda r: httpx.Response(
				200, json={'answers': {'q': {'choice': 'invented', 'confidence': 1, 'probabilities': {'invented': 1}}}}
			)
		)
	)
	with pytest.raises(ValueError):
		await client.ask(state={}, questions=QUESTION, purpose='test')
	assert client.summary()['unknown_cost_calls'] == 1
	await client.close()
