"""Regression tests for #5366: a WS drop inside the reconnect window must not be lost.

BrowserSession.reconnect() re-attaches the one-shot WS drop callback as its
final step, while _auto_reconnect() only clears _reconnecting in its finally.
If the brand-new socket drops inside that window, the callback fires, sees
_reconnecting is True, and returns — and because add_done_callback is one-shot
and the task it was attached to is already done, no future drop can ever be
detected again. The session is left permanently disconnected with drop
detection disabled.
"""

import asyncio

from bubus import BaseEvent, EventBus

from browser_use.browser.session import BrowserSession


class NoopEventBus(EventBus):
	"""EventBus whose dispatch() is a no-op, so no background loop task starts."""

	def dispatch(self, event: BaseEvent) -> BaseEvent:
		return event


class FakeClient:
	"""Minimal stand-in for CDPClient exposing the message handler task."""

	def __init__(self, task: asyncio.Task | None = None):
		self._message_handler_task = task


def _make_session() -> BrowserSession:
	s = BrowserSession(cdp_url='ws://127.0.0.1:9222/x')
	s._intentional_stop = False
	# Don't start the real bubus event loop: its background loop task never
	# completes on its own and would hang asyncio teardown in tests.
	s.event_bus = NoopEventBus()
	return s


async def test_drop_during_reconnect_window_records_flag():
	"""A drop consumed by the one-shot callback while reconnecting is recorded."""
	s = _make_session()
	# Simulate _auto_reconnect() having entered its try but not yet reached
	# its finally, so _reconnecting is still True (step 8 of reconnect()).
	s._reconnecting = True

	loop = asyncio.get_running_loop()
	fut = loop.create_future()
	task = asyncio.ensure_future(fut)
	s._cdp_client_root = FakeClient(task)
	s._attach_ws_drop_callback()

	# The brand-new WebSocket drops inside the window.
	fut.set_exception(ConnectionResetError('ws dropped again'))
	await asyncio.sleep(0.05)

	assert s._drop_while_reconnecting is True


async def test_auto_reconnect_loops_after_drop_in_window(monkeypatch):
	"""_auto_reconnect() re-runs when a drop landed inside the reconnect window."""
	s = _make_session()
	call_count = 0

	async def fake_reconnect(self: BrowserSession) -> None:
		nonlocal call_count
		call_count += 1
		loop = asyncio.get_running_loop()
		fut = loop.create_future()
		task = asyncio.ensure_future(fut)
		self._cdp_client_root = FakeClient(task)
		if call_count == 1:
			# First pass: the new socket dies inside the reconnect window.
			self._attach_ws_drop_callback()
			fut.set_exception(ConnectionResetError('ws dropped again'))
		else:
			# Second pass: healthy socket — mark the task done before attach so
			# no drop callback is registered (nothing can fire, no extra pass).
			fut.set_result(None)
			await asyncio.sleep(0)  # let the task complete
			self._attach_ws_drop_callback()
		await asyncio.sleep(0.05)

	monkeypatch.setattr(BrowserSession, 'reconnect', fake_reconnect)

	await s._auto_reconnect(max_attempts=1)
	# The finally must have re-scheduled a fresh reconnect pass.
	retry = s._reconnect_task
	assert retry is not None, 'expected a re-scheduled reconnect pass'
	await retry

	assert call_count == 2
	assert s._reconnecting is False
	assert s._drop_while_reconnecting is False
