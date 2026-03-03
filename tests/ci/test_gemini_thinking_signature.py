"""Tests for Gemini 3 thinking signature integration."""

from typing import cast
from unittest.mock import MagicMock

from google.genai.types import Content

from browser_use.llm.google.chat import ChatGoogle
from browser_use.llm.google.serializer import GoogleMessageSerializer
from browser_use.llm.messages import AssistantMessage, SystemMessage, UserMessage
from browser_use.llm.views import ChatInvokeCompletion


class TestThinkingExtractionFromGeminiResponse:
	"""Test extraction of thinking and thought_signature from Gemini responses."""

	def test_extract_thinking_and_signature_with_thinking(self):
		"""Test extraction when response has thinking parts."""
		mock_part_thinking = MagicMock()
		mock_part_thinking.thought = True
		mock_part_thinking.text = 'Let me think about this step by step...'
		mock_part_thinking.thought_signature = None

		mock_part_content = MagicMock()
		mock_part_content.thought = False
		mock_part_content.text = '{"action": "click"}'
		mock_part_content.thought_signature = b'encrypted_signature_bytes'

		mock_content = MagicMock()
		mock_content.parts = [mock_part_thinking, mock_part_content]

		mock_candidate = MagicMock()
		mock_candidate.content = mock_content

		mock_response = MagicMock()
		mock_response.candidates = [mock_candidate]

		# Create ChatGoogle instance and test extraction
		chat = ChatGoogle(model='gemini-3-pro-preview')
		thinking, signature = chat._extract_thinking_and_signature(mock_response)

		assert thinking == 'Let me think about this step by step...'
		assert signature == b'encrypted_signature_bytes'

	def test_extract_thinking_and_signature_no_thinking(self):
		"""Test extraction when response has no thinking parts."""
		mock_part = MagicMock()
		mock_part.thought = False
		mock_part.text = '{"action": "done"}'
		mock_part.thought_signature = b'sig'

		mock_content = MagicMock()
		mock_content.parts = [mock_part]

		mock_candidate = MagicMock()
		mock_candidate.content = mock_content

		mock_response = MagicMock()
		mock_response.candidates = [mock_candidate]

		chat = ChatGoogle(model='gemini-3-flash-preview')
		thinking, signature = chat._extract_thinking_and_signature(mock_response)

		assert thinking is None
		assert signature == b'sig'

	def test_extract_thinking_and_signature_empty_response(self):
		"""Test extraction when response is empty."""
		mock_response = MagicMock()
		mock_response.candidates = None

		chat = ChatGoogle(model='gemini-3-pro-preview')
		thinking, signature = chat._extract_thinking_and_signature(mock_response)

		assert thinking is None
		assert signature is None

	def test_extract_thinking_and_signature_no_content(self):
		"""Test extraction when candidate has no content."""
		mock_candidate = MagicMock()
		mock_candidate.content = None

		mock_response = MagicMock()
		mock_response.candidates = [mock_candidate]

		chat = ChatGoogle(model='gemini-3-pro-preview')
		thinking, signature = chat._extract_thinking_and_signature(mock_response)

		assert thinking is None
		assert signature is None

	def test_extract_thinking_multiple_thinking_parts(self):
		"""Test extraction with multiple thinking parts concatenated."""
		mock_part1 = MagicMock()
		mock_part1.thought = True
		mock_part1.text = 'First, I need to understand the problem.'
		mock_part1.thought_signature = None

		mock_part2 = MagicMock()
		mock_part2.thought = True
		mock_part2.text = 'Then, I should consider the best approach.'
		mock_part2.thought_signature = b'sig'

		mock_content = MagicMock()
		mock_content.parts = [mock_part1, mock_part2]

		mock_candidate = MagicMock()
		mock_candidate.content = mock_content

		mock_response = MagicMock()
		mock_response.candidates = [mock_candidate]

		chat = ChatGoogle(model='gemini-3-pro-preview')
		thinking, signature = chat._extract_thinking_and_signature(mock_response)

		assert thinking == 'First, I need to understand the problem.\n\nThen, I should consider the best approach.'
		assert signature == b'sig'


class TestGemini3ModelDetection:
	"""Test is_gemini_3 property on ChatGoogle."""

	def test_is_gemini_3_pro(self):
		"""Test detection of Gemini 3 Pro."""
		chat = ChatGoogle(model='gemini-3-pro-preview')
		assert chat.is_gemini_3 is True

	def test_is_gemini_3_flash(self):
		"""Test detection of Gemini 3 Flash."""
		chat = ChatGoogle(model='gemini-3-flash-preview')
		assert chat.is_gemini_3 is True

	def test_is_not_gemini_3_for_2_5(self):
		"""Test that Gemini 2.5 is not detected as Gemini 3."""
		chat = ChatGoogle(model='gemini-2.5-pro')
		assert chat.is_gemini_3 is False

	def test_is_not_gemini_3_for_flash(self):
		"""Test that older Gemini Flash is not detected as Gemini 3."""
		chat = ChatGoogle(model='gemini-2.0-flash')
		assert chat.is_gemini_3 is False


class TestThoughtSignatureInMessageSerialization:
	"""Test thought_signature handling in Google message serializer."""

	def test_serialize_assistant_message_with_thought_signature(self):
		"""Test that thought_signature is included in serialized assistant message."""
		messages = [
			SystemMessage(content='You are a helpful assistant.'),
			UserMessage(content='Hello'),
			AssistantMessage(content='Hi there!', thought_signature=b'test_signature_bytes'),
			UserMessage(content='How are you?'),
		]

		contents, system_instruction = GoogleMessageSerializer.serialize_messages(messages)

		# Find the assistant message in contents
		assistant_content = None
		for content in cast(list[Content], contents):
			if content.role == 'model':
				assistant_content = content
				break

		assert assistant_content is not None
		assert assistant_content.parts is not None
		assert len(assistant_content.parts) > 0
		# Check that thought_signature was set on the part
		assert assistant_content.parts[0].thought_signature == b'test_signature_bytes'

	def test_serialize_assistant_message_without_thought_signature(self):
		"""Test serialization of assistant message without thought_signature."""
		messages = [
			SystemMessage(content='You are a helpful assistant.'),
			UserMessage(content='Hello'),
			AssistantMessage(content='Hi there!'),
			UserMessage(content='How are you?'),
		]

		contents, system_instruction = GoogleMessageSerializer.serialize_messages(messages)

		# Find the assistant message
		assistant_content = None
		for content in cast(list[Content], contents):
			if content.role == 'model':
				assistant_content = content
				break

		assert assistant_content is not None
		assert assistant_content.parts is not None
		# thought_signature should not be set (or be None)
		assert (
			not hasattr(assistant_content.parts[0], 'thought_signature') or assistant_content.parts[0].thought_signature is None
		)

	def test_serialize_assistant_message_empty_content_with_signature(self):
		"""Test serialization of assistant message with empty content but has signature."""
		messages = [
			SystemMessage(content='You are a helpful assistant.'),
			UserMessage(content='Hello'),
			AssistantMessage(content=None, thought_signature=b'signature_only'),
			UserMessage(content='Continue'),
		]

		contents, system_instruction = GoogleMessageSerializer.serialize_messages(messages)

		# Find the assistant message
		assistant_content = None
		for content in cast(list[Content], contents):
			if content.role == 'model':
				assistant_content = content
				break

		assert assistant_content is not None
		assert assistant_content.parts is not None
		assert len(assistant_content.parts) > 0
		assert assistant_content.parts[0].thought_signature == b'signature_only'


class TestChatInvokeCompletionWithThoughtSignature:
	"""Test ChatInvokeCompletion model with thought_signature."""

	def test_completion_with_all_thinking_fields(self):
		"""Test that ChatInvokeCompletion can hold all thinking-related fields."""
		completion = ChatInvokeCompletion(
			completion='Test response',
			thinking='My reasoning process...',
			thought_signature=b'encrypted_sig',
			usage=None,
			stop_reason='end_turn',
		)

		assert completion.completion == 'Test response'
		assert completion.thinking == 'My reasoning process...'
		assert completion.thought_signature == b'encrypted_sig'

	def test_completion_with_bytes_signature(self):
		"""Test that thought_signature accepts bytes."""
		completion = ChatInvokeCompletion(completion='Test', thought_signature=b'\x00\x01\x02\xff', usage=None)

		assert isinstance(completion.thought_signature, bytes)
		assert completion.thought_signature == b'\x00\x01\x02\xff'


class TestAssistantMessageWithThoughtSignature:
	"""Test AssistantMessage model with thought_signature field."""

	def test_assistant_message_with_signature(self):
		"""Test creating AssistantMessage with thought_signature."""
		msg = AssistantMessage(content='Hello', thought_signature=b'test_sig')

		assert msg.content == 'Hello'
		assert msg.thought_signature == b'test_sig'
		assert msg.role == 'assistant'

	def test_assistant_message_without_signature(self):
		"""Test that thought_signature defaults to None."""
		msg = AssistantMessage(content='Hello')

		assert msg.content == 'Hello'
		assert msg.thought_signature is None
