import pytest

from browser_use.llm.messages import ContentPartTextParam, SystemMessage, UserMessage
from browser_use.llm.orcarouter.chat import ChatOrcaRouter
from browser_use.llm.orcarouter.serializer import OrcaRouterMessageSerializer
from browser_use.llm.views import ChatInvokeUsage
from browser_use.tokens.service import TokenCost


def test_orcarouter_serializer_uses_openai_format() -> None:
	"""OrcaRouter speaks the OpenAI wire format, so the serializer must match OpenAI's."""
	messages = [
		SystemMessage(content=[ContentPartTextParam(text='You are a helpful assistant.', type='text')]),
		UserMessage(content='What is the capital of France? Answer in one word.'),
	]

	serialized = OrcaRouterMessageSerializer.serialize_messages(messages)

	assert serialized == [
		{'role': 'system', 'content': [{'type': 'text', 'text': 'You are a helpful assistant.'}]},
		{'role': 'user', 'content': 'What is the capital of France? Answer in one word.'},
	]


def test_orcarouter_chat_defaults() -> None:
	"""ChatOrcaRouter must expose the OrcaRouter provider and default gateway base URL."""
	chat = ChatOrcaRouter(model='orcarouter/auto', api_key='test-key')

	assert chat.provider == 'orcarouter'
	assert str(chat.base_url) == 'https://api.orcarouter.ai/v1'
	assert chat.name == 'orcarouter/auto'


async def test_registered_orcarouter_llm_never_matches_upstream_pricing(
	monkeypatch: pytest.MonkeyPatch,
) -> None:
	"""OrcaRouter is a gateway; upstream model pricing must not be attributed to it."""
	seen_model_names = []

	async def fake_openrouter_pricing(model_name: str):
		seen_model_names.append(model_name)
		return None

	monkeypatch.setattr('browser_use.tokens.service.get_openrouter_model_pricing', fake_openrouter_pricing)

	token_cost = TokenCost(include_cost=True)
	token_cost._initialized = True
	token_cost._pricing_data = {}
	token_cost.register_llm(ChatOrcaRouter(model='openai/gpt-4o-mini', api_key='test-key'))

	cost = await token_cost.calculate_cost(
		'openai/gpt-4o-mini',
		ChatInvokeUsage(
			prompt_tokens=10,
			prompt_cached_tokens=None,
			prompt_cache_creation_tokens=None,
			prompt_image_tokens=None,
			completion_tokens=5,
			total_tokens=15,
		),
	)

	assert seen_model_names == ['orcarouter/openai/gpt-4o-mini']
	assert cost is None
