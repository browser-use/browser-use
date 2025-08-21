"""Test for handling Anthropic 502 errors"""

import pytest
from anthropic import APIStatusError

from browser_use.llm.anthropic.chat import ChatAnthropic
from browser_use.llm.exceptions import ModelProviderError
from browser_use.llm.messages import BaseMessage, UserMessage


@pytest.mark.asyncio
async def test_anthropic_502_error_handling(monkeypatch):
	"""Test that ChatAnthropic properly handles 502 errors from the API"""
	# Create a ChatAnthropic instance
	chat = ChatAnthropic(model='claude-3-5-sonnet-20240620', api_key='test-key')

	# Create test messages
	messages: list[BaseMessage] = [UserMessage(content='Test message')]

	# Mock the client to raise a 502 error
	class MockClient:
		class Messages:
			async def create(self, **kwargs):
				# Simulate a 502 error from Anthropic API
				import httpx

				request = httpx.Request('POST', 'https://api.anthropic.com/v1/messages')
				response = httpx.Response(status_code=502, headers={}, content=b'Bad Gateway', request=request)
				raise APIStatusError(
					message='Bad Gateway', response=response, body={'error': {'message': 'Bad Gateway', 'type': 'server_error'}}
				)

		messages = Messages()

	# Replace the client with our mock
	monkeypatch.setattr(chat, 'get_client', lambda: MockClient())

	# Test that the error is properly caught and re-raised as ModelProviderError
	with pytest.raises(ModelProviderError) as exc_info:
		await chat.ainvoke(messages)

	# Verify the error details
	assert exc_info.value.args[0] == 'Bad Gateway'
	assert exc_info.value.args[1] == 502
	assert str(exc_info.value) == "('Bad Gateway', 502)"


@pytest.mark.asyncio
async def test_anthropic_error_does_not_access_usage(monkeypatch):
	"""Test that error handling doesn't try to access usage attribute on error responses"""
	chat = ChatAnthropic(model='claude-3-5-sonnet-20240620', api_key='test-key')

	messages: list[BaseMessage] = [UserMessage(content='Test message')]

	# Mock the client to return a string instead of a proper response
	class MockClient:
		class Messages:
			async def create(self, **kwargs):
				# This simulates what might happen if the API returns an unexpected response
				# that gets parsed as a string
				return 'Error: Bad Gateway'

		messages = Messages()

	monkeypatch.setattr(chat, 'get_client', lambda: MockClient())

	# This should raise a ModelProviderError with a clear message
	with pytest.raises(ModelProviderError) as exc_info:
		await chat.ainvoke(messages)

	# The error should be about unexpected response type, not missing 'usage' attribute
	assert "'str' object has no attribute 'usage'" not in str(exc_info.value)
	assert 'Unexpected response type from Anthropic API' in str(exc_info.value)
	assert exc_info.value.args[1] == 502
