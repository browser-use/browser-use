import pytest
from anthropic.types import ImageBlockParam

from browser_use.llm.anthropic.serializer import AnthropicMessageSerializer
from browser_use.llm.messages import ContentPartImageParam, ImageURL, UserMessage

PNG_DATA = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='
JPEG_DATA = '/9j/4AAQSkZJRgABAQAAAQABAAD/2wAAA=='
GIF_DATA = 'R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw=='
WEBP_DATA = 'UklGRiIAAABXRUJQVlA4IBYAAAAwAQCdASoBAAEADsD+JaQAA3AAAAAA'
HTTPS_URL = 'https://example.com/cat.png'


def serialize_image(url: str) -> ImageBlockParam:
	message = UserMessage(content=[ContentPartImageParam(image_url=ImageURL(url=url))])
	serialized = AnthropicMessageSerializer.serialize(message)
	content = serialized['content']
	assert isinstance(content, list)
	block = content[0]
	# Narrow the ContentBlockParam union down to an image block before indexing into it.
	assert isinstance(block, dict)
	assert block['type'] == 'image'
	return block


@pytest.mark.parametrize(
	'url',
	[
		f'data:image/png;base64,{PNG_DATA}',
		f'data:image/PNG;base64,{PNG_DATA}',
		f'DATA:image/png;base64,{PNG_DATA}',
		f'Data:Image/Png;base64,{PNG_DATA}',
	],
)
def test_data_url_case_variants_remain_png_base64_images(url):
	block = serialize_image(url)
	assert block['source'] == {
		'type': 'base64',
		'media_type': 'image/png',
		'data': PNG_DATA,
	}


@pytest.mark.parametrize(
	'media_type,data',
	[
		('image/jpeg', JPEG_DATA),
		('image/png', PNG_DATA),
		('image/gif', GIF_DATA),
		('image/webp', WEBP_DATA),
	],
)
def test_supported_media_types_keep_canonical_lowercase(media_type, data):
	block = serialize_image(f'data:{media_type.upper()};base64,{data}')
	assert block['source'] == {
		'type': 'base64',
		'media_type': media_type,
		'data': data,
	}


def test_remote_https_image_stays_a_url_source():
	block = serialize_image(HTTPS_URL)
	assert block['source'] == {'type': 'url', 'url': HTTPS_URL}
