"""Network failures in ChatBrowserUse must surface as ModelProviderError so the agent's fallback_llm can engage."""

import httpx
import pytest

from browser_use.llm.browser_use.chat import ChatBrowserUse
from browser_use.llm.exceptions import ModelProviderError
from browser_use.llm.messages import UserMessage


def _llm(max_retries: int) -> ChatBrowserUse:
	return ChatBrowserUse(api_key='test-key-not-real', max_retries=max_retries, retry_base_delay=0, retry_max_delay=0)


@pytest.mark.parametrize(
	'error, status_code',
	[
		(httpx.ReadTimeout('read timed out'), 504),
		(httpx.ConnectError('connection refused'), 502),
		(httpx.RemoteProtocolError('server disconnected without sending a response'), 502),
	],
)
async def test_exhausted_network_errors_are_provider_errors(error: httpx.TransportError, status_code: int):
	llm = _llm(max_retries=2)
	attempts = 0

	async def failing_request(payload):
		nonlocal attempts
		attempts += 1
		raise error

	llm._make_request = failing_request  # type: ignore[method-assign]

	with pytest.raises(ModelProviderError) as exc_info:
		await llm.ainvoke([UserMessage(content='hi')])
	assert exc_info.value.status_code == status_code
	assert exc_info.value.__cause__ is error
	assert attempts == 2


async def test_dropped_connection_is_retried():
	llm = _llm(max_retries=3)
	attempts = 0

	async def flaky_request(payload):
		nonlocal attempts
		attempts += 1
		if attempts == 1:
			raise httpx.RemoteProtocolError('server disconnected without sending a response')
		return {'completion': 'ok', 'usage': None}

	llm._make_request = flaky_request  # type: ignore[method-assign]

	result = await llm.ainvoke([UserMessage(content='hi')])
	assert result.completion == 'ok'
	assert attempts == 2


async def test_unexpected_errors_are_provider_errors():
	llm = _llm(max_retries=1)

	async def broken_request(payload):
		raise KeyError('completion')

	llm._make_request = broken_request  # type: ignore[method-assign]

	with pytest.raises(ModelProviderError, match='request failed'):
		await llm.ainvoke([UserMessage(content='hi')])
