"""Tests for Azure OpenAI Responses API support."""

import os
from typing import Any

import pytest
from openai.types.responses import Response
from pydantic import BaseModel

from browser_use.llm.azure.chat import RESPONSES_API_ONLY_MODELS, ChatAzureOpenAI
from browser_use.llm.exceptions import ModelProviderError
from browser_use.llm.messages import (
	AssistantMessage,
	ContentPartImageParam,
	ContentPartTextParam,
	Function,
	ImageURL,
	SystemMessage,
	ToolCall,
	UserMessage,
)
from browser_use.llm.openai.responses_serializer import ResponsesAPIMessageSerializer


class TestResponsesAPIMessageSerializer:
	"""Tests for the ResponsesAPIMessageSerializer class."""

	def test_serialize_user_message_string_content(self):
		"""Test serializing a user message with string content."""
		message = UserMessage(content='Hello, world!')
		result = ResponsesAPIMessageSerializer.serialize(message)

		assert result['role'] == 'user'
		assert result['content'] == 'Hello, world!'

	def test_serialize_user_message_text_parts(self):
		"""Test serializing a user message with text content parts."""
		message = UserMessage(
			content=[
				ContentPartTextParam(type='text', text='First part'),
				ContentPartTextParam(type='text', text='Second part'),
			]
		)
		result = ResponsesAPIMessageSerializer.serialize(message)

		assert result['role'] == 'user'
		assert isinstance(result['content'], list)
		assert len(result['content']) == 2
		assert result['content'][0]['type'] == 'input_text'
		assert result['content'][0]['text'] == 'First part'
		assert result['content'][1]['type'] == 'input_text'
		assert result['content'][1]['text'] == 'Second part'

	def test_serialize_user_message_with_image(self):
		"""Test serializing a user message with image content."""
		message = UserMessage(
			content=[
				ContentPartTextParam(type='text', text='What is in this image?'),
				ContentPartImageParam(
					type='image_url',
					image_url=ImageURL(url='https://example.com/image.png', detail='auto'),
				),
			]
		)
		result = ResponsesAPIMessageSerializer.serialize(message)

		assert result['role'] == 'user'
		assert isinstance(result['content'], list)
		assert len(result['content']) == 2
		assert result['content'][0]['type'] == 'input_text'
		assert result['content'][1]['type'] == 'input_image'
		assert result['content'][1].get('image_url') == 'https://example.com/image.png'
		assert result['content'][1].get('detail') == 'auto'

	def test_serialize_system_message_string_content(self):
		"""Test serializing a system message with string content."""
		message = SystemMessage(content='You are a helpful assistant.')
		result = ResponsesAPIMessageSerializer.serialize(message)

		assert result['role'] == 'system'
		assert result['content'] == 'You are a helpful assistant.'

	def test_serialize_system_message_text_parts(self):
		"""Test serializing a system message with text content parts."""
		message = SystemMessage(content=[ContentPartTextParam(type='text', text='System instruction')])
		result = ResponsesAPIMessageSerializer.serialize(message)

		assert result['role'] == 'system'
		assert isinstance(result['content'], list)
		assert len(result['content']) == 1
		assert result['content'][0]['type'] == 'input_text'

	def test_serialize_assistant_message_string_content(self):
		"""Test serializing an assistant message with string content."""
		message = AssistantMessage(content='Here is my response.')
		result = ResponsesAPIMessageSerializer.serialize(message)

		assert result['role'] == 'assistant'
		assert result['content'] == 'Here is my response.'

	def test_serialize_assistant_message_none_content_with_tool_calls(self):
		"""Test serializing an assistant message with None content and tool calls."""
		message = AssistantMessage(
			content=None,
			tool_calls=[
				ToolCall(
					id='call_123',
					type='function',
					function=Function(name='search', arguments='{"query": "test"}'),
				)
			],
		)
		result = ResponsesAPIMessageSerializer.serialize(message)

		assert result['role'] == 'assistant'
		assert '[Tool call: search({"query": "test"})]' in result['content']

	def test_serialize_assistant_message_none_content_no_tool_calls(self):
		"""Test serializing an assistant message with None content and no tool calls."""
		message = AssistantMessage(content=None)
		result = ResponsesAPIMessageSerializer.serialize(message)

		assert result['role'] == 'assistant'
		assert result['content'] == ''

	def test_serialize_messages_list(self):
		"""Test serializing a list of messages."""
		messages = [
			SystemMessage(content='You are helpful.'),
			UserMessage(content='Hello!'),
			AssistantMessage(content='Hi there!'),
		]
		results = ResponsesAPIMessageSerializer.serialize_messages(messages)

		assert len(results) == 3
		assert results[0]['role'] == 'system'
		assert results[1]['role'] == 'user'
		assert results[2]['role'] == 'assistant'


class TestChatAzureOpenAIShouldUseResponsesAPI:
	"""Tests for the _should_use_responses_api method."""

	def test_use_responses_api_true(self):
		"""Test that use_responses_api=True forces Responses API."""
		llm = ChatAzureOpenAI(
			model='gpt-4o',
			api_key='test',
			azure_endpoint='https://test.openai.azure.com',
			use_responses_api=True,
		)
		assert llm._should_use_responses_api() is True

	def test_use_responses_api_false(self):
		"""Test that use_responses_api=False forces Chat Completions API."""
		llm = ChatAzureOpenAI(
			model='gpt-5.1-codex-mini',  # Even with a Responses-only model
			api_key='test',
			azure_endpoint='https://test.openai.azure.com',
			use_responses_api=False,
		)
		assert llm._should_use_responses_api() is False

	def test_use_responses_api_auto_with_responses_only_model(self):
		"""Test that auto mode detects Responses-only models."""
		for model_name in RESPONSES_API_ONLY_MODELS:
			llm = ChatAzureOpenAI(
				model=model_name,
				api_key='test',
				azure_endpoint='https://test.openai.azure.com',
				use_responses_api='auto',
			)
			assert llm._should_use_responses_api() is True, f'Expected Responses API for {model_name}'

	def test_use_responses_api_auto_with_regular_model(self):
		"""Test that auto mode uses Chat Completions for regular models."""
		regular_models = ['gpt-4o', 'gpt-4.1-mini', 'gpt-3.5-turbo', 'gpt-4']
		for model_name in regular_models:
			llm = ChatAzureOpenAI(
				model=model_name,
				api_key='test',
				azure_endpoint='https://test.openai.azure.com',
				use_responses_api='auto',
			)
			assert llm._should_use_responses_api() is False, f'Expected Chat Completions for {model_name}'

	def test_use_responses_api_auto_is_default(self):
		"""Test that 'auto' is the default value for use_responses_api."""
		llm = ChatAzureOpenAI(
			model='gpt-4o',
			api_key='test',
			azure_endpoint='https://test.openai.azure.com',
		)
		assert llm.use_responses_api == 'auto'

	def test_responses_api_only_models_list(self):
		"""Test that the RESPONSES_API_ONLY_MODELS list contains expected models."""
		expected_models = [
			'gpt-5.1-codex',
			'gpt-5.1-codex-mini',
			'gpt-5.1-codex-max',
			'gpt-5-codex',
			'codex-mini-latest',
			'computer-use-preview',
		]
		for model in expected_models:
			assert model in RESPONSES_API_ONLY_MODELS, f'{model} should be in RESPONSES_API_ONLY_MODELS'


class TestChatAzureOpenAIIntegration:
	"""Integration tests for Azure OpenAI with Responses API.

	These tests require valid Azure OpenAI credentials and are skipped if not available.
	"""

	@pytest.fixture
	def azure_credentials(self):
		"""Get Azure OpenAI credentials from environment."""
		api_key = os.getenv('AZURE_OPENAI_KEY') or os.getenv('AZURE_OPENAI_API_KEY')
		endpoint = os.getenv('AZURE_OPENAI_ENDPOINT')
		if not api_key or not endpoint:
			pytest.skip('Azure OpenAI credentials not available')
		return {'api_key': api_key, 'azure_endpoint': endpoint}

	async def test_chat_completions_api_basic_call(self, azure_credentials):
		"""Test basic call using Chat Completions API."""
		llm = ChatAzureOpenAI(
			model='gpt-4.1-mini',
			api_key=azure_credentials['api_key'],
			azure_endpoint=azure_credentials['azure_endpoint'],
			use_responses_api=False,  # Force Chat Completions API
		)

		messages = [
			SystemMessage(content='You are a helpful assistant.'),
			UserMessage(content='Say "hello" and nothing else.'),
		]

		result = await llm.ainvoke(messages)
		assert result.completion is not None
		assert 'hello' in result.completion.lower()

	async def test_responses_api_basic_call(self, azure_credentials):
		"""Test basic call using Responses API.

		This test only runs if the Azure deployment supports the Responses API
		(api_version >= 2025-03-01-preview).
		"""
		llm = ChatAzureOpenAI(
			model='gpt-4.1-mini',
			api_key=azure_credentials['api_key'],
			azure_endpoint=azure_credentials['azure_endpoint'],
			api_version='2025-03-01-preview',  # Required for Responses API
			use_responses_api=True,  # Force Responses API
		)

		messages = [
			SystemMessage(content='You are a helpful assistant.'),
			UserMessage(content='Say "hello" and nothing else.'),
		]

		try:
			result = await llm.ainvoke(messages)
			assert result.completion is not None
			assert 'hello' in result.completion.lower()
		except Exception as e:
			# Skip if Responses API is not supported
			if 'Responses API' in str(e) or '404' in str(e):
				pytest.skip('Responses API not supported by this Azure deployment')
			raise


class _Answer(BaseModel):
	answer: str


def _message(number: int, *parts: str) -> dict[str, Any]:
	"""One output message whose content is one output_text part per text."""
	content = []
	for text in parts:
		content.append({'type': 'output_text', 'text': text, 'annotations': []})
	return {'type': 'message', 'id': f'msg_{number}', 'role': 'assistant', 'status': 'completed', 'content': content}


def _response(*output: dict[str, Any]) -> Response:
	"""A Responses API response with the given output items."""
	return Response.model_validate(
		{
			'id': 'resp_1',
			'created_at': 0,
			'model': 'test-model',
			'object': 'response',
			'output': list(output),
			'parallel_tool_calls': False,
			'tool_choice': 'auto',
			'tools': [],
		}
	)


def _response_with_messages(*texts: str) -> Response:
	"""A Responses API response whose output is one message per text."""
	output = []
	for number, text in enumerate(texts):
		output.append(_message(number, text))
	return _response(*output)


class _FakeResponses:
	def __init__(self, response: Response):
		self.response = response

	async def create(self, **params: Any) -> Response:
		return self.response


class _FakeClient:
	def __init__(self, response: Response):
		self.responses = _FakeResponses(response)


def _llm_returning(response: Response) -> ChatAzureOpenAI:
	llm = ChatAzureOpenAI(
		model='test-model',
		api_key='test',
		azure_endpoint='https://test.openai.azure.com',
		use_responses_api=True,
	)
	llm.client = _FakeClient(response)  # type: ignore[assignment]
	return llm


class TestResponsesAPIStructuredOutput:
	"""Structured output when the model returns more than one output message."""

	async def test_single_message(self):
		llm = _llm_returning(_response_with_messages('{"answer": "42"}'))

		result = await llm.ainvoke([UserMessage(content='q')], output_format=_Answer)

		assert result.completion == _Answer(answer='42')

	async def test_text_before_the_json_message(self):
		llm = _llm_returning(_response_with_messages('Let me check that.', '{"answer": "42"}'))

		result = await llm.ainvoke([UserMessage(content='q')], output_format=_Answer)

		assert result.completion == _Answer(answer='42')

	async def test_first_valid_message_wins(self):
		llm = _llm_returning(_response_with_messages('{"answer": "first"}', '{"answer": "second"}'))

		result = await llm.ainvoke([UserMessage(content='q')], output_format=_Answer)

		assert result.completion == _Answer(answer='first')

	async def test_text_after_the_json_message(self):
		llm = _llm_returning(_response_with_messages('{"answer": "42"}', 'I will now click the button.'))

		result = await llm.ainvoke([UserMessage(content='q')], output_format=_Answer)

		assert result.completion == _Answer(answer='42')

	async def test_parts_of_one_message_are_joined(self):
		# One message whose JSON is split across two output_text parts.
		response = _response(_message(0, '{"answer": ', '"42"}'))
		llm = _llm_returning(response)

		result = await llm.ainvoke([UserMessage(content='q')], output_format=_Answer)

		assert ChatAzureOpenAI._output_message_texts(response) == ['{"answer": "42"}']
		assert result.completion == _Answer(answer='42')

	async def test_non_message_items_are_skipped(self):
		function_call = {
			'type': 'function_call',
			'id': 'fc_1',
			'call_id': 'call_1',
			'name': 'lookup',
			'arguments': '{"answer": "not this"}',
			'status': 'completed',
		}
		response = _response(function_call, _message(1, '{"answer": "42"}'))
		llm = _llm_returning(response)

		result = await llm.ainvoke([UserMessage(content='q')], output_format=_Answer)

		assert ChatAzureOpenAI._output_message_texts(response) == ['{"answer": "42"}']
		assert result.completion == _Answer(answer='42')

	async def test_joined_text_is_parsed_when_no_single_message_validates(self):
		# Neither message is valid JSON on its own, but response.output_text (all of them joined) is.
		response = _response_with_messages('{"answer": ', '"42"}')
		llm = _llm_returning(response)

		result = await llm.ainvoke([UserMessage(content='q')], output_format=_Answer)

		assert response.output_text == '{"answer": "42"}'
		assert result.completion == _Answer(answer='42')

	async def test_no_valid_message_still_raises(self):
		llm = _llm_returning(_response_with_messages('not json', 'still not json'))

		with pytest.raises(ModelProviderError):
			await llm.ainvoke([UserMessage(content='q')], output_format=_Answer)
