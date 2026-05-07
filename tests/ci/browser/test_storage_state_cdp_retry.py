import pytest

from browser_use.browser.session import BrowserSession
from browser_use.browser.views import BrowserError


class FakeStorage:
	def __init__(self, failures_before_success=1):
		self.calls = 0
		self.failures_before_success = failures_before_success

	async def getCookies(self, session_id):
		self.calls += 1
		if self.calls <= self.failures_before_success:
			raise TimeoutError('silent WebSocket during Storage.getCookies')
		return {'cookies': [{'name': 'session', 'value': 'ok'}]}


class FakeSend:
	def __init__(self, storage):
		self.Storage = storage


class FakeCdpClient:
	def __init__(self, storage):
		self.send = FakeSend(storage)


class FakeCdpSession:
	def __init__(self, storage):
		self.cdp_client = FakeCdpClient(storage)
		self.session_id = 'session-1'


@pytest.mark.asyncio
async def test_cdp_get_cookies_retries_once_after_timeout(monkeypatch):
	session = BrowserSession(headless=True)
	session.browser_profile.cdp_url = 'ws://example.test/devtools/browser/1'
	storage = FakeStorage(failures_before_success=1)
	reconnect_calls = 0

	async def fake_get_or_create_cdp_session(self, target_id=None, focus=True):
		return FakeCdpSession(storage)

	async def fake_reconnect(self):
		nonlocal reconnect_calls
		reconnect_calls += 1

	monkeypatch.setattr(BrowserSession, 'get_or_create_cdp_session', fake_get_or_create_cdp_session)
	monkeypatch.setattr(BrowserSession, 'reconnect', fake_reconnect)

	cookies = await session._cdp_get_cookies()

	assert cookies == [{'name': 'session', 'value': 'ok'}]
	assert storage.calls == 2
	assert reconnect_calls == 1


@pytest.mark.asyncio
async def test_cdp_get_cookies_raises_actionable_error_after_retry(monkeypatch):
	session = BrowserSession(headless=True)
	session.browser_profile.cdp_url = 'ws://example.test/devtools/browser/1'
	storage = FakeStorage(failures_before_success=2)

	async def fake_get_or_create_cdp_session(self, target_id=None, focus=True):
		return FakeCdpSession(storage)

	async def fake_reconnect(self):
		return None

	monkeypatch.setattr(BrowserSession, 'get_or_create_cdp_session', fake_get_or_create_cdp_session)
	monkeypatch.setattr(BrowserSession, 'reconnect', fake_reconnect)

	with pytest.raises(BrowserError) as exc_info:
		await session._cdp_get_cookies()

	message = str(exc_info.value)
	assert 'storage state' in message.lower()
	assert 'cdp connection' in message.lower()
	assert storage.calls == 2


@pytest.mark.asyncio
async def test_cdp_get_cookies_retries_without_reconnect_during_intentional_stop(monkeypatch):
	session = BrowserSession(headless=True)
	session.browser_profile.cdp_url = 'ws://example.test/devtools/browser/1'
	session._intentional_stop = True
	storage = FakeStorage(failures_before_success=1)
	reconnect_calls = 0

	async def fake_get_or_create_cdp_session(self, target_id=None, focus=True):
		return FakeCdpSession(storage)

	async def fake_reconnect(self):
		nonlocal reconnect_calls
		reconnect_calls += 1

	monkeypatch.setattr(BrowserSession, 'get_or_create_cdp_session', fake_get_or_create_cdp_session)
	monkeypatch.setattr(BrowserSession, 'reconnect', fake_reconnect)

	cookies = await session._cdp_get_cookies()

	assert cookies == [{'name': 'session', 'value': 'ok'}]
	assert storage.calls == 2
	assert reconnect_calls == 0
