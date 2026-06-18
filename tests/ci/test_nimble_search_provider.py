"""Tests for the Nimble API-backed search engine on the native ``search`` action.

Per the repo's testing rules these use real objects — a real ``AsyncNimble``
client driven against a local ``pytest-httpserver`` — rather than mocks, and never
hit a real remote URL. The client is pointed at the local server via the
``NIMBLE_BASE_URL`` env var. ``nimble-python`` is the optional ``nimble`` extra; the
module skips cleanly when it is not installed.

The ``nimble_python``-not-installed branch (``service.py``: friendly install hint) is
not exercised here on purpose — the module is skipped when the package is absent.
"""

import pytest

pytest.importorskip('nimble_python')

from browser_use import BrowserProfile, BrowserSession
from browser_use.agent.views import ActionResult
from browser_use.tools.service import Tools, _search_nimble


def _search_payload() -> dict:
	return {
		'request_id': '00000000-0000-0000-0000-000000000000',
		'total_results': 2,
		'results': [
			{
				'title': 'Example One',
				'url': 'https://example.com/one',
				'content': 'First result content.',
				'description': 'First description.',
				'metadata': {'country': 'US', 'entity_type': 'organic', 'locale': 'en', 'position': 1},
			},
			{
				'title': 'Example Two',
				'url': 'https://example.com/two',
				'content': 'Second result content.',
				'description': 'Second description.',
				'metadata': {'country': 'US', 'entity_type': 'organic', 'locale': 'en', 'position': 2},
			},
		],
	}


def _point_client_at(httpserver, monkeypatch) -> None:
	"""Redirect the real AsyncNimble client at the local pytest-httpserver."""
	monkeypatch.setenv('NIMBLE_API_KEY', 'test-key')
	monkeypatch.setenv('NIMBLE_BASE_URL', httpserver.url_for('/').rstrip('/'))


# Real registry + real (headless) browser, mirroring tests/ci/test_search_find.py.


@pytest.fixture(scope='module')
async def browser_session():
	session = BrowserSession(browser_profile=BrowserProfile(headless=True, user_data_dir=None, keep_alive=True))
	await session.start()
	yield session
	await session.kill()


@pytest.fixture(scope='function')
def tools():
	return Tools()


# --- Through the real registered `search` action (engine routing + side-effects) ---


async def test_search_action_nimble_engine_returns_results_inline(tools, browser_session, httpserver, monkeypatch):
	"""engine='nimble' on the real search action returns structured results inline,
	without navigating the browser."""
	httpserver.expect_request('/v1/search', method='POST').respond_with_json(_search_payload())
	_point_client_at(httpserver, monkeypatch)

	url_before = await browser_session.get_current_page_url()
	result = await tools.search(query='browser use release notes', engine='nimble', browser_session=browser_session)

	assert isinstance(result, ActionResult)
	assert result.error is None
	assert result.include_extracted_content_only_once is True
	assert result.extracted_content is not None
	assert 'Example One' in result.extracted_content
	assert 'https://example.com/two' in result.extracted_content
	assert '2 results' in (result.long_term_memory or '')

	# The nimble path returns before any NavigateToUrlEvent, so the browser does not move.
	assert await browser_session.get_current_page_url() == url_before

	# The request really reached the API, carrying the tracking header.
	request, _ = httpserver.log[-1]
	assert request.headers.get('X-Client-Source') == 'browser-use'


async def test_search_action_nimble_missing_key(tools, browser_session, monkeypatch):
	"""Through the action: no key → friendly error, no API call, no navigation."""
	monkeypatch.delenv('NIMBLE_API_KEY', raising=False)

	url_before = await browser_session.get_current_page_url()
	result = await tools.search(query='anything', engine='nimble', browser_session=browser_session)

	assert result.error == 'NIMBLE_API_KEY environment variable not set'
	assert result.extracted_content is None
	assert await browser_session.get_current_page_url() == url_before


async def test_search_action_unknown_engine_errors(tools, browser_session):
	"""An unknown engine returns a clear ActionResult error, not a crash. nimble must
	NOT fall into this branch."""
	result = await tools.search(query='x', engine='altavista', browser_session=browser_session)

	assert isinstance(result, ActionResult)
	assert result.error is not None
	assert 'Unsupported search engine' in result.error
	assert 'altavista' in result.error


# --- Registration (mirrors tests/ci/test_search_find.py TestRegistration) ---


def test_search_action_registered(tools):
	"""The search action (which now routes engine='nimble') is registered."""
	assert 'search' in tools.registry.registry.actions


def test_search_action_excludable():
	"""Excluding 'search' removes the nimble entrypoint without breaking siblings."""
	excluded = Tools(exclude_actions=['search'])
	assert 'search' not in excluded.registry.registry.actions
	assert 'navigate' in excluded.registry.registry.actions


# --- Helper-level coverage of the nimble engine (no browser needed) ---


async def test_nimble_search_returns_structured_results(httpserver, monkeypatch):
	"""The nimble engine formats the API results into ActionResult.extracted_content."""
	httpserver.expect_request('/v1/search', method='POST').respond_with_json(_search_payload())
	_point_client_at(httpserver, monkeypatch)

	result = await _search_nimble('browser use release notes')

	assert isinstance(result, ActionResult)
	assert result.error is None
	assert result.include_extracted_content_only_once is True
	assert result.extracted_content is not None
	assert 'Example One' in result.extracted_content
	assert 'https://example.com/two' in result.extracted_content
	assert '2 results' in (result.long_term_memory or '')


async def test_nimble_search_missing_key_returns_friendly_error(monkeypatch):
	"""Without a key the engine returns a friendly error and never calls the API."""
	monkeypatch.delenv('NIMBLE_API_KEY', raising=False)

	result = await _search_nimble('anything')

	assert result.error == 'NIMBLE_API_KEY environment variable not set'
	assert result.extracted_content is None


async def test_nimble_search_handles_empty_results(httpserver, monkeypatch):
	"""An empty result set is reported without error."""
	payload = {'request_id': '00000000-0000-0000-0000-000000000000', 'total_results': 0, 'results': []}
	httpserver.expect_request('/v1/search', method='POST').respond_with_json(payload)
	_point_client_at(httpserver, monkeypatch)

	result = await _search_nimble('obscure query with no hits')

	assert result.error is None
	assert '0 results' in (result.extracted_content or '')
