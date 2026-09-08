import pytest

from browser_use.llm.anthropic.chat import ChatAnthropic
from browser_use.llm.cerebras.chat import ChatCerebras
from browser_use.llm.models import get_llm_by_name


@pytest.mark.parametrize(
	('alias', 'model'),
	[
		('openai_gpt_6_astra', 'gpt-6-astra'),
		('openai_gpt_5_6_luna', 'gpt-5.6-luna'),
		('anthropic_claude_opus_5', 'claude-opus-5'),
	],
)
def test_current_model_aliases_preserve_provider_ids(alias, model):
	assert get_llm_by_name(alias).model == model


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
