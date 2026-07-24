"""Test ChatGroq structured output via tool-calling path."""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel


class DummyOutput(BaseModel):
	answer: str


class TestChatGroqToolCallingStructuredOutput:
	"""Test that _invoke_structured_output correctly reads tool_calls when model uses tool-calling path."""

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
