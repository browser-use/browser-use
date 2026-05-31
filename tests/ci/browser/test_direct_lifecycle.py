from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest

from browser_use import Browser
from browser_use.browser.events import (
	BrowserConnectedEvent,
	BrowserKillEvent,
	BrowserLaunchEvent,
	BrowserLaunchResult,
	BrowserStartEvent,
	BrowserStopEvent,
	BrowserStoppedEvent,
)
from browser_use.browser.services import DialogService
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
async def test_start_direct_initializes_connected_services_without_connected_event(monkeypatch) -> None:
	browser = Browser(headless=True)
	calls: list[str] = []

	class FakeLocalBrowserWatchdog:
		async def launch_browser(self) -> BrowserLaunchResult:
			calls.append('launch')
			return BrowserLaunchResult(cdp_url='http://127.0.0.1:9334')

	class FakeDownloadsWatchdog:
		async def initialize_downloads_directory(self) -> None:
			calls.append('downloads')

	class FakeStorageStateWatchdog:
		async def initialize_storage_state(self) -> None:
			calls.append('storage')

	class FakePermissionsWatchdog:
		async def grant_permissions(self) -> None:
			calls.append('permissions')

	class FakeRecordingWatchdog:
		async def start_configured_recording(self) -> None:
			calls.append('recording')

	class FakeHarRecordingWatchdog:
		async def start_configured_recording(self) -> None:
			calls.append('har')

	class FakeCaptchaWatchdog:
		async def register_cdp_handlers(self) -> None:
			calls.append('captcha')

	async def fake_attach_all_watchdogs(self) -> None:
		self._local_browser_watchdog = FakeLocalBrowserWatchdog()
		self._downloads_watchdog = FakeDownloadsWatchdog()
		self._storage_state_watchdog = FakeStorageStateWatchdog()
		self._permissions_watchdog = FakePermissionsWatchdog()
		self._recording_watchdog = FakeRecordingWatchdog()
		self._har_recording_watchdog = FakeHarRecordingWatchdog()
		self._captcha_watchdog = FakeCaptchaWatchdog()
		self._watchdogs_attached = True

	async def fake_connect(self, cdp_url: str | None = None):
		calls.append(f'connect:{cdp_url}')
		self._cdp_client_root = cast(Any, object())
		return self

	original_dispatch = browser.event_bus.dispatch

	def guarded_dispatch(event, *args, **kwargs):
		if isinstance(event, BrowserConnectedEvent):
			raise RuntimeError('BrowserConnectedEvent must not own connected-service initialization')
		return original_dispatch(event, *args, **kwargs)

	monkeypatch.setattr(type(browser), 'attach_all_watchdogs', fake_attach_all_watchdogs)
	monkeypatch.setattr(type(browser), 'connect', fake_connect)
	monkeypatch.setattr(browser.event_bus, 'dispatch', guarded_dispatch)

	try:
		result = await browser.start_direct()
	finally:
		browser._cdp_client_root = None
		await browser.event_bus.stop(clear=True, timeout=1)

	assert result == {'cdp_url': 'http://127.0.0.1:9334'}
	assert calls == [
		'launch',
		'connect:http://127.0.0.1:9334',
		'downloads',
		'storage',
		'permissions',
		'recording',
		'har',
		'captcha',
	]


@pytest.mark.asyncio
async def test_target_services_initialize_without_tab_created_event(monkeypatch) -> None:
	browser = Browser(headless=True)
	calls: list[str] = []

	class FakeSecurityWatchdog:
		async def validate_new_tab(self, url: str, target_id: str) -> bool:
			calls.append(f'security:{url}:{target_id}')
			return True

	class FakeAboutBlankWatchdog:
		async def handle_tab_created(self, *, target_id: str, url: str) -> None:
			calls.append(f'aboutblank:{url}:{target_id}')

	class FakeDownloadsWatchdog:
		async def attach_to_target(self, target_id: str) -> None:
			calls.append(f'downloads:{target_id}')

	class FakeCrashWatchdog:
		async def attach_to_target(self, target_id: str) -> None:
			calls.append(f'crash:{target_id}')

	async def fake_apply_viewport(self, target_id: str) -> None:
		calls.append(f'viewport:{target_id}')

	async def fake_register_dialog_handlers(self, target_id: str) -> None:
		calls.append(f'dialogs:{target_id}')

	monkeypatch.setattr(type(browser), '_apply_viewport_to_target', fake_apply_viewport)
	monkeypatch.setattr(DialogService, 'register_handlers', fake_register_dialog_handlers)
	browser._security_watchdog = FakeSecurityWatchdog()
	browser._aboutblank_watchdog = FakeAboutBlankWatchdog()
	browser._downloads_watchdog = FakeDownloadsWatchdog()
	browser._crash_watchdog = FakeCrashWatchdog()

	await browser._initialize_target_services_direct('target-123', 'about:blank')

	assert calls == [
		'viewport:target-123',
		'security:about:blank:target-123',
		'aboutblank:about:blank:target-123',
		'downloads:target-123',
		'dialogs:target-123',
		'crash:target-123',
	]


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
async def test_stop_direct_cancels_pending_reconnect(monkeypatch) -> None:
	browser = Browser(headless=True)
	cancelled = asyncio.Event()

	async def pending_reconnect() -> None:
		try:
			await asyncio.sleep(30)
		except asyncio.CancelledError:
			cancelled.set()
			raise

	async def noop(self, *args, **kwargs) -> None:
		return None

	monkeypatch.setattr(type(browser), '_notify_watchdogs_before_stop', noop)
	monkeypatch.setattr(type(browser), 'reset', noop)
	monkeypatch.setattr(type(browser), '_notify_browser_stopped_compatibility', noop)

	task = asyncio.create_task(pending_reconnect())
	browser._reconnect_task = task
	browser._reconnecting = True
	browser._reconnect_event.clear()
	await asyncio.sleep(0)

	await browser.stop_direct(force=True)

	assert browser._intentional_stop is True
	assert browser._reconnect_task is None
	assert browser._reconnecting is False
	assert browser._reconnect_event.is_set()
	assert cancelled.is_set()


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

	class FakeDownloadsWatchdog:
		async def cleanup_after_stop(self) -> None:
			calls.append('downloads')

	class FakeCaptchaWatchdog:
		def reset_state(self) -> None:
			calls.append('captcha')

	class FakeLocalBrowserWatchdog:
		async def cleanup_browser(self) -> None:
			calls.append('local')

	browser._aboutblank_watchdog = FakeAboutBlankWatchdog()
	browser._downloads_watchdog = FakeDownloadsWatchdog()
	browser._storage_state_watchdog = FakeStorageStateWatchdog()
	browser._recording_watchdog = FakeRecordingWatchdog()
	browser._har_recording_watchdog = FakeHarRecordingWatchdog()
	browser._captcha_watchdog = FakeCaptchaWatchdog()
	browser._local_browser_watchdog = FakeLocalBrowserWatchdog()

	original_dispatch = browser.event_bus.dispatch

	def guarded_dispatch(event, *args, **kwargs):
		assert not isinstance(event, (BrowserStopEvent, BrowserKillEvent, BrowserStoppedEvent))
		return original_dispatch(event, *args, **kwargs)

	monkeypatch.setattr(browser.event_bus, 'dispatch', guarded_dispatch)

	try:
		await browser.stop_direct(force=True)
	finally:
		await browser.event_bus.stop(clear=True, timeout=1)

	assert calls == ['aboutblank', 'downloads', 'storage', 'recording', 'har', 'captcha', 'local']
