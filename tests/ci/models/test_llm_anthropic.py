"""Test Anthropic model button click."""

from browser_use.llm.anthropic.chat import ChatAnthropic
from tests.ci.models.model_test_helper import run_model_button_click_test


async def test_anthropic_claude_sonnet_4_6(httpserver):
	"""Test Anthropic claude-sonnet-4-6 can click a button."""
	await run_model_button_click_test(
		model_class=ChatAnthropic,
		model_name='claude-sonnet-4-6',
		api_key_env='ANTHROPIC_API_KEY',
		extra_kwargs={},
		httpserver=httpserver,
	)
