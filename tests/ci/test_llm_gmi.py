"""Tests for the native ChatGMI provider. HTTP goes to a real local server (pytest-httpserver).

The only substitution is in the pricing test, which replaces the OpenRouter price lookup so it makes no network call.
"""

from typing import Any

import pytest
from pydantic import BaseModel
from pytest_httpserver import HTTPServer

from browser_use.llm.exceptions import ModelOutputTruncatedError, ModelProviderError, ModelRateLimitError
from browser_use.llm.gmi import chat as gmi_chat
from browser_use.llm.gmi.chat import ChatGMI, _gmi_error_detail
from browser_use.llm.messages import SystemMessage, UserMessage
from browser_use.llm.views import ChatInvokeUsage
from browser_use.tokens.service import TokenCost

MODEL = 'deepseek-ai/DeepSeek-V4-Flash'
GEMINI = 'google/gemini-3.6-flash'


class Person(BaseModel):
	name: str
	age: int


class Step(BaseModel):
	"""Has a union (anyOf) like the real Agent output, which is where Gemini rejected additionalProperties."""

	action: list[Person | None]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.delenv('GMI_API_KEY', raising=False)


def _completion(content: str | None, finish_reason: str = 'stop', cached: int | None = None) -> dict[str, Any]:
	usage: dict[str, Any] = {'prompt_tokens': 5, 'completion_tokens': 3, 'total_tokens': 8}
	if cached is not None:
		usage['prompt_tokens_details'] = {'cached_tokens': cached}
	return {
		'id': 'x',
		'object': 'chat.completion',
		'created': 0,
		'model': 'm',
		'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': content}, 'finish_reason': finish_reason}],
		'usage': usage,
	}


def _serve(httpserver: HTTPServer, payload: dict[str, Any], status: int = 200) -> None:
	httpserver.expect_request('/v1/chat/completions', method='POST').respond_with_json(payload, status=status)


def _llm(httpserver: HTTPServer, model: str = MODEL, **kwargs: Any) -> ChatGMI:
	kwargs.setdefault('api_key', 'test-key')
	return ChatGMI(model=model, base_url=httpserver.url_for('/v1'), max_retries=0, **kwargs)


def _last_request(httpserver: HTTPServer):
	return httpserver.log[-1][0]


def _contains_key(node: Any, key: str) -> bool:
	if isinstance(node, dict):
		return key in node or any(_contains_key(v, key) for v in node.values())
	if isinstance(node, list):
		return any(_contains_key(v, key) for v in node)
	return False


MESSAGES = [
	SystemMessage(content='You are concise.'),
	UserMessage(content='Give a person named Alice who is 30. Respond in JSON.'),
]


# --- defaults and request shape ---------------------------------------------------------------


def test_defaults() -> None:
	chat = ChatGMI(model=MODEL, api_key='test-key')

	assert chat.provider == 'gmi'
	assert chat.name == MODEL
	assert str(chat.base_url) == 'https://api.gmi-serving.com/v1'
	assert chat._get_request_params() == {}


async def test_unset_params_are_not_sent_and_frequency_penalty_never_is(httpserver: HTTPServer) -> None:
	"""GMI rejects frequency_penalty on some models, and the SDK would send None as JSON null."""
	_serve(httpserver, _completion('pong'))

	await _llm(httpserver).ainvoke(MESSAGES)

	body = _last_request(httpserver).get_json()
	assert set(body) == {'model', 'messages'}
	assert 'frequency_penalty' not in body


async def test_params_are_sent_when_set(httpserver: HTTPServer) -> None:
	_serve(httpserver, _completion('pong'))

	await _llm(httpserver, temperature=0.2, top_p=0.9, seed=7, max_completion_tokens=256).ainvoke(MESSAGES)

	body = _last_request(httpserver).get_json()
	assert (body['temperature'], body['top_p'], body['seed'], body['max_completion_tokens']) == (0.2, 0.9, 7, 256)


async def test_text_completion_returns_content_usage_and_stop_reason(httpserver: HTTPServer) -> None:
	_serve(httpserver, _completion('pong', cached=2))

	result = await _llm(httpserver).ainvoke(MESSAGES)

	assert result.completion == 'pong'
	assert result.stop_reason == 'stop'
	assert result.usage is not None
	assert (result.usage.prompt_tokens, result.usage.prompt_cached_tokens, result.usage.total_tokens) == (5, 2, 8)


async def test_structured_output_sends_strict_schema_and_parses(httpserver: HTTPServer) -> None:
	_serve(httpserver, _completion('{"name":"Alice","age":30}'))

	result = await _llm(httpserver).ainvoke(MESSAGES, output_format=Person)

	assert result.completion == Person(name='Alice', age=30)
	response_format = _last_request(httpserver).get_json()['response_format']
	assert response_format['type'] == 'json_schema'
	assert response_format['json_schema']['strict'] is True
	assert response_format['json_schema']['name'] == 'agent_output'


# --- API key handling (the credential-leak regression from the OrcaRouter review) --------------


async def test_never_falls_back_to_the_openai_key(httpserver: HTTPServer, monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.setenv('OPENAI_API_KEY', 'sk-unrelated-openai-key')
	chat = ChatGMI(model=MODEL, base_url=httpserver.url_for('/v1'), max_retries=0)

	with pytest.raises(ModelProviderError) as exc_info:
		await chat.ainvoke(MESSAGES)

	assert exc_info.value.status_code == 401
	assert 'sk-unrelated-openai-key' not in str(exc_info.value)
	assert httpserver.log == []  # nothing was sent anywhere


async def test_reads_gmi_api_key_from_env(httpserver: HTTPServer, monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.setenv('GMI_API_KEY', 'env-gmi-key')
	monkeypatch.setenv('OPENAI_API_KEY', 'sk-unrelated-openai-key')
	_serve(httpserver, _completion('pong'))

	await ChatGMI(model=MODEL, base_url=httpserver.url_for('/v1'), max_retries=0).ainvoke(MESSAGES)

	assert _last_request(httpserver).headers['Authorization'] == 'Bearer env-gmi-key'


async def test_explicit_api_key_wins_over_env(httpserver: HTTPServer, monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.setenv('GMI_API_KEY', 'env-gmi-key')
	_serve(httpserver, _completion('pong'))

	await _llm(httpserver, api_key='explicit-key').ainvoke(MESSAGES)

	assert _last_request(httpserver).headers['Authorization'] == 'Bearer explicit-key'


# --- GMI wraps upstream failures; the real reason is in error.details ------------------------------

PENALTY_DETAILS = '{\n  "error": {\n    "code": 400,\n    "message": "Penalty is not enabled for this model",\n    "status": "INVALID_ARGUMENT"\n  }\n}\n'
JSON_WORD_DETAILS = (
	'{"error":{"code":"invalid_parameter_error","message":"\'messages\' must contain the word \'json\' in some form."}}'
)


@pytest.mark.parametrize(
	('details', 'expected'),
	[
		(PENALTY_DETAILS, 'Penalty is not enabled for this model'),
		(JSON_WORD_DETAILS, "'messages' must contain the word 'json' in some form."),
		('upstream said: plain text', 'upstream said: plain text'),
	],
)
async def test_gmi_error_details_are_surfaced(httpserver: HTTPServer, details: str, expected: str) -> None:
	body = {
		'error': {'message': 'Backend request failed with status 400', 'type': 'backend_error', 'code': 400, 'details': details}
	}
	_serve(httpserver, body, status=400)

	with pytest.raises(ModelProviderError) as exc_info:
		await _llm(httpserver).ainvoke(MESSAGES)

	assert exc_info.value.status_code == 400
	assert 'Backend request failed with status 400' in exc_info.value.message
	assert exc_info.value.message.endswith(expected)


async def test_errors_without_details_keep_status_and_message(httpserver: HTTPServer) -> None:
	_serve(
		httpserver, {'error': {'message': 'Max retries (2) exhausted for model: m', 'type': 'max_retries_exceeded'}}, status=503
	)

	with pytest.raises(ModelProviderError) as exc_info:
		await _llm(httpserver).ainvoke(MESSAGES)

	assert exc_info.value.status_code == 503
	assert exc_info.value.message == 'Error code: 503 - Max retries (2) exhausted for model: m'


async def test_rate_limit_maps_to_rate_limit_error(httpserver: HTTPServer) -> None:
	_serve(httpserver, {'error': {'message': 'Too many requests'}}, status=429)

	with pytest.raises(ModelRateLimitError) as exc_info:
		await _llm(httpserver).ainvoke(MESSAGES)

	assert exc_info.value.status_code == 429


@pytest.mark.parametrize(
	'body',
	[None, 'text', {}, {'details': None}, {'details': '   '}, {'details': 5}],
)
def test_error_detail_ignores_missing_or_unusable_details(body: object) -> None:
	assert _gmi_error_detail(body) is None


def test_error_detail_is_truncated() -> None:
	assert len(_gmi_error_detail({'details': 'x' * 2000}) or '') == 500


# --- malformed or unusual responses --------------------------------------------------------------


async def test_empty_choices_is_a_502(httpserver: HTTPServer) -> None:
	_serve(httpserver, {**_completion('x'), 'choices': []})

	with pytest.raises(ModelProviderError) as exc_info:
		await _llm(httpserver).ainvoke(MESSAGES)

	assert exc_info.value.status_code == 502
	assert 'missing or empty `choices`' in exc_info.value.message


@pytest.mark.parametrize('content', [None, ''])
async def test_structured_output_without_content_is_a_500(httpserver: HTTPServer, content: str | None) -> None:
	_serve(httpserver, _completion(content))

	with pytest.raises(ModelProviderError) as exc_info:
		await _llm(httpserver).ainvoke(MESSAGES, output_format=Person)

	assert exc_info.value.status_code == 500


async def test_truncated_structured_output_raises_truncation_error(httpserver: HTTPServer) -> None:
	_serve(httpserver, _completion(None, finish_reason='length'))

	with pytest.raises(ModelOutputTruncatedError) as exc_info:
		await _llm(httpserver, max_completion_tokens=64).ainvoke(MESSAGES, output_format=Person)

	assert exc_info.value.status_code == 400
	assert 'max_completion_tokens=64' in exc_info.value.message


# --- Gemini rejects additionalProperties inside anyOf (GMI forwards to Google's response_schema) ----------


async def test_gemini_schema_has_no_additional_properties(httpserver: HTTPServer) -> None:
	_serve(httpserver, _completion('{"action":[]}'))

	await _llm(httpserver, model=GEMINI).ainvoke(MESSAGES, output_format=Step)

	schema = _last_request(httpserver).get_json()['response_format']['json_schema']['schema']
	assert not _contains_key(schema, 'additionalProperties')


async def test_other_models_keep_additional_properties_false(httpserver: HTTPServer) -> None:
	_serve(httpserver, _completion('{"action":[]}'))

	await _llm(httpserver).ainvoke(MESSAGES, output_format=Step)

	schema = _last_request(httpserver).get_json()['response_format']['json_schema']['schema']
	assert schema['additionalProperties'] is False


@pytest.mark.parametrize(('model', 'override', 'stripped'), [(MODEL, True, True), (GEMINI, False, False)])
async def test_schema_cleanup_can_be_overridden(httpserver: HTTPServer, model: str, override: bool, stripped: bool) -> None:
	_serve(httpserver, _completion('{"action":[]}'))

	await _llm(httpserver, model=model, remove_additional_properties_from_schema=override).ainvoke(MESSAGES, output_format=Step)

	schema = _last_request(httpserver).get_json()['response_format']['json_schema']['schema']
	assert _contains_key(schema, 'additionalProperties') is not stripped


def test_stripping_keeps_a_field_that_is_named_additional_properties() -> None:
	schema = {
		'type': 'object',
		'additionalProperties': False,
		'properties': {'additionalProperties': {'type': 'string'}, 'x': {'type': 'object', 'additionalProperties': False}},
	}

	cleaned = gmi_chat._strip_additional_properties(schema)

	assert cleaned == {
		'type': 'object',
		'properties': {'additionalProperties': {'type': 'string'}, 'x': {'type': 'object'}},
	}
	assert schema['additionalProperties'] is False  # input is not mutated


# --- token cost attribution -----------------------------------------------------------------------


async def test_registered_gmi_llm_never_matches_upstream_pricing(monkeypatch: pytest.MonkeyPatch) -> None:
	"""GMI ids look like OpenRouter ids (`google/gemini-3.6-flash`); another gateway's prices must not be attributed to GMI."""
	seen_model_names = []

	async def fake_openrouter_pricing(model_name: str):
		seen_model_names.append(model_name)
		return None

	monkeypatch.setattr('browser_use.tokens.service.get_openrouter_model_pricing', fake_openrouter_pricing)

	token_cost = TokenCost(include_cost=True)
	token_cost._initialized = True
	token_cost._pricing_data = {}
	token_cost.register_llm(ChatGMI(model=GEMINI, api_key='test-key'))

	cost = await token_cost.calculate_cost(
		GEMINI,
		ChatInvokeUsage(
			prompt_tokens=10,
			prompt_cached_tokens=None,
			prompt_cache_creation_tokens=None,
			prompt_image_tokens=None,
			completion_tokens=5,
			total_tokens=15,
		),
	)

	assert seen_model_names == ['gmi/google/gemini-3.6-flash']
	assert cost is None
