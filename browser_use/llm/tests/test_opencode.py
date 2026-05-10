"""
Tests for ChatOpenCode — OpenCode Go provider.

Live tests require the OPENCODE_API_KEY environment variable.
Unit tests run without any API key.
"""

import os

import pytest
from pydantic import BaseModel

from browser_use.llm.opencode.chat import OPENCODE_MODELS, ChatOpenCode, OPENCODE_BASE_URL
from browser_use.llm.messages import UserMessage, SystemMessage
from browser_use.llm.messages import ContentPartTextParam


# ---------------------------------------------------------------------------
# Unit tests (no API key required)
# ---------------------------------------------------------------------------

class TestChatOpenCodeUnit:
	"""Unit tests that do not require network access or an API key."""

	def test_provider_property(self):
		llm = ChatOpenCode(model='kimi-k2.6', api_key='dummy')
		assert llm.provider == 'opencode'

	def test_default_base_url(self):
		llm = ChatOpenCode(model='kimi-k2.6', api_key='dummy')
		assert str(llm.base_url) == OPENCODE_BASE_URL

	def test_custom_base_url(self):
		custom_url = 'https://custom.opencode.example/v1'
		llm = ChatOpenCode(model='kimi-k2.6', api_key='dummy', base_url=custom_url)
		assert str(llm.base_url) == custom_url

	def test_supported_models_list(self):
		assert 'kimi-k2.6' in OPENCODE_MODELS
		assert 'deepseek-v4-pro' in OPENCODE_MODELS
		assert 'mimo-v2.5-pro' in OPENCODE_MODELS
		assert len(OPENCODE_MODELS) == 14

	def test_name_property(self):
		llm = ChatOpenCode(model='glm-5.1', api_key='dummy')
		assert llm.name == 'glm-5.1'

	def test_lazy_import_via_llm_module(self):
		from browser_use import llm
		assert llm.ChatOpenCode is ChatOpenCode

	def test_get_llm_by_name_opencode(self):
		from browser_use.llm.models import get_llm_by_name
		# Supply a dummy key so ChatOpenCode is instantiated without env var
		os.environ.setdefault('OPENCODE_API_KEY', 'dummy')
		instance = get_llm_by_name('opencode_kimi_k2_6')
		assert isinstance(instance, ChatOpenCode)
		assert instance.provider == 'opencode'


# ---------------------------------------------------------------------------
# Live integration tests (require OPENCODE_API_KEY)
# ---------------------------------------------------------------------------

class CapitalResponse(BaseModel):
	country: str
	capital: str


class TestChatOpenCodeLive:
	"""Live tests that call the real OpenCode Go API."""

	SYSTEM_MSG = SystemMessage(content=[ContentPartTextParam(text='You are a helpful assistant.', type='text')])
	QUESTION = UserMessage(content='What is the capital of France? Answer in one word.')

	@pytest.fixture
	def llm(self):
		api_key = os.getenv('OPENCODE_API_KEY')
		if not api_key:
			pytest.skip('OPENCODE_API_KEY not set')
		return ChatOpenCode(model='kimi-k2.6', api_key=api_key, temperature=0)

	@pytest.mark.asyncio
	async def test_ainvoke_normal(self, llm):
		"""Test plain text response."""
		response = await llm.ainvoke([self.SYSTEM_MSG, self.QUESTION])
		assert isinstance(response.completion, str)
		assert 'paris' in response.completion.lower()

	@pytest.mark.asyncio
	async def test_ainvoke_structured(self, llm):
		"""Test structured JSON output."""
		response = await llm.ainvoke(
			[UserMessage(content='What is the capital of France?')],
			output_format=CapitalResponse,
		)
		assert isinstance(response.completion, CapitalResponse)
		assert response.completion.capital.lower() == 'paris'

	@pytest.mark.asyncio
	async def test_ainvoke_usage(self, llm):
		"""Verify usage metadata is returned."""
		response = await llm.ainvoke([self.QUESTION])
		if response.usage is not None:
			assert response.usage.prompt_tokens > 0
			assert response.usage.completion_tokens > 0
