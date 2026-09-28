"""Tests for ChatOllama option handling and structured-output parsing."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from browser_use.llm.exceptions import ModelProviderError
from browser_use.llm.messages import ContentPartImageParam, ImageURL, UserMessage
from browser_use.llm.ollama.chat import ChatOllama
from browser_use.llm.ollama.serializer import OllamaMessageSerializer


class Answer(BaseModel):
	answer: str


def _client_returning(content: str) -> MagicMock:
	client = MagicMock()
	client.chat = AsyncMock(return_value=MagicMock(message=MagicMock(content=content)))
	return client


def test_serializes_data_image_urls_case_insensitively():
	message = UserMessage(content=[ContentPartImageParam(image_url=ImageURL(url='DATA:image/png;base64,aGVsbG8='))])

	serialized = OllamaMessageSerializer.serialize(message)

	assert serialized.model_dump(mode='json')['images'] == ['aGVsbG8=']


def test_downloads_remote_images_before_ollama_serialization(httpserver):
	httpserver.expect_request('/image.png').respond_with_data(b'png-bytes', content_type='image/png')
	message = UserMessage(content=[ContentPartImageParam(image_url=ImageURL(url=httpserver.url_for('/image.png')))])

	serialized = OllamaMessageSerializer.serialize(message)

	assert serialized.model_dump(mode='json')['images'] == ['cG5nLWJ5dGVz']


async def test_splits_top_level_chat_parameters_from_ollama_options():
	"""Top-level chat parameters must not be sent inside model options (#5017)."""
	client = _client_returning('{"answer": "ok"}')
	llm = ChatOllama(
		model='test-model',
		ollama_options={
			'think': False,
			'logprobs': True,
			'top_logprobs': 3,
			'keep_alive': '10m',
			'format': 'json',
			'stream': False,
			'num_ctx': 2048,
		},
	)

	with patch.object(ChatOllama, 'get_client', return_value=client):
		result = await llm.ainvoke([UserMessage(content='hi')], output_format=Answer)

	assert result.completion.answer == 'ok'
	kwargs = client.chat.await_args.kwargs
	assert kwargs['options'] == {'num_ctx': 2048}
	assert kwargs['think'] is False
	assert kwargs['logprobs'] is True
	assert kwargs['top_logprobs'] == 3
	assert kwargs['keep_alive'] == '10m'
	assert kwargs['format'] == Answer.model_json_schema()
	assert kwargs.get('stream') is None


@pytest.mark.parametrize('fence', ['```json', '```JSON', '``` json', '```'])
async def test_parses_json_wrapped_in_markdown_fences(fence: str):
	client = _client_returning(f'{fence}\n{{"answer": "ok"}}\n```')
	llm = ChatOllama(model='test-model')

	with patch.object(ChatOllama, 'get_client', return_value=client):
		result = await llm.ainvoke([UserMessage(content='hi')], output_format=Answer)

	assert result.completion.answer == 'ok'


async def test_truncated_json_raises_model_provider_error():
	client = _client_returning('{\n')
	llm = ChatOllama(model='test-model')

	with patch.object(ChatOllama, 'get_client', return_value=client), pytest.raises(ModelProviderError) as exc_info:
		await llm.ainvoke([UserMessage(content='hi')], output_format=Answer)

	assert 'Invalid JSON' in exc_info.value.message or 'invalid JSON' in exc_info.value.message.lower()
