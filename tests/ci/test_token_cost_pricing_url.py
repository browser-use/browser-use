from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_core import core_schema

from browser_use.agent.service import Agent
from browser_use.code_use.service import CodeAgent
from browser_use.llm.views import ChatInvokeUsage
from browser_use.tokens.service import TokenCost
from browser_use.tokens.views import CachedPricingData
from tests.ci.conftest import create_mock_llm


def pricing_entry(input_cost: float = 0.000001, output_cost: float = 0.000002) -> dict[str, float | None]:
	return {
		'input_cost_per_token': input_cost,
		'output_cost_per_token': output_cost,
		'cache_read_input_token_cost': None,
		'cache_creation_input_token_cost': None,
	}


def build_async_client(response_json: dict) -> AsyncMock:
	response = MagicMock()
	response.raise_for_status = MagicMock()
	response.json.return_value = response_json

	client = AsyncMock()
	client.get = AsyncMock(return_value=response)
	client.__aenter__ = AsyncMock(return_value=client)
	client.__aexit__ = AsyncMock(return_value=None)
	return client


class TestTokenCostPricingUrl:
	@pytest.mark.asyncio
	async def test_uses_default_pricing_url_when_no_override(self, monkeypatch, tmp_path):
		monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path))
		monkeypatch.delenv('BROWSER_USE_MODEL_PRICING_URL', raising=False)

		client = build_async_client({})

		with patch('browser_use.tokens.service.httpx.AsyncClient', return_value=client):
			token_cost = TokenCost(include_cost=True)
			await token_cost.initialize()

		assert token_cost.pricing_url == TokenCost.DEFAULT_PRICING_URL
		client.get.assert_awaited_once_with(TokenCost.DEFAULT_PRICING_URL, timeout=30)

	@pytest.mark.asyncio
	async def test_uses_env_pricing_url_override(self, monkeypatch, tmp_path):
		override_url = 'https://pricing.example/env.json'
		monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path))
		monkeypatch.setenv('BROWSER_USE_MODEL_PRICING_URL', override_url)

		client = build_async_client({})

		with patch('browser_use.tokens.service.httpx.AsyncClient', return_value=client):
			token_cost = TokenCost(include_cost=True)
			await token_cost.initialize()

		assert token_cost.pricing_url == override_url
		client.get.assert_awaited_once_with(override_url, timeout=30)

	@pytest.mark.asyncio
	async def test_constructor_pricing_url_overrides_env(self, monkeypatch, tmp_path):
		constructor_url = 'https://pricing.example/constructor.json'
		monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path))
		monkeypatch.setenv('BROWSER_USE_MODEL_PRICING_URL', 'https://pricing.example/env.json')

		client = build_async_client({})

		with patch('browser_use.tokens.service.httpx.AsyncClient', return_value=client):
			token_cost = TokenCost(include_cost=True, pricing_url=constructor_url)
			await token_cost.initialize()

		assert token_cost.pricing_url == constructor_url
		client.get.assert_awaited_once_with(constructor_url, timeout=30)

	@pytest.mark.asyncio
	async def test_ignores_cache_files_from_different_source_url(self, monkeypatch, tmp_path):
		override_url = 'https://pricing.example/right.json'
		cache_dir = tmp_path / 'browser_use' / 'token_cost'
		cache_dir.mkdir(parents=True)
		cache_file = cache_dir / 'pricing_wrong_source.json'
		cache_file.write_text(
			CachedPricingData(
				timestamp=datetime.now(),
				source_url='https://pricing.example/wrong.json',
				data={'wrong-model': pricing_entry()},
			).model_dump_json()
		)

		monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path))
		client = build_async_client({'right-model': pricing_entry()})

		with patch('browser_use.tokens.service.httpx.AsyncClient', return_value=client):
			token_cost = TokenCost(include_cost=True, pricing_url=override_url)
			pricing = await token_cost.get_model_pricing('right-model')

		assert pricing is not None
		assert pricing.model == 'right-model'
		assert cache_file.exists()
		client.get.assert_awaited_once_with(override_url, timeout=30)

	@pytest.mark.asyncio
	async def test_legacy_cache_without_source_url_works_for_default_url(self, monkeypatch, tmp_path):
		cache_dir = tmp_path / 'browser_use' / 'token_cost'
		cache_dir.mkdir(parents=True)
		cache_file = cache_dir / 'pricing_legacy.json'
		cache_file.write_text(
			CachedPricingData(timestamp=datetime.now(), data={'legacy-model': pricing_entry()}).model_dump_json(exclude_none=True)
		)

		monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path))
		monkeypatch.delenv('BROWSER_USE_MODEL_PRICING_URL', raising=False)

		with patch('browser_use.tokens.service.httpx.AsyncClient') as mock_client_class:
			token_cost = TokenCost(include_cost=True)
			pricing = await token_cost.get_model_pricing('legacy-model')

		assert pricing is not None
		assert pricing.model == 'legacy-model'
		mock_client_class.assert_not_called()

	@pytest.mark.asyncio
	async def test_custom_pricing_still_takes_precedence(self):
		token_cost = TokenCost(include_cost=False)
		token_cost._initialized = True
		token_cost._pricing_data = {
			'bu-1-0': {
				'input_cost_per_token': 999,
				'output_cost_per_token': 999,
			}
		}

		pricing = await token_cost.get_model_pricing('bu-1-0')

		assert pricing is not None
		assert pricing.input_cost_per_token != 999
		assert pricing.output_cost_per_token != 999

	@pytest.mark.asyncio
	async def test_override_source_can_supply_missing_qwen_pricing(self, monkeypatch, tmp_path):
		override_url = 'https://pricing.example/qwen.json'
		monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path))

		qwen_model = 'openrouter/qwen/qwen3.5-flash-02-23'
		client = build_async_client({qwen_model: pricing_entry(0.000003, 0.000007)})

		with patch('browser_use.tokens.service.httpx.AsyncClient', return_value=client):
			token_cost = TokenCost(include_cost=True, pricing_url=override_url)
			cost = await token_cost.calculate_cost(
				qwen_model,
				ChatInvokeUsage(
					prompt_tokens=100,
					prompt_cached_tokens=None,
					prompt_cache_creation_tokens=None,
					prompt_image_tokens=None,
					completion_tokens=25,
					total_tokens=125,
				),
			)

		assert cost is not None
		assert cost.total_cost > 0
		client.get.assert_awaited_once_with(override_url, timeout=30)


class TestPricingUrlPlumbing:
	def test_agent_passes_pricing_url_to_token_cost(self):
		llm = create_mock_llm()

		with patch('browser_use.agent.service.TokenCost') as token_cost_cls:
			token_cost = MagicMock()
			token_cost_cls.return_value = token_cost

			Agent(task='Test task', llm=llm, pricing_url='https://pricing.example/agent.json')

		token_cost_cls.assert_called_once_with(include_cost=False, pricing_url='https://pricing.example/agent.json')

	def test_code_agent_passes_pricing_url_to_token_cost(self):
		class MockChatBrowserUse:
			model = 'mock-browser-use'
			_verified_api_keys = True
			provider = 'mock'
			name = 'mock-browser-use'
			model_name = 'mock-browser-use'

			async def ainvoke(self, messages, output_format=None, **kwargs):
				raise NotImplementedError

			@classmethod
			def __get_pydantic_core_schema__(cls, source_type, handler):
				return core_schema.any_schema()

		llm = MockChatBrowserUse()

		with patch('browser_use.code_use.service.TokenCost') as token_cost_cls:
			token_cost = MagicMock()
			token_cost_cls.return_value = token_cost

			CodeAgent(task='Test task', llm=llm, pricing_url='https://pricing.example/code.json')

		token_cost_cls.assert_called_once_with(include_cost=False, pricing_url='https://pricing.example/code.json')
