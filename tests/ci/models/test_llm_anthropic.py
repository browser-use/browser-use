"""Test Anthropic model button click."""

from browser_use.llm.anthropic.chat import ChatAnthropic
from tests.ci.models.model_test_helper import run_model_button_click_test


async def test_anthropic_claude_sonnet_4_6(httpserver):
	"""Test Anthropic claude-sonnet-4-6 can click a button."""
	await run_model_button_click_test(
		model_class=ChatAnthropic,
		model_name='claude-sonnet-4-6',
		api_key_env='ANTHROPIC_API_KEY',
		extra_kwargs={},
		httpserver=httpserver,
	)


def test_anthropic_serializer_preserves_all_system_messages():
	"""Multiple system messages must all survive serialization.

	Previously only the last SystemMessage was kept, dropping earlier system rules from
	the Anthropic request.
	"""
	from browser_use.llm.anthropic.serializer import AnthropicMessageSerializer
	from browser_use.llm.messages import SystemMessage, UserMessage

	messages, system_instruction = AnthropicMessageSerializer.serialize_messages(
		[
			SystemMessage(content='Follow the base system rule.'),
			SystemMessage(content='Also follow the additional system rule.'),
			UserMessage(content='Continue the task.'),
		]
	)

	assert len(messages) == 1, 'only the user message should remain in the conversation'
	assert system_instruction is not None
	text = (
		system_instruction
		if isinstance(system_instruction, str)
		else ''.join(block.get('text', '') for block in system_instruction)
	)
	assert 'Follow the base system rule.' in text
	assert 'Also follow the additional system rule.' in text


def test_anthropic_serializer_single_system_message_unchanged():
	"""A single system message keeps the existing return shape (plain string)."""
	from browser_use.llm.anthropic.serializer import AnthropicMessageSerializer
	from browser_use.llm.messages import SystemMessage, UserMessage

	messages, system_instruction = AnthropicMessageSerializer.serialize_messages(
		[
			SystemMessage(content='Follow the base system rule.'),
			UserMessage(content='Continue the task.'),
		]
	)

	assert isinstance(system_instruction, str)
	assert system_instruction == 'Follow the base system rule.'


def test_anthropic_serializer_merges_list_based_system_messages():
	"""System messages with content-part lists are merged without dropping any text."""
	from browser_use.llm.anthropic.serializer import AnthropicMessageSerializer
	from browser_use.llm.messages import ContentPartTextParam, SystemMessage, UserMessage

	messages, system_instruction = AnthropicMessageSerializer.serialize_messages(
		[
			SystemMessage(content=[ContentPartTextParam(text='Rule A.1'), ContentPartTextParam(text='Rule A.2')]),
			SystemMessage(content='Rule B'),
			UserMessage(content='Go.'),
		]
	)

	assert isinstance(system_instruction, list), 'merged system messages should be a block list'
	text = ''.join(block.get('text', '') for block in system_instruction)  # type: ignore[attr-defined]
	assert 'Rule A.1' in text and 'Rule A.2' in text
	assert 'Rule B' in text


def test_anthropic_serializer_multiple_system_messages_cache_semantics():
	"""Multiple system messages must not silently change existing cache semantics.

	An earlier SystemMessage(cache=True) must not gain a new cache breakpoint just
	because it is now merged into the combined system instruction, when the final
	system message is not cached.
	"""
	from browser_use.llm.anthropic.serializer import AnthropicMessageSerializer
	from browser_use.llm.messages import SystemMessage, UserMessage

	messages, system_instruction = AnthropicMessageSerializer.serialize_messages(
		[
			SystemMessage(content='Base rules', cache=True),
			SystemMessage(content='Additional rules', cache=False),
			UserMessage(content='Go.'),
		]
	)

	assert isinstance(system_instruction, list)
	blocks = system_instruction
	text = ''.join(block.get('text', '') for block in blocks)  # type: ignore[attr-defined]
	assert 'Base rules' in text and 'Additional rules' in text
	# The final system message is not cached, so no cache_control may appear anywhere.
	cache_count = sum(1 for block in blocks if block.get('cache_control') is not None)  # type: ignore[attr-defined]
	assert cache_count == 0, f'Expected no cache breakpoint, got {cache_count}'


def test_anthropic_serializer_multiple_system_messages_cache_last_only():
	"""When the final system message is cached, only it gets the cache breakpoint."""
	from browser_use.llm.anthropic.serializer import AnthropicMessageSerializer
	from browser_use.llm.messages import SystemMessage, UserMessage

	messages, system_instruction = AnthropicMessageSerializer.serialize_messages(
		[
			SystemMessage(content='Base rules', cache=True),
			SystemMessage(content='Additional rules', cache=True),
			UserMessage(content='Go.'),
		]
	)

	assert isinstance(system_instruction, list)
	blocks = system_instruction
	cache_count = sum(1 for block in blocks if block.get('cache_control') is not None)  # type: ignore[attr-defined]
	assert cache_count == 1, f'Expected exactly 1 cache breakpoint, got {cache_count}'
	assert blocks[-1].get('cache_control') is not None  # type: ignore[attr-defined]
	assert blocks[0].get('cache_control') is None  # type: ignore[attr-defined]
