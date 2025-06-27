"""
Test script for tool calling methods to ensure proper handling of different LLM method arguments.
"""

from unittest.mock import Mock

import pytest
from langchain_core.language_models.chat_models import BaseChatModel

from browser_use.agent.service import Agent


class TestToolCallingMethods:
	"""Tests for different tool calling methods handling."""

	@pytest.fixture
	def mock_llm_with_structured_output(self):
		"""Create a mock LLM that tracks with_structured_output calls."""
		mock_llm = Mock(spec=BaseChatModel)

		# Track calls to with_structured_output
		structured_output_calls = []

		def mock_with_structured_output(schema, include_raw=True, method=None):
			structured_output_calls.append({'schema': schema, 'include_raw': include_raw, 'method': method})

			# Return a mock that can be invoked
			mock_structured = Mock()
			mock_structured.invoke = Mock(return_value={'parsed': None, 'raw': Mock(content='test')})
			mock_structured.ainvoke = Mock(return_value={'parsed': None, 'raw': Mock(content='test')})
			return mock_structured

		mock_llm.with_structured_output = mock_with_structured_output
		mock_llm.structured_output_calls = structured_output_calls
		mock_llm.invoke = Mock(return_value=Mock(content='{"answer": "paris"}'))

		return mock_llm

	async def test_tools_method_error(self, mock_llm_with_structured_output):
		"""Test that 'tools' method causes the expected error."""
		# Create agent with 'tools' method
		agent = Agent(
			task='Test task',
			llm=mock_llm_with_structured_output,
			tool_calling_method='tools',
		)

		# The error should occur during initialization when _test_tool_calling_method is called
		# Check that with_structured_output was called with 'tools' method
		assert len(mock_llm_with_structured_output.structured_output_calls) > 0

		# Find the call that used 'tools' method
		tools_call = next(
			(call for call in mock_llm_with_structured_output.structured_output_calls if call['method'] == 'tools'), None
		)
		assert tools_call is not None, "Expected with_structured_output to be called with method='tools'"

	async def test_function_calling_method_works(self, mock_llm_with_structured_output):
		"""Test that 'function_calling' method works correctly."""
		# Create agent with 'function_calling' method
		agent = Agent(
			task='Test task',
			llm=mock_llm_with_structured_output,
			tool_calling_method='function_calling',
		)

		# Check that with_structured_output was called with 'function_calling' method
		assert len(mock_llm_with_structured_output.structured_output_calls) > 0

		# Find the call that used 'function_calling' method
		fc_call = next(
			(call for call in mock_llm_with_structured_output.structured_output_calls if call['method'] == 'function_calling'),
			None,
		)
		assert fc_call is not None, "Expected with_structured_output to be called with method='function_calling'"

	async def test_json_mode_method_works(self, mock_llm_with_structured_output):
		"""Test that 'json_mode' method works correctly."""
		# Create agent with 'json_mode' method
		agent = Agent(
			task='Test task',
			llm=mock_llm_with_structured_output,
			tool_calling_method='json_mode',
		)

		# For json_mode, it should not call with_structured_output during testing
		# because it uses raw mode
		# Check the calls
		json_mode_calls = [
			call for call in mock_llm_with_structured_output.structured_output_calls if call['method'] == 'json_mode'
		]
		# json_mode is handled specially and doesn't use with_structured_output in _test_tool_calling_method
		assert len(json_mode_calls) == 0

	async def test_raw_method_works(self, mock_llm_with_structured_output):
		"""Test that 'raw' method works correctly."""
		# Create agent with 'raw' method
		agent = Agent(
			task='Test task',
			llm=mock_llm_with_structured_output,
			tool_calling_method='raw',
		)

		# For raw mode, it should not call with_structured_output during testing
		# Check the calls
		raw_calls = [call for call in mock_llm_with_structured_output.structured_output_calls if call['method'] == 'raw']
		# raw is handled specially and doesn't use with_structured_output in _test_tool_calling_method
		assert len(raw_calls) == 0

	async def test_auto_method_selection(self, mock_llm_with_structured_output):
		"""Test that 'auto' method selects appropriate method based on LLM."""
		# Mock the agent to simulate Azure OpenAI with GPT-4
		agent = Agent(
			task='Test task',
			llm=mock_llm_with_structured_output,
			tool_calling_method='auto',
		)

		# Monkey patch to simulate Azure OpenAI
		agent.chat_model_library = 'AzureChatOpenAI'
		agent.chat_model_name = 'gpt-4-1106-preview'

		# Call _get_tool_calling_method_for_model to see what it returns
		method = agent._get_tool_calling_method_for_model()

		# For Azure OpenAI with GPT-4, it should return 'tools'
		assert method == 'tools'
