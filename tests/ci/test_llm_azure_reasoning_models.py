"""Test for Azure OpenAI reasoning model compatibility fix (#2990)"""

import pytest

from browser_use.llm.azure.chat import ChatAzureOpenAI
from browser_use.llm.messages import BaseMessage, UserMessage


@pytest.mark.asyncio
async def test_azure_openai_reasoning_model_parameter_filtering(monkeypatch):
	"""Test that ChatAzureOpenAI filters out reasoning_effort parameter for Azure OpenAI API"""

	# Create Azure OpenAI instance with reasoning model
	chat = ChatAzureOpenAI(
		model='gpt-5-chat',  # This triggers reasoning model logic
		api_key='test-key',
		azure_endpoint='https://test.openai.azure.com',
		azure_deployment='gpt-5-chat',
		service_tier='auto',  # This should be filtered out for Azure
	)

	# Create test messages
	messages: list[BaseMessage] = [UserMessage(content='Test message')]

	# Track the parameters passed to the API call
	captured_params = {}

	class MockClient:
		class Chat:
			class Completions:
				async def create(self, **kwargs):
					# Capture all parameters for inspection
					captured_params.update(kwargs)

					# Mock successful response
					from types import SimpleNamespace

					response = SimpleNamespace()
					response.choices = [SimpleNamespace()]
					response.choices[0].message = SimpleNamespace()
					response.choices[0].message.content = 'Test response'
					response.usage = SimpleNamespace()
					response.usage.prompt_tokens = 10
					response.usage.completion_tokens = 5
					response.usage.total_tokens = 15
					response.usage.prompt_tokens_details = None
					response.usage.completion_tokens_details = None

					return response

			completions = Completions()

		chat = Chat()

	# Replace the client with our mock
	monkeypatch.setattr(chat, 'get_client', lambda: MockClient())

	# Execute the call
	result = await chat.ainvoke(messages)

	# Verify that reasoning_effort parameter was NOT passed to Azure API
	assert 'reasoning_effort' not in captured_params, 'reasoning_effort parameter should be filtered out for Azure OpenAI'

	# Verify that service_tier parameter was NOT passed to Azure API
	assert 'service_tier' not in captured_params, 'service_tier parameter should be filtered out for Azure OpenAI'

	# Verify that standard parameters are still included
	assert captured_params.get('model') == 'gpt-5-chat'
	assert 'messages' in captured_params

	# For reasoning models, temperature and frequency_penalty should be removed
	assert 'temperature' not in captured_params, 'temperature should be removed for reasoning models'
	assert 'frequency_penalty' not in captured_params, 'frequency_penalty should be removed for reasoning models'

	# Verify the response was properly handled
	assert result.completion == 'Test response'
	assert result.usage is not None
	assert result.usage.total_tokens == 15


@pytest.mark.asyncio
async def test_azure_openai_non_reasoning_model_parameters(monkeypatch):
	"""Test that non-reasoning models retain temperature/frequency_penalty but still filter Azure-specific params"""

	# Create Azure OpenAI instance with NON-reasoning model
	chat = ChatAzureOpenAI(
		model='gpt-4o',  # This is NOT a reasoning model
		api_key='test-key',
		azure_endpoint='https://test.openai.azure.com',
		azure_deployment='gpt-4o',
		temperature=0.7,
		frequency_penalty=0.5,
		service_tier='auto',  # This should still be filtered out for Azure
	)

	messages: list[BaseMessage] = [UserMessage(content='Test message')]
	captured_params = {}

	class MockClient:
		class Chat:
			class Completions:
				async def create(self, **kwargs):
					captured_params.update(kwargs)

					from types import SimpleNamespace

					response = SimpleNamespace()
					response.choices = [SimpleNamespace()]
					response.choices[0].message = SimpleNamespace()
					response.choices[0].message.content = 'Test response'
					response.usage = SimpleNamespace()
					response.usage.prompt_tokens = 10
					response.usage.completion_tokens = 5
					response.usage.total_tokens = 15
					response.usage.prompt_tokens_details = None
					response.usage.completion_tokens_details = None

					return response

			completions = Completions()

		chat = Chat()

	monkeypatch.setattr(chat, 'get_client', lambda: MockClient())

	# Execute the call
	result = await chat.ainvoke(messages)

	# Verify Azure-specific parameters are still filtered
	assert 'reasoning_effort' not in captured_params
	assert 'service_tier' not in captured_params

	# Verify standard parameters for non-reasoning models are preserved
	assert captured_params.get('temperature') == 0.7
	assert captured_params.get('frequency_penalty') == 0.5

	assert result.completion == 'Test response'


@pytest.mark.asyncio
async def test_azure_openai_structured_output_fallback(monkeypatch):
	"""Test that structured output falls back to string output for Azure compatibility"""

	from pydantic import BaseModel

	class TestModel(BaseModel):
		result: str

	chat = ChatAzureOpenAI(model='gpt-4o', api_key='test-key', azure_endpoint='https://test.openai.azure.com')

	messages: list[BaseMessage] = [UserMessage(content='Test message')]

	# Mock the parent class ainvoke method
	async def mock_parent_ainvoke(self, messages, output_format):
		from browser_use.llm.views import ChatInvokeCompletion

		return ChatInvokeCompletion(completion='{"result": "test"}', usage=None)

	monkeypatch.setattr(chat.__class__.__bases__[0], 'ainvoke', mock_parent_ainvoke)

	# Execute with structured output - should fallback to string
	result = await chat.ainvoke(messages, output_format=TestModel)

	# Verify it returns a string completion (fallback behavior)
	assert result.completion == '{"result": "test"}'
