"""Regression tests for DeepSeek client setup."""

from types import SimpleNamespace

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


def _response(**usage_fields):
	usage = SimpleNamespace(prompt_tokens_details=None, **usage_fields)
	return SimpleNamespace(usage=usage)


def test_usage_is_reported_from_the_openai_shaped_block():
	response = _response(prompt_tokens=900, completion_tokens=80, total_tokens=980)

	usage = ChatDeepSeek(model='deepseek-v4-flash', api_key='x')._get_usage(response)

	assert usage is not None
	assert (usage.prompt_tokens, usage.completion_tokens, usage.total_tokens) == (900, 80, 980)


def test_cached_tokens_come_from_either_field_name():
	"""DeepSeek reports cache hits as prompt_cache_hit_tokens, not the OpenAI name."""
	openai_shaped = SimpleNamespace(
		usage=SimpleNamespace(
			prompt_tokens=900,
			completion_tokens=80,
			total_tokens=980,
			prompt_tokens_details=SimpleNamespace(cached_tokens=600),
		)
	)
	deepseek_shaped = _response(prompt_tokens=900, completion_tokens=80, total_tokens=980, prompt_cache_hit_tokens=600)

	model = ChatDeepSeek(model='deepseek-v4-flash', api_key='x')

	assert model._get_usage(openai_shaped).prompt_cached_tokens == 600
	assert model._get_usage(deepseek_shaped).prompt_cached_tokens == 600


def test_usage_is_none_when_the_response_has_no_usage_block():
	response = SimpleNamespace(usage=None)

	assert ChatDeepSeek(model='deepseek-v4-flash', api_key='x')._get_usage(response) is None
