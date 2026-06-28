"""Test OpenAI model button click."""

from browser_use.llm.openai.chat import ChatOpenAI
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


def test_reasoning_model_classification():
	"""gpt-5-chat-latest is a chat model, not a reasoning model, despite the gpt-5 prefix.

	Regression: the reasoning-model gate used a plain substring match, so
	``'gpt-5' in 'gpt-5-chat-latest'`` was true and the SDK silently dropped
	``temperature`` (and added ``reasoning_effort``) for a model that supports
	sampling params.
	"""
	# non-reasoning gpt-5-chat snapshots must NOT be treated as reasoning models
	assert ChatOpenAI(model='gpt-5-chat-latest')._is_reasoning_model() is False
	assert ChatOpenAI(model='gpt-5-chat')._is_reasoning_model() is False
	# ...even when embedded in an Azure deployment name
	assert ChatOpenAI(model='prod-gpt-5-chat-eastus')._is_reasoning_model() is False
	# genuine reasoning models are still classified correctly
	for model in ('gpt-5', 'gpt-5-mini', 'gpt-5-nano', 'o3', 'o3-mini', 'o1', 'o1-pro'):
		assert ChatOpenAI(model=model)._is_reasoning_model() is True, model
	# dated snapshots / known variants still match via substring
	assert ChatOpenAI(model='gpt-5-2025-08-07')._is_reasoning_model() is True
	assert ChatOpenAI(model='o1-preview')._is_reasoning_model() is True
	# reasoning deployments whose name merely contains "chat" elsewhere stay reasoning
	assert ChatOpenAI(model='prod-chat-gpt-5')._is_reasoning_model() is True
	assert ChatOpenAI(model='team-chat-o3-mini')._is_reasoning_model() is True
	# plain chat models are unaffected
	assert ChatOpenAI(model='gpt-4o')._is_reasoning_model() is False
