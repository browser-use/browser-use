"""Tests for API key sanitization in logs and errors."""

import pytest

from browser_use.llm.anthropic.chat import ChatAnthropic
from browser_use.llm.browser_use.chat import ChatBrowserUse
from browser_use.llm.cerebras.chat import ChatCerebras
from browser_use.llm.deepseek.chat import ChatDeepSeek
from browser_use.llm.exceptions import ModelProviderError
from browser_use.llm.google.chat import ChatGoogle
from browser_use.llm.groq.chat import ChatGroq
from browser_use.llm.openai.chat import ChatOpenAI
from browser_use.llm.openrouter.chat import ChatOpenRouter
from browser_use.llm.sanitization import sanitize_api_key, sanitize_dict, sanitize_string


class TestSanitization:
	"""Test API key sanitization utilities."""

	def test_sanitize_api_key_basic(self):
		"""Test basic API key sanitization."""
		# Test with a typical API key
		api_key = 'sk-1234567890abcdefghijklmnopqrstuvwxyz'
		sanitized = sanitize_api_key(api_key)
		assert sanitized == 'sk-…'
		assert 'abcdefghijklmnopqrstuvwxyz' not in sanitized

	def test_sanitize_api_key_short(self):
		"""Test sanitization of short keys."""
		short_key = 'sk'
		sanitized = sanitize_api_key(short_key)
		assert sanitized == '***'

	def test_sanitize_api_key_none(self):
		"""Test sanitization of None."""
		sanitized = sanitize_api_key(None)
		assert sanitized == '<not set>'

	def test_sanitize_dict(self):
		"""Test dictionary sanitization."""
		data = {
			'model': 'gpt-4o',
			'api_key': 'sk-1234567890abcdefghijklmnopqrstuvwxyz',
			'temperature': 0.5,
			'nested': {'auth_token': 'secret-token-here', 'value': 42},
		}
		sanitized = sanitize_dict(data)
		assert sanitized['model'] == 'gpt-4o'
		assert sanitized['temperature'] == 0.5
		assert 'abcdefghijklmnopqrstuvwxyz' not in sanitized['api_key']
		assert 'secret-token-here' not in sanitized['nested']['auth_token']
		assert sanitized['nested']['value'] == 42

	def test_sanitize_string_openai(self):
		"""Test string sanitization with OpenAI-style keys."""
		text = "Error: Invalid API key 'sk-1234567890abcdefghijklmnopqrstuvwxyz' provided"
		sanitized = sanitize_string(text)
		assert 'abcdefghijklmnopqrstuvwxyz' not in sanitized
		assert 'sk-…' in sanitized

	def test_sanitize_string_cerebras(self):
		"""Test string sanitization with Cerebras-style keys."""
		text = "Error with key csk-c9m9rpdkjpjfxcr1234567890abcdefghijklmnopqrstuvwxyz"
		sanitized = sanitize_string(text)
		assert 'c9m9rpdkjpjfxcr1234567890abcdefghijklmnopqrstuvwxyz' not in sanitized
		assert 'csk-…' in sanitized

	def test_sanitize_string_google(self):
		"""Test string sanitization with Google API keys."""
		text = "Google API key AIzaSyC1234567890abcdefghijklmnopqrstuvwxyz failed"
		sanitized = sanitize_string(text)
		assert 'AIzaSyC1234567890abcdefghijklmnopqrstuvwxyz' not in sanitized

	def test_model_provider_error_sanitization(self):
		"""Test that ModelProviderError sanitizes API keys in messages."""
		error_msg = "API request failed with key 'sk-1234567890abcdefghijklmnopqrstuvwxyz'"
		error = ModelProviderError(error_msg, status_code=401)
		assert 'abcdefghijklmnopqrstuvwxyz' not in str(error)
		assert 'abcdefghijklmnopqrstuvwxyz' not in error.message


class TestChatModelRepr:
	"""Test that chat model __repr__ and __str__ don't expose API keys."""

	def test_openai_repr(self):
		"""Test ChatOpenAI repr doesn't expose API key."""
		model = ChatOpenAI(model='gpt-4o', api_key='sk-1234567890abcdefghijklmnopqrstuvwxyz')
		repr_str = repr(model)
		str_str = str(model)
		assert 'abcdefghijklmnopqrstuvwxyz' not in repr_str
		assert 'abcdefghijklmnopqrstuvwxyz' not in str_str
		assert 'sk-…' in repr_str or '<not set>' in repr_str or '***' in repr_str

	def test_anthropic_repr(self):
		"""Test ChatAnthropic repr doesn't expose API key."""
		model = ChatAnthropic(model='claude-sonnet-4-0', api_key='sk-ant-1234567890abcdefghijklmnopqrstuvwxyz')
		repr_str = repr(model)
		str_str = str(model)
		assert 'abcdefghijklmnopqrstuvwxyz' not in repr_str
		assert 'abcdefghijklmnopqrstuvwxyz' not in str_str

	def test_google_repr(self):
		"""Test ChatGoogle repr doesn't expose API key."""
		model = ChatGoogle(model='gemini-2.5-flash', api_key='AIzaSyC1234567890abcdefghijklmnopqrstuvwxyz')
		repr_str = repr(model)
		str_str = str(model)
		assert 'AIzaSyC1234567890abcdefghijklmnopqrstuvwxyz' not in repr_str
		assert 'AIzaSyC1234567890abcdefghijklmnopqrstuvwxyz' not in str_str

	def test_cerebras_repr(self):
		"""Test ChatCerebras repr doesn't expose API key."""
		model = ChatCerebras(model='llama3.1-8b', api_key='csk-c9m9rpdkjpjfxcr1234567890abcdefghijklmnopqrstuvwxyz')
		repr_str = repr(model)
		str_str = str(model)
		assert 'c9m9rpdkjpjfxcr1234567890abcdefghijklmnopqrstuvwxyz' not in repr_str
		assert 'c9m9rpdkjpjfxcr1234567890abcdefghijklmnopqrstuvwxyz' not in str_str

	def test_groq_repr(self):
		"""Test ChatGroq repr doesn't expose API key."""
		model = ChatGroq(model='qwen/qwen3-32b', api_key='gsk-1234567890abcdefghijklmnopqrstuvwxyz')
		repr_str = repr(model)
		str_str = str(model)
		assert 'abcdefghijklmnopqrstuvwxyz' not in repr_str
		assert 'abcdefghijklmnopqrstuvwxyz' not in str_str

	def test_deepseek_repr(self):
		"""Test ChatDeepSeek repr doesn't expose API key."""
		model = ChatDeepSeek(model='deepseek-chat', api_key='sk-1234567890abcdefghijklmnopqrstuvwxyz')
		repr_str = repr(model)
		str_str = str(model)
		assert 'abcdefghijklmnopqrstuvwxyz' not in repr_str
		assert 'abcdefghijklmnopqrstuvwxyz' not in str_str

	def test_openrouter_repr(self):
		"""Test ChatOpenRouter repr doesn't expose API key."""
		model = ChatOpenRouter(model='openai/gpt-4o', api_key='sk-or-1234567890abcdefghijklmnopqrstuvwxyz')
		repr_str = repr(model)
		str_str = str(model)
		assert 'abcdefghijklmnopqrstuvwxyz' not in repr_str
		assert 'abcdefghijklmnopqrstuvwxyz' not in str_str

	def test_browser_use_repr(self):
		"""Test ChatBrowserUse repr doesn't expose API key."""
		# This will fail to initialize without a valid key, but we can test the repr after catching the error
		try:
			model = ChatBrowserUse(model='bu-latest', api_key='bu-1234567890abcdefghijklmnopqrstuvwxyz')
			# If it doesn't fail, test the repr
			repr_str = repr(model)
			str_str = str(model)
			assert 'abcdefghijklmnopqrstuvwxyz' not in repr_str
			assert 'abcdefghijklmnopqrstuvwxyz' not in str_str
		except ValueError:
			# Expected if API key validation fails
			pass


if __name__ == '__main__':
	pytest.main([__file__, '-v'])
