"""DeepSeek and Cerebras must surface the provider's real status code and a clear error for empty responses."""

import httpx
import pytest
from pydantic import BaseModel

from browser_use.llm.cerebras.chat import ChatCerebras
from browser_use.llm.deepseek.chat import ChatDeepSeek
from browser_use.llm.exceptions import ModelProviderError, ModelRateLimitError
from browser_use.llm.messages import UserMessage


class Answer(BaseModel):
	answer: str


def _llm(cls, transport: httpx.MockTransport):
	client = httpx.AsyncClient(transport=transport)
	return cls(model='test-model', api_key='test-key', client_params={'http_client': client, 'max_retries': 0})


def _error_transport(status: int) -> httpx.MockTransport:
	return httpx.MockTransport(lambda request: httpx.Response(status, json={'error': {'message': f'upstream said {status}'}}))


def _empty_choices_transport() -> httpx.MockTransport:
	body = {'id': 'x', 'object': 'chat.completion', 'created': 0, 'model': 'test-model', 'choices': []}
	return httpx.MockTransport(lambda request: httpx.Response(200, json=body))


@pytest.mark.parametrize('cls', [ChatDeepSeek, ChatCerebras])
@pytest.mark.parametrize('status', [400, 401, 402, 500])
@pytest.mark.parametrize('structured', [False, True])
async def test_api_status_code_is_preserved(cls, status: int, structured: bool):
	llm = _llm(cls, _error_transport(status))
	with pytest.raises(ModelProviderError) as exc_info:
		await llm.ainvoke([UserMessage(content='hi')], output_format=Answer if structured else None)
	assert exc_info.value.status_code == status
	assert f'upstream said {status}' in exc_info.value.message


@pytest.mark.parametrize('cls', [ChatDeepSeek, ChatCerebras])
async def test_rate_limit_maps_to_rate_limit_error(cls):
	llm = _llm(cls, _error_transport(429))
	with pytest.raises(ModelRateLimitError) as exc_info:
		await llm.ainvoke([UserMessage(content='hi')])
	assert exc_info.value.status_code == 429


@pytest.mark.parametrize('cls', [ChatDeepSeek, ChatCerebras])
@pytest.mark.parametrize('structured', [False, True])
async def test_empty_choices_is_a_provider_error(cls, structured: bool):
	llm = _llm(cls, _empty_choices_transport())
	with pytest.raises(ModelProviderError, match='returned no choices'):
		await llm.ainvoke([UserMessage(content='hi')], output_format=Answer if structured else None)
