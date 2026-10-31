"""Regression test: assistant refusal content must survive Anthropic serialization.

`AssistantMessage.content` can contain `ContentPartRefusalParam` blocks, and `AssistantMessage.text`
renders them with a `[Refusal] ` prefix. The Anthropic serializer used to skip refusal parts entirely,
so a refusal-only message became an empty string and mixed content silently lost the refusal.
"""

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

	blocks = messages[0]['content']
	assert isinstance(blocks, list)
	assert [block['text'] for block in blocks] == [
		'Here is the summary.',
		'[Refusal] I cannot share the raw page contents.',
	]
	assert [block['type'] for block in blocks] == ['text', 'text']


def test_refusal_with_cache_keeps_cache_control_on_last_block() -> None:
	message = AssistantMessage(content=[ContentPartRefusalParam(refusal='Declined 0.')], cache=True)
	messages, _ = AnthropicMessageSerializer.serialize_messages([message])

	blocks = messages[0]['content']
	assert isinstance(blocks, list)
	assert blocks[0]['text'] == '[Refusal] Declined 0.'
	assert blocks[0]['cache_control'] == {'type': 'ephemeral'}
