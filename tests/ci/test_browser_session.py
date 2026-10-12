import asyncio

import pytest

import browser_use.browser.session as session_module
from browser_use.browser.events import BrowserStopEvent, SaveStorageStateEvent
from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession


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


def _unstarted_session() -> BrowserSession:
	return BrowserSession(browser_profile=BrowserProfile(headless=True, user_data_dir=None, cdp_url='ws://127.0.0.1:9222'))


async def test_kill_completes_without_browser() -> None:
	"""Healthy teardown stays fast: kill() on an unstarted session must return, not raise."""
	session = _unstarted_session()
	await asyncio.wait_for(session.kill(), timeout=30)


async def test_kill_fails_loudly_when_stop_handler_wedges(monkeypatch) -> None:
	"""A wedged BrowserStopEvent handler must not stall kill() forever (browser-use#5770).

	Simulates the Windows CI runner symptom where teardown stops making progress with no
	error and no timeout: kill() must raise TimeoutError naming the stuck phase instead.
	"""
	monkeypatch.setattr(session_module, 'BROWSER_SESSION_TEARDOWN_TIMEOUT_S', 2.0)
	session = _unstarted_session()
	release = asyncio.Event()

	async def wedged_handler(event: BrowserStopEvent) -> None:
		await release.wait()

	session.event_bus.on('BrowserStopEvent', wedged_handler)
	with pytest.raises(TimeoutError, match='BrowserStopEvent handlers'):
		await session.kill()
	# Release the wedged handler so the bus can shut down cleanly without leaked tasks.
	release.set()
	await session.event_bus.stop(clear=True, timeout=5)


async def test_kill_fails_loudly_when_storage_save_wedges(monkeypatch) -> None:
	"""A wedged SaveStorageStateEvent handler must not stall kill() forever either."""
	monkeypatch.setattr(session_module, 'BROWSER_SESSION_TEARDOWN_TIMEOUT_S', 2.0)
	session = _unstarted_session()
	release = asyncio.Event()

	async def wedged_handler(event: SaveStorageStateEvent) -> None:
		await release.wait()

	session.event_bus.on('SaveStorageStateEvent', wedged_handler)
	with pytest.raises(TimeoutError, match='storage-state save'):
		await session.kill()
	release.set()
	await session.event_bus.stop(clear=True, timeout=5)


async def test_stop_fails_loudly_when_stop_handler_wedges(monkeypatch) -> None:
	"""stop() shares the same unbounded teardown awaits as kill() and needs the same bound."""
	monkeypatch.setattr(session_module, 'BROWSER_SESSION_TEARDOWN_TIMEOUT_S', 2.0)
	session = _unstarted_session()
	release = asyncio.Event()

	async def wedged_handler(event: BrowserStopEvent) -> None:
		await release.wait()

	session.event_bus.on('BrowserStopEvent', wedged_handler)
	with pytest.raises(TimeoutError, match='BrowserStopEvent handlers'):
		await session.stop()
	release.set()
	await session.event_bus.stop(clear=True, timeout=5)
