from __future__ import annotations

import pytest

from browser_use import Browser
from browser_use.browser.events import NavigateToUrlEvent


@pytest.mark.asyncio
async def test_public_navigate_to_uses_direct_navigation(monkeypatch) -> None:
	browser = Browser(headless=True)
	direct_calls: list[tuple[str, bool]] = []

	async def fake_navigate_to_url_direct(self, url: str, *, new_tab: bool = False, **kwargs) -> None:
		assert kwargs == {}
		direct_calls.append((url, new_tab))

	original_dispatch = browser.event_bus.dispatch

	def guarded_dispatch(event, *args, **kwargs):
		assert not isinstance(event, NavigateToUrlEvent)
		return original_dispatch(event, *args, **kwargs)

	monkeypatch.setattr(type(browser), 'navigate_to_url_direct', fake_navigate_to_url_direct)
	monkeypatch.setattr(browser.event_bus, 'dispatch', guarded_dispatch)

	await browser.navigate_to('https://example.com', new_tab=True)

	assert direct_calls == [('https://example.com', True)]


@pytest.mark.asyncio
async def test_navigate_event_handler_remains_compatibility_adapter(monkeypatch) -> None:
	browser = Browser(headless=True)
	direct_calls: list[tuple[str, bool, int | None, str, float | None]] = []

	async def fake_navigate_to_url_direct(
		self,
		url: str,
		*,
		new_tab: bool = False,
		timeout_ms: int | None = None,
		wait_until: str = 'load',
		event_timeout: float | None = None,
	) -> None:
		direct_calls.append((url, new_tab, timeout_ms, wait_until, event_timeout))

	monkeypatch.setattr(type(browser), 'navigate_to_url_direct', fake_navigate_to_url_direct)

	await browser.on_NavigateToUrlEvent(
		NavigateToUrlEvent(
			url='https://example.com',
			new_tab=True,
			timeout_ms=1234,
			wait_until='commit',
			event_timeout=5.0,
		)
	)

	assert direct_calls == [('https://example.com', True, 1234, 'commit', 5.0)]
