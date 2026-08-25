"""Test OpenAI model behavior."""

from types import SimpleNamespace

import pytest

from browser_use.llm.openai.chat import ChatOpenAI, OpenAIMessageSerializer
from tests.ci.models.model_test_helper import run_model_button_click_test


async def test_openai_gpt_4_1_mini(httpserver):
	"""Test OpenAI gpt-4.1-mini can click a button."""
	await run_model_button_click_test(
		model_class=ChatOpenAI,
		model_name='gpt-4.1-mini',
		api_key_env='OPENAI_API_KEY',
		extra_kwargs={},
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
	chat = ChatOpenAI(
		model=model,
		temperature=0.7,
		frequency_penalty=0.5,
		reasoning_models=reasoning_models,
	)
	captured = {}

	async def create(**kwargs):
		captured.update(kwargs)
		return SimpleNamespace(
			choices=[SimpleNamespace(message=SimpleNamespace(content='ok'), finish_reason='stop')],
			usage=None,
		)

	client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
	monkeypatch.setattr(
		OpenAIMessageSerializer,
		'serialize_messages',
		lambda _messages: [{'role': 'user', 'content': 'ping'}],
	)
	monkeypatch.setattr(chat, 'get_client', lambda: client)

	await chat.ainvoke(messages=[])

	assert ('reasoning_effort' in captured) is expect_reasoning
	assert ('temperature' in captured) is not expect_reasoning
	assert ('frequency_penalty' in captured) is not expect_reasoning
