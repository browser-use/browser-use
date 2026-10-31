"""Regression tests for TimeoutWrappedCDPClient request timeout and cleanup."""

from __future__ import annotations

import asyncio
import json
import time

import pytest

from browser_use.browser._cdp_timeout import (
	DEFAULT_CDP_REQUEST_TIMEOUT_S,
	TimeoutWrappedCDPClient,
	_coerce_valid_timeout,
	_parse_env_cdp_timeout,
)


class _FakeWebSocket:
	def __init__(self, on_send=None):
		self.on_send = on_send
		self.sent = asyncio.Event()
		self.messages = []

	async def send(self, message: str) -> None:
		decoded = json.loads(message)
		self.messages.append(decoded)
		self.sent.set()
		if self.on_send is not None:
			self.on_send(decoded)


def _make_wrapped_client_without_websocket(timeout_s: float, websocket: _FakeWebSocket) -> TimeoutWrappedCDPClient:
	"""Build a TimeoutWrappedCDPClient without opening a real WebSocket.

	Calling `CDPClient.__init__` directly would try to construct a working
	client. We construct the object via __new__ and provide the state used by
	cdp_use's request/response path.
	"""
	client = TimeoutWrappedCDPClient.__new__(TimeoutWrappedCDPClient)
	client._cdp_request_timeout_s = timeout_s
	client.msg_id = 0
	client.pending_requests = {}
	client.ws = websocket  # type: ignore[assignment]
	return client


@pytest.mark.asyncio
async def test_send_raw_times_out_on_silent_server():
	"""The production TimeoutWrappedCDPClient.send_raw must cap a silent server
	within the configured timeout.

	We deliberately exercise the real `send_raw` (not an inline copy) so
	regressions in the wrapper itself — e.g. accidentally removing the
	asyncio.wait_for — fail this test.
	"""
	websocket = _FakeWebSocket()
	client = _make_wrapped_client_without_websocket(timeout_s=0.05, websocket=websocket)
	start = time.monotonic()
	with pytest.raises(TimeoutError) as exc:
		await client.send_raw('Target.getTargets')
	elapsed = time.monotonic() - start

	assert websocket.sent.is_set()
	assert elapsed < 0.5, f'wrapper did not enforce timeout; took {elapsed:.2f}s'
	assert 'Target.getTargets' in str(exc.value)
	assert 'within' in str(exc.value)
	assert client.pending_requests == {}


@pytest.mark.asyncio
async def test_send_raw_passes_through_when_fast():
	"""A matching CDP response should bubble up unchanged."""

	def reply_to_request(message):
		client.pending_requests[message['id']].set_result({'ok': True, 'method': message['method']})

	websocket = _FakeWebSocket(on_send=reply_to_request)
	client = _make_wrapped_client_without_websocket(timeout_s=5.0, websocket=websocket)
	result = await client.send_raw('Target.getTargets', params={'filter': []}, session_id='session-1')

	assert result == {'ok': True, 'method': 'Target.getTargets'}
	assert websocket.messages == [{'id': 1, 'method': 'Target.getTargets', 'params': {'filter': []}, 'sessionId': 'session-1'}]
	assert client.pending_requests == {}


@pytest.mark.asyncio
async def test_send_raw_removes_pending_request_when_cancelled():
	websocket = _FakeWebSocket()
	client = _make_wrapped_client_without_websocket(timeout_s=5.0, websocket=websocket)
	task = asyncio.create_task(client.send_raw('Target.getTargets'))
	await websocket.sent.wait()
	task.cancel()
	with pytest.raises(asyncio.CancelledError):
		await task

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
