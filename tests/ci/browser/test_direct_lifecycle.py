from __future__ import annotations

from typing import Any, cast

import pytest

from browser_use import Browser
from browser_use.browser.events import BrowserLaunchEvent, BrowserLaunchResult, BrowserStartEvent
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
