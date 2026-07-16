"""Tests for the ChatGroq structured-output paths."""

from unittest.mock import AsyncMock, patch

import pytest
from groq.types.chat import ChatCompletion, ChatCompletionMessage, ChatCompletionMessageToolCall
from groq.types.chat.chat_completion import Choice
from groq.types.chat.chat_completion_message_tool_call import Function
from pydantic import BaseModel

from browser_use.llm.exceptions import ModelProviderError
from browser_use.llm.groq.chat import ChatGroq, ToolCallingModels
from browser_use.llm.messages import UserMessage

# A syntactically-valid key so the constructor doesn't bail before we reach the
# code under test. These unit tests never hit the network.
TEST_API_KEY = 'test-key-not-real'

TOOL_CALLING_MODEL = ToolCallingModels[0]


class Answer(BaseModel):
	answer: str


def _completion(model: str, *, content: str | None, tool_arguments: str | None) -> ChatCompletion:
	"""Build a Groq ChatCompletion with either message content or tool-call arguments."""
	tool_calls = None
	if tool_arguments is not None:
		tool_calls = [
			ChatCompletionMessageToolCall(
				id='call_1',
				type='function',
				function=Function(name='Answer', arguments=tool_arguments),
			)
		]

	message = ChatCompletionMessage(role='assistant', content=content, tool_calls=tool_calls)
	return ChatCompletion(
		id='chatcmpl-test',
		choices=[Choice(finish_reason='tool_calls' if tool_calls else 'stop', index=0, message=message)],
		created=0,
		model=model,
		object='chat.completion',
	)


async def _ainvoke(llm: ChatGroq, response: ChatCompletion):
	create = AsyncMock(return_value=response)
	with patch.object(type(llm.get_client().chat.completions), 'create', create):
		return await llm.ainvoke([UserMessage(content='question')], Answer)


async def test_tool_calling_model_parses_arguments():
	"""Tool-calling models return the payload in tool_calls with content=None (see #4945)."""
	llm = ChatGroq(model=TOOL_CALLING_MODEL, api_key=TEST_API_KEY)
	response = _completion(TOOL_CALLING_MODEL, content=None, tool_arguments='{"answer": "42"}')

	result = await _ainvoke(llm, response)

	assert result.completion == Answer(answer='42')


async def test_tool_calling_model_without_tool_calls_raises():
	"""An empty tool-call list is a provider error, not an unpacking crash."""
	llm = ChatGroq(model=TOOL_CALLING_MODEL, api_key=TEST_API_KEY)
	response = _completion(TOOL_CALLING_MODEL, content=None, tool_arguments=None)

	with pytest.raises(ModelProviderError, match='No tool calls in response'):
		await _ainvoke(llm, response)


async def test_json_schema_model_parses_content():
	"""Models outside ToolCallingModels still read the payload from message content."""
	model = 'llama-3.3-70b-versatile'
	assert model not in ToolCallingModels
	llm = ChatGroq(model=model, api_key=TEST_API_KEY)
	response = _completion(model, content='{"answer": "42"}', tool_arguments=None)

	result = await _ainvoke(llm, response)

	assert result.completion == Answer(answer='42')


async def test_json_schema_model_without_content_raises():
	"""The content guard still applies on the JSON-schema path."""
	model = 'llama-3.3-70b-versatile'
	llm = ChatGroq(model=model, api_key=TEST_API_KEY)
	response = _completion(model, content=None, tool_arguments=None)

	with pytest.raises(ModelProviderError, match='No content in response'):
		await _ainvoke(llm, response)
