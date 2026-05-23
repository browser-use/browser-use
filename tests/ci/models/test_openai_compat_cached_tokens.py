"""Surface OpenAI-compatible `prompt_tokens_details.cached_tokens` through provider usage parsers.

OpenAI introduced `usage.prompt_tokens_details.cached_tokens` as the standard reporting
field for automatic prefix caching in chat completions. Most OpenAI-compatible providers
(Groq, Cerebras, Mistral, OpenRouter, ...) cloned the convention. When a wrapper drops
this field, every cached call still costs the user money on paper — they just can't see
the discount.

These tests pin the parsers to actually read it.
"""

from types import SimpleNamespace

from browser_use.llm.cerebras.chat import ChatCerebras
from browser_use.llm.groq.chat import ChatGroq
from browser_use.llm.mistral.chat import ChatMistral


def _fake_openai_usage(prompt: int, completion: int, cached: int | None) -> SimpleNamespace:
	"""Mimic the openai.types.CompletionUsage shape: usage.prompt_tokens_details.cached_tokens."""
	details = SimpleNamespace(cached_tokens=cached) if cached is not None else None
	return SimpleNamespace(
		prompt_tokens=prompt,
		completion_tokens=completion,
		total_tokens=prompt + completion,
		prompt_tokens_details=details,
	)


def test_groq_surfaces_cached_tokens():
	chat = ChatGroq(model='llama-3.3-70b-versatile', api_key='fake')
	response = SimpleNamespace(usage=_fake_openai_usage(1200, 50, cached=900))
	usage = chat._get_usage(response)  # type: ignore[arg-type]
	assert usage is not None
	assert usage.prompt_tokens == 1200
	assert usage.prompt_cached_tokens == 900


def test_groq_handles_missing_details():
	chat = ChatGroq(model='llama-3.3-70b-versatile', api_key='fake')
	response = SimpleNamespace(usage=_fake_openai_usage(100, 20, cached=None))
	usage = chat._get_usage(response)  # type: ignore[arg-type]
	assert usage is not None
	assert usage.prompt_cached_tokens is None


def test_cerebras_surfaces_cached_tokens():
	chat = ChatCerebras(model='llama3.1-70b', api_key='fake')
	response = SimpleNamespace(usage=_fake_openai_usage(2048, 100, cached=1500))
	usage = chat._get_usage(response)  # type: ignore[arg-type]
	assert usage is not None
	assert usage.prompt_cached_tokens == 1500


def test_cerebras_handles_missing_details():
	chat = ChatCerebras(model='llama3.1-70b', api_key='fake')
	response = SimpleNamespace(usage=_fake_openai_usage(50, 10, cached=None))
	usage = chat._get_usage(response)  # type: ignore[arg-type]
	assert usage is not None
	assert usage.prompt_cached_tokens is None


def test_mistral_surfaces_cached_tokens():
	chat = ChatMistral(model='mistral-large-latest', api_key='fake')
	usage = chat._build_usage(
		{
			'prompt_tokens': 1500,
			'completion_tokens': 80,
			'total_tokens': 1580,
			'prompt_tokens_details': {'cached_tokens': 1024},
		}
	)
	assert usage is not None
	assert usage.prompt_tokens == 1500
	assert usage.prompt_cached_tokens == 1024


def test_mistral_handles_missing_details():
	chat = ChatMistral(model='mistral-large-latest', api_key='fake')
	usage = chat._build_usage({'prompt_tokens': 200, 'completion_tokens': 30, 'total_tokens': 230})
	assert usage is not None
	assert usage.prompt_cached_tokens is None


def test_mistral_returns_none_on_empty_usage():
	chat = ChatMistral(model='mistral-large-latest', api_key='fake')
	assert chat._build_usage(None) is None
	assert chat._build_usage({}) is None
