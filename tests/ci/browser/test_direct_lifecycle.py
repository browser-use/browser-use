from __future__ import annotations

from typing import Any, cast

import pytest

from browser_use import Browser
from browser_use.browser.events import (
	BrowserKillEvent,
	BrowserLaunchEvent,
	BrowserLaunchResult,
	BrowserStartEvent,
	BrowserStopEvent,
)
from browser_use.browser.watchdogs.local_browser_watchdog import LocalBrowserWatchdog


@pytest.mark.asyncio
async def test_public_start_uses_direct_start(monkeypatch) -> None:
	browser = Browser(headless=True)
	start_calls = 0

	async def fake_start_direct(self) -> dict[str, str]:
		nonlocal start_calls
		start_calls += 1
		return {'cdp_url': 'http://127.0.0.1:9222'}

	original_dispatch = browser.event_bus.dispatch

	def guarded_dispatch(event, *args, **kwargs):
		assert not isinstance(event, BrowserStartEvent)
		return original_dispatch(event, *args, **kwargs)

	monkeypatch.setattr(type(browser), 'start_direct', fake_start_direct)
	monkeypatch.setattr(browser.event_bus, 'dispatch', guarded_dispatch)

	await browser.start()

	assert start_calls == 1


@pytest.mark.asyncio
async def test_start_event_handler_remains_compatibility_adapter(monkeypatch) -> None:
	browser = Browser(headless=True)
	start_calls = 0

	async def fake_start_direct(self) -> dict[str, str]:
		nonlocal start_calls
		start_calls += 1
		return {'cdp_url': 'http://127.0.0.1:9222'}

	monkeypatch.setattr(type(browser), 'start_direct', fake_start_direct)

	result = await browser.on_BrowserStartEvent(BrowserStartEvent())

	assert result == {'cdp_url': 'http://127.0.0.1:9222'}
	assert start_calls == 1


@pytest.mark.asyncio
async def test_start_direct_launches_local_browser_without_launch_event(monkeypatch) -> None:
	browser = Browser(headless=True)
	launch_calls = 0
	connect_calls: list[str | None] = []

	class FakeLocalBrowserWatchdog:
		async def launch_browser(self) -> BrowserLaunchResult:
			nonlocal launch_calls
			launch_calls += 1
			return BrowserLaunchResult(cdp_url='http://127.0.0.1:9333')

	async def fake_attach_all_watchdogs(self) -> None:
		self._local_browser_watchdog = FakeLocalBrowserWatchdog()
		self._watchdogs_attached = True

	async def fake_connect(self, cdp_url: str | None = None):
		connect_calls.append(cdp_url)
		self._cdp_client_root = cast(Any, object())
		return self

	original_dispatch = browser.event_bus.dispatch

	def guarded_dispatch(event, *args, **kwargs):
		assert not isinstance(event, (BrowserStartEvent, BrowserLaunchEvent))
		return original_dispatch(event, *args, **kwargs)

	monkeypatch.setattr(type(browser), 'attach_all_watchdogs', fake_attach_all_watchdogs)
	monkeypatch.setattr(type(browser), 'connect', fake_connect)
	monkeypatch.setattr(browser.event_bus, 'dispatch', guarded_dispatch)

	try:
		result = await browser.start_direct()
	finally:
		browser._cdp_client_root = None
		await browser.event_bus.stop(clear=True, timeout=1)

	assert result == {'cdp_url': 'http://127.0.0.1:9333'}
	assert launch_calls == 1
	assert connect_calls == ['http://127.0.0.1:9333']


@pytest.mark.asyncio
async def test_local_browser_watchdog_launch_browser_is_direct_adapter(monkeypatch) -> None:
	browser = Browser(headless=True)
	watchdog = LocalBrowserWatchdog(event_bus=browser.event_bus, browser_session=browser)
	fake_process = cast(Any, object())
	launch_calls: list[int] = []

	async def fake_launch_browser(self, max_retries: int = 3):
		launch_calls.append(max_retries)
		return fake_process, 'http://127.0.0.1:9444'

	original_dispatch = browser.event_bus.dispatch

	def guarded_dispatch(event, *args, **kwargs):
		assert not isinstance(event, BrowserLaunchEvent)
		return original_dispatch(event, *args, **kwargs)

	monkeypatch.setattr(type(watchdog), '_launch_browser', fake_launch_browser)
	monkeypatch.setattr(browser.event_bus, 'dispatch', guarded_dispatch)

	result = await watchdog.launch_browser(max_retries=5)

	assert result.cdp_url == 'http://127.0.0.1:9444'
	assert watchdog._subprocess is fake_process
	assert launch_calls == [5]


@pytest.mark.asyncio
async def test_public_kill_uses_direct_stop(monkeypatch) -> None:
	browser = Browser(headless=True)
	stop_calls: list[tuple[bool, bool]] = []

	async def fake_save_storage_state_before_stop(self) -> None:
		return None

	async def fake_stop_direct(self, *, force: bool = False, notify_watchdogs: bool = True) -> None:
		stop_calls.append((force, notify_watchdogs))

	original_dispatch = browser.event_bus.dispatch

	def guarded_dispatch(event, *args, **kwargs):
		assert not isinstance(event, BrowserStopEvent)
		return original_dispatch(event, *args, **kwargs)

	monkeypatch.setattr(type(browser), '_save_storage_state_before_stop', fake_save_storage_state_before_stop)
	monkeypatch.setattr(type(browser), 'stop_direct', fake_stop_direct)
	monkeypatch.setattr(browser.event_bus, 'dispatch', guarded_dispatch)

	await browser.kill()

	assert stop_calls == [(True, True)]


@pytest.mark.asyncio
async def test_stop_event_handler_remains_compatibility_adapter(monkeypatch) -> None:
	browser = Browser(headless=True)
	stop_calls: list[tuple[bool, bool]] = []

	async def fake_stop_direct(self, *, force: bool = False, notify_watchdogs: bool = True) -> None:
		stop_calls.append((force, notify_watchdogs))

	monkeypatch.setattr(type(browser), 'stop_direct', fake_stop_direct)

	await browser.on_BrowserStopEvent(BrowserStopEvent(force=True))

	assert stop_calls == [(True, False)]


@pytest.mark.asyncio
async def test_stop_direct_notifies_watchdogs_without_stop_events(monkeypatch) -> None:
	browser = Browser(headless=True)
	calls: list[str] = []

	class FakeAboutBlankWatchdog:
		def mark_stopping(self) -> None:
			calls.append('aboutblank')

	class FakeStorageStateWatchdog:
		async def stop_monitoring(self) -> None:
			calls.append('storage')

	class FakeRecordingWatchdog:
		async def stop_recording(self) -> None:
			calls.append('recording')

	class FakeHarRecordingWatchdog:
		async def save_har(self) -> None:
			calls.append('har')

	class FakeLocalBrowserWatchdog:
		async def cleanup_browser(self) -> None:
			calls.append('local')

	browser._aboutblank_watchdog = FakeAboutBlankWatchdog()
	browser._storage_state_watchdog = FakeStorageStateWatchdog()
	browser._recording_watchdog = FakeRecordingWatchdog()
	browser._har_recording_watchdog = FakeHarRecordingWatchdog()
	browser._local_browser_watchdog = FakeLocalBrowserWatchdog()

	original_dispatch = browser.event_bus.dispatch

	def guarded_dispatch(event, *args, **kwargs):
		assert not isinstance(event, (BrowserStopEvent, BrowserKillEvent))
		return original_dispatch(event, *args, **kwargs)

	monkeypatch.setattr(browser.event_bus, 'dispatch', guarded_dispatch)

	try:
		await browser.stop_direct(force=True)
	finally:
		await browser.event_bus.stop(clear=True, timeout=1)

	assert calls == ['aboutblank', 'storage', 'recording', 'har', 'local']
