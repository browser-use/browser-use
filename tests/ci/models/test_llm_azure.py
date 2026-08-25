"""Test Azure OpenAI model behavior."""

from types import SimpleNamespace

import pytest

from browser_use.llm.azure.chat import ChatAzureOpenAI, ResponsesAPIMessageSerializer
from tests.ci.models.model_test_helper import run_model_button_click_test


async def test_azure_gpt_4_1_mini(httpserver):
	"""Test Azure OpenAI gpt-4.1-mini can click a button."""
	await run_model_button_click_test(
		model_class=ChatAzureOpenAI,
		model_name='gpt-4.1-mini',
		api_key_env='AZURE_OPENAI_KEY',
		extra_kwargs={},  # Azure endpoint will be added by helper
		httpserver=httpserver,
	)


@pytest.mark.parametrize(
	('reasoning_models', 'expect_reasoning'),
	[
		([''], False),
		(['gpt-5'], True),
	],
)
async def test_reasoning_model_patterns_ignore_empty_entries(monkeypatch, reasoning_models, expect_reasoning):
	"""Empty patterns must not classify every model as a reasoning model."""
	model = 'gpt-5-mini' if expect_reasoning else 'gpt-4.1'
	chat = ChatAzureOpenAI(
		model=model,
		temperature=0.7,
		reasoning_models=reasoning_models,
		use_responses_api=True,
	)
	captured = {}

	async def create(**kwargs):
		captured.update(kwargs)
		return SimpleNamespace(output_text='ok', usage=None, status='completed')

	client = SimpleNamespace(responses=SimpleNamespace(create=create))
	monkeypatch.setattr(ResponsesAPIMessageSerializer, 'serialize_messages', lambda _messages: [])
	monkeypatch.setattr(chat, 'get_client', lambda: client)

	await chat.ainvoke(messages=[])

	assert ('reasoning' in captured) is expect_reasoning
	assert ('temperature' in captured) is not expect_reasoning
