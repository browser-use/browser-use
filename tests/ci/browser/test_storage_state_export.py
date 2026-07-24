import json
from pathlib import Path
from typing import Any

import pytest

from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession

COOKIE = {
	'name': 'session',
	'value': 'abc123',
	'domain': '.example.com',
	'path': '/',
	'expires': 1893456000,
	'httpOnly': True,
	'secure': True,
	'sameSite': 'Lax',
}

ORIGIN = {
	'origin': 'https://example.com',
	'localStorage': [{'name': 'token', 'value': 'xyz789'}],
	'sessionStorage': [{'name': 'tab', 'value': '1'}],
}


@pytest.fixture
def browser_session() -> BrowserSession:
	return BrowserSession(browser_profile=BrowserProfile(headless=True, user_data_dir=None))


@pytest.mark.asyncio
async def test_export_storage_state_defaults_to_cookies_only(
	browser_session: BrowserSession,
	monkeypatch: pytest.MonkeyPatch,
) -> None:
	calls: list[str] = []

	async def fake_get_cookies(self: BrowserSession) -> list[dict[str, Any]]:
		calls.append('cookies')
		return [COOKIE]

	async def fake_get_storage_state(self: BrowserSession) -> dict[str, Any]:
		calls.append('storage')
		return {'cookies': [COOKIE], 'origins': [ORIGIN]}

	monkeypatch.setattr(BrowserSession, '_cdp_get_cookies', fake_get_cookies)
	monkeypatch.setattr(BrowserSession, '_cdp_get_storage_state', fake_get_storage_state)

	storage_state = await browser_session.export_storage_state()

	assert calls == ['cookies']
	assert storage_state['cookies'] == [COOKIE]
	assert storage_state['origins'] == []


@pytest.mark.asyncio
async def test_export_storage_state_can_include_browser_storage(
	browser_session: BrowserSession,
	tmp_path: Path,
	monkeypatch: pytest.MonkeyPatch,
) -> None:
	calls: list[str] = []

	async def fake_get_cookies(self: BrowserSession) -> list[dict[str, Any]]:
		calls.append('cookies')
		return [COOKIE]

	async def fake_get_storage_state(self: BrowserSession) -> dict[str, Any]:
		calls.append('storage')
		return {'cookies': [COOKIE], 'origins': [ORIGIN]}

	monkeypatch.setattr(BrowserSession, '_cdp_get_cookies', fake_get_cookies)
	monkeypatch.setattr(BrowserSession, '_cdp_get_storage_state', fake_get_storage_state)

	output_path = tmp_path / 'storage_state.json'
	storage_state = await browser_session.export_storage_state(output_path, include_storage=True)

	assert calls == ['storage']
	assert storage_state['cookies'] == [COOKIE]
	assert storage_state['origins'] == [ORIGIN]
	assert json.loads(output_path.read_text(encoding='utf-8')) == storage_state
