import pytest

from browser_use import Browser
from browser_use.browser.events import SwitchTabEvent, TabClosedEvent
from browser_use.browser.services import TabService


@pytest.mark.asyncio
async def test_tab_closed_switches_focus_directly(monkeypatch) -> None:
	browser = Browser(headless=True)
	browser.agent_focus_target_id = 'current-tab'
	switch_calls: list[str | None] = []

	async def fake_switch_tab_direct(self, target_id=None, *, require_existing_focus: bool = False):
		switch_calls.append(target_id)
		return 'next-tab'

	original_dispatch = browser.event_bus.dispatch

	def guarded_dispatch(event):
		assert not isinstance(event, SwitchTabEvent)
		return original_dispatch(event)

	monkeypatch.setattr(type(browser), 'switch_tab_direct', fake_switch_tab_direct)
	monkeypatch.setattr(browser.event_bus, 'dispatch', guarded_dispatch)

	await browser.on_TabClosedEvent(TabClosedEvent(target_id='current-tab'))

	assert switch_calls == [None]


@pytest.mark.asyncio
async def test_tab_service_uses_direct_switch(monkeypatch) -> None:
	browser = Browser(headless=True)
	tab_service = TabService(browser_session=browser)
	switch_calls: list[str | None] = []

	async def fake_switch_tab_direct(self, target_id=None, *, require_existing_focus: bool = False):
		switch_calls.append(target_id)
		return 'target-2'

	monkeypatch.setattr(type(browser), 'switch_tab_direct', fake_switch_tab_direct)

	result = await tab_service.switch('target-2')

	assert result == 'target-2'
	assert switch_calls == ['target-2']
