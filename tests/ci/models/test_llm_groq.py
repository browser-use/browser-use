"""Test ChatGroq structured output for tool-calling and JSON-schema paths."""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel


class DummyOutput(BaseModel):
	answer: str


class TestChatGroqStructuredOutput:
	@pytest.mark.asyncio
	async def test_tool_calling_path_returns_parsed_output(self):
		"""ToolCallingModels return content=None; JSON lives in tool_calls[0].function.arguments."""
		from browser_use.llm.groq.chat import ChatGroq

		chat = ChatGroq(model='moonshotai/kimi-k2-instruct')

		mock_tool_call = MagicMock()
		mock_tool_call.function.arguments = '{"answer": "42"}'

		mock_message = MagicMock()
		mock_message.content = None
		mock_message.tool_calls = [mock_tool_call]

		mock_choice = MagicMock()
		mock_choice.message = mock_message

		mock_completion = MagicMock()
		mock_completion.choices = [mock_choice]
		mock_completion.usage = None

		with patch.object(chat, '_invoke_with_tool_calling', return_value=mock_completion):
			result = await chat._invoke_structured_output([], DummyOutput)

		assert result.completion.answer == '42'

	@pytest.mark.asyncio
	async def test_json_schema_path_returns_parsed_output(self):
		"""JsonSchemaModels return structured JSON in message.content."""
		from browser_use.llm.groq.chat import ChatGroq

		chat = ChatGroq(model='meta-llama/llama-4-scout-17b-16e-instruct')

		mock_message = MagicMock()
		mock_message.content = '{"answer": "hello"}'
		mock_message.tool_calls = None

		mock_choice = MagicMock()
		mock_choice.message = mock_message

		mock_completion = MagicMock()
		mock_completion.choices = [mock_choice]
		mock_completion.usage = None

		with patch.object(chat, '_invoke_with_json_schema', return_value=mock_completion):
			result = await chat._invoke_structured_output([], DummyOutput)

		assert result.completion.answer == 'hello'

	@pytest.mark.asyncio
	async def test_tool_calling_path_raises_when_arguments_missing(self):
		from browser_use.llm.exceptions import ModelProviderError
		from browser_use.llm.groq.chat import ChatGroq

		chat = ChatGroq(model='moonshotai/kimi-k2-instruct')

		mock_message = MagicMock()
		mock_message.content = None
		mock_message.tool_calls = []

		mock_choice = MagicMock()
		mock_choice.message = mock_message

		mock_completion = MagicMock()
		mock_completion.choices = [mock_choice]

		with patch.object(chat, '_invoke_with_tool_calling', return_value=mock_completion):
			with pytest.raises(ModelProviderError, match='No tool call arguments in response'):
				await chat._invoke_structured_output([], DummyOutput)
