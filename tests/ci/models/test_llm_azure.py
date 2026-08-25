"""Test Azure OpenAI model button click."""

from types import SimpleNamespace

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


async def test_azure_empty_reasoning_model_pattern_does_not_match_every_model(
	monkeypatch,
):
	chat = ChatAzureOpenAI(
		model='gpt-4.1',
		temperature=0.7,
		reasoning_models=[''],
		use_responses_api=True,
		azure_endpoint='https://dummy.openai.azure.com',
		api_key='dummy_key',
	)
	captured = {}

	async def create(**kwargs):
		captured.update(kwargs)
		return SimpleNamespace(
			output_text='ok',
			status='completed',
			usage=None,
		)

	client = SimpleNamespace(
		responses=SimpleNamespace(create=create),
	)

	monkeypatch.setattr(
		ResponsesAPIMessageSerializer,
		'serialize_messages',
		lambda _messages: [{'role': 'user', 'content': 'ping'}],
	)
	monkeypatch.setattr(chat, 'get_client', lambda: client)

	await chat.ainvoke(messages=[])

	assert 'reasoning' not in captured
	assert captured.get('temperature') == 0.7


