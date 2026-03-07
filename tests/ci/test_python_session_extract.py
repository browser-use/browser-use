import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from browser_use.agent.views import ActionResult
from browser_use.skill_cli.python_session import BrowserWrapper


@pytest.mark.asyncio
async def test_browser_wrapper_extract_returns_structured_data(monkeypatch):
	loop = asyncio.get_running_loop()
	wrapper = BrowserWrapper(session=MagicMock(), loop=loop)

	mock_llm = object()
	mock_extract = AsyncMock(
		return_value=ActionResult(
			extracted_content='<structured_result>{"title":"Example"}</structured_result>',
			metadata={'extraction_result': {'data': {'title': 'Example'}}},
		)
	)

	class StubTools:
		def __init__(self) -> None:
			self.extract = mock_extract

	monkeypatch.setattr('browser_use.skill_cli.commands.agent.get_llm', lambda model=None: mock_llm)
	monkeypatch.setattr('browser_use.tools.service.Tools', StubTools)

	result = await wrapper._extract_async(
		query='Extract the title',
		output_schema={'type': 'object', 'properties': {'title': {'type': 'string'}}},
	)

	assert result == {'title': 'Example'}
	mock_extract.assert_awaited_once()


@pytest.mark.asyncio
async def test_browser_wrapper_extract_raises_when_no_llm(monkeypatch):
	loop = asyncio.get_running_loop()
	wrapper = BrowserWrapper(session=MagicMock(), loop=loop)

	monkeypatch.setattr('browser_use.skill_cli.commands.agent.get_llm', lambda model=None: None)

	with pytest.raises(RuntimeError, match='No LLM configured for browser.extract'):
		await wrapper._extract_async(query='Extract page summary')
