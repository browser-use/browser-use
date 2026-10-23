import asyncio
from pathlib import Path

import pytest

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


async def test_reset_awaits_reconnect_before_finalizing_recording(monkeypatch) -> None:
	session = BrowserSession(browser_profile=BrowserProfile(headless=True, user_data_dir=None, cdp_url='ws://127.0.0.1:9222'))

	reconnect_started = asyncio.Event()
	reconnect_cleanup_complete = asyncio.Event()
	finalized_path = Path('recording.mp4')
	finalization_order: list[tuple[bool, bool, bool]] = []

	async def reconnect(self: BrowserSession) -> None:
		reconnect_started.set()
		try:
			await asyncio.Event().wait()
		finally:
			self._cdp_client_root = None  # type: ignore[assignment]
			reconnect_cleanup_complete.set()

	class ActiveRecordingWatchdog:
		is_recording = True
		recording_path = finalized_path

		async def stop_recording(self) -> Path:
			finalization_order.append(
				(reconnect_task.done(), reconnect_cleanup_complete.is_set(), session._cdp_client_root is None)
			)
			self.is_recording = False
			return finalized_path

	monkeypatch.setattr(BrowserSession, 'reconnect', reconnect)
	session._cdp_client_root = object()  # type: ignore[assignment]
	session._recording_watchdog = ActiveRecordingWatchdog()
	reconnect_task = asyncio.create_task(session._auto_reconnect(max_attempts=1))
	session._reconnect_task = reconnect_task

	try:
		await reconnect_started.wait()
		await session.reset()

		assert reconnect_task.cancelled()
		assert reconnect_cleanup_complete.is_set()
		assert finalization_order == [(True, True, True)]
		assert session.recording_path == finalized_path
		assert session._reconnect_task is None
		assert not session._reconnecting
		assert not session._reconnect_pending
		assert session._reconnect_event.is_set()
	finally:
		if not reconnect_task.done():
			reconnect_task.cancel()
			try:
				await reconnect_task
			except asyncio.CancelledError:
				pass
		await session.event_bus.stop(clear=True, timeout=5)


@pytest.mark.parametrize(
	('method', 'failure'),
	[(method, failure) for method in ['Target.setDiscoverTargets', 'Target.setAutoAttach'] for failure in ['cancel', 'error']]
	+ [('Target.setDiscoverTargets', 'stop_cancel')],
)
async def test_failed_reconnect_closes_replacement_client(monkeypatch, method, failure):
	from browser_use.browser._cdp_timeout import TimeoutWrappedCDPClient
	from browser_use.browser.session_manager import SessionManager

	session = BrowserSession(browser_profile=BrowserProfile(headless=True, user_data_dir=None, cdp_url='ws://127.0.0.1:9222'))
	started = asyncio.Event()
	clients = []
	stop_started = asyncio.Event()
	allow_stop = asyncio.Event()
	manager_cleared = asyncio.Event()
	original_stop = TimeoutWrappedCDPClient.stop
	original_clear = SessionManager.clear

	async def stop(client):
		if failure == 'stop_cancel':
			stop_started.set()
			await allow_stop.wait()
		await original_stop(client)

	async def clear(manager):
		await original_clear(manager)
		manager_cleared.set()

	async def start(client):
		clients.append(client)
		client._message_handler_task = asyncio.create_task(asyncio.Event().wait())

	async def send_raw(client, method: str, params=None, session_id=None):
		if method == blocked_method:
			started.set()
			if failure in {'error', 'stop_cancel'}:
				raise ConnectionError('Initialization failed')
			await asyncio.Event().wait()
		return {'targetInfos': []} if method == 'Target.getTargets' else {}

	blocked_method = method
	monkeypatch.setattr(TimeoutWrappedCDPClient, 'stop', stop)
	monkeypatch.setattr(SessionManager, 'clear', clear)
	monkeypatch.setattr(TimeoutWrappedCDPClient, 'start', start)
	monkeypatch.setattr(TimeoutWrappedCDPClient, 'send_raw', send_raw)
	reconnect = asyncio.create_task(session.reconnect())
	try:
		await asyncio.wait_for(started.wait(), timeout=5)
		if failure == 'cancel':
			reconnect.cancel()
		if failure == 'stop_cancel':
			await asyncio.wait_for(stop_started.wait(), timeout=5)
			reconnect.cancel()
			allow_stop.set()
		with pytest.raises(asyncio.CancelledError if failure in {'cancel', 'stop_cancel'} else ConnectionError):
			await reconnect
		assert session._cdp_client_root is None
		assert session.session_manager is None
		assert session.agent_focus_target_id is None
		assert clients[0]._message_handler_task is None
		assert manager_cleared.is_set()
	finally:
		allow_stop.set()
		if not reconnect.done():
			reconnect.cancel()
		await asyncio.gather(reconnect, return_exceptions=True)
		for client in clients:
			await client.stop()
		await session.event_bus.stop(clear=True, timeout=5)
