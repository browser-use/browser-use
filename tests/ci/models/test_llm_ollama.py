"""Tests for ChatOllama option handling and structured-output parsing."""

import socket
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
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


async def test_serializes_data_image_urls_case_insensitively():
	message = UserMessage(content=[ContentPartImageParam(image_url=ImageURL(url='DATA:image/png;base64,aGVsbG8='))])

	serialized = await OllamaMessageSerializer.serialize(message)

	assert serialized.model_dump(mode='json')['images'] == ['aGVsbG8=']


async def test_downloads_remote_images_before_ollama_serialization():
	message = UserMessage(content=[ContentPartImageParam(image_url=ImageURL(url='https://images.example/image.png'))])

	with patch.object(OllamaMessageSerializer, '_download_image', new=AsyncMock(return_value=b'png-bytes')) as download:
		serialized = await OllamaMessageSerializer.serialize(message)

	download.assert_awaited_once_with('https://images.example/image.png')
	assert serialized.model_dump(mode='json')['images'] == ['cG5nLWJ5dGVz']


async def test_blocks_hosts_that_resolve_to_private_addresses():
	requests: list[httpx.Request] = []

	def handle_request(request: httpx.Request) -> httpx.Response:
		requests.append(request)
		return httpx.Response(200, content=b'not-reached')

	private_address = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('10.0.0.1', 0))]
	async with httpx.AsyncClient(transport=httpx.MockTransport(handle_request)) as client:
		with patch('browser_use.llm.ollama.serializer.socket.getaddrinfo', return_value=private_address):
			with pytest.raises(ValueError, match='non-public host'):
				await OllamaMessageSerializer._download_image_with_client('https://images.example/image.png', client)

	assert requests == []


async def test_follows_redirects_after_validating_each_destination():
	requests: list[str] = []

	def handle_request(request: httpx.Request) -> httpx.Response:
		requests.append(str(request.url))
		if request.url.path == '/redirect':
			return httpx.Response(302, headers={'location': '/image.png'})
		return httpx.Response(200, content=b'png-bytes')

	async with httpx.AsyncClient(transport=httpx.MockTransport(handle_request), follow_redirects=False) as client:
		with patch.object(OllamaMessageSerializer, '_is_public_host', new=AsyncMock(return_value=True)) as is_public:
			image = await OllamaMessageSerializer._download_image_with_client('https://images.example/redirect', client)

	assert image == b'png-bytes'
	assert requests == ['https://images.example/redirect', 'https://images.example/image.png']
	assert is_public.await_count == 2


async def test_rejects_redirects_to_non_public_hosts():
	requests: list[str] = []

	def handle_request(request: httpx.Request) -> httpx.Response:
		requests.append(str(request.url))
		return httpx.Response(302, headers={'location': 'http://127.0.0.1/private.png'})

	async with httpx.AsyncClient(transport=httpx.MockTransport(handle_request), follow_redirects=False) as client:
		with patch.object(OllamaMessageSerializer, '_is_public_host', new=AsyncMock(side_effect=[True, False])):
			with pytest.raises(ValueError, match='non-public host'):
				await OllamaMessageSerializer._download_image_with_client('https://images.example/redirect', client)

	assert requests == ['https://images.example/redirect']


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
