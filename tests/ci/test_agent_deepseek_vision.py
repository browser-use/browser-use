"""DeepSeek vision gating: only the models that accept images keep use_vision.

DeepSeek's vision guide (https://api-docs.deepseek.com/guides/vision) documents
deepseek-flash as accepting images; the rest of the family does not — deepseek-v4-pro
silently replaces every image part with '[Unsupported Image]' and then reports that it
cannot see the page. Which models accept images is the provider's knowledge, so the
agent asks ChatDeepSeek instead of matching on the model name.
"""

from browser_use.agent.service import Agent
from browser_use.llm.deepseek.chat import ChatDeepSeek


def _agent_for(model: str) -> Agent:
	"""Build an Agent for `model`. conftest disables live API-key verification."""
	return Agent(task='Inspect vision.', llm=ChatDeepSeek(model=model), directly_open_url=False, use_vision=True)


def test_image_capable_deepseek_models_keep_vision():
	for model in ['deepseek-flash', 'deepseek-v4-flash', 'deepseek-v4-flash-vision-exp']:
		assert _agent_for(model).settings.use_vision is True


def test_deepseek_models_without_image_support_revoke_vision():
	for model in ['deepseek-v4-pro', 'deepseek-chat']:
		assert _agent_for(model).settings.use_vision is False


def test_capability_is_reported_by_the_llm_itself():
	assert ChatDeepSeek(model='deepseek-flash').supports_vision() is True
	assert ChatDeepSeek(model='deepseek-v4-flash-vision-exp').supports_vision() is True
	assert ChatDeepSeek(model='deepseek-v4-pro').supports_vision() is False
