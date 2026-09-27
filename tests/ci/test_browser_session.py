import asyncio

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
