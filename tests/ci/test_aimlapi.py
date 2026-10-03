import re

import pytest

from browser_use.llm.aimlapi.chat import _ATTRIBUTION_HEADERS, ChatAIMLAPI
from browser_use.llm.aimlapi.serializer import AIMLAPIMessageSerializer
from browser_use.llm.exceptions import ModelProviderError
from browser_use.llm.messages import ContentPartTextParam, SystemMessage, UserMessage
from browser_use.llm.views import ChatInvokeUsage
from browser_use.tokens.service import TokenCost

# Mirrors the gateway-side contract; a malformed id is dropped silently at runtime.
PARTNER_ID_PATTERN = re.compile(r'^part_[A-Za-z0-9]{1,64}$')


def test_aimlapi_serializer_uses_openai_format() -> None:
	"""aimlapi.com speaks the OpenAI wire format, so the serializer must match OpenAI's."""
	messages = [
		SystemMessage(content=[ContentPartTextParam(text='You are a helpful assistant.', type='text')]),
		UserMessage(content='What is the capital of France? Answer in one word.'),
	]

	serialized = AIMLAPIMessageSerializer.serialize_messages(messages)

	assert serialized == [
		{'role': 'system', 'content': [{'type': 'text', 'text': 'You are a helpful assistant.'}]},
		{'role': 'user', 'content': 'What is the capital of France? Answer in one word.'},
	]


def test_aimlapi_chat_defaults() -> None:
	"""ChatAIMLAPI must expose the aimlapi provider and default gateway base URL."""
	chat = ChatAIMLAPI(model='anthropic/claude-sonnet-4.6', api_key='test-key')

	assert chat.provider == 'aimlapi'
	assert str(chat.base_url) == 'https://api.aimlapi.com/v1'
	assert chat.name == 'anthropic/claude-sonnet-4.6'


async def test_registered_aimlapi_llm_never_matches_upstream_pricing(
	monkeypatch: pytest.MonkeyPatch,
) -> None:
	"""aimlapi.com is a gateway; upstream model pricing must not be attributed to it."""
	seen_model_names = []

	async def fake_openrouter_pricing(model_name: str):
		seen_model_names.append(model_name)
		return None

	monkeypatch.setattr('browser_use.tokens.service.get_openrouter_model_pricing', fake_openrouter_pricing)

	token_cost = TokenCost(include_cost=True)
	token_cost._initialized = True
	token_cost._pricing_data = {}
	token_cost.register_llm(ChatAIMLAPI(model='openai/gpt-4o-mini', api_key='test-key'))

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

	assert seen_model_names == ['aimlapi/openai/gpt-4o-mini']
	assert cost is None


def test_aimlapi_reads_api_key_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
	"""AIMLAPI_API_KEY is the documented env var, so it must actually be read."""
	monkeypatch.setenv('AIMLAPI_API_KEY', 'aimlapi-key')
	monkeypatch.setenv('OPENAI_API_KEY', 'sk-unrelated-openai-key')

	client = ChatAIMLAPI(model='anthropic/claude-sonnet-4.6').get_client()

	assert client.api_key == 'aimlapi-key'


def test_aimlapi_never_falls_back_to_the_openai_key(monkeypatch: pytest.MonkeyPatch) -> None:
	"""An unset aimlapi.com key must fail loudly, not ship OPENAI_API_KEY to the gateway."""
	monkeypatch.delenv('AIMLAPI_API_KEY', raising=False)
	monkeypatch.setenv('OPENAI_API_KEY', 'sk-unrelated-openai-key')

	with pytest.raises(ModelProviderError) as exc_info:
		ChatAIMLAPI(model='anthropic/claude-sonnet-4.6').get_client()

	assert exc_info.value.status_code == 401
	assert 'sk-unrelated-openai-key' not in str(exc_info.value)


def test_aimlapi_omits_unset_model_params() -> None:
	"""The gateway 400s on an explicit `"top_p": null`, so unset params must not be sent."""
	assert ChatAIMLAPI(model='openai/gpt-4o-mini', api_key='test-key')._get_request_params() == {}

	chat = ChatAIMLAPI(model='openai/gpt-4o-mini', api_key='test-key', temperature=0.0, seed=7)

	assert chat._get_request_params() == {'temperature': 0.0, 'seed': 7}


def test_aimlapi_partner_id_header_is_well_formed() -> None:
	"""A partner id that does not match the gateway pattern is dropped without any error."""
	assert PARTNER_ID_PATTERN.match(_ATTRIBUTION_HEADERS['X-AIMLAPI-Partner-ID'])


def test_aimlapi_sends_attribution_headers_naming_the_host_project() -> None:
	"""HTTP-Referer / X-Title identify browser-use, the calling app - not the gateway."""
	headers = ChatAIMLAPI(model='openai/gpt-4o-mini', api_key='test-key')._get_client_params()['default_headers']

	assert headers['X-AIMLAPI-Source'] == 'agent/browser-use'
	assert headers['HTTP-Referer'] == 'https://github.com/browser-use/browser-use'
	assert headers['X-Title'] == 'Browser Use'


def test_aimlapi_user_headers_win_and_the_shared_constant_is_never_mutated() -> None:
	"""Merging, not assigning: caller headers survive and the module constant stays clean."""
	chat = ChatAIMLAPI(
		model='openai/gpt-4o-mini',
		api_key='test-key',
		default_headers={'X-Title': 'My App', 'X-Custom': 'kept'},
	)

	headers = chat._get_client_params()['default_headers']

	assert headers['X-Title'] == 'My App'
	assert headers['X-Custom'] == 'kept'
	assert headers['X-AIMLAPI-Partner-ID'] == _ATTRIBUTION_HEADERS['X-AIMLAPI-Partner-ID']
	# The shared constant must be untouched for every other instance.
	assert dict(_ATTRIBUTION_HEADERS)['X-Title'] == 'Browser Use'
	assert 'X-Custom' not in _ATTRIBUTION_HEADERS


def test_aimlapi_attribution_never_rides_a_request_to_another_host() -> None:
	"""Pointing base_url at a proxy or another vendor must not leak attribution headers."""
	chat = ChatAIMLAPI(model='openai/gpt-4o-mini', api_key='test-key', base_url='https://example.com/v1')

	assert chat._get_client_params().get('default_headers') is None
