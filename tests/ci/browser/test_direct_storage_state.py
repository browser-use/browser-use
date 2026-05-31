import pytest

from browser_use import Browser
from browser_use.browser.events import BrowserConnectedEvent, LoadStorageStateEvent
from browser_use.browser.watchdogs.storage_state_watchdog import StorageStateWatchdog


@pytest.mark.asyncio
async def test_storage_watchdog_loads_directly_on_browser_connected(monkeypatch) -> None:
	browser = Browser(headless=True)
	watchdog = StorageStateWatchdog(event_bus=browser.event_bus, browser_session=browser)
	calls: list[str | None] = []

	async def fake_start_monitoring(self) -> None:
		return None

	async def fake_load_storage_state(self, path: str | None = None) -> None:
		calls.append(path)

	original_dispatch = browser.event_bus.dispatch

	def guarded_dispatch(event):
		assert not isinstance(event, LoadStorageStateEvent)
		return original_dispatch(event)

	monkeypatch.setattr(StorageStateWatchdog, '_start_monitoring', fake_start_monitoring)
	monkeypatch.setattr(StorageStateWatchdog, 'load_storage_state', fake_load_storage_state)
	monkeypatch.setattr(browser.event_bus, 'dispatch', guarded_dispatch)

	await watchdog.on_BrowserConnectedEvent(BrowserConnectedEvent(cdp_url='http://127.0.0.1:9222'))

	assert calls == [None]


@pytest.mark.asyncio
async def test_browser_session_saves_storage_state_directly_before_stop(monkeypatch) -> None:
	browser = Browser(headless=True)
	calls = 0

	class FakeStorageStateWatchdog:
		async def save_storage_state(self) -> None:
			nonlocal calls
			calls += 1

	def guarded_dispatch(event):
		raise AssertionError(f'Unexpected event dispatch: {event.event_type}')

	browser._storage_state_watchdog = FakeStorageStateWatchdog()
	monkeypatch.setattr(type(browser), 'is_cdp_connected', property(lambda self: True))
	monkeypatch.setattr(browser.event_bus, 'dispatch', guarded_dispatch)

	await browser._save_storage_state_before_stop()

	assert calls == 1


@pytest.mark.asyncio
async def test_browser_session_skips_direct_storage_save_when_not_connected(monkeypatch) -> None:
	browser = Browser(headless=True)
	calls = 0

	class FakeStorageStateWatchdog:
		async def save_storage_state(self) -> None:
			nonlocal calls
			calls += 1

	def guarded_dispatch(event):
		raise AssertionError(f'Unexpected event dispatch: {event.event_type}')

	browser._storage_state_watchdog = FakeStorageStateWatchdog()
	monkeypatch.setattr(browser.event_bus, 'dispatch', guarded_dispatch)

	await browser._save_storage_state_before_stop()

	assert calls == 0
