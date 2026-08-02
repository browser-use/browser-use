"""Regression tests for Groq structured-output extraction.

See https://github.com/browser-use/browser-use/issues/4945: models in
``ToolCallingModels`` return ``message.content = None`` and place the structured
JSON in ``tool_calls[0].function.arguments``. ``_invoke_structured_output`` must
read from the tool call on that path instead of unconditionally requiring
``message.content`` (which previously always raised ``ModelProviderError``).
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel

from browser_use.llm.groq.chat import ChatGroq, ToolCallingModels


class _Output(BaseModel):
	value: str


def _tool_call_response(arguments: str) -> MagicMock:
	"""Build a ChatCompletion-like mock for a tool-calling reply (content=None)."""
	tool_call = MagicMock()
	tool_call.function.arguments = arguments

	message = MagicMock()
	message.content = None
	message.tool_calls = [tool_call]

	choice = MagicMock()
	choice.message = message

	response = MagicMock()
	response.choices = [choice]
	response.usage = None
	return response


def test_extract_tool_call_arguments_prefers_tool_calls():
	response = _tool_call_response('{"value": "from-tool-call"}')
	assert ChatGroq._extract_tool_call_arguments(response) == '{"value": "from-tool-call"}'


def test_extract_tool_call_arguments_falls_back_to_content():
	response = _tool_call_response('{"value": "x"}')
	response.choices[0].message.tool_calls = []
	response.choices[0].message.content = '{"value": "from-content"}'
	assert ChatGroq._extract_tool_call_arguments(response) == '{"value": "from-content"}'


@pytest.mark.asyncio
async def test_structured_output_reads_tool_calls_for_tool_calling_models():
	"""Tool-calling models must not raise 'No content in response' (issue #4945)."""
	chat = ChatGroq(model=ToolCallingModels[0], api_key='test-key')
	chat._invoke_with_tool_calling = AsyncMock(return_value=_tool_call_response('{"value": "ok"}'))

	result = await chat._invoke_structured_output([], _Output)

	assert result.completion == _Output(value='ok')
	chat._invoke_with_tool_calling.assert_awaited_once()
