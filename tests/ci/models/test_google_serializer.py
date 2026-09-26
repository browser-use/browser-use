"""Regression tests for GoogleMessageSerializer's handling of system messages and images."""

from google.genai.types import Content, ContentListUnion, Part
from pytest_httpserver import HTTPServer

from browser_use.llm.google.serializer import GoogleMessageSerializer
from browser_use.llm.messages import AssistantMessage, ContentPartImageParam, ImageURL, SystemMessage, UserMessage


def _role_and_text(contents: ContentListUnion) -> list[tuple[str | None, str | None]]:
	"""Flatten serialized contents into (role, first part text) pairs for assertions."""
	assert isinstance(contents, list)

	pairs: list[tuple[str | None, str | None]] = []
	for content in contents:
		assert isinstance(content, Content)
		parts = content.parts
		assert parts is not None
		assert isinstance(parts[0], Part)
		pairs.append((content.role, parts[0].text))

	return pairs


def test_single_system_message_becomes_the_system_instruction():
	"""The common case must keep returning the system text verbatim."""
	contents, system_instruction = GoogleMessageSerializer.serialize_messages(
		[SystemMessage(content='Follow the base system rule.'), UserMessage(content='Continue the task.')]
	)

	assert system_instruction == 'Follow the base system rule.'
	assert _role_and_text(contents) == [('user', 'Continue the task.')]


def test_all_system_messages_reach_the_system_instruction():
	"""Every SystemMessage must survive, in order, instead of the last one winning."""
	contents, system_instruction = GoogleMessageSerializer.serialize_messages(
		[
			SystemMessage(content='Follow the base system rule.'),
			SystemMessage(content='Also follow the additional system rule.'),
			UserMessage(content='Continue the task.'),
		]
	)

	assert system_instruction == 'Follow the base system rule.\n\nAlso follow the additional system rule.'
	assert _role_and_text(contents) == [('user', 'Continue the task.')]


def test_system_text_is_prepended_even_when_an_assistant_message_comes_first():
	"""include_system_in_user must target the first *user* message, not the first message."""
	contents, system_instruction = GoogleMessageSerializer.serialize_messages(
		[
			SystemMessage(content='Follow the system rule.'),
			AssistantMessage(content='Earlier assistant turn.'),
			UserMessage(content='Continue the task.'),
		],
		include_system_in_user=True,
	)

	assert system_instruction is None
	assert _role_and_text(contents) == [
		('model', 'Earlier assistant turn.'),
		('user', 'Follow the system rule.\n\nContinue the task.'),
	]


def test_system_text_falls_back_to_the_instruction_when_there_is_no_user_message():
	"""With nothing to merge into, the system text must not be silently dropped."""
	_, system_instruction = GoogleMessageSerializer.serialize_messages(
		[SystemMessage(content='Follow the system rule.'), AssistantMessage(content='Earlier assistant turn.')],
		include_system_in_user=True,
	)

	assert system_instruction == 'Follow the system rule.'


def test_system_message_after_the_first_user_turn_is_not_merged_into_a_later_one():
	"""The merge target is the *first* user message; once it is gone, fall back to the instruction."""
	contents, system_instruction = GoogleMessageSerializer.serialize_messages(
		[
			UserMessage(content='First user turn.'),
			SystemMessage(content='Follow the system rule.'),
			UserMessage(content='Second user turn.'),
		],
		include_system_in_user=True,
	)

	assert system_instruction == 'Follow the system rule.'
	assert _role_and_text(contents) == [('user', 'First user turn.'), ('user', 'Second user turn.')]


def _inline_image_part(contents: ContentListUnion) -> Part:
	"""Return the single inline-data image part of a serialized user message."""
	assert isinstance(contents, list)
	assert len(contents) == 1
	content = contents[0]
	assert isinstance(content, Content)
	parts = content.parts
	assert parts is not None and len(parts) == 1
	assert isinstance(parts[0], Part)
	return parts[0]


def test_remote_image_url_is_downloaded_and_inlined(httpserver: HTTPServer) -> None:
	"""A remote image URL must be downloaded instead of being split like a base64 data URL."""
	image_bytes = b'image-bytes'
	httpserver.expect_request('/photo.jpg').respond_with_data(image_bytes, content_type='image/jpeg')
	url = httpserver.url_for('/photo.jpg')

	contents, _ = GoogleMessageSerializer.serialize_messages(
		[UserMessage(content=[ContentPartImageParam(image_url=ImageURL(url=url))])]
	)

	part = _inline_image_part(contents)
	assert part.inline_data is not None
	assert part.inline_data.data == image_bytes
	assert part.inline_data.mime_type == 'image/jpeg'


def test_remote_image_url_falls_back_to_url_path_when_content_type_is_unavailable(httpserver: HTTPServer) -> None:
	"""Without a usable content type, the URL path extension decides the mime type."""
	image_bytes = b'image-bytes'
	httpserver.expect_request('/photo.png').respond_with_data(image_bytes, content_type='application/octet-stream')
	url = httpserver.url_for('/photo.png')

	contents, _ = GoogleMessageSerializer.serialize_messages(
		[UserMessage(content=[ContentPartImageParam(image_url=ImageURL(url=url))])]
	)

	part = _inline_image_part(contents)
	assert part.inline_data is not None
	assert part.inline_data.data == image_bytes
	assert part.inline_data.mime_type == 'image/png'


def test_data_url_image_still_inlines_base64_bytes() -> None:
	"""Base64 data URLs must keep their existing inline-bytes behavior."""
	contents, _ = GoogleMessageSerializer.serialize_messages(
		[UserMessage(content=[ContentPartImageParam(image_url=ImageURL(url='data:image/png;base64,aGVsbG8='))])]
	)

	part = _inline_image_part(contents)
	assert part.inline_data is not None
	assert part.inline_data.data == b'hello'
	assert part.inline_data.mime_type == 'image/png'


def test_uppercase_data_url_scheme_is_still_inlined() -> None:
	"""URI schemes are case-insensitive, so an upper-case DATA: URL must not be downloaded."""
	contents, _ = GoogleMessageSerializer.serialize_messages(
		[UserMessage(content=[ContentPartImageParam(image_url=ImageURL(url='DATA:image/png;base64,aGVsbG8='))])]
	)

	part = _inline_image_part(contents)
	assert part.inline_data is not None
	assert part.inline_data.data == b'hello'
	assert part.inline_data.mime_type == 'image/png'
