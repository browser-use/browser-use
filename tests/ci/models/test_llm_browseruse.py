"""Test Browser Use model button click."""

from browser_use.llm.browser_use.chat import ChatBrowserUse
from tests.ci.models.model_test_helper import run_model_button_click_test


async def test_browseruse_bu_latest(httpserver):
	"""Test Browser Use bu-latest can click a button."""
	await run_model_button_click_test(
		model_class=ChatBrowserUse,
		model_name='bu-latest',
		api_key_env='BROWSER_USE_API_KEY',
		extra_kwargs={},
		httpserver=httpserver,
	)
