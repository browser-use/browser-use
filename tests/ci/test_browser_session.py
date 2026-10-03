import asyncio

import pytest

import browser_use.browser.session as session_module
from browser_use.browser.events import BrowserStopEvent
from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession
from browser_use.browser.watchdogs.local_browser_watchdog import LocalBrowserWatchdog


class MessageHandlerClient:
	def __init__(self, task: asyncio.Task) -> None:
		self._message_handler_task = task


async def test_ws_drop_during_reconnect_triggers_follow_up_attempt(monkeypatch) -> None:
	session = BrowserSession(browser_profile=BrowserProfile(headless=True, user_data_dir=None, cdp_url='ws://127.0.0.1:9222'))

	reconnect_started = asyncio.Event()
	allow_reconnect = asyncio.Event()
	reconnect_attempts = 0

	async def reconnect(self: BrowserSession) -> None:
		nonlocal reconnect_attempts
		reconnect_attempts += 1
		if reconnect_attempts == 1:
			reconnect_started.set()
			await allow_reconnect.wait()

	monkeypatch.setattr(BrowserSession, 'reconnect', reconnect)

	connection_closed = asyncio.get_running_loop().create_future()
	task = asyncio.ensure_future(connection_closed)
	session._cdp_client_root = MessageHandlerClient(task)  # type: ignore[assignment]
	initial_reconnect = asyncio.create_task(session._auto_reconnect(max_attempts=1))
	await reconnect_started.wait()
	session._attach_ws_drop_callback()
	connection_closed.set_exception(ConnectionResetError('ws dropped again'))
	await asyncio.sleep(0)
	connection_closed.exception()
	allow_reconnect.set()
	await initial_reconnect

	assert session._reconnect_task is not None
	await session._reconnect_task
	assert reconnect_attempts == 2
	await session.event_bus.stop(clear=True, timeout=5)


async def _cancel_leftover_tasks() -> None:
	"""Cancel every pending task except the current one (wedged handler cleanup)."""
	current = asyncio.current_task()
	for task in asyncio.all_tasks():
		if task is not current and not task.done():
			task.cancel()
	await asyncio.sleep(0)


async def _shrink_teardown_timeouts(monkeypatch: pytest.MonkeyPatch) -> None:
	"""Shrink teardown phase timeouts when the implementation provides them."""
	shrunk = False
	for name in (
		'TEARDOWN_SAVE_TIMEOUT_S',
		'TEARDOWN_STOP_TIMEOUT_S',
		'TEARDOWN_PROCESS_KILL_TIMEOUT_S',
		'TEARDOWN_RESET_TIMEOUT_S',
		'TEARDOWN_STOPPED_NOTIFY_TIMEOUT_S',
	):
		if hasattr(session_module, name):
			monkeypatch.setattr(session_module, name, 0.5)
			shrunk = True
	return shrunk


async def test_kill_completes_despite_wedged_stop_handler(monkeypatch: pytest.MonkeyPatch) -> None:
	"""kill() must return even when a BrowserStopEvent handler never completes.

	Regression test for https://github.com/browser-use/browser-use/issues/5770:
	repeated start/kill hung on CI because kill() awaited the stop-event
	dispatch with no timeout, so one wedged handler blocked teardown forever.
	"""
	await _shrink_teardown_timeouts(monkeypatch)
	session = BrowserSession(browser_profile=BrowserProfile(headless=True, user_data_dir=None, keep_alive=True))

	async def wedged_handler(event: BrowserStopEvent) -> None:
		await asyncio.Event().wait()  # never resolves: simulates a stuck teardown handler

	session.event_bus.on(BrowserStopEvent, wedged_handler)
	try:
		await asyncio.wait_for(session.kill(), timeout=30)
	finally:
		await _cancel_leftover_tasks()


async def test_kill_reaps_browser_process_when_stop_handlers_wedge(monkeypatch: pytest.MonkeyPatch) -> None:
	"""kill() must leave no orphan browser process when graceful stop wedges.

	Regression test for https://github.com/browser-use/browser-use/issues/5770:
	the runner had to terminate orphaned chrome processes because the
	event-driven BrowserKillEvent was stuck behind the wedged stop handler.
	"""
	await _shrink_teardown_timeouts(monkeypatch)
	session = BrowserSession(browser_profile=BrowserProfile(headless=True, user_data_dir=None, keep_alive=True))
	watchdog = LocalBrowserWatchdog(event_bus=session.event_bus, browser_session=session)

	class FakeProcess:
		def __init__(self) -> None:
			self.alive = True
			self.terminate_called = False
			self.kill_called = False

		def is_running(self) -> bool:
			return self.alive

		def terminate(self) -> None:
			self.terminate_called = True
			self.alive = False

		def kill(self) -> None:
			self.kill_called = True
			self.alive = False

	proc = FakeProcess()
	watchdog._subprocess = proc  # type: ignore[assignment]
	session._local_browser_watchdog = watchdog

	async def wedged_handler(event: BrowserStopEvent) -> None:
		await asyncio.Event().wait()  # never resolves: simulates a stuck teardown handler

	session.event_bus.on(BrowserStopEvent, wedged_handler)
	try:
		await asyncio.wait_for(session.kill(), timeout=30)
	finally:
		await _cancel_leftover_tasks()

	assert proc.terminate_called or proc.kill_called, 'browser process was never reaped'


def test_teardown_phase_timeouts_are_bounded() -> None:
	"""Every teardown phase must have a finite, reasonably small timeout."""
	for name in (
		'TEARDOWN_SAVE_TIMEOUT_S',
		'TEARDOWN_STOP_TIMEOUT_S',
		'TEARDOWN_PROCESS_KILL_TIMEOUT_S',
		'TEARDOWN_RESET_TIMEOUT_S',
		'TEARDOWN_STOPPED_NOTIFY_TIMEOUT_S',
	):
		value = getattr(session_module, name, None)
		assert value is not None, f'{name} must be defined so teardown cannot hang forever'
		assert 0 < value <= 30, f'{name}={value} must be a small positive bound'
