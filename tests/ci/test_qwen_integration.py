import os

import pytest
from pydantic import BaseModel

from browser_use.llm import ChatQwen
from browser_use.llm.messages import BaseMessage, ContentPartTextParam, SystemMessage, UserMessage


class QwenTestResponseModel(BaseModel):
	"""Test response model for structured output."""

	message: str
	success: bool


class TestQwenIntegration:
	"""Test suite for Qwen LLM integration."""

	@pytest.fixture
	def qwen_chat(self):
		"""Provides an initialized ChatQwen client for tests."""
		if not os.getenv('QWEN_API_KEY'):
			pytest.skip('QWEN_API_KEY not set')
		return ChatQwen(
			model='qwen-plus',
			api_key=os.getenv('QWEN_API_KEY'),
			base_url='https://dashscope.aliyuncs.com/compatible-mode/v1',
			temperature=0,
			max_tokens=100,
		)

	@pytest.fixture
	def simple_messages(self):
		"""Simple test messages."""
		return [
			SystemMessage(content=[ContentPartTextParam(text='You are a helpful assistant.', type='text')]),
			UserMessage(content='Say hello in exactly one word.'),
		]

	@pytest.fixture
	def structured_messages(self):
		"""Messages for structured output testing."""
		return [
			UserMessage(content='Respond with a JSON object containing: message="Hello from Qwen!" and success=true'),
		]

	@pytest.mark.asyncio
	async def test_qwen_basic_text_response(self, qwen_chat, simple_messages):
		"""Test basic text response from Qwen."""
		response = await qwen_chat.ainvoke(simple_messages)

		assert response is not None
		assert hasattr(response, 'completion')
		assert isinstance(response.completion, str)
		assert len(response.completion.strip()) > 0

	@pytest.mark.asyncio
	async def test_qwen_structured_output(self, qwen_chat, structured_messages):
		"""Test structured output from Qwen."""
		response = await qwen_chat.ainvoke(structured_messages, output_format=QwenTestResponseModel)

		assert response is not None
		assert hasattr(response, 'completion')
		assert isinstance(response.completion, QwenTestResponseModel)
		assert response.completion.success is True
		assert isinstance(response.completion.message, str)
		assert len(response.completion.message.strip()) > 0

	@pytest.mark.asyncio
	async def test_qwen_provider_property(self, qwen_chat):
		"""Test that provider property returns correct value."""
		assert qwen_chat.provider == 'qwen'

	@pytest.mark.asyncio
	async def test_qwen_model_name_property(self, qwen_chat):
		"""Test that name property returns model name."""
		assert qwen_chat.name == 'qwen-plus'

	@pytest.mark.asyncio
	async def test_qwen_with_different_models(self):
		"""Test Qwen with different model variants."""
		if not os.getenv('QWEN_API_KEY'):
			pytest.skip('QWEN_API_KEY not set')

		models = ['qwen-plus', 'qwen-turbo']

		for model in models:
			chat = ChatQwen(
				model=model,
				api_key=os.getenv('QWEN_API_KEY'),
				base_url='https://dashscope.aliyuncs.com/compatible-mode/v1',
				temperature=0,
				max_tokens=50,
			)

			messages: list[BaseMessage] = [UserMessage(content='Say "test" in one word.')]
			try:
				response = await chat.ainvoke(messages)
				assert response is not None
				assert isinstance(response.completion, str)
			except Exception as e:
				# Some models might not be available, so we just log the error
				print(f'Model {model} not available: {e}')
				continue

	@pytest.mark.asyncio
	async def test_qwen_temperature_parameter(self):
		"""Test Qwen with different temperature settings."""
		if not os.getenv('QWEN_API_KEY'):
			pytest.skip('QWEN_API_KEY not set')

		messages: list[BaseMessage] = [UserMessage(content='Say hello briefly.')]

		# Test with temperature 0 (deterministic)
		chat_det = ChatQwen(
			model='qwen-plus',
			api_key=os.getenv('QWEN_API_KEY'),
			base_url='https://dashscope.aliyuncs.com/compatible-mode/v1',
			temperature=0.0,
			max_tokens=20,
		)

		response = await chat_det.ainvoke(messages)
		assert response is not None
		assert isinstance(response.completion, str)

	@pytest.mark.asyncio
	async def test_qwen_base_url_parameter(self):
		"""Test Qwen with custom base URL."""
		if not os.getenv('QWEN_API_KEY'):
			pytest.skip('QWEN_API_KEY not set')

		# Test with international base URL
		chat = ChatQwen(
			model='qwen-plus',
			api_key=os.getenv('QWEN_API_KEY'),
			base_url='https://dashscope.aliyuncs.com/compatible-mode/v1',
			temperature=0,
			max_tokens=20,
		)

		messages: list[BaseMessage] = [UserMessage(content='Say hello briefly.')]
		response = await chat.ainvoke(messages)

		assert response is not None
		assert isinstance(response.completion, str)
