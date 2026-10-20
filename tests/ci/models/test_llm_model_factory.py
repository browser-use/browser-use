import pytest

from browser_use.llm.anthropic.chat import ChatAnthropic
from browser_use.llm.cerebras.chat import ChatCerebras
from browser_use.llm.minimax.chat import ChatMiniMax
from browser_use.llm.models import get_llm_by_name
from browser_use.tokens.custom_pricing import CUSTOM_MODEL_PRICING


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


def test_get_llm_by_name_resolves_minimax_models_and_global_endpoint(monkeypatch):
	monkeypatch.setenv('MINIMAX_API_KEY', 'minimax-test-key')
	monkeypatch.delenv('MINIMAX_REGION', raising=False)
	monkeypatch.delenv('MINIMAX_BASE_URL', raising=False)

	flash = get_llm_by_name('minimax_m3_1_flash')
	m3 = get_llm_by_name('minimax_m3')
	m2_7 = get_llm_by_name('minimax_m2_7')

	assert isinstance(flash, ChatMiniMax)
	assert flash.model == 'MiniMax-M3.1-Flash'

	assert isinstance(m3, ChatMiniMax)
	assert m3.model == 'MiniMax-M3'
	assert str(m3.base_url) == 'https://api.minimax.io/v1'
	assert m3.api_key == 'minimax-test-key'
	assert isinstance(m2_7, ChatMiniMax)
	assert m2_7.model == 'MiniMax-M2.7'
	assert m2_7.model_metadata is not None
	assert m2_7.model_metadata.thinking_modes == ('always_on',)


def test_minimax_china_endpoint_and_model_metadata(monkeypatch):
	monkeypatch.delenv('MINIMAX_BASE_URL', raising=False)
	llm = ChatMiniMax(region='cn')

	assert str(llm.base_url) == 'https://api.minimaxi.com/v1'
	assert llm.model_metadata is not None
	assert llm.model_metadata.input_modalities == ('text', 'image', 'video')
	assert llm.model_metadata.thinking_modes == ('adaptive',)


def test_minimax_pricing_metadata():
	flash = CUSTOM_MODEL_PRICING['MiniMax-M3.1-Flash']
	m2_7 = CUSTOM_MODEL_PRICING['MiniMax-M2.7']

	assert flash['input_cost_per_token'] == 0.15 / 1_000_000
	assert flash['output_cost_per_token'] == 0.60 / 1_000_000
	assert flash['cache_read_input_token_cost'] == 0.015 / 1_000_000
	assert flash['cache_creation_input_token_cost'] is None
	assert flash['max_input_tokens'] == 1_000_000
	assert 'MiniMax-M3' not in CUSTOM_MODEL_PRICING  # Tiered pricing cannot be represented by a flat override.
	assert m2_7['input_cost_per_token'] == 0.3 / 1_000_000
	assert m2_7['output_cost_per_token'] == 1.2 / 1_000_000
	assert m2_7['cache_read_input_token_cost'] == 0.06 / 1_000_000
	assert m2_7['cache_creation_input_token_cost'] == 0.375 / 1_000_000


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
