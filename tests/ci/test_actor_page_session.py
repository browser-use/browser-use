from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from browser_use.actor.page import Page


def make_page(*, session_id: str = 'stale-session') -> tuple[Page, MagicMock, AsyncMock]:
	client = MagicMock()
	client.send.Page.reload = AsyncMock()

	browser_session = MagicMock()
	browser_session.cdp_client = client
	browser_session.get_or_create_cdp_session = AsyncMock(return_value=SimpleNamespace(session_id='active-session'))

	page = Page(cast(Any, browser_session), target_id='target-1', session_id=session_id)
	return page, browser_session, client.send.Page.reload


async def test_reload_refreshes_a_stale_cached_session() -> None:
	page, browser_session, reload_command = make_page()
	page._mouse = cast(Any, object())

	await page.reload()

	browser_session.get_or_create_cdp_session.assert_awaited_once_with('target-1', focus=False)
	reload_command.assert_awaited_once_with(session_id='active-session')
	assert page._session_id == 'active-session'
	assert page._mouse is None


async def test_reload_raises_when_the_target_detached() -> None:
	page, browser_session, reload_command = make_page()
	browser_session.get_or_create_cdp_session.side_effect = ValueError('Target target-1 has detached - no active sessions')

	with pytest.raises(ValueError, match='Target target-1 has detached'):
		await page.reload()

	reload_command.assert_not_awaited()
	assert page._session_id is None
