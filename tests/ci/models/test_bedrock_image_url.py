import pytest
from browser_use.llm.aws.serializer import AWSBedrockMessageSerializer


def test_bedrock_is_url_image_accepts_query_strings_and_fragments():
    valid_urls = [
        "https://cdn.example.com/photo.jpg",
        "https://cdn.example.com/photo.jpg?width=800",
        "https://cdn.example.com/photo.jpg#preview",
        "https://cdn.example.com/photo.jpg?width=800#preview",
        "HTTPS://cdn.example.com/photo.jpg",
        "http://cdn.example.com/photo.png?v=1.2.3&token=xyz",
        "https://cdn.example.com/photo.PNG",
        "https://cdn.example.com/photo.webp?format=auto",
    ]
    for url in valid_urls:
        assert AWSBedrockMessageSerializer._is_url_image(url) is True, f"Failed for valid image URL: {url}"


def test_bedrock_is_url_image_rejects_non_image_urls():
    invalid_urls = [
        "https://cdn.example.com/document.pdf",
        "https://cdn.example.com/page.html?img=photo.jpg",
        "ftp://cdn.example.com/photo.jpg",
        "data:image/png;base64,iVBORw0KGgo=",
        "not-a-url",
        "",
    ]
    for url in invalid_urls:
        assert AWSBedrockMessageSerializer._is_url_image(url) is False, f"Should reject: {url}"
