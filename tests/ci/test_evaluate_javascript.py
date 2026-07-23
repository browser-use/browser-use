from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from browser_use.tools.service import Tools


@pytest.mark.parametrize(
	'code',
	[
		r'JSON.parse("{\"path\":\"C:\\\\temp\\\\report.json\"}")',
		r'(() => /^C:\\temp\\files$/.test("C:\\temp\\files"))()',
		r'document.querySelector("[data-label=\"Save\"]")',
	],
	ids=['escaped-json', 'regex-backslashes', 'escaped-selector'],
)
async def test_evaluate_sends_valid_javascript_to_cdp_unchanged(code: str):
	runtime_evaluate = AsyncMock(return_value={'result': {'value': True}})
	cdp_session = SimpleNamespace(
		cdp_client=SimpleNamespace(send=SimpleNamespace(Runtime=SimpleNamespace(evaluate=runtime_evaluate))),
		session_id='test-session',
	)
	browser_session = SimpleNamespace(
		cdp_client=cdp_session.cdp_client,
		get_or_create_cdp_session=AsyncMock(return_value=cdp_session),
	)

	result = await Tools().evaluate(code=code, browser_session=browser_session)

	assert result.error is None
	runtime_evaluate.assert_awaited_once_with(
		params={'expression': code, 'returnByValue': True, 'awaitPromise': True},
		session_id='test-session',
	)
