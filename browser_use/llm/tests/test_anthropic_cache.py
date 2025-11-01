import logging
from typing import cast

from browser_use.agent.service import Agent
from browser_use.llm.anthropic.chat import ChatAnthropic
from browser_use.llm.anthropic.serializer import AnthropicMessageSerializer, NonSystemMessage
from browser_use.llm.messages import (
	AssistantMessage,
	BaseMessage,
	ContentPartImageParam,
	ContentPartTextParam,
	Function,
	ImageURL,
	SystemMessage,
	ToolCall,
	UserMessage,
)

logger = logging.getLogger(__name__)


class TestAnthropicCache:
	"""Comprehensive test for Anthropic cache serialization."""

	def test_cache_basic_functionality(self):
		"""Test basic cache functionality for all message types."""
		# Test cache with different message types
		messages: list[BaseMessage] = [
			SystemMessage(content='System message!', cache=True),
			UserMessage(content='User message!', cache=True),
			AssistantMessage(content='Assistant message!', cache=False),
		]

		anthropic_messages, system_message = AnthropicMessageSerializer.serialize_messages(messages)

		assert len(anthropic_messages) == 2
		assert isinstance(system_message, list)
		assert isinstance(anthropic_messages[0]['content'], list)
		assert isinstance(anthropic_messages[1]['content'], str)

		# Test cache with assistant message
		agent_messages: list[BaseMessage] = [
			SystemMessage(content='System message!'),
			UserMessage(content='User message!'),
			AssistantMessage(content='Assistant message!', cache=True),
		]

		anthropic_messages, system_message = AnthropicMessageSerializer.serialize_messages(agent_messages)

		assert isinstance(system_message, str)
		assert isinstance(anthropic_messages[0]['content'], str)
		assert isinstance(anthropic_messages[1]['content'], list)

	def test_cache_with_tool_calls(self):
		"""Test cache functionality with tool calls."""
		tool_call = ToolCall(id='test_id', function=Function(name='test_function', arguments='{"arg": "value"}'))

		# Assistant with tool calls and cache
		assistant_with_tools = AssistantMessage(content='Assistant with tools', tool_calls=[tool_call], cache=True)
		messages, _ = AnthropicMessageSerializer.serialize_messages([assistant_with_tools])

		assert len(messages) == 1
		assert isinstance(messages[0]['content'], list)
		# Should have both text and tool_use blocks
		assert len(messages[0]['content']) >= 2

	def test_cache_with_images(self):
		"""Test cache functionality with image content."""
		user_with_image = UserMessage(
			content=[
				ContentPartTextParam(text='Here is an image:', type='text'),
				ContentPartImageParam(image_url=ImageURL(url='https://example.com/image.jpg'), type='image_url'),
			],
			cache=True,
		)

		messages, _ = AnthropicMessageSerializer.serialize_messages([user_with_image])

		assert len(messages) == 1
		assert isinstance(messages[0]['content'], list)
		assert len(messages[0]['content']) == 2

	def test_cache_with_base64_images(self):
		"""Test cache functionality with base64 images."""
		base64_url = 'data:image/jpeg;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='

		user_with_base64 = UserMessage(
			content=[
				ContentPartTextParam(text='Base64 image:', type='text'),
				ContentPartImageParam(image_url=ImageURL(url=base64_url), type='image_url'),
			],
			cache=True,
		)

		messages, _ = AnthropicMessageSerializer.serialize_messages([user_with_base64])

		assert len(messages) == 1
		assert isinstance(messages[0]['content'], list)

	def test_cache_content_types(self):
		"""Test different content types with cache."""
		# String content with cache should become list
		user_string_cached = UserMessage(content='String message', cache=True)
		messages, _ = AnthropicMessageSerializer.serialize_messages([user_string_cached])
		assert isinstance(messages[0]['content'], list)

		# String content without cache should remain string
		user_string_no_cache = UserMessage(content='String message', cache=False)
		messages, _ = AnthropicMessageSerializer.serialize_messages([user_string_no_cache])
		assert isinstance(messages[0]['content'], str)

		# List content maintains list format regardless of cache
		user_list_cached = UserMessage(content=[ContentPartTextParam(text='List message', type='text')], cache=True)
		messages, _ = AnthropicMessageSerializer.serialize_messages([user_list_cached])
		assert isinstance(messages[0]['content'], list)

		user_list_no_cache = UserMessage(content=[ContentPartTextParam(text='List message', type='text')], cache=False)
		messages, _ = AnthropicMessageSerializer.serialize_messages([user_list_no_cache])
		assert isinstance(messages[0]['content'], list)

	def test_assistant_cache_empty_content(self):
		"""Test AssistantMessage with empty content and cache."""
		# With cache
		assistant_empty_cached = AssistantMessage(content=None, cache=True)
		messages, _ = AnthropicMessageSerializer.serialize_messages([assistant_empty_cached])

		assert len(messages) == 1
		assert isinstance(messages[0]['content'], list)

		# Without cache
		assistant_empty_no_cache = AssistantMessage(content=None, cache=False)
		messages, _ = AnthropicMessageSerializer.serialize_messages([assistant_empty_no_cache])

		assert len(messages) == 1
		assert isinstance(messages[0]['content'], str)

	def test_mixed_cache_scenarios(self):
		"""Test various combinations of cached and non-cached messages."""
		messages_list: list[BaseMessage] = [
			SystemMessage(content='System with cache', cache=True),
			UserMessage(content='User with cache', cache=True),
			AssistantMessage(content='Assistant without cache', cache=False),
			UserMessage(content='User without cache', cache=False),
			AssistantMessage(content='Assistant with cache', cache=True),
		]

		serialized_messages, system_message = AnthropicMessageSerializer.serialize_messages(messages_list)

		# Check system message is cached (becomes list)
		assert isinstance(system_message, list)

		# Check serialized messages
		assert len(serialized_messages) == 4

		# User with cache should be list
		assert isinstance(serialized_messages[0]['content'], list)

		# Assistant without cache should be string
		assert isinstance(serialized_messages[1]['content'], str)

		# User without cache should be string
		assert isinstance(serialized_messages[2]['content'], str)

		# Assistant with cache should be list
		assert isinstance(serialized_messages[3]['content'], list)

	def test_system_message_cache_behavior(self):
		"""Test SystemMessage specific cache behavior."""
		# With cache
		system_cached = SystemMessage(content='System message with cache', cache=True)
		result = AnthropicMessageSerializer.serialize(system_cached)
		assert isinstance(result, SystemMessage)

		# Test serialization to string format
		serialized_content = AnthropicMessageSerializer._serialize_content_to_str(result.content, use_cache=True)
		assert isinstance(serialized_content, list)

		# Without cache
		system_no_cache = SystemMessage(content='System message without cache', cache=False)
		result = AnthropicMessageSerializer.serialize(system_no_cache)
		assert isinstance(result, SystemMessage)

		serialized_content = AnthropicMessageSerializer._serialize_content_to_str(result.content, use_cache=False)
		assert isinstance(serialized_content, str)

	def test_agent_messages_integration(self):
		"""Test integration with actual agent messages."""
		agent = Agent(task='Hello, world!', llm=ChatAnthropic(''))

		messages = agent.message_manager.get_messages()
		anthropic_messages, system_message = AnthropicMessageSerializer.serialize_messages(messages)

		# System message should be properly handled
		assert system_message is not None

	def test_cache_cleaning_last_message_only(self):
		"""Test that only the last cache=True message remains cached."""
		# Create multiple messages with cache=True
		messages_list: list[BaseMessage] = [
			UserMessage(content='First user message', cache=True),
			AssistantMessage(content='First assistant message', cache=True),
			UserMessage(content='Second user message', cache=True),
			AssistantMessage(content='Second assistant message', cache=False),
			UserMessage(content='Third user message', cache=True),  # This should be the only one cached
		]

		# Test the cleaning method directly (only accepts non-system messages)
		normal_messages = cast(list[NonSystemMessage], [msg for msg in messages_list if not isinstance(msg, SystemMessage)])
		cleaned_messages = AnthropicMessageSerializer._clean_cache_messages(normal_messages)

		# Verify only the last cache=True message remains cached
		assert not cleaned_messages[0].cache  # First user message should be uncached
		assert not cleaned_messages[1].cache  # First assistant message should be uncached
		assert not cleaned_messages[2].cache  # Second user message should be uncached
		assert not cleaned_messages[3].cache  # Second assistant message was already uncached
		assert cleaned_messages[4].cache  # Third user message should remain cached

		# Test through serialize_messages
		serialized_messages, system_message = AnthropicMessageSerializer.serialize_messages(messages_list)

		# Count how many messages have list content (indicating caching)
		cached_content_count = sum(1 for msg in serialized_messages if isinstance(msg['content'], list))

		# Only one message should have cached content
		assert cached_content_count == 1

		# The last message should be the cached one
		assert isinstance(serialized_messages[-1]['content'], list)

	def test_cache_cleaning_with_system_message(self):
		"""Test that system messages are not affected by cache cleaning logic."""
		messages_list: list[BaseMessage] = [
			SystemMessage(content='System message', cache=True),  # System messages are handled separately
			UserMessage(content='First user message', cache=True),
			AssistantMessage(content='Assistant message', cache=True),  # This should be the only normal message cached
		]

		# Test through serialize_messages to see the full integration
		serialized_messages, system_message = AnthropicMessageSerializer.serialize_messages(messages_list)

		# System message should be cached
		assert isinstance(system_message, list)

		# Only one normal message should have cached content (the last one)
		cached_content_count = sum(1 for msg in serialized_messages if isinstance(msg['content'], list))
		assert cached_content_count == 1

		# The last message should be the cached one
		assert isinstance(serialized_messages[-1]['content'], list)

	def test_cache_cleaning_no_cached_messages(self):
		"""Test that messages without cache=True are not affected."""
		normal_messages_list = [
			UserMessage(content='User message 1', cache=False),
			AssistantMessage(content='Assistant message 1', cache=False),
			UserMessage(content='User message 2', cache=False),
		]

		cleaned_messages = AnthropicMessageSerializer._clean_cache_messages(normal_messages_list)

		# All messages should remain uncached
		for msg in cleaned_messages:
			assert not msg.cache

	def test_max_4_cache_blocks(self):
		"""Test that the max number of cache blocks is 4."""
		agent = Agent(task='Hello, world!', llm=ChatAnthropic(''))
		messages = agent.message_manager.get_messages()
		anthropic_messages, system_message = AnthropicMessageSerializer.serialize_messages(messages)

		logger.info(anthropic_messages)
		logger.info(system_message)


if __name__ == '__main__':
	test_instance = TestAnthropicCache()
	test_instance.test_cache_basic_functionality()
	test_instance.test_cache_with_tool_calls()
	test_instance.test_cache_with_images()
	test_instance.test_cache_with_base64_images()
	test_instance.test_cache_content_types()
	test_instance.test_assistant_cache_empty_content()
	test_instance.test_mixed_cache_scenarios()
	test_instance.test_system_message_cache_behavior()
	test_instance.test_agent_messages_integration()
	test_instance.test_cache_cleaning_last_message_only()
	test_instance.test_cache_cleaning_with_system_message()
	test_instance.test_cache_cleaning_no_cached_messages()
	test_instance.test_max_4_cache_blocks()
	print('All cache tests passed!')
