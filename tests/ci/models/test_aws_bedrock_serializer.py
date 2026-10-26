from typing import Any

import pytest
from pytest_httpserver import HTTPServer
from werkzeug import Response

from browser_use.llm.aws.serializer import AWSBedrockMessageSerializer
from browser_use.llm.messages import (
	AssistantMessage,
	ContentPartImageParam,
	ContentPartRefusalParam,
	ContentPartTextParam,
	Function,
	ImageURL,
	ToolCall,
)


@pytest.mark.parametrize('with_tool', [False, True])
@pytest.mark.parametrize('parts', [('refusal',), ('text', 'refusal'), ('refusal', 'text'), ('refusal', 'text', 'refusal')])
def test_assistant_refusal_preserves_content_order_and_tool_calls(parts: tuple[str, ...], with_tool: bool) -> None:
	content = [
		ContentPartRefusalParam(refusal=f'Declined {index}.')
		if part == 'refusal'
		else ContentPartTextParam(text=f'Text {index}.')
		for index, part in enumerate(parts)
	]
	expected: list[dict[str, Any]] = [
		{'text': f'[Refusal] Declined {index}.' if part == 'refusal' else f'Text {index}.'} for index, part in enumerate(parts)
	]
	tool_calls = [ToolCall(id='tool_1', function=Function(name='lookup', arguments='{"query":"value"}'))] if with_tool else []
	message = AssistantMessage(content=content, tool_calls=tool_calls)
	original = message.model_dump()
	serialized, system = AWSBedrockMessageSerializer.serialize_messages([message])
	if with_tool:
		expected.append({'toolUse': {'toolUseId': 'tool_1', 'name': 'lookup', 'input': {'query': 'value'}}})
	assert serialized == [{'role': 'assistant', 'content': expected}]
	assert system is None
	assert message.model_dump() == original


@pytest.mark.parametrize('content', [None, '', 'Plain text'])
def test_assistant_plain_and_empty_content_is_unchanged(content: str | None) -> None:
	serialized, system = AWSBedrockMessageSerializer.serialize_messages([AssistantMessage(content=content)])
	assert serialized == [{'role': 'assistant', 'content': [{'text': content or ''}]}]
	assert system is None


@pytest.mark.parametrize('with_tool', [False, True])
@pytest.mark.parametrize('content', [None, [], 'Explanation.', [ContentPartRefusalParam(refusal='Content refusal.')]])
def test_top_level_refusal_preserves_content_and_tool_calls(
	content: str | list[ContentPartTextParam | ContentPartRefusalParam] | None, with_tool: bool
) -> None:
	tool_calls = [ToolCall(id='tool_1', function=Function(name='lookup', arguments='{}'))] if with_tool else []
	message = AssistantMessage(content=content, refusal='Top-level refusal.', tool_calls=tool_calls)
	original = message.model_dump()
	expected: list[dict[str, Any]] = []
	if isinstance(content, str):
		expected.append({'text': content})
	elif content:
		expected.append({'text': '[Refusal] Content refusal.'})
	expected.append({'text': '[Refusal] Top-level refusal.'})
	if with_tool:
		expected.append({'toolUse': {'toolUseId': 'tool_1', 'name': 'lookup', 'input': {}}})
	serialized, system = AWSBedrockMessageSerializer.serialize_messages([message])
	assert serialized == [{'role': 'assistant', 'content': expected}]
	assert system is None
	assert message.model_dump() == original


@pytest.mark.parametrize(
	'url',
	[
		'https://cdn.example.com/photo.jpg',
		'https://cdn.example.com/photo.jpg?width=800',
		'https://cdn.example.com/photo.jpg#preview',
		'https://cdn.example.com/photo.jpg?width=800#preview',
		'HTTPS://cdn.example.com/photo.jpg',
		'https://cdn.example.com/photo.PNG?width=800',
	],
)
def test_is_url_image_accepts_supported_http_urls(url: str) -> None:
	assert AWSBedrockMessageSerializer._is_url_image(url)


@pytest.mark.parametrize(
	'url',
	[
		'ftp://cdn.example.com/photo.jpg',
		'data:image/png;base64,aGVsbG8=',
		'https://cdn.example.com/photo.svg',
		'https://cdn.example.com/photo.bmp',
		'https://cdn.example.com/photo.bmp?signature=example',
		'https://cdn.example.com/photo?format=.jpg',
		'https:photo.jpg',
		'https:///photo.jpg',
		'https://[::1/photo.jpg',
		'https://[not-an-ipv6-address]/photo.jpg',
		'https://cdn.example.com:invalid/photo.jpg',
	],
)
def test_is_url_image_rejects_unsupported_urls(url: str) -> None:
	assert not AWSBedrockMessageSerializer._is_url_image(url)


def test_serialize_content_part_prefers_response_content_type(httpserver: HTTPServer) -> None:
	image_bytes = b'image-bytes'
	httpserver.expect_request('/photo.jpg').respond_with_data(
		image_bytes,
		content_type='image/png',
	)
	url = httpserver.url_for('/photo.jpg')

	result = AWSBedrockMessageSerializer._serialize_content_part_image(ContentPartImageParam(image_url=ImageURL(url=url)))

	assert result == {
		'image': {
			'format': 'png',
			'source': {
				'bytes': image_bytes,
			},
		}
	}


@pytest.mark.parametrize('content_type', ['application/octet-stream', None])
def test_serialize_content_part_uses_url_path_when_content_type_is_unavailable(
	httpserver: HTTPServer,
	content_type: str | None,
) -> None:
	image_bytes = b'image-bytes'
	response = Response(image_bytes, content_type=content_type)
	if content_type is None:
		response.headers.pop('Content-Type', None)
	httpserver.expect_request('/photo.png', query_string='signature=example').respond_with_response(response)
	url = f'{httpserver.url_for("/photo.png")}?signature=example'.replace('http://', 'HTTP://', 1)

	result = AWSBedrockMessageSerializer._serialize_content_part_image(ContentPartImageParam(image_url=ImageURL(url=url)))

	assert result == {
		'image': {
			'format': 'png',
			'source': {
				'bytes': image_bytes,
			},
		}
	}
