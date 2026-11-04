"""Regression test: assistant refusal content must survive Anthropic serialization.

`AssistantMessage.content` can contain `ContentPartRefusalParam` blocks, and `AssistantMessage.text`
renders them with a `[Refusal] ` prefix. The Anthropic serializer used to skip refusal parts entirely,
so a refusal-only message became an empty string and mixed content silently lost the refusal.
"""

from typing import cast

import pytest
from anthropic.types import TextBlockParam

from browser_use.llm.anthropic.serializer import AnthropicMessageSerializer
from browser_use.llm.messages import AssistantMessage, ContentPartRefusalParam, ContentPartTextParam


def test_refusal_only_message_is_preserved_as_text() -> None:
	message = AssistantMessage(content=[ContentPartRefusalParam(refusal='Declined 0.')])
	messages, _ = AnthropicMessageSerializer.serialize_messages([message])

	assert messages[0]['content'] == '[Refusal] Declined 0.'


def test_mixed_text_and_refusal_keeps_content_order() -> None:
	message = AssistantMessage(
		content=[
			ContentPartTextParam(text='Here is the summary.'),
			ContentPartRefusalParam(refusal='I cannot share the raw page contents.'),
		]
	)
	messages, _ = AnthropicMessageSerializer.serialize_messages([message])

	blocks = cast(list[TextBlockParam], messages[0]['content'])
	assert isinstance(blocks, list)
	assert [block['text'] for block in blocks] == [
		'Here is the summary.',
		'[Refusal] I cannot share the raw page contents.',
	]
	assert [block['type'] for block in blocks] == ['text', 'text']


def test_refusal_before_text_keeps_its_position() -> None:
	"""A serializer that hoists every refusal to the end would pass the text-first case below."""
	message = AssistantMessage(
		content=[
			ContentPartRefusalParam(refusal='I cannot share the raw page contents.'),
			ContentPartTextParam(text='Here is the summary.'),
		]
	)
	messages, _ = AnthropicMessageSerializer.serialize_messages([message])

	blocks = cast(list[TextBlockParam], messages[0]['content'])
	assert [block['text'] for block in blocks] == [
		'[Refusal] I cannot share the raw page contents.',
		'Here is the summary.',
	]


@pytest.mark.parametrize(
	'content, expected_texts',
	[
		(
			[ContentPartRefusalParam(refusal='Declined 0.'), ContentPartTextParam(text='Here is the summary.')],
			['[Refusal] Declined 0.', 'Here is the summary.'],
		),
		(
			[ContentPartTextParam(text='Here is the summary.'), ContentPartRefusalParam(refusal='Declined 0.')],
			['Here is the summary.', '[Refusal] Declined 0.'],
		),
	],
	ids=['refusal-first', 'refusal-last'],
)
def test_cache_control_lands_on_the_final_content_block_only(
	content: list[ContentPartTextParam | ContentPartRefusalParam], expected_texts: list[str]
) -> None:
	"""A single-block fixture cannot distinguish `blocks[0]` from `blocks[-1]`."""
	message = AssistantMessage(content=content, cache=True)
	messages, _ = AnthropicMessageSerializer.serialize_messages([message])

	blocks = cast(list[TextBlockParam], messages[0]['content'])
	assert [block['text'] for block in blocks] == expected_texts
	assert [block.get('cache_control') for block in blocks] == [None, {'type': 'ephemeral'}]
