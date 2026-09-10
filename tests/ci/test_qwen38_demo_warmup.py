"""Cold inference must not consume browser-agent steps or hide auth failures."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from examples.models.qwen38_modal import wait_for_inference


@pytest.mark.asyncio
async def test_warmup_recovers_after_cold_503() -> None:
	calls = 0

	def respond(request: httpx.Request) -> httpx.Response:
		nonlocal calls
		calls += 1
		assert request.headers['Authorization'] == 'Bearer test-key'
		if calls == 1:
			return httpx.Response(503)
		return httpx.Response(200, json={'choices': [{'message': {'content': 'OK'}}]})

	async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
		with patch('examples.models.qwen38_modal.asyncio.sleep', new=AsyncMock()):
			await wait_for_inference(client, 'https://inference.test/v1/', 'test-key', 'test-model')
	assert calls == 2


@pytest.mark.asyncio
async def test_warmup_rejects_bad_credentials_immediately() -> None:
	async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(401))) as client:
		with pytest.raises(httpx.HTTPStatusError):
			await wait_for_inference(client, 'https://inference.test/v1', 'test-key', 'test-model')


@pytest.mark.asyncio
async def test_warmup_rejects_empty_success_response() -> None:
	async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={'choices': []}))) as client:
		with pytest.raises(ValueError, match='no completion'):
			await wait_for_inference(client, 'https://inference.test/v1', 'test-key', 'test-model')


@pytest.mark.asyncio
async def test_warmup_has_a_deadline() -> None:
	clock = 0.0

	async def advance_clock(seconds: float) -> None:
		nonlocal clock
		clock += seconds

	async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(503))) as client:
		with (
			patch('examples.models.qwen38_modal.time', new=SimpleNamespace(monotonic=lambda: clock)),
			patch('examples.models.qwen38_modal.asyncio.sleep', side_effect=advance_clock),
		):
			with pytest.raises(TimeoutError, match='five minutes'):
				await wait_for_inference(client, 'https://inference.test/v1', 'test-key', 'test-model')
	assert clock == 300
