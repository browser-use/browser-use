from unittest.mock import AsyncMock, Mock

import pytest

from browser_use.agent.views import ActionResult
from browser_use.tools.service import Tools


class AwaitableEvent:
	def __init__(self, result: str | None) -> None:
		self.event_result = AsyncMock(return_value=result)

	def __await__(self):
		async def wait() -> 'AwaitableEvent':
			return self

		return wait().__await__()


@pytest.mark.asyncio
async def test_switch_returns_error_when_tab_id_is_invalid() -> None:
	tools = Tools()
	browser_session = Mock()
	browser_session.get_target_id_from_tab_id = AsyncMock(side_effect=ValueError('unknown tab'))

	result = await tools.switch(tab_id='zzzz', browser_session=browser_session)

	assert isinstance(result, ActionResult)
	assert result.error == 'Failed to switch to tab #zzzz: unknown tab'
	assert result.extracted_content is None


@pytest.mark.asyncio
async def test_switch_returns_error_when_event_does_not_activate_target() -> None:
	tools = Tools()
	browser_session = Mock()
	browser_session.get_target_id_from_tab_id = AsyncMock(return_value='target-id')
	event = AwaitableEvent(None)
	browser_session.event_bus.dispatch.return_value = event

	result = await tools.switch(tab_id='1234', browser_session=browser_session)

	assert isinstance(result, ActionResult)
	assert result.error == 'Failed to switch to tab #1234: no target was activated'
	assert result.extracted_content is None


@pytest.mark.asyncio
async def test_switch_reports_activated_target() -> None:
	tools = Tools()
	browser_session = Mock()
	browser_session.get_target_id_from_tab_id = AsyncMock(return_value='target-id1234')
	event = AwaitableEvent('target-id5678')
	browser_session.event_bus.dispatch.return_value = event

	result = await tools.switch(tab_id='1234', browser_session=browser_session)

	assert result.error is None
	assert result.extracted_content == 'Switched to tab #5678'
