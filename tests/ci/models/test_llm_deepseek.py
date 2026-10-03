"""Regression tests for DeepSeek client setup."""

import pytest

from browser_use.llm.deepseek.chat import ChatDeepSeek
from browser_use.llm.exceptions import ModelProviderError


def test_provider_key_does_not_fall_back_to_openai_key(monkeypatch: pytest.MonkeyPatch):
	monkeypatch.setenv('OPENAI_API_KEY', 'wrong-provider-key')
	monkeypatch.setenv('DEEPSEEK_API_KEY', 'deepseek-key')
	assert ChatDeepSeek(model='deepseek-v4-flash')._client().api_key == 'deepseek-key'

	monkeypatch.delenv('DEEPSEEK_API_KEY')
	with pytest.raises(ModelProviderError, match='Missing DeepSeek API key') as exc_info:
		ChatDeepSeek(model='deepseek-v4-flash')._client()
	assert exc_info.value.status_code == 401


def test_explicit_api_key_takes_precedence_over_env(monkeypatch: pytest.MonkeyPatch):
	monkeypatch.setenv('DEEPSEEK_API_KEY', 'env-key')
	assert ChatDeepSeek(model='deepseek-v4-flash', api_key='explicit-key')._client().api_key == 'explicit-key'
