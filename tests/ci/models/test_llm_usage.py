"""Unit tests for token-usage parsing in the Ollama and DeepSeek wrappers.

These wrappers previously dropped all usage information (`usage=None`). The
`_get_usage` helpers now build a `ChatInvokeUsage` from the provider response.
The tests use lightweight fakes so they run without any network access or API
keys.
"""

from types import SimpleNamespace

from browser_use.llm.deepseek.chat import ChatDeepSeek
from browser_use.llm.ollama.chat import ChatOllama


def test_ollama_usage_parsed_from_response():
	llm = ChatOllama(model='llama3')
	response = SimpleNamespace(prompt_eval_count=12, eval_count=34)

	usage = llm._get_usage(response)

	assert usage is not None
	assert usage.prompt_tokens == 12
	assert usage.completion_tokens == 34
	assert usage.total_tokens == 46
	assert usage.prompt_cached_tokens is None


def test_ollama_usage_none_when_counts_missing():
	llm = ChatOllama(model='llama3')
	response = SimpleNamespace()

	assert llm._get_usage(response) is None


def test_ollama_usage_handles_partial_counts():
	llm = ChatOllama(model='llama3')
	response = SimpleNamespace(prompt_eval_count=None, eval_count=5)

	usage = llm._get_usage(response)

	assert usage is not None
	assert usage.prompt_tokens == 0
	assert usage.completion_tokens == 5
	assert usage.total_tokens == 5


def test_deepseek_usage_parsed_from_response():
	llm = ChatDeepSeek()
	usage_obj = SimpleNamespace(
		prompt_tokens=100,
		completion_tokens=20,
		total_tokens=120,
		prompt_cache_hit_tokens=64,
	)
	response = SimpleNamespace(usage=usage_obj)

	usage = llm._get_usage(response)

	assert usage is not None
	assert usage.prompt_tokens == 100
	assert usage.completion_tokens == 20
	assert usage.total_tokens == 120
	assert usage.prompt_cached_tokens == 64


def test_deepseek_usage_falls_back_to_prompt_tokens_details():
	llm = ChatDeepSeek()
	usage_obj = SimpleNamespace(
		prompt_tokens=80,
		completion_tokens=10,
		total_tokens=90,
		prompt_tokens_details=SimpleNamespace(cached_tokens=16),
	)
	response = SimpleNamespace(usage=usage_obj)

	usage = llm._get_usage(response)

	assert usage is not None
	assert usage.prompt_cached_tokens == 16


def test_deepseek_usage_none_when_missing():
	llm = ChatDeepSeek()
	response = SimpleNamespace(usage=None)

	assert llm._get_usage(response) is None
