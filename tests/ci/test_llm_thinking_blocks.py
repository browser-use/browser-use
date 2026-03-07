"""Tests for thinking block stripping in ChatOpenAI."""

import pytest

from browser_use.llm.openai.chat import ChatOpenAI


class TestChatOpenAIThinkingBlocks:
	"""Tests for thinking block stripping functionality."""

	def test_strip_thinking_blocks_well_formed(self):
		"""Test stripping well-formed thinking blocks."""
		llm = ChatOpenAI(model='test-model', strip_thinking_blocks=True)

		# Test with well-formed thinking blocks
		text = """
	<think>
	This is some thinking about the problem.
	The solution requires parsing JSON.
	</think>
	{"name": "test", "value": 42}
	"""
		result = llm._strip_thinking_blocks(text)
		assert result == '{"name": "test", "value": 42}'

	def test_strip_thinking_blocks_multiple(self):
		"""Test stripping multiple thinking blocks."""
		llm = ChatOpenAI(model='test-model', strip_thinking_blocks=True)

		text = """
	<think>
	First block of thinking
	</think>
	some text
	<think>
	Second block of thinking
	</think>
	{"name": "test", "value": 42}
	"""
		result = llm._strip_thinking_blocks(text)
		# Just verify the JSON is present and thinking blocks are removed
		assert '{"name": "test", "value": 42}' in result
		assert '<think>' not in result

	def test_strip_thinking_blocks_stray_close_tag(self):
		"""Test stripping with stray closing tag."""
		llm = ChatOpenAI(model='test-model', strip_thinking_blocks=True)

		# Test with stray closing tag (malformed)
		text = """
	This is some text without proper opening
	</think>
	{"name": "test", "value": 42}
	"""
		result = llm._strip_thinking_blocks(text)
		assert result == '{"name": "test", "value": 42}'

	def test_strip_thinking_blocks_no_thinking(self):
		"""Test that text without thinking blocks is unchanged."""
		llm = ChatOpenAI(model='test-model', strip_thinking_blocks=True)

		text = '{"name": "test", "value": 42}'
		result = llm._strip_thinking_blocks(text)
		assert result == '{"name": "test", "value": 42}'

	def test_strip_thinking_blocks_method_always_strips(self):
		"""Test that the _strip_thinking_blocks method always strips - flag is checked by caller."""
		llm = ChatOpenAI(model='test-model', strip_thinking_blocks=False)

		# The _strip_thinking_blocks method always strips - the flag is checked by the caller
		# This test verifies the method works correctly
		text = """
	<think>
	Thinking block
	</think>
	{"name": "test", "value": 42}
	"""
		result = llm._strip_thinking_blocks(text)
		assert '<think>' not in result
		assert '{"name": "test", "value": 42}' in result


if __name__ == '__main__':
	pytest.main([__file__, '-v'])
