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


async def test_anthropic_claude_opus_5(httpserver):
	"""Exercise Opus 5 with the adapter's default thinking and tool choice."""
	await run_model_button_click_test(
		model_class=ChatAnthropic,
		model_name='claude-opus-5',
		api_key_env='ANTHROPIC_API_KEY',
		extra_kwargs={},
		httpserver=httpserver,
	)
