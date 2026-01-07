"""
Tests for ChatOllama model validation.

Tests the fix for: https://github.com/browser-use/browser-use/issues/3813
"""

import pytest

from browser_use.llm.exceptions import ModelProviderError
from browser_use.llm.ollama.chat import (
	ChatOllama,
	get_unsupported_model_message,
	is_unsupported_qwen_model,
)


class TestQwenModelDetection:
	"""Test detection of unsupported Qwen 3 VL MoE models."""

	@pytest.mark.parametrize(
		'model_name',
		[
			'qwen3-vl-moe',
			'qwen3vlmoe',
			'qwen-3-vl-moe',
			'qwen3_vl_moe',
			'Qwen3-VL-MoE',  # Case insensitive
			'QWEN3VLMOE',
			'qwen-3-vl-moe-7b',
			'some-prefix-qwen3vlmoe-suffix',
		],
	)
	def test_detects_unsupported_qwen3_vl_moe(self, model_name: str):
		"""Should detect Qwen 3 VL MoE variants as unsupported."""
		assert is_unsupported_qwen_model(model_name) is True

	@pytest.mark.parametrize(
		'model_name',
		[
			'qwen2-vl',
			'qwen2.5-vl',
			'qwen-vl',  # No "3" and no "moe"
			'qwen3',  # No "vl" or "moe"
			'qwen-moe',  # No "3" or "vl"
			'llama3',
			'llava',
			'phi-3-vision',
			'gpt-4',
			'',
		],
	)
	def test_allows_supported_models(self, model_name: str):
		"""Should allow supported models through."""
		assert is_unsupported_qwen_model(model_name) is False

	def test_handles_none_gracefully(self):
		"""Should handle None input gracefully."""
		assert is_unsupported_qwen_model('') is False


class TestChatOllamaValidation:
	"""Test ChatOllama model validation."""

	def test_validate_model_raises_for_unsupported(self):
		"""Should raise ModelProviderError for unsupported models."""
		chat = ChatOllama(model='qwen3-vl-moe')

		with pytest.raises(ModelProviderError) as exc_info:
			chat._validate_model()

		assert 'qwen3vlmoe' in exc_info.value.message.lower()
		assert 'not supported' in exc_info.value.message.lower()
		assert exc_info.value.model == 'qwen3-vl-moe'

	def test_validate_model_passes_for_supported(self):
		"""Should not raise for supported models."""
		chat = ChatOllama(model='qwen2.5-vl')

		# Should not raise
		chat._validate_model()

	@pytest.mark.asyncio
	async def test_ainvoke_raises_early_for_unsupported_model(self):
		"""Should raise before attempting API call for unsupported models."""
		chat = ChatOllama(model='qwen3vlmoe')

		with pytest.raises(ModelProviderError) as exc_info:
			await chat.ainvoke(messages=[])

		assert 'qwen3vlmoe' in exc_info.value.message.lower()


class TestErrorMessages:
	"""Test error message quality."""

	def test_error_message_includes_alternatives(self):
		"""Error message should include helpful alternatives."""
		message = get_unsupported_model_message('qwen3-vl-moe')

		assert 'qwen2.5-vl' in message
		assert 'qwen2-vl' in message
		assert 'llava' in message
		assert 'OpenRouter' in message or 'cloud' in message.lower()

	def test_error_message_includes_issue_link(self):
		"""Error message should reference the GitHub issue."""
		message = get_unsupported_model_message('qwen3-vl-moe')

		assert '3813' in message
