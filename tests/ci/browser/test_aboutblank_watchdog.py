import pytest

from browser_use import Browser
from browser_use.browser.events import NavigateToUrlEvent, TabClosedEvent
from browser_use.browser.watchdogs.aboutblank_watchdog import AboutBlankWatchdog


@pytest.mark.asyncio
async def test_aboutblank_watchdog_creates_recovery_tab_directly(monkeypatch) -> None:
	browser = Browser(headless=True)
	watchdog = AboutBlankWatchdog(event_bus=browser.event_bus, browser_session=browser)
	opened_tabs: list[str] = []
	screensaver_calls = 0

	async def fake_get_all_pages(self):
		return []

	async def fake_open_about_blank_tab(self) -> str:
		opened_tabs.append('about:blank')
		return 'target-1'

	async def fake_show_dvd_screensaver(self) -> None:
		nonlocal screensaver_calls
		screensaver_calls += 1

	original_dispatch = browser.event_bus.dispatch

	def guarded_dispatch(event):
		assert not isinstance(event, NavigateToUrlEvent)
		return original_dispatch(event)

	monkeypatch.setattr(type(browser), 'is_cdp_connected', property(lambda self: True))
	monkeypatch.setattr(type(browser), '_cdp_get_all_pages', fake_get_all_pages)
	monkeypatch.setattr(AboutBlankWatchdog, '_open_about_blank_tab', fake_open_about_blank_tab)
	monkeypatch.setattr(AboutBlankWatchdog, '_show_dvd_screensaver_on_about_blank_tabs', fake_show_dvd_screensaver)
	monkeypatch.setattr(browser.event_bus, 'dispatch', guarded_dispatch)

	await watchdog._check_and_ensure_about_blank_tab()

	assert opened_tabs == ['about:blank']
	assert screensaver_calls == 1


@pytest.mark.asyncio
async def test_aboutblank_watchdog_recovers_last_tab_close_directly(monkeypatch) -> None:
	browser = Browser(headless=True)
	watchdog = AboutBlankWatchdog(event_bus=browser.event_bus, browser_session=browser)
	opened_tabs: list[str] = []

	async def fake_get_all_pages(self):
		return []

	async def fake_open_about_blank_tab(self) -> str:
		opened_tabs.append('about:blank')
		return 'target-1'

	async def fake_show_dvd_screensaver(self) -> None:
		return None

	original_dispatch = browser.event_bus.dispatch

	def guarded_dispatch(event):
		assert not isinstance(event, NavigateToUrlEvent)
		return original_dispatch(event)

	monkeypatch.setattr(type(browser), 'is_cdp_connected', property(lambda self: True))
	monkeypatch.setattr(type(browser), '_cdp_get_all_pages', fake_get_all_pages)
	monkeypatch.setattr(AboutBlankWatchdog, '_open_about_blank_tab', fake_open_about_blank_tab)
	monkeypatch.setattr(AboutBlankWatchdog, '_show_dvd_screensaver_on_about_blank_tabs', fake_show_dvd_screensaver)
	monkeypatch.setattr(browser.event_bus, 'dispatch', guarded_dispatch)

	await watchdog.on_TabClosedEvent(TabClosedEvent(target_id='closed-tab'))

	assert opened_tabs == ['about:blank']
