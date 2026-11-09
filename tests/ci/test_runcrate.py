import json

import pytest
from pydantic import BaseModel
from pytest_httpserver import HTTPServer

from browser_use.llm.exceptions import ModelProviderError
from browser_use.llm.messages import ContentPartTextParam, SystemMessage, UserMessage
from browser_use.llm.runcrate.chat import ChatRuncrate
from browser_use.llm.runcrate.serializer import RuncrateMessageSerializer
from browser_use.llm.views import ChatInvokeUsage
from browser_use.tokens.service import TokenCost


def test_runcrate_serializer_uses_openai_format() -> None:
	"""Runcrate speaks the OpenAI wire format, so the serializer must match OpenAI's."""
	messages = [
		SystemMessage(content=[ContentPartTextParam(text='You are a helpful assistant.', type='text')]),
		UserMessage(content='What is the capital of France? Answer in one word.'),
	]

	serialized = RuncrateMessageSerializer.serialize_messages(messages)

	assert serialized == [
		{'role': 'system', 'content': [{'type': 'text', 'text': 'You are a helpful assistant.'}]},
		{'role': 'user', 'content': 'What is the capital of France? Answer in one word.'},
	]


def test_runcrate_chat_defaults() -> None:
	"""ChatRuncrate must expose the Runcrate provider and default base URL."""
	chat = ChatRuncrate(model='deepseek-ai/DeepSeek-V4.1-Flash', api_key='test-key')

	assert chat.provider == 'runcrate'
	assert str(chat.base_url) == 'https://api.runcrate.ai/v1'
	assert chat.name == 'deepseek-ai/DeepSeek-V4.1-Flash'


async def test_registered_runcrate_llm_never_matches_upstream_pricing(
	monkeypatch: pytest.MonkeyPatch,
) -> None:
	"""Runcrate has its own model catalog; upstream model pricing must not be attributed to it."""
	seen_model_names = []

	async def fake_openrouter_pricing(model_name: str):
		seen_model_names.append(model_name)
		return None

	monkeypatch.setattr('browser_use.tokens.service.get_openrouter_model_pricing', fake_openrouter_pricing)

	token_cost = TokenCost(include_cost=True)
	token_cost._initialized = True
	token_cost._pricing_data = {}
	token_cost.register_llm(ChatRuncrate(model='deepseek-ai/DeepSeek-V4.1-Flash', api_key='test-key'))

	cost = await token_cost.calculate_cost(
		'deepseek-ai/DeepSeek-V4.1-Flash',
		ChatInvokeUsage(
			prompt_tokens=10,
			prompt_cached_tokens=None,
			prompt_cache_creation_tokens=None,
			prompt_image_tokens=None,
			completion_tokens=5,
			total_tokens=15,
		),
	)

	assert seen_model_names == ['runcrate/deepseek-ai/DeepSeek-V4.1-Flash']
	assert cost is None


def test_runcrate_reads_api_key_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
	"""RUNCRATE_API_KEY is the documented env var, so it must actually be read."""
	monkeypatch.setenv('RUNCRATE_API_KEY', 'runcrate-key')
	monkeypatch.setenv('OPENAI_API_KEY', 'sk-unrelated-openai-key')

	client = ChatRuncrate(model='deepseek-ai/DeepSeek-V4.1-Flash').get_client()

	assert client.api_key == 'runcrate-key'


def test_runcrate_never_falls_back_to_the_openai_key(monkeypatch: pytest.MonkeyPatch) -> None:
	"""An unset Runcrate key must fail loudly, not ship OPENAI_API_KEY to the Runcrate endpoint."""
	monkeypatch.delenv('RUNCRATE_API_KEY', raising=False)
	monkeypatch.setenv('OPENAI_API_KEY', 'sk-unrelated-openai-key')

	with pytest.raises(ModelProviderError) as exc_info:
		ChatRuncrate(model='deepseek-ai/DeepSeek-V4.1-Flash').get_client()

	assert exc_info.value.status_code == 401
	assert 'sk-unrelated-openai-key' not in str(exc_info.value)


def _completion(content: str) -> dict:
	return {
		'id': 'chatcmpl-test',
		'object': 'chat.completion',
		'created': 0,
		'model': 'deepseek-ai/DeepSeek-V4.1-Flash',
		'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': content}, 'finish_reason': 'stop'}],
		'usage': {'prompt_tokens': 7, 'completion_tokens': 3, 'total_tokens': 10},
	}


async def test_runcrate_ainvoke_sends_bearer_key_and_parses_text(httpserver: HTTPServer) -> None:
	"""A plain call posts to /chat/completions with the Runcrate key and returns the text and usage."""
	httpserver.expect_request(
		'/v1/chat/completions', method='POST', headers={'Authorization': 'Bearer runcrate-key'}
	).respond_with_json(_completion('Paris'))

	chat = ChatRuncrate(model='deepseek-ai/DeepSeek-V4.1-Flash', api_key='runcrate-key', base_url=httpserver.url_for('/v1'))
	result = await chat.ainvoke([UserMessage(content='Capital of France?')])

	assert result.completion == 'Paris'
	assert result.usage is not None
	assert (result.usage.prompt_tokens, result.usage.completion_tokens, result.usage.total_tokens) == (7, 3, 10)


async def test_runcrate_ainvoke_structured_output_sends_json_schema(httpserver: HTTPServer) -> None:
	"""With an output format the request carries a JSON schema and the reply is parsed into the model."""

	class Answer(BaseModel):
		city: str

	httpserver.expect_request('/v1/chat/completions', method='POST').respond_with_json(_completion('{"city": "Paris"}'))

	chat = ChatRuncrate(model='deepseek-ai/DeepSeek-V4.1-Flash', api_key='runcrate-key', base_url=httpserver.url_for('/v1'))
	result = await chat.ainvoke([UserMessage(content='Capital of France?')], output_format=Answer)

	assert result.completion == Answer(city='Paris')
	body = json.loads(httpserver.log[0][0].get_data())
	assert body['model'] == 'deepseek-ai/DeepSeek-V4.1-Flash'
	assert body['response_format']['type'] == 'json_schema'
	assert body['response_format']['json_schema']['name'] == 'agent_output'


async def test_runcrate_ainvoke_omits_unset_sampling_params(httpserver: HTTPServer) -> None:
	"""Runcrate rejects explicit nulls, so unset sampling params must be left out and set ones sent."""
	httpserver.expect_request('/v1/chat/completions', method='POST').respond_with_json(_completion('Paris'))
	messages = [UserMessage(content='Capital of France?')]

	await ChatRuncrate(model='m', api_key='k', base_url=httpserver.url_for('/v1')).ainvoke(messages)
	await ChatRuncrate(model='m', api_key='k', base_url=httpserver.url_for('/v1'), temperature=0.3, seed=7).ainvoke(messages)

	unset, configured = (json.loads(entry[0].get_data()) for entry in httpserver.log)
	assert not {'temperature', 'top_p', 'seed'} & unset.keys()
	assert (configured['temperature'], configured['seed']) == (0.3, 7)
	assert 'top_p' not in configured
