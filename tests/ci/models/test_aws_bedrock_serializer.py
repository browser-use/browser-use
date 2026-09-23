import pytest
from pytest_httpserver import HTTPServer
from werkzeug import Response

from browser_use.llm.aws.serializer import AWSBedrockMessageSerializer
from browser_use.llm.messages import (
	BaseMessage,
	ContentPartImageParam,
	ContentPartTextParam,
	ImageURL,
	SystemMessage,
	UserMessage,
)


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


def test_single_system_message_is_serialized_as_one_block() -> None:
	"""A lone system message must still produce the single-block list the Converse API expects."""
	messages: list[BaseMessage] = [SystemMessage(content='Only rule.'), UserMessage(content='Go.')]

	_, system = AWSBedrockMessageSerializer.serialize_messages(messages)

	assert system == [{'text': 'Only rule.'}]


def test_all_system_messages_are_preserved_in_order() -> None:
	"""Bedrock takes `system` as a list of content blocks, so every system message must survive.

	The agent builds its prompt from several system messages, and dropping all but the last one
	silently discards instructions the caller supplied.
	"""
	messages: list[BaseMessage] = [
		SystemMessage(content='First rule.'),
		SystemMessage(content='Second rule.'),
		SystemMessage(content='Third rule.'),
		UserMessage(content='Go.'),
	]

	_, system = AWSBedrockMessageSerializer.serialize_messages(messages)

	# Separated by a blank line, so one instruction does not run into the next.
	assert system == [{'text': 'First rule.\n\n'}, {'text': 'Second rule.\n\n'}, {'text': 'Third rule.'}]


def test_multi_part_system_messages_keep_every_text_block() -> None:
	"""A system message carrying several text parts contributes all of them, still in order."""
	messages: list[BaseMessage] = [
		SystemMessage(content=[ContentPartTextParam(text='Part one.'), ContentPartTextParam(text='Part two.')]),
		SystemMessage(content='Part three.'),
		UserMessage(content='Go.'),
	]

	_, system = AWSBedrockMessageSerializer.serialize_messages(messages)

	# Parts one and two belong to the same message, so nothing separates them; only the
	# boundary to the next message earns a blank line.
	assert system == [{'text': 'Part one.'}, {'text': 'Part two.\n\n'}, {'text': 'Part three.'}]


def test_system_messages_do_not_reach_the_conversation() -> None:
	"""System text belongs in the `system` field only; it must not leak into the message list."""
	messages: list[BaseMessage] = [
		SystemMessage(content='First rule.'),
		UserMessage(content='Go.'),
		SystemMessage(content='Late rule.'),
	]

	bedrock_messages, system = AWSBedrockMessageSerializer.serialize_messages(messages)

	assert system == [{'text': 'First rule.\n\n'}, {'text': 'Late rule.'}]
	assert [message['role'] for message in bedrock_messages] == ['user']


def test_a_block_that_already_ends_in_a_newline_is_still_separated_by_one_blank_line() -> None:
	"""Trailing newlines in the message must not make the gap between blocks wider."""
	messages: list[BaseMessage] = [
		SystemMessage(content='First rule.\n'),
		SystemMessage(content='Second rule.'),
		UserMessage(content='Go.'),
	]

	_, system = AWSBedrockMessageSerializer.serialize_messages(messages)

	assert system == [{'text': 'First rule.\n\n'}, {'text': 'Second rule.'}]


def test_an_empty_text_part_inside_a_system_message_is_dropped() -> None:
	"""A message can carry real text and an empty part; Converse rejects the empty block."""
	messages: list[BaseMessage] = [
		SystemMessage(content=[ContentPartTextParam(text='First rule.'), ContentPartTextParam(text='')]),
		SystemMessage(content='Second rule.'),
		UserMessage(content='Go.'),
	]

	_, system = AWSBedrockMessageSerializer.serialize_messages(messages)

	assert system == [{'text': 'First rule.\n\n'}, {'text': 'Second rule.'}]


def test_a_block_ending_in_crlf_is_separated_by_one_blank_line() -> None:
	"""A prompt written with Windows line endings gets the same single blank line."""
	messages: list[BaseMessage] = [
		SystemMessage(content='First rule.\r\n'),
		SystemMessage(content='Second rule.'),
		UserMessage(content='Go.'),
	]

	_, system = AWSBedrockMessageSerializer.serialize_messages(messages)

	assert system == [{'text': 'First rule.\n\n'}, {'text': 'Second rule.'}]


def test_empty_system_messages_are_dropped_rather_than_sent_as_empty_blocks() -> None:
	"""Converse rejects an empty text block, so an empty extend_system_message must not turn a
	working request into a validation error."""
	messages: list[BaseMessage] = [
		SystemMessage(content=''),
		SystemMessage(content='Only rule.'),
		UserMessage(content='Go.'),
	]

	_, system = AWSBedrockMessageSerializer.serialize_messages(messages)

	assert system == [{'text': 'Only rule.'}]


def test_system_messages_that_are_all_empty_leave_no_system_field() -> None:
	"""Nothing to say means no `system` field at all, rather than a list of empty blocks."""
	messages: list[BaseMessage] = [SystemMessage(content=''), SystemMessage(content=''), UserMessage(content='Go.')]

	_, system = AWSBedrockMessageSerializer.serialize_messages(messages)

	assert system is None


def test_conversation_without_system_messages_has_no_system_field() -> None:
	"""Without any system message the serializer returns None so the request omits `system`."""
	messages: list[BaseMessage] = [UserMessage(content='Go.')]

	bedrock_messages, system = AWSBedrockMessageSerializer.serialize_messages(messages)

	assert system is None
	assert len(bedrock_messages) == 1
