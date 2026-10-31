"""Tests for the optional Desearch web search action."""

import json

import httpx
import pytest
from pydantic import ValidationError

from browser_use import Tools
from browser_use.integrations.desearch import DesearchSearchParams, register_desearch_actions


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [200, 401, 429, 500])
async def test_desearch_request_and_status(monkeypatch, status):
	monkeypatch.setenv('DESEARCH_API_KEY', 'test-secret')
	requests = []

	def respond(request):
		requests.append(request)
		return httpx.Response(
			status,
			json={'data': [{'title': 'Docs', 'link': 'https://example.com', 'snippet': 'Documentation'}] * 6},
		)

	client_class = httpx.AsyncClient
	monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: client_class(transport=httpx.MockTransport(respond), **kwargs))
	tools = Tools()
	register_desearch_actions(tools)
	result = await tools.registry.execute_action('desearch_search', {'query': 'browser automation', 'limit': 2})
	assert len(requests) == 1
	assert requests[0].method == 'GET'
	assert str(requests[0].url) == 'https://api.desearch.ai/web?query=browser+automation&num=2'
	assert requests[0].headers['Authorization'] == 'Bearer test-secret'
	if status == 200:
		assert result.error is None
		assert len(json.loads(result.extracted_content)['data']) == 2
	else:
		assert str(status) in result.error
		assert 'test-secret' not in result.error


@pytest.mark.asyncio
@pytest.mark.parametrize('response', ['empty', 'invalid', 'timeout'])
async def test_desearch_empty_and_failed_responses(monkeypatch, response):
	monkeypatch.setenv('DESEARCH_API_KEY', 'test-secret')

	def respond(request):
		if response == 'timeout':
			raise httpx.ReadTimeout('test-secret', request=request)
		return httpx.Response(200, json={'data': []} if response == 'empty' else {'unexpected': []})

	client_class = httpx.AsyncClient
	monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: client_class(transport=httpx.MockTransport(respond), **kwargs))
	tools = Tools()
	register_desearch_actions(tools)
	result = await tools.registry.execute_action('desearch_search', {'query': 'documentation'})
	if response == 'empty':
		assert json.loads(result.extracted_content) == {'data': []}
		assert result.error is None
	else:
		assert result.error
		assert 'test-secret' not in result.error


def test_desearch_requires_key(monkeypatch):
	monkeypatch.delenv('DESEARCH_API_KEY', raising=False)
	with pytest.raises(ValueError, match='DESEARCH_API_KEY is not set'):
		register_desearch_actions(Tools())


@pytest.mark.parametrize(
	'params', [{'query': ''}, {'query': '   '}, {'query': 'docs', 'limit': 0}, {'query': 'docs', 'limit': 6}]
)
def test_desearch_validates_input(params):
	with pytest.raises(ValidationError):
		DesearchSearchParams(**params)
