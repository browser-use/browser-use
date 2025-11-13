"""Test that API keys and sensitive data are sanitized from logs and errors."""

import logging

import pytest

from browser_use.exceptions import LLMException
from browser_use.llm.exceptions import ModelProviderError, ModelRateLimitError
from browser_use.utils import sanitize_sensitive_data


class TestSanitizeSensitiveData:
	"""Test the sanitize_sensitive_data function."""

	def test_sanitize_api_key_with_quotes(self):
		"""Test sanitizing API keys in various quoted formats."""
		text = "'api_key': 'sk-proj-abcd1234efgh5678ijkl9012mnop3456'"
		result = sanitize_sensitive_data(text)
		assert 'sk-proj-abcd1234efgh5678ijkl9012mnop3456' not in result
		assert '[REDACTED]' in result
		assert "'api_key':" in result

	def test_sanitize_api_key_colon_format(self):
		"""Test sanitizing API keys in colon format."""
		text = '"api_key": "csk-c9m9rpdkjpjfxcr3456789abcdefghijklmnop"'
		result = sanitize_sensitive_data(text)
		assert 'csk-c9m9rpdkjpjfxcr3456789abcdefghijklmnop' not in result
		assert '[REDACTED]' in result

	def test_sanitize_bearer_token(self):
		"""Test sanitizing Bearer tokens."""
		text = 'Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0'
		result = sanitize_sensitive_data(text)
		assert 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0' not in result
		assert 'Bearer [REDACTED]' in result

	def test_sanitize_url_query_params(self):
		"""Test sanitizing API keys in URL query parameters."""
		text = 'https://api.example.com/endpoint?api_key=abc123def456ghi789'
		result = sanitize_sensitive_data(text)
		assert 'abc123def456ghi789' not in result
		assert 'api_key=[REDACTED]' in result

	def test_sanitize_openai_style_key(self):
		"""Test sanitizing OpenAI-style API keys."""
		text = 'api_key=sk-1234567890abcdefghijklmnopqrstuvwxyz'
		result = sanitize_sensitive_data(text)
		assert 'sk-1234567890abcdefghijklmnopqrstuvwxyz' not in result
		assert '[REDACTED]' in result

	def test_sanitize_cerebras_style_key(self):
		"""Test sanitizing Cerebras-style API keys (csk- prefix)."""
		text = "{'api_key': 'csk-c9m9rpdkjpjfxcr3456789', 'model': 'cerebras_qwen'}"
		result = sanitize_sensitive_data(text)
		assert 'csk-c9m9rpdkjpjfxcr3456789' not in result
		assert '[REDACTED]' in result

	def test_sanitize_password_field(self):
		"""Test sanitizing password fields."""
		text = "password='mySecretPassword123'"
		result = sanitize_sensitive_data(text)
		assert 'mySecretPassword123' not in result
		assert '[REDACTED]' in result

	def test_sanitize_token_field(self):
		"""Test sanitizing token fields."""
		text = 'token: "ghp_1234567890abcdefghijklmnopqrstuvwxyz"'
		result = sanitize_sensitive_data(text)
		assert 'ghp_1234567890abcdefghijklmnopqrstuvwxyz' not in result
		assert '[REDACTED]' in result

	def test_sanitize_key_field_with_long_value(self):
		"""Test sanitizing key fields with long values."""
		text = "'key': '1234567890abcdefghijklmnopqrstuvwxyz1234567890'}"
		result = sanitize_sensitive_data(text)
		# Note: This won't be redacted unless it has a sensitive field name
		# This is intentional to avoid false positives with model names, etc.
		assert '1234567890abcdefghijklmnopqrstuvwxyz1234567890' in result

	def test_preserve_normal_text(self):
		"""Test that normal text is preserved."""
		text = 'This is a normal error message without sensitive data'
		result = sanitize_sensitive_data(text)
		assert result == text

	def test_preserve_short_strings(self):
		"""Test that short strings are not redacted."""
		text = 'api_key: abc123'
		result = sanitize_sensitive_data(text)
		# Short strings (< 8 chars) should be preserved
		assert 'abc123' in result

	def test_empty_string(self):
		"""Test handling of empty strings."""
		assert sanitize_sensitive_data('') == ''

	def test_none_value(self):
		"""Test handling of None values."""
		assert sanitize_sensitive_data(None) is None

	def test_complex_error_message(self):
		"""Test sanitizing a complex error message with multiple sensitive fields."""
		text = (
			"Error 422: {'detail': [{'type': 'enum', 'loc': ['body', 'llm'], "
			"'input': {'model': 'cerebras_qwen', 'api_key': 'csk-c9m9rpdkjpjfxcr3456789', "
			"'base_url': 'https://api.cerebras.ai/v1', 'timeout': None}}]}"
		)
		result = sanitize_sensitive_data(text)
		assert 'csk-c9m9rpdkjpjfxcr3456789' not in result
		assert '[REDACTED]' in result
		assert 'cerebras_qwen' in result  # Model name should be preserved
		assert 'https://api.cerebras.ai/v1' in result  # URL should be preserved


class TestExceptionSanitization:
	"""Test that exceptions sanitize sensitive data."""

	def test_model_provider_error_sanitizes_message(self):
		"""Test that ModelProviderError sanitizes the error message."""
		error = ModelProviderError(
			message="API error: api_key='sk-1234567890abcdefghijklmnopqrstuvwxyz' is invalid",
			status_code=401,
			model='gpt-4',
		)
		assert 'sk-1234567890abcdefghijklmnopqrstuvwxyz' not in str(error)
		assert '[REDACTED]' in str(error)
		assert 'API error' in str(error)

	def test_model_rate_limit_error_sanitizes_message(self):
		"""Test that ModelRateLimitError sanitizes the error message."""
		error = ModelRateLimitError(
			message="Rate limit exceeded for token: abc123def456ghi789jkl012mno345pqr678",
			status_code=429,
			model='gpt-4',
		)
		assert 'abc123def456ghi789jkl012mno345pqr678' not in str(error)
		assert '[REDACTED]' in str(error)

	def test_llm_exception_sanitizes_message(self):
		"""Test that LLMException sanitizes the error message."""
		error = LLMException(
			status_code=422,
			message="Invalid request: {'api_key': 'csk-c9m9rpdkjpjfxcr3456789'}",
		)
		assert 'csk-c9m9rpdkjpjfxcr3456789' not in str(error)
		assert '[REDACTED]' in str(error)
		assert 'Invalid request' in str(error)


class TestLoggingSanitization:
	"""Test that logging sanitizes sensitive data."""

	def test_log_message_sanitization(self, caplog):
		"""Test that log messages are sanitized."""
		from browser_use.logging_config import setup_logging

		setup_logging(force_setup=True)
		logger = logging.getLogger('browser_use.test')

		with caplog.at_level(logging.INFO):
			logger.info("API key: sk-1234567890abcdefghijklmnopqrstuvwxyz")

		# Check that the API key was sanitized in the log output
		assert 'sk-1234567890abcdefghijklmnopqrstuvwxyz' not in caplog.text
		assert '[REDACTED]' in caplog.text

	def test_log_args_sanitization(self, caplog):
		"""Test that log arguments are sanitized."""
		from browser_use.logging_config import setup_logging

		setup_logging(force_setup=True)
		logger = logging.getLogger('browser_use.test')

		with caplog.at_level(logging.INFO):
			logger.info('Error with key: %s', 'csk-c9m9rpdkjpjfxcr3456789')

		# Check that the API key was sanitized in the log output
		assert 'csk-c9m9rpdkjpjfxcr3456789' not in caplog.text
		assert '[REDACTED]' in caplog.text

	def test_error_log_sanitization(self, caplog):
		"""Test that error logs are sanitized."""
		from browser_use.logging_config import setup_logging

		setup_logging(force_setup=True)
		logger = logging.getLogger('browser_use.test')

		with caplog.at_level(logging.ERROR):
			logger.error("Authentication failed: token='ghp_1234567890abcdefghijklmnopqrstuvwxyz'")

		# Check that the token was sanitized in the log output
		assert 'ghp_1234567890abcdefghijklmnopqrstuvwxyz' not in caplog.text
		assert '[REDACTED]' in caplog.text


if __name__ == '__main__':
	pytest.main([__file__, '-v'])
