import pytest

from browser_use.llm.aws.serializer import AWSBedrockMessageSerializer


@pytest.mark.parametrize(
	'url',
	[
		'https://cdn.example.com/photo.jpg?width=800',
		'https://cdn.example.com/photo.png#preview',
		'https://cdn.example.com/photo.webp?width=800#preview',
		'HTTPS://cdn.example.com/photo.JPEG',
	],
)
def test_is_url_image_accepts_query_fragments_and_mixed_case(url: str) -> None:
	assert AWSBedrockMessageSerializer._is_url_image(url) is True


@pytest.mark.parametrize(
	'url',
	[
		'https://cdn.example.com/photo.jpg.exe?format=jpg',
		'https://cdn.example.com/photo?format=jpg',
		'ftp://cdn.example.com/photo.jpg',
	],
)
def test_is_url_image_rejects_non_image_paths_and_unsupported_schemes(url: str) -> None:
	assert AWSBedrockMessageSerializer._is_url_image(url) is False
