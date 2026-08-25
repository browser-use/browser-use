"""Test OpenAI model button click."""

from types import SimpleNamespace

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


async def test_empty_reasoning_model_pattern_does_not_match_every_model(
	monkeypatch,
):
	chat = ChatOpenAI(
		model='gpt-4.1',
		temperature=0.7,
		frequency_penalty=0.5,
		reasoning_models=[''],
	)
	captured = {}

	async def create(**kwargs):
		captured.update(kwargs)
		return SimpleNamespace(
			choices=[
				SimpleNamespace(
					message=SimpleNamespace(content='ok'),
					finish_reason='stop',
				)
			],
			usage=None,
		)

	client = SimpleNamespace(
		chat=SimpleNamespace(
			completions=SimpleNamespace(create=create),
		)
	)

	monkeypatch.setattr(
		OpenAIMessageSerializer,
		'serialize_messages',
		lambda _messages: [{'role': 'user', 'content': 'ping'}],
	)
	monkeypatch.setattr(chat, 'get_client', lambda: client)

	await chat.ainvoke(messages=[])

	assert 'reasoning_effort' not in captured
	assert captured.get('temperature') == 0.7
	assert captured.get('frequency_penalty') == 0.5

