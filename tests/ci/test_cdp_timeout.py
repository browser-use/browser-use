"""Regression tests for TimeoutWrappedCDPClient.

cdp_use.CDPClient.send_raw awaits a future that only resolves when the browser
sends a matching response. When the server goes silent (observed against cloud
browsers whose WebSocket stays connected at TCP/keepalive layer but never
replies), send_raw hangs forever. The wrapper turns that hang into a fast
TimeoutError.
"""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager

import pytest
from websockets.asyncio.server import serve

from browser_use.browser._cdp_timeout import (
	DEFAULT_CDP_REQUEST_TIMEOUT_S,
	TimeoutWrappedCDPClient,
	_coerce_valid_timeout,
	_parse_env_cdp_timeout,
)


@asynccontextmanager
async def _connected_client(handler, timeout_s: float):
	"""Exercise the production request/response path over a real localhost WebSocket."""
	async with serve(handler, '127.0.0.1', 0) as server:
		port = next(iter(server.sockets)).getsockname()[1]
		async with TimeoutWrappedCDPClient(url=f'ws://127.0.0.1:{port}', cdp_request_timeout_s=timeout_s) as client:
			yield client


@pytest.mark.asyncio
async def test_send_raw_times_out_on_silent_server():
	"""A silent server must time out promptly and release the abandoned request."""
	requests = []

	async def silent_server(websocket):
		requests.append(json.loads(await websocket.recv()))
		await websocket.wait_closed()

	async with _connected_client(silent_server, timeout_s=0.5) as client:
		start = time.monotonic()
		with pytest.raises(TimeoutError) as exc:
			await client.send_raw('Target.getTargets')
		elapsed = time.monotonic() - start
		assert client.pending_requests == {}

	assert len(requests) == 1
	# Returned within the cap (plus scheduling margin), not after the full 30s.
	assert elapsed < 2.0, f'wrapper did not enforce timeout; took {elapsed:.2f}s'
	assert 'Target.getTargets' in str(exc.value)
	# Error message mentions "within 0s" (0.5 rounded with %.0f) or "within 1s".
	assert 'within' in str(exc.value)


@pytest.mark.asyncio
async def test_send_raw_passes_through_when_fast():
	"""Preserve response content, request parameters and session routing."""
	requests = []

	async def responding_server(websocket):
		request = json.loads(await websocket.recv())
		requests.append(request)
		await websocket.send(json.dumps({'id': request['id'], 'result': {'ok': True, 'method': request['method']}}))
		await websocket.wait_closed()

	async with _connected_client(responding_server, timeout_s=5.0) as client:
		result = await client.send_raw('Target.getTargets', params={'filter': []}, session_id='session-1')
		assert client.pending_requests == {}

	assert result == {'ok': True, 'method': 'Target.getTargets'}
	assert requests == [{'id': 1, 'method': 'Target.getTargets', 'params': {'filter': []}, 'sessionId': 'session-1'}]


@pytest.mark.parametrize('abandonment', ['cancel', 'timeout'])
async def test_abandoned_response_cannot_consume_next_request(abandonment):
	"""A late response to a cancelled/timed-out ID must not resolve another request."""
	received = asyncio.Event()
	requests = []

	async def late_server(websocket):
		first = json.loads(await websocket.recv())
		requests.append(first)
		received.set()
		second = json.loads(await websocket.recv())
		requests.append(second)
		await websocket.send(json.dumps({'id': first['id'], 'result': {'value': 'stale'}}))
		await websocket.send(json.dumps({'id': second['id'], 'result': {'value': 'fresh'}}))
		await websocket.wait_closed()

	async with _connected_client(late_server, timeout_s=0.5) as client:
		first_task = asyncio.create_task(client.send_raw('Runtime.evaluate', {'expression': 'first'}))
		await asyncio.wait_for(received.wait(), timeout=3)
		first_id = requests[0]['id']
		first_future = client.pending_requests[first_id]
		if abandonment == 'cancel':
			first_task.cancel()
			with pytest.raises(asyncio.CancelledError):
				await first_task
		else:
			with pytest.raises(TimeoutError):
				await first_task
		assert first_future.cancelled()
		assert client.pending_requests == {}
		assert await client.send_raw('Runtime.evaluate', {'expression': 'second'}) == {'value': 'fresh'}
		assert requests[1]['id'] != first_id
		assert client.pending_requests == {}


async def test_response_cancellation_race_preserves_other_request():
	"""Cancel on response completion while another request is still awaiting its own result."""
	received = asyncio.Event()
	reply_first = asyncio.Event()
	reply_second = asyncio.Event()
	requests = []

	async def racing_server(websocket):
		requests.append(json.loads(await websocket.recv()))
		requests.append(json.loads(await websocket.recv()))
		received.set()
		await asyncio.wait_for(reply_first.wait(), timeout=3)
		await websocket.send(json.dumps({'id': requests[0]['id'], 'result': {'value': 'first'}}))
		await asyncio.wait_for(reply_second.wait(), timeout=3)
		await websocket.send(json.dumps({'id': requests[1]['id'], 'result': {'value': 'second'}}))
		await websocket.wait_closed()

	async with _connected_client(racing_server, timeout_s=5.0) as client:
		first = asyncio.create_task(client.send_raw('Runtime.evaluate', {'expression': 'first'}))
		second = asyncio.create_task(client.send_raw('Runtime.evaluate', {'expression': 'second'}))
		await asyncio.wait_for(received.wait(), timeout=3)
		first_id, second_id = (request['id'] for request in requests)
		second_future = client.pending_requests[second_id]
		client.pending_requests[first_id].add_done_callback(lambda _future: first.cancel())
		reply_first.set()
		try:
			result = await first
		except asyncio.CancelledError:
			pass  # Cancellation may win after the response future is resolved.
		else:
			assert result == {'value': 'first'}
		assert first_id not in client.pending_requests
		assert client.pending_requests[second_id] is second_future
		assert not second_future.done()
		reply_second.set()
		assert await second == {'value': 'second'}
		assert client.pending_requests == {}


async def test_cdp_error_is_preserved_and_releases_request():
	async def error_server(websocket):
		request = json.loads(await websocket.recv())
		await websocket.send(json.dumps({'id': request['id'], 'error': {'code': -32601, 'message': 'Unknown test method'}}))
		await websocket.wait_closed()

	async with _connected_client(error_server, timeout_s=5.0) as client:
		with pytest.raises(RuntimeError, match='Unknown test method'):
			await client.send_raw('Missing.testMethod')
		assert client.pending_requests == {}


async def test_serialization_failure_releases_unsent_request():
	async def silent_server(websocket):
		await websocket.wait_closed()

	async with _connected_client(silent_server, timeout_s=5.0) as client:
		with pytest.raises(TypeError, match='JSON serializable'):
			await client.send_raw('Runtime.evaluate', {'invalid': object()})
		assert client.pending_requests == {}


def test_constructor_rejects_invalid_timeout():
	"""Non-finite / non-positive constructor args must fall back to the default,
	mirroring the env-var path in _parse_env_cdp_timeout."""
	# None → default.
	assert _coerce_valid_timeout(None) == DEFAULT_CDP_REQUEST_TIMEOUT_S
	# Invalid values → default, with a warning.
	for bad in (float('nan'), float('inf'), float('-inf'), 0.0, -5.0, -0.01):
		assert _coerce_valid_timeout(bad) == DEFAULT_CDP_REQUEST_TIMEOUT_S, f'Expected fallback for {bad!r}, got something else'
	# Valid finite positives are preserved.
	assert _coerce_valid_timeout(0.1) == 0.1
	assert _coerce_valid_timeout(30.0) == 30.0


def test_default_cdp_timeout_is_reasonable():
	"""Default must give headroom above typical slow CDP calls but stay below
	the 180s agent step_timeout so hangs surface before step-level kills."""
	assert 10.0 <= DEFAULT_CDP_REQUEST_TIMEOUT_S <= 120.0, (
		f'Default CDP timeout ({DEFAULT_CDP_REQUEST_TIMEOUT_S}s) is outside the sensible 10–120s range'
	)


def test_parse_env_rejects_malformed_values():
	"""Mirrors the defensive parse used for BROWSER_USE_ACTION_TIMEOUT_S."""
	for bad in ('', 'nan', 'NaN', 'inf', '-inf', '0', '-5', 'abc'):
		assert _parse_env_cdp_timeout(bad) == 60.0, f'Expected fallback for {bad!r}'

	# Finite positive values take effect.
	assert _parse_env_cdp_timeout('30') == 30.0
	assert _parse_env_cdp_timeout('15.5') == 15.5
	# None (env var not set) also falls back.
	assert _parse_env_cdp_timeout(None) == 60.0
