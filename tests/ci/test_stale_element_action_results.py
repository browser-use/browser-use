"""Stale element references must be reported as action errors."""

# Tests use an intentionally partial BrowserSession double.
# pyright: reportArgumentType=false

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from browser_use.tools.service import Tools
from browser_use.tools.views import ClickElementActionIndexOnly, InputTextAction


def _stale_browser_session():
	return SimpleNamespace(get_element_by_index=AsyncMock(return_value=None))


@pytest.mark.asyncio
async def test_stale_click_index_is_an_error() -> None:
	tools = Tools()
	browser_session = _stale_browser_session()

	result = await tools._click_by_index(
		ClickElementActionIndexOnly(index=999),
		browser_session,
	)

	assert result.error == 'Element index 999 not available - page may have changed. Try refreshing browser state.'
	assert result.extracted_content is None


@pytest.mark.asyncio
async def test_stale_input_index_is_an_error() -> None:
	tools = Tools()
	browser_session = _stale_browser_session()
	action = tools.registry.registry.actions['input']

	result = await action.function(
		params=InputTextAction(index=999, text='hello'),
		browser_session=browser_session,
	)

	assert result.error == 'Element index 999 not available - page may have changed. Try refreshing browser state.'
	assert result.extracted_content is None
