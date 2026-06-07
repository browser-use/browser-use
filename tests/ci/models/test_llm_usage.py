"""Tests for DeepSeek and Ollama LLM usage tracking."""

from types import SimpleNamespace
import pytest

from browser_use.llm.deepseek.chat import ChatDeepSeek
from browser_use.llm.ollama.chat import ChatOllama
from browser_use.llm.views import ChatInvokeUsage


def test_deepseek_get_usage_full():
	"""Test ChatDeepSeek._get_usage with deepseek prompt_cache_hit_tokens field."""
	llm = ChatDeepSeek(api_key='fake')
	response = SimpleNamespace(
		usage=SimpleNamespace(
			prompt_tokens=100,
			completion_tokens=50,
			total_tokens=150,
			prompt_cache_hit_tokens=40,
		)
	)
	usage = llm._get_usage(response)
	assert usage == ChatInvokeUsage(
		prompt_tokens=100,
		prompt_cached_tokens=40,
		prompt_cache_creation_tokens=None,
		prompt_image_tokens=None,
		completion_tokens=50,
		total_tokens=150,
	)


def test_deepseek_get_usage_fallback():
	"""Test ChatDeepSeek._get_usage falling back to prompt_tokens_details.cached_tokens."""
	llm = ChatDeepSeek(api_key='fake')
	response = SimpleNamespace(
		usage=SimpleNamespace(
			prompt_tokens=100,
			completion_tokens=50,
			total_tokens=150,
			prompt_tokens_details=SimpleNamespace(
				cached_tokens=30,
			),
		)
	)
	# prompt_cache_hit_tokens is missing
	usage = llm._get_usage(response)
	assert usage == ChatInvokeUsage(
		prompt_tokens=100,
		prompt_cached_tokens=30,
		prompt_cache_creation_tokens=None,
		prompt_image_tokens=None,
		completion_tokens=50,
		total_tokens=150,
	)


def test_deepseek_get_usage_none():
	"""Test ChatDeepSeek._get_usage with missing usage details."""
	llm = ChatDeepSeek(api_key='fake')
	response = SimpleNamespace(usage=None)
	assert llm._get_usage(response) is None
	
	response_no_attr = SimpleNamespace()
	assert llm._get_usage(response_no_attr) is None


def test_ollama_get_usage_mapping():
	"""Test ChatOllama._get_usage with dictionary response."""
	llm = ChatOllama(model='fake')
	response = {
		'prompt_eval_count': 80,
		'eval_count': 40,
	}
	usage = llm._get_usage(response)
	assert usage == ChatInvokeUsage(
		prompt_tokens=80,
		prompt_cached_tokens=None,
		prompt_cache_creation_tokens=None,
		prompt_image_tokens=None,
		completion_tokens=40,
		total_tokens=120,
	)


def test_ollama_get_usage_object():
	"""Test ChatOllama._get_usage with response object."""
	llm = ChatOllama(model='fake')
	response = SimpleNamespace(
		prompt_eval_count=90,
		eval_count=35,
	)
	usage = llm._get_usage(response)
	assert usage == ChatInvokeUsage(
		prompt_tokens=90,
		prompt_cached_tokens=None,
		prompt_cache_creation_tokens=None,
		prompt_image_tokens=None,
		completion_tokens=35,
		total_tokens=125,
	)


def test_ollama_get_usage_none():
	"""Test ChatOllama._get_usage with missing counts."""
	llm = ChatOllama(model='fake')
	assert llm._get_usage({}) is None
	assert llm._get_usage(SimpleNamespace()) is None
