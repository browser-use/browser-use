"""Tests for BrowserSession tab id resolution."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from browser_use.browser import BrowserSession
from browser_use.browser.views import TabInfo


class _StubSessionManager:
	"""Minimal SessionManager stub for tab id resolution tests."""

	def __init__(self, target_ids: list[str], *, valid_target_ids: set[str] | None = None) -> None:
		self._target_ids = target_ids
		self._valid_target_ids = valid_target_ids or set(target_ids)

	def get_all_target_ids(self) -> list[str]:
		return list(self._target_ids)

	async def is_target_valid(self, target_id: str) -> bool:
		return target_id in self._valid_target_ids


@pytest.mark.asyncio
async def test_get_target_id_from_tab_id_resolves_suffix_from_session_manager():
	"""A real target id suffix should resolve directly from SessionManager."""
	session = BrowserSession(headless=True)
	session.session_manager = _StubSessionManager(['target-home-abcd', 'target-page-ef01'])

	target_id = await session.get_target_id_from_tab_id('ef01')

	assert target_id == 'target-page-ef01'


@pytest.mark.asyncio
async def test_get_target_id_from_tab_id_falls_back_to_zero_padded_index():
	"""Numeric ids like 0001 should resolve to the second open tab."""
	session = BrowserSession(headless=True)
	session.session_manager = _StubSessionManager([])
	object.__setattr__(
		session,
		'get_tabs',
		AsyncMock(
			return_value=[
				TabInfo(target_id='target-home-abcd', url='http://example.com/home', title='Home'),
				TabInfo(target_id='target-page-ef01', url='http://example.com/page1', title='Page 1'),
			]
		),
	)

	target_id = await session.get_target_id_from_tab_id('0001')

	assert target_id == 'target-page-ef01'


@pytest.mark.asyncio
async def test_get_target_id_from_tab_id_raises_for_missing_reference():
	"""Unknown tab ids should still fail clearly."""
	session = BrowserSession(headless=True)
	session.session_manager = _StubSessionManager([])
	object.__setattr__(session, 'get_tabs', AsyncMock(return_value=[]))

	with pytest.raises(ValueError, match='No TargetID found'):
		await session.get_target_id_from_tab_id('9999')
