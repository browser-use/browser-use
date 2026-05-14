from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from browser_use.tools.service import Tools


class AwaitableEvent:
	def __init__(self, result=None):
		self._result = result

	def __await__(self):
		async def _wait():
			return self

		return _wait().__await__()

	async def event_result(self, *args, **kwargs):
		return self._result


@pytest.mark.asyncio
async def test_send_keys_reports_new_tab():
	tools = Tools()
	browser_session = MagicMock()
	browser_session.get_current_page_url = AsyncMock(return_value='https://example.com')
	browser_session.cdp_client = None
	browser_session.get_tabs = AsyncMock(
		side_effect=[
			[SimpleNamespace(target_id='tab-before')],
			[SimpleNamespace(target_id='tab-before'), SimpleNamespace(target_id='tab-after')],
		]
	)
	browser_session.event_bus.dispatch.return_value = AwaitableEvent()

	result = await tools.registry.execute_action(
		action_name='send_keys',
		params={'keys': 'Enter'},
		browser_session=browser_session,
	)

	assert result.extracted_content == 'Sent keys: Enter. Automatically switched to new tab (tab_id: fter).'
	assert result.long_term_memory == result.extracted_content
