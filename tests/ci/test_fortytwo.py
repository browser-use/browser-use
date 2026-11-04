"""Behavioural coverage for the Fortytwo provider and isolated price identity."""

import json
import traceback
from contextlib import asynccontextmanager
from typing import Any, cast

import httpx
import pytest
from pydantic import BaseModel
from pydantic.v1 import BaseModel as LegacyBaseModel

from browser_use import ChatFortytwo
from browser_use.llm import ChatFortytwo as LlmChatFortytwo
from browser_use.llm.exceptions import ModelOutputTruncatedError, ModelProviderError, ModelRateLimitError
from browser_use.llm.messages import ContentPartImageParam, ContentPartTextParam, ImageURL, SystemMessage, UserMessage
from browser_use.llm.openai.chat import ChatOpenAI
from browser_use.llm.orcarouter.chat import ChatOrcaRouter
from browser_use.llm.views import ChatInvokeUsage
from browser_use.tokens.service import TokenCost

MODEL = 'qwen/qwen3.8-27b'
PRICE_NAME = f'fortytwo/{MODEL}'
SECRET = 'synthetic-secret-not-to-be-logged'


class Answer(BaseModel):
	value: int


class LegacyAnswer(LegacyBaseModel):
	value: int


def completion(content: str | None = 'hello') -> dict[str, Any]:
	return {
		'id': 'chatcmpl-fixture',
		'object': 'chat.completion',
		'created': 1,
		'model': MODEL,
		'choices': [{'index': 0, 'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': content}}],
		'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15, 'prompt_tokens_details': {'cached_tokens': 3}},
	}


@asynccontextmanager
async def controlled_client(
	payload: dict[str, Any] | None = None, status: int = 200, connection_error: bool = False, **options: Any
):
	seen: list[httpx.Request] = []

	def handle(request: httpx.Request) -> httpx.Response:
		seen.append(request)
		if connection_error:
			raise httpx.ConnectError(SECRET, request=request)
		return httpx.Response(status, json=completion() if payload is None else payload)

	async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as transport:
		config = {'api_key': 'fortytwo-unit-key', 'http_client': transport, 'max_retries': 0, **options}
		chat = ChatFortytwo(**config)
		try:
			yield chat, seen
		finally:
			if chat._client is not None:
				await chat.get_client().close()


def usage() -> ChatInvokeUsage:
	return ChatInvokeUsage(
		prompt_tokens=10,
		prompt_cached_tokens=3,
		prompt_cache_creation_tokens=None,
		prompt_image_tokens=None,
		completion_tokens=5,
		total_tokens=15,
	)


def tariff(rate: float = 2) -> dict[str, Any]:
	# Deliberately synthetic rates; this is not a pinned public Fortytwo tariff.
	return {'input_cost_per_token': rate, 'output_cost_per_token': 3, 'cache_read_input_token_cost': 0.5}


def priced_service(monkeypatch: pytest.MonkeyPatch) -> TokenCost:
	monkeypatch.setattr('browser_use.tokens.service.CUSTOM_MODEL_PRICING', {})
	service = TokenCost(include_cost=True)
	service._initialized = True
	service._pricing_data = {PRICE_NAME: tariff(), MODEL: tariff(99), f'orcarouter/{MODEL}': tariff(7)}
	return service


def test_public_defaults_and_repr() -> None:
	assert ChatFortytwo is LlmChatFortytwo
	chat = ChatFortytwo(
		api_key=SECRET, default_headers={'Authorization': SECRET}, default_query={'secret': SECRET}, extra_body={'secret': SECRET}
	)
	assert (chat.provider, chat.name, str(chat.base_url)) == ('fortytwo', MODEL, 'https://api.fortytwo.network/v1')
	assert SECRET not in repr(chat)


async def test_plain_request_overrides_headers_and_usage() -> None:
	headers = {'x-title': 'caller', 'X-Custom': 'kept'}
	async with controlled_client(
		model='custom/model',
		base_url=httpx.URL('https://local.invalid/custom/v1'),
		default_headers=headers,
		temperature=0.2,
		top_p=0.8,
		seed=42,
		extra_body={'max_completion_tokens': 123},
	) as (chat, seen):
		result = await chat.ainvoke([UserMessage(content='hello')])
		assert result.completion == 'hello'
		assert result.usage is not None
		assert (
			result.usage.prompt_tokens,
			result.usage.completion_tokens,
			result.usage.total_tokens,
			result.usage.prompt_cached_tokens,
		) == (10, 5, 15, 3)
		request = seen[0]
		assert str(request.url) == 'https://local.invalid/custom/v1/chat/completions'
		assert request.headers.get_list('x-title') == ['caller']
		assert request.headers['x-custom'] == 'kept'
		body = json.loads(request.content)
		assert body['model'] == 'custom/model'
		assert (body['temperature'], body['top_p'], body['seed'], body['max_completion_tokens']) == (0.2, 0.8, 42, 123)
		assert headers == {'x-title': 'caller', 'X-Custom': 'kept'}


@pytest.mark.parametrize(
	'headers,expected',
	[(None, 'browser-use'), ({'X-Title': 'one', 'x-title': 'two'}, 'two'), ({'X-Other': 'kept'}, 'browser-use')],
)
async def test_effective_attribution_and_optional_omission(headers, expected) -> None:
	async with controlled_client(default_headers=headers) as (chat, seen):
		await chat.ainvoke([UserMessage(content='hello')])
		assert seen[0].headers.get_list('x-title') == [expected]
		body = json.loads(seen[0].content)
		assert not {'temperature', 'top_p', 'seed', 'reasoning_effort', 'reasoning', 'frequency_penalty'}.intersection(body)


@pytest.mark.parametrize(
	'explicit,expected', [(None, 'fortytwo-env-key'), ('explicit-key', 'explicit-key'), ('', 'fortytwo-env-key')]
)
async def test_key_precedence(monkeypatch: pytest.MonkeyPatch, explicit, expected) -> None:
	monkeypatch.setenv('FORTYTWO_API_KEY', 'fortytwo-env-key')
	monkeypatch.setenv('OPENAI_API_KEY', 'unrelated-openai-key')
	async with controlled_client(api_key=explicit) as (chat, seen):
		await chat.ainvoke([UserMessage(content='hello')])
		assert seen[0].headers['authorization'] == f'Bearer {expected}'


async def test_missing_key_cannot_fall_back(monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.delenv('FORTYTWO_API_KEY', raising=False)
	monkeypatch.setenv('OPENAI_API_KEY', SECRET)
	async with controlled_client(api_key=None) as (chat, seen):
		with pytest.raises(ModelProviderError) as exc:
			await chat.ainvoke([UserMessage(content='hello')])
		assert exc.value.status_code == 401
		assert SECRET not in ''.join(traceback.format_exception(exc.value))
		assert not seen


async def test_strict_v2_and_typed_usage() -> None:
	payload = completion('{"value":7}')
	payload['usage'].pop('prompt_tokens_details')
	async with controlled_client(payload) as (chat, seen):
		result = await chat.ainvoke([UserMessage(content='hello')], Answer)
		assert isinstance(result.completion, Answer) and result.completion.value == 7
		assert result.usage and result.usage.prompt_cached_tokens is None
		fmt = json.loads(seen[0].content)['response_format']
		assert fmt['type'] == 'json_schema' and fmt['json_schema']['strict'] is True
		assert fmt['json_schema']['schema']['additionalProperties'] is False


@pytest.mark.parametrize('output_type', [LegacyAnswer, dict, object])
async def test_unsupported_output_type_is_local(output_type) -> None:
	async with controlled_client() as (chat, seen):
		with pytest.raises(ModelProviderError) as exc:
			await chat.ainvoke([UserMessage(content='hello')], cast(Any, output_type))
		assert exc.value.status_code == 400 and not seen


@pytest.mark.parametrize(
	'image',
	[
		'data:image/png;base64,AAAA',
		'data:image/jpeg;base64,BBBB',
		'data:image/webp;base64,CCCC',
		'https://fixture.invalid/image.png',
	],
)
async def test_image_representation_is_preserved(image: str) -> None:
	messages = [
		SystemMessage(content='Follow instructions'),
		UserMessage(
			content=[ContentPartTextParam(text='Look'), ContentPartImageParam(image_url=ImageURL(url=image, detail='high'))]
		),
	]
	async with controlled_client() as (chat, seen):
		await chat.ainvoke(messages)
		body = json.loads(seen[0].content)
		assert body['messages'] == [
			{'role': 'system', 'content': 'Follow instructions'},
			{
				'role': 'user',
				'content': [
					{'type': 'text', 'text': 'Look'},
					{'type': 'image_url', 'image_url': {'url': image, 'detail': 'high'}},
				],
			},
		]


@pytest.mark.parametrize('effort', ['none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'])
@pytest.mark.parametrize('typed', [False, True])
async def test_all_efforts_and_unset_typed(effort, typed) -> None:
	async with controlled_client(completion('{"value":1}'), reasoning_effort=effort) as (chat, seen):
		await chat.ainvoke([UserMessage(content='hello')], Answer if typed else None)
		assert json.loads(seen[0].content)['reasoning_effort'] == effort
	async with controlled_client(completion('{"value":1}')) as (chat, seen):
		await chat.ainvoke([UserMessage(content='hello')], Answer if typed else None)
		assert 'reasoning_effort' not in json.loads(seen[0].content)


@pytest.mark.parametrize(
	'extra',
	[
		{'model': 'other'},
		{'response_format': {'type': 'text'}},
		{'stream': True},
		{'reasoning_effort': 'high'},
		{'messages': []},
		{'temperature': 1},
		{'top_p': 0.5},
		{'seed': 1},
	],
)
async def test_reserved_extra_body_rejected(extra) -> None:
	async with controlled_client(extra_body=extra) as (chat, seen):
		with pytest.raises(ModelProviderError) as exc:
			await chat.ainvoke([UserMessage(content='hello')], Answer)
		assert exc.value.status_code == 400 and not seen


async def test_invalid_effort_and_no_usage() -> None:
	async with controlled_client(reasoning_effort=cast(Any, 'unsupported-secret')) as (chat, seen):
		with pytest.raises(ModelProviderError) as exc:
			await chat.ainvoke([UserMessage(content='hello')])
		assert exc.value.status_code == 400 and not seen
		assert 'unsupported-secret' not in str(exc.value)
	payload = completion()
	payload.pop('usage')
	async with controlled_client(payload) as (chat, _):
		assert (await chat.ainvoke([UserMessage(content='hello')])).usage is None


@pytest.mark.parametrize('typed', [False, True])
@pytest.mark.parametrize('missing', [False, True])
async def test_empty_or_missing_choices_keep_502(typed, missing) -> None:
	payload = completion()
	if missing:
		payload.pop('choices')
	else:
		payload['choices'] = []
	async with controlled_client(payload) as (chat, _):
		with pytest.raises(ModelProviderError) as exc:
			await chat.ainvoke([UserMessage(content='hello')], Answer if typed else None)
		assert exc.value.status_code == 502
		assert 'choices' in str(exc.value)


@pytest.mark.parametrize('content,status', [(None, 500), ('bad-json', 502), ('{"value":"' + SECRET + '"}', 502)])
async def test_structured_failure_is_safe(content, status) -> None:
	async with controlled_client(completion(content)) as (chat, _):
		with pytest.raises(ModelProviderError) as exc:
			await chat.ainvoke([UserMessage(content='hello')], Answer)
		assert exc.value.status_code == status
		assert SECRET not in ''.join(traceback.format_exception(exc.value))


@pytest.mark.parametrize('status', [401, 429, 503])
async def test_upstream_status_and_secret_redaction(status) -> None:
	payload = {'error': {'message': SECRET, 'type': 'invalid_request_error'}}
	async with controlled_client(payload, status) as (chat, _):
		with pytest.raises(ModelProviderError) as exc:
			await chat.ainvoke([UserMessage(content='hello')])
		assert exc.value.status_code == status
		assert isinstance(exc.value, ModelRateLimitError) is (status == 429)
		assert SECRET not in ''.join(traceback.format_exception(exc.value))


async def test_connection_error_is_safe() -> None:
	async with controlled_client(connection_error=True) as (chat, _):
		with pytest.raises(ModelProviderError) as exc:
			await chat.ainvoke([UserMessage(content='hello')])
		assert exc.value.status_code == 502
		assert SECRET not in ''.join(traceback.format_exception(exc.value))


@pytest.mark.parametrize('kind', ['named', 'named-openrouter-base', 'generic', 'generic-slash'])
async def test_exact_fortytwo_tariff_and_namespace(monkeypatch: pytest.MonkeyPatch, kind) -> None:
	service = priced_service(monkeypatch)
	chat = (
		ChatFortytwo(
			api_key='test',
			base_url=('https://openrouter.ai/api/v1' if kind == 'named-openrouter-base' else 'https://custom.invalid/v1'),
		)
		if kind.startswith('named')
		else ChatOpenAI(
			model=MODEL, api_key='test', base_url='https://api.fortytwo.network/v1' + ('/' if kind.endswith('slash') else '')
		)
	)
	service.register_llm(chat)
	cost = await service.calculate_cost(MODEL, usage())
	assert cost is not None
	row = tariff()
	assert cost.total_cost == pytest.approx(
		7 * row['input_cost_per_token'] + 3 * row['cache_read_input_token_cost'] + 5 * row['output_cost_per_token']
	)


async def test_no_borrowed_tariff_or_zero_price_claim(monkeypatch: pytest.MonkeyPatch) -> None:
	service = priced_service(monkeypatch)
	service._pricing_data = {MODEL: tariff(99)}
	monkeypatch.setattr('browser_use.tokens.service.CUSTOM_MODEL_PRICING', {MODEL: tariff(101)})

	async def forbidden_fallback(_):
		raise AssertionError('Fortytwo must not query OpenRouter fallback')

	monkeypatch.setattr('browser_use.tokens.service.get_openrouter_model_pricing', forbidden_fallback)
	service.register_llm(ChatFortytwo(api_key='test'))
	assert await service.calculate_cost(MODEL, usage()) is None
	service.add_usage(MODEL, usage())
	summary = await service.get_usage_summary()
	assert summary.total_tokens == 15 and summary.total_cost == 0.0
	assert summary.by_model[MODEL].cost == 0.0  # Legacy exclusion, not a free rate.


async def test_scoped_custom_tariff(monkeypatch: pytest.MonkeyPatch) -> None:
	service = priced_service(monkeypatch)
	monkeypatch.setattr('browser_use.tokens.service.CUSTOM_MODEL_PRICING', {MODEL: tariff(99), PRICE_NAME: tariff(5)})
	service.register_llm(ChatFortytwo(api_key='test'))
	cost = await service.calculate_cost(MODEL, usage())
	assert cost is not None and cost.new_prompt_cost == 7 * 5


@pytest.mark.parametrize('generic', [False, True])
@pytest.mark.parametrize('reverse', [False, True])
async def test_mixed_provider_ambiguity_is_sticky(monkeypatch: pytest.MonkeyPatch, generic, reverse) -> None:
	service = priced_service(monkeypatch)
	fortytwo = (
		ChatOpenAI(model=MODEL, api_key='test', base_url='https://api.fortytwo.network/v1/')
		if generic
		else ChatFortytwo(api_key='test')
	)
	other = ChatOpenAI(model=MODEL, api_key='test', base_url='https://other.invalid/v1')
	for chat in [other, fortytwo] if reverse else [fortytwo, other]:
		service.register_llm(chat)
	assert await service.calculate_cost(MODEL, usage()) is None
	for chat in [fortytwo, other, ChatFortytwo(api_key='new'), ChatOpenAI(model=MODEL, api_key='new')]:
		service.register_llm(chat)
		assert await service.calculate_cost(MODEL, usage()) is None
	service.add_usage(MODEL, usage())
	summary = await service.get_usage_summary()
	assert summary.total_tokens == 15 and summary.total_cost == 0.0
	assert await service.get_model_pricing(PRICE_NAME) is not None


@pytest.mark.parametrize('reverse', [False, True])
async def test_unrelated_collisions_keep_legacy_behaviour(monkeypatch: pytest.MonkeyPatch, reverse) -> None:
	service = priced_service(monkeypatch)
	generic = ChatOpenAI(model=MODEL, api_key='test', base_url='https://other.invalid/v1')
	orca = ChatOrcaRouter(model=MODEL, api_key='test')
	for chat in [orca, generic] if reverse else [generic, orca]:
		service.register_llm(chat)
	cost = await service.calculate_cost(MODEL, usage())
	assert cost is not None
	assert cost.new_prompt_cost == 7 * (99 if reverse else 7)


@pytest.mark.parametrize('finish_reason', ['stop', 'length', 'content_filter'])
@pytest.mark.parametrize('structured', [False, True])
async def test_completion_stop_reason(finish_reason: str, structured: bool) -> None:
	payload = completion('{"value": 7}' if structured else 'partial answer')
	payload['choices'][0]['finish_reason'] = finish_reason
	async with controlled_client(payload) as (chat, seen):
		if structured and finish_reason == 'length':
			with pytest.raises(ModelOutputTruncatedError) as exc:
				await chat.ainvoke([UserMessage(content='hello')], Answer)
			assert exc.value.status_code == 400
		else:
			result = await chat.ainvoke([UserMessage(content='hello')], Answer if structured else None)
			assert result.stop_reason == finish_reason
		assert len(seen) == 1


@pytest.mark.parametrize('content', [None, '{"value":'])
async def test_structured_truncation_before_missing_content_or_parse(content: str | None) -> None:
	payload = completion(content)
	payload['choices'][0]['finish_reason'] = 'length'
	async with controlled_client(payload) as (chat, seen):
		with pytest.raises(ModelOutputTruncatedError) as exc:
			await chat.ainvoke([UserMessage(content='hello')], Answer)
		assert exc.value.status_code == 400
		assert SECRET not in str(exc.value)
		assert len(seen) == 1


@pytest.mark.parametrize('named', [False, True])
async def test_already_namespaced_exact_tariff(monkeypatch: pytest.MonkeyPatch, named: bool) -> None:
	service = priced_service(monkeypatch)
	chat = (
		ChatFortytwo(model=PRICE_NAME, api_key='test')
		if named
		else ChatOpenAI(model=PRICE_NAME, api_key='test', base_url='https://api.fortytwo.network/v1/')
	)
	assert service._get_pricing_model_name(chat) == PRICE_NAME
	service.register_llm(chat)
	cost = await service.calculate_cost(PRICE_NAME, usage())
	assert cost is not None
	row = tariff()
	assert cost.total_cost == pytest.approx(
		7 * row['input_cost_per_token'] + 3 * row['cache_read_input_token_cost'] + 5 * row['output_cost_per_token']
	)
