from browser_use.llm.anthropic.chat import ChatAnthropic
from browser_use.llm.cerebras.chat import ChatCerebras
from browser_use.llm.models import get_llm_by_name


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
