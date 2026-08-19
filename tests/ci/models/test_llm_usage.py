from types import SimpleNamespace

from browser_use.llm.deepseek.chat import _extract_deepseek_usage
from browser_use.llm.ollama.chat import _extract_ollama_usage


def test_extract_ollama_usage_object():
	response = SimpleNamespace(prompt_eval_count=100, eval_count=50)
	usage = _extract_ollama_usage(response)
	assert usage is not None
	assert usage.prompt_tokens == 100
	assert usage.completion_tokens == 50
	assert usage.total_tokens == 150


def test_extract_ollama_usage_dict():
	response = {'prompt_eval_count': 80, 'eval_count': 40}
	usage = _extract_ollama_usage(response)
	assert usage is not None
	assert usage.prompt_tokens == 80
	assert usage.completion_tokens == 40
	assert usage.total_tokens == 120


def test_extract_ollama_usage_none():
	assert _extract_ollama_usage(None) is None
	assert _extract_ollama_usage(SimpleNamespace()) is None


def test_extract_deepseek_usage_object():
	usage_obj = SimpleNamespace(prompt_tokens=200, completion_tokens=75, total_tokens=275, prompt_cache_hit_tokens=50)
	resp = SimpleNamespace(usage=usage_obj)
	usage = _extract_deepseek_usage(resp)
	assert usage is not None
	assert usage.prompt_tokens == 200
	assert usage.completion_tokens == 75
	assert usage.total_tokens == 275
	assert usage.prompt_cached_tokens == 50


def test_extract_deepseek_usage_dict():
	resp = {'usage': {'prompt_tokens': 150, 'completion_tokens': 30, 'total_tokens': 180, 'prompt_cache_hit_tokens': 20}}
	usage = _extract_deepseek_usage(resp)
	assert usage is not None
	assert usage.prompt_tokens == 150
	assert usage.completion_tokens == 30
	assert usage.total_tokens == 180
	assert usage.prompt_cached_tokens == 20


def test_extract_deepseek_usage_none():
	assert _extract_deepseek_usage(None) is None
	assert _extract_deepseek_usage(SimpleNamespace(usage=None)) is None
