"""Regression tests for HAR recording response-body capture.

The watchdog fetches each finished response's body via CDP in a fire-and-forget
task. Those tasks must be tracked (so they can't be garbage-collected
mid-flight) and drained before the HAR is written on stop — otherwise entries
fall back to the (possibly incomplete) dataReceived buffer and response bodies
go missing from the HAR.
"""

import asyncio
import base64
import json
from typing import Any
from unittest.mock import MagicMock

from bubus import EventBus

from browser_use.browser.session import BrowserSession
from browser_use.browser.watchdogs.har_recording_watchdog import HarRecordingWatchdog


def _make_watchdog(tmp_path) -> HarRecordingWatchdog:
	watchdog = HarRecordingWatchdog(
		event_bus=MagicMock(spec=EventBus),
		browser_session=MagicMock(spec=BrowserSession),
	)
	watchdog._enabled = True
	watchdog._content_mode = 'embed'
	watchdog._mode = 'full'
	watchdog._har_path = tmp_path / 'out.har'
	watchdog._har_dir = tmp_path
	watchdog._browser_name = 'Chromium'
	watchdog._browser_version = ''
	return watchdog


def _prime_entry(watchdog: HarRecordingWatchdog, request_id: str = 'r1') -> None:
	params: Any = {'requestId': request_id, 'request': {'url': 'https://example.com/', 'method': 'GET'}}
	watchdog._on_request_will_be_sent(params, session_id='s1')


def _finish_loading(watchdog: HarRecordingWatchdog, get_body, request_id: str = 'r1') -> None:
	network: Any = watchdog.browser_session.cdp_client.send.Network
	network.getResponseBody = get_body
	params: Any = {'requestId': request_id, 'timestamp': 123.0}
	watchdog._on_loading_finished(params, session_id='s1')


async def test_body_fetch_tasks_are_tracked(tmp_path):
	"""loadingFinished must keep a strong reference to the body-fetch task."""
	watchdog = _make_watchdog(tmp_path)
	_prime_entry(watchdog)

	gate = asyncio.Event()
	body_b64 = base64.b64encode(b'<html>hi</html>').decode()

	async def slow_get_body(params, session_id=None):
		await gate.wait()
		return {'body': body_b64, 'base64Encoded': True}

	try:
		_finish_loading(watchdog, slow_get_body)
		pending = [t for t in watchdog._pending_body_fetches if not t.done()]
		assert len(pending) == 1, f'expected 1 tracked body-fetch task, got {len(pending)}'
	finally:
		gate.set()
		await asyncio.gather(*watchdog._pending_body_fetches, return_exceptions=True)


async def test_stop_waits_for_in_flight_body_fetch(tmp_path):
	"""on_BrowserStopEvent must drain pending body fetches so their content lands in the HAR."""
	watchdog = _make_watchdog(tmp_path)
	_prime_entry(watchdog)

	gate = asyncio.Event()
	body_b64 = base64.b64encode(b'<html>secret body</html>').decode()

	async def slow_get_body(params, session_id=None):
		await gate.wait()
		return {'body': body_b64, 'base64Encoded': True}

	_finish_loading(watchdog, slow_get_body)

	stop_task = asyncio.create_task(watchdog.on_BrowserStopEvent(MagicMock()))
	await asyncio.sleep(0.05)
	assert not stop_task.done(), 'stop completed while a body fetch was still in flight'

	gate.set()
	await asyncio.wait_for(stop_task, timeout=2)

	har = json.loads(watchdog._har_path.read_text())
	texts = [e['response']['content'].get('text') for e in har['log']['entries']]
	assert '<html>secret body</html>' in texts, f'fetched body missing from HAR: {texts}'


async def test_stop_writes_har_when_body_fetch_is_stuck(tmp_path):
	"""A stuck body fetch must not block HAR writing forever (bounded drain)."""
	watchdog = _make_watchdog(tmp_path)
	_prime_entry(watchdog)

	never = asyncio.Event()

	async def stuck_get_body(params, session_id=None):
		await never.wait()
		return {'body': '', 'base64Encoded': False}

	_finish_loading(watchdog, stuck_get_body)

	await asyncio.wait_for(watchdog._drain_body_fetches(timeout_s=0.05), timeout=2)
	for task in watchdog._pending_body_fetches:
		task.cancel()
