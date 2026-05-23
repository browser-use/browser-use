"""Test OpenAI model button click."""

from browser_use.llm.openai.chat import ChatOpenAI, _normalize_openai_assistant_json_content
from tests.ci.models.model_test_helper import run_model_button_click_test


def test_normalize_openai_assistant_json_strips_fences_and_preamble():
	assert _normalize_openai_assistant_json_content('```json\n{"a": 1}\n```') == '{"a": 1}'
	assert _normalize_openai_assistant_json_content('```\n{"b": 2}\n```') == '{"b": 2}'
	assert _normalize_openai_assistant_json_content('Here you go:\n{"c": 3}') == '{"c": 3}'
	assert _normalize_openai_assistant_json_content('  {"d": 4}  ') == '{"d": 4}'


async def test_openai_gpt_4_1_mini(httpserver):
	"""Test OpenAI gpt-4.1-mini can click a button."""
	await run_model_button_click_test(
		model_class=ChatOpenAI,
		model_name='gpt-4.1-mini',
		api_key_env='OPENAI_API_KEY',
		extra_kwargs={},
		httpserver=httpserver,
	)
