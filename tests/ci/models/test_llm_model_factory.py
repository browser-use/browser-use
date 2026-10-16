import pytest

from browser_use.llm import models
from browser_use.llm.anthropic.chat import ChatAnthropic
from browser_use.llm.cerebras.chat import ChatCerebras
from browser_use.llm.deepseek.chat import ChatDeepSeek
from browser_use.llm.groq.chat import ChatGroq
from browser_use.llm.models import get_llm_by_name
from browser_use.llm.openrouter.chat import ChatOpenRouter

try:
	from browser_use.llm.ollama.chat import ChatOllama
except ImportError:
	ChatOllama = None  # type: ignore


def test_get_llm_by_name_resolves_anthropic_from_env(monkeypatch):
	monkeypatch.setenv('ANTHROPIC_API_KEY', 'anthropic-test-key')

	llm = get_llm_by_name('anthropic_claude_sonnet_4_0')

	assert isinstance(llm, ChatAnthropic)
	assert llm.model == 'claude-sonnet-4-0'
	assert llm.api_key == 'anthropic-test-key'


def test_get_llm_by_name_preserves_cerebras_zai_glm_version_separator(monkeypatch):
	monkeypatch.setenv('CEREBRAS_API_KEY', 'cerebras-test-key')

	llm = get_llm_by_name('cerebras_zai_glm_4_7')

	assert isinstance(llm, ChatCerebras)
	assert llm.model == 'zai-glm-4.7'
	assert llm.api_key == 'cerebras-test-key'


def test_get_llm_by_name_remaps_retired_pixtral_alias(monkeypatch: pytest.MonkeyPatch):
	monkeypatch.setenv('MISTRAL_API_KEY', 'mistral-key')
	# 'pixtral_large' has no provider prefix and hits the top-level alias table
	assert get_llm_by_name('pixtral_large').model == 'mistral-medium-latest'
	# 'mistral_pixtral-large' is provider-prefixed and hits the mistral_map branch
	assert get_llm_by_name('mistral_pixtral-large').model == 'mistral-medium-latest'


def test_get_llm_by_name_preserves_served_mistral_aliases(monkeypatch: pytest.MonkeyPatch):
	monkeypatch.setenv('MISTRAL_API_KEY', 'mistral-key')
	assert get_llm_by_name('mistral_large').model == 'mistral-large-latest'
	assert get_llm_by_name('mistral_medium').model == 'mistral-medium-latest'
	assert get_llm_by_name('mistral_small').model == 'mistral-small-latest'
	assert get_llm_by_name('codestral').model == 'codestral-latest'


def test_get_llm_by_name_resolves_deepseek_from_env(monkeypatch: pytest.MonkeyPatch):
	monkeypatch.setenv('DEEPSEEK_API_KEY', 'deepseek-test-key')

	llm = get_llm_by_name('deepseek_chat')
	assert isinstance(llm, ChatDeepSeek)
	assert llm.model == 'deepseek-chat'
	assert llm.api_key == 'deepseek-test-key'
	assert llm.base_url == 'https://api.deepseek.com/v1'

	llm_reasoner = get_llm_by_name('deepseek_reasoner')
	assert isinstance(llm_reasoner, ChatDeepSeek)
	assert llm_reasoner.model == 'deepseek-reasoner'


def test_get_llm_by_name_resolves_groq_from_env(monkeypatch: pytest.MonkeyPatch):
	monkeypatch.setenv('GROQ_API_KEY', 'groq-test-key')

	llm = get_llm_by_name('groq_llama_4_scout')
	assert isinstance(llm, ChatGroq)
	assert llm.model == 'meta-llama/llama-4-scout-17b-16e-instruct'
	assert llm.api_key == 'groq-test-key'

	llm_33 = get_llm_by_name('groq_llama_3_3_70b')
	assert isinstance(llm_33, ChatGroq)
	assert llm_33.model == 'llama-3.3-70b-versatile'


@pytest.mark.skipif(not models.OLLAMA_AVAILABLE, reason='ollama not installed')
def test_get_llm_by_name_resolves_ollama_from_env(monkeypatch: pytest.MonkeyPatch):
	monkeypatch.setenv('OLLAMA_HOST', 'http://localhost:11434')

	llm = get_llm_by_name('ollama_llama3')
	assert isinstance(llm, ChatOllama)
	assert llm.model == 'llama3'
	assert llm.host == 'http://localhost:11434'

	# Dotted model normalization
	llm_dotted = get_llm_by_name('ollama_llama3_2')
	assert isinstance(llm_dotted, ChatOllama)
	assert llm_dotted.model == 'llama3.2'

	llm_qwen = get_llm_by_name('ollama_qwen2_5')
	assert isinstance(llm_qwen, ChatOllama)
	assert llm_qwen.model == 'qwen2.5'

	# Multi-digit minor versions are normalized to dot
	llm_multi_digit = get_llm_by_name('ollama_v2_10')
	assert isinstance(llm_multi_digit, ChatOllama)
	assert llm_multi_digit.model == 'v2.10'

	# Parameter size suffixes preserved without dot conversion
	llm_size = get_llm_by_name('ollama_qwen3_32b')
	assert isinstance(llm_size, ChatOllama)
	assert llm_size.model == 'qwen3-32b'

	llm_r1_size = get_llm_by_name('ollama_deepseek_r1_7b')
	assert isinstance(llm_r1_size, ChatOllama)
	assert llm_r1_size.model == 'deepseek-r1-7b'


def test_ollama_unavailable_raises_import_error(monkeypatch: pytest.MonkeyPatch):
	monkeypatch.setattr(models, 'OLLAMA_AVAILABLE', False)
	with pytest.raises(ImportError, match='Ollama integration not available'):
		get_llm_by_name('ollama_llama3')

	with pytest.raises(ImportError, match='Ollama integration not available'):
		models.__getattr__('ChatOllama')


def test_get_llm_by_name_resolves_openrouter_from_env(monkeypatch: pytest.MonkeyPatch):
	monkeypatch.setenv('OPENROUTER_API_KEY', 'openrouter-test-key')

	llm = get_llm_by_name('openrouter_anthropic_claude_3_5_sonnet')
	assert isinstance(llm, ChatOpenRouter)
	assert llm.model == 'anthropic/claude-3.5-sonnet'
	assert llm.api_key == 'openrouter-test-key'
	assert llm.base_url == 'https://openrouter.ai/api/v1'


def test_models_lazy_attributes_and_exports(monkeypatch: pytest.MonkeyPatch):
	monkeypatch.setenv('DEEPSEEK_API_KEY', 'deepseek-key')
	monkeypatch.setenv('GROQ_API_KEY', 'groq-key')

	assert models.ChatDeepSeek is ChatDeepSeek
	assert models.ChatGroq is ChatGroq
	if models.OLLAMA_AVAILABLE:
		assert models.ChatOllama is ChatOllama
	assert models.ChatOpenRouter is ChatOpenRouter

	deepseek_model = models.deepseek_chat
	assert isinstance(deepseek_model, ChatDeepSeek)
	assert deepseek_model.model == 'deepseek-chat'
