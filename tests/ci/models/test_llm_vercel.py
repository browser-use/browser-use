"""Regression tests for Vercel AI Gateway client setup."""

import pytest

from browser_use.llm.exceptions import ModelProviderError
from browser_use.llm.vercel.chat import ChatVercel


async def test_provider_key_does_not_fall_back_to_openai_key(monkeypatch: pytest.MonkeyPatch):
	monkeypatch.setenv('OPENAI_API_KEY', 'wrong-provider-key')
	monkeypatch.setenv('AI_GATEWAY_API_KEY', 'gateway-key')
	assert ChatVercel(model='openai/gpt-4o').get_client().api_key == 'gateway-key'

	monkeypatch.delenv('AI_GATEWAY_API_KEY')
	monkeypatch.delenv('VERCEL_OIDC_TOKEN', raising=False)
	with pytest.raises(ModelProviderError, match='Missing Vercel AI Gateway API key') as exc_info:
		await ChatVercel(model='openai/gpt-4o').ainvoke([])
	assert exc_info.value.status_code == 401
