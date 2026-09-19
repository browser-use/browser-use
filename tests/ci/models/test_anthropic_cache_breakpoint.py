"""The Anthropic cache breakpoint has to survive a message that ends on an image block.

`Agent` sends its vision step as a `UserMessage(cache=True)` whose last content part is the
screenshot image (`browser_use/agent/prompts.py`), so this is the shape every Anthropic/Bedrock
agent turn takes.
"""

from typing import Any

from anthropic.types import CacheControlEphemeralParam

from browser_use.llm.anthropic.serializer import AnthropicMessageSerializer
from browser_use.llm.messages import ContentPartImageParam, ContentPartTextParam, ImageURL, UserMessage

PNG_DATA = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='
PNG_URL = f'data:image/png;base64,{PNG_DATA}'
REMOTE_URL = 'https://example.com/cat.png'
EPHEMERAL = CacheControlEphemeralParam(type='ephemeral')


def serialize_parts(parts: list[ContentPartTextParam | ContentPartImageParam], cache: bool) -> list[dict[str, Any]]:
	message = UserMessage(content=parts, cache=cache)
	serialized = AnthropicMessageSerializer.serialize(message)
	content = serialized['content']
	assert isinstance(content, list)
	return [dict(block) for block in content if isinstance(block, dict)]


def parts(text: str, image_url: str) -> list[ContentPartTextParam | ContentPartImageParam]:
	return [ContentPartTextParam(text=text), ContentPartImageParam(image_url=ImageURL(url=image_url))]


def cached_block_indices(blocks: list[dict]) -> list[int]:
	return [i for i, block in enumerate(blocks) if block.get('cache_control') is not None]


def test_trailing_text_block_carries_the_breakpoint():
	blocks = serialize_parts([ContentPartTextParam(text='a'), ContentPartTextParam(text='b')], cache=True)

	assert cached_block_indices(blocks) == [1]
	assert blocks[1]['cache_control'] == EPHEMERAL


def test_trailing_image_block_carries_the_breakpoint():
	blocks = serialize_parts(parts('Current screenshot:', PNG_URL), cache=True)

	assert [block['type'] for block in blocks] == ['text', 'image']
	assert cached_block_indices(blocks) == [1], 'no block was marked cacheable, so cache=True was dropped'
	assert blocks[1]['cache_control'] == EPHEMERAL


def test_trailing_remote_url_image_block_carries_the_breakpoint():
	blocks = serialize_parts(parts('Here is an image:', REMOTE_URL), cache=True)

	assert blocks[1]['source'] == {'type': 'url', 'url': REMOTE_URL}
	assert cached_block_indices(blocks) == [1]
	assert blocks[1]['cache_control'] == EPHEMERAL


def test_no_breakpoint_when_caching_is_off():
	blocks = serialize_parts(parts('Current screenshot:', PNG_URL), cache=False)

	assert cached_block_indices(blocks) == []
	assert blocks[1]['source']['data'] == PNG_DATA
