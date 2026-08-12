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

	m3 = get_llm_by_name('minimax_m3')
	m2_7 = get_llm_by_name('minimax_m2_7')

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
	assert llm.model_metadata.context_window == 1_000_000
	assert llm.model_metadata.input_modalities == ('text', 'image', 'video')
	assert llm.model_metadata.thinking_modes == ('adaptive', 'disabled')


def test_minimax_pricing_metadata():
	m3 = CUSTOM_MODEL_PRICING['MiniMax-M3']
	m2_7 = CUSTOM_MODEL_PRICING['MiniMax-M2.7']

	assert m3['input_cost_per_token'] == 0.6 / 1_000_000
	assert m3['output_cost_per_token'] == 2.4 / 1_000_000
	assert m3['cache_read_input_token_cost'] == 0.12 / 1_000_000
	assert m3['cache_creation_input_token_cost'] is None
	assert m2_7['input_cost_per_token'] == 0.3 / 1_000_000
	assert m2_7['output_cost_per_token'] == 1.2 / 1_000_000
	assert m2_7['cache_read_input_token_cost'] == 0.06 / 1_000_000
	assert m2_7['cache_creation_input_token_cost'] == 0.375 / 1_000_000
