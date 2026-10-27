"""Regression tests for Cerebras client setup."""

import pytest

from browser_use.llm.cerebras.chat import ChatCerebras
from browser_use.llm.exceptions import ModelProviderError


def test_provider_key_does_not_fall_back_to_openai_key(monkeypatch: pytest.MonkeyPatch):
	monkeypatch.setenv('OPENAI_API_KEY', 'wrong-provider-key')
	monkeypatch.setenv('CEREBRAS_API_KEY', 'cerebras-key')
	assert ChatCerebras(model='llama3.3-70b')._client().api_key == 'cerebras-key'

	monkeypatch.delenv('CEREBRAS_API_KEY')
	with pytest.raises(ModelProviderError, match='Missing Cerebras API key') as exc_info:
		ChatCerebras(model='llama3.3-70b')._client()
	assert exc_info.value.status_code == 401


def test_explicit_api_key_takes_precedence_over_env(monkeypatch: pytest.MonkeyPatch):
	monkeypatch.setenv('CEREBRAS_API_KEY', 'env-key')
	assert ChatCerebras(model='llama3.3-70b', api_key='explicit-key')._client().api_key == 'explicit-key'
