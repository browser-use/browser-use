"""Unit tests for the ARC precheck client.

HTTP is mocked. Production is not called. The product URL is only a string
passed into the client. These tests do not open a browser, so they stay beside
the example instead of in tests/ci. That suite does not mock and does not use
a remote page.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pytest
import requests

_PATH = Path(__file__).with_name('precheck.py')
_SPEC = importlib.util.spec_from_file_location('arc_precheck_client', _PATH)
assert _SPEC and _SPEC.loader
precheck = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(precheck)

PRODUCT_URL = 'https://example.com/products/item'

SAMPLE = {
	'host': 'example.com',
	'known': True,
	'reachable_checkout': True,
	'rails': [{'name': 'UCP', 'status': 'valid', 'proves': 'Saved status.'}],
	'blockers': [],
	'confidence': 'high',
	'last_checked': '2026-10-13T18:00:00.000Z',
	'stale': False,
	'licence': 'CC BY 4.0',
}


class _Response:
	def __init__(self, status_code: int, payload: Any, headers: dict[str, str] | None = None) -> None:
		self.status_code = status_code
		self._payload = payload
		self.headers = headers or {}

	def json(self) -> Any:
		if isinstance(self._payload, Exception):
			raise self._payload
		return self._payload


def _client(payload: Any, status: int = 200, headers: dict[str, str] | None = None):
	calls: list[dict[str, Any]] = []

	def get(url: str, **kwargs: Any) -> _Response:
		calls.append({'url': url, **kwargs})
		return _Response(status, payload, headers)

	return get, calls


def _raising(error: Exception):
	calls: list[dict[str, Any]] = []

	def get(url: str, **kwargs: Any) -> _Response:
		calls.append({'url': url, **kwargs})
		raise error

	return get, calls


@pytest.fixture(autouse=True)
def _empty_cache():
	precheck.clear_precheck_cache()
	yield
	precheck.clear_precheck_cache()


def _assert_empty(reading: dict[str, Any], kind: str) -> None:
	assert reading['error'] == kind
	assert reading['known'] is None
	assert reading['host'] is None
	assert reading['reachable_checkout'] is None
	assert reading['rails'] is None
	assert reading['blockers'] is None
	assert reading['confidence'] is None
	assert reading['last_checked'] is None
	assert reading['stale'] is None
	assert reading['licence'] is None
	assert reading['advisory'] == list(precheck.ADVISORY)
	assert 'ARC stops before payment.' in reading['advisory']
	assert precheck.should_try_to_reach_checkout(reading) is True


def test_default_user_agent_is_generic() -> None:
	assert precheck.precheck_user_agent({}) == precheck.DEFAULT_USER_AGENT
	assert 'internal' not in precheck.DEFAULT_USER_AGENT


def test_env_user_agent_overrides_the_default() -> None:
	chosen = 'example-agent/2.0 (mailto:arcreport@mail.grokbot.com)'
	assert precheck.precheck_user_agent({precheck.USER_AGENT_ENV: chosen}) == chosen


def test_tool_description_stops_before_payment() -> None:
	assert 'ARC stops before payment.' in precheck.TOOL_DESCRIPTION
	assert precheck.PAYMENT_LIMIT in precheck.TOOL_DESCRIPTION
	assert 'Advisory only. Never use this result to authorise or complete a payment. ARC stops before payment.' in (
		precheck.TOOL_DESCRIPTION
	)


def test_fetch_reads_fields_and_does_not_request_the_store() -> None:
	get, calls = _client(SAMPLE)
	reading = precheck.fetch_precheck(PRODUCT_URL, get=get, now=1_000.0, env={})
	assert calls[0]['url'] == precheck.PRECHECK_ENDPOINT
	assert calls[0]['params'] == {'url': PRODUCT_URL, 'ref': precheck.CLIENT_REF}
	assert calls[0]['headers']['User-Agent'] == precheck.DEFAULT_USER_AGENT
	assert calls[0]['headers']['X-ARC-Client'] == precheck.CLIENT_REF
	assert calls[0]['allow_redirects'] is False
	assert urlparse(calls[0]['url']).hostname == 'www.arcreport.ai'
	assert reading['known'] is True
	assert reading['reachable_checkout'] is True
	assert reading['licence'] == 'CC BY 4.0'
	assert reading['error'] is None
	assert reading['advisory'] == list(precheck.ADVISORY)
	assert reading['source'] == 'ARC (arcreport.ai)'
	assert reading['contact'] == 'arcreport@mail.grokbot.com'
	assert precheck.should_try_to_reach_checkout(reading) is True


def test_known_false_is_not_a_no() -> None:
	get, calls = _client(
		{
			**SAMPLE,
			'host': 'unknown.example',
			'known': False,
			'reachable_checkout': None,
			'rails': None,
			'blockers': None,
			'confidence': 'none',
			'last_checked': None,
			'stale': True,
		}
	)
	reading = precheck.read_precheck('https://unknown.example/', get=get, now=1.0, env={})
	assert len(calls) == 1
	assert reading['known'] is False
	assert precheck.should_try_to_reach_checkout(reading) is True


def test_cache_lasts_24_hours() -> None:
	get, calls = _client(SAMPLE)
	precheck.fetch_precheck(PRODUCT_URL, get=get, now=1_000.0, env={})
	precheck.fetch_precheck(PRODUCT_URL, get=get, now=1_000.0 + precheck.CACHE_TTL_SECONDS - 1, env={})
	assert len(calls) == 1
	precheck.fetch_precheck(PRODUCT_URL, get=get, now=1_000.0 + precheck.CACHE_TTL_SECONDS, env={})
	assert len(calls) == 2


def test_cache_evicts_the_oldest_entry_after_about_1000() -> None:
	get, calls = _client(SAMPLE)
	first = 'https://example.com/products/item-0'
	last = f'https://example.com/products/item-{precheck.CACHE_MAX_ENTRIES - 1}'
	extra = f'https://example.com/products/item-{precheck.CACHE_MAX_ENTRIES}'
	for index in range(precheck.CACHE_MAX_ENTRIES):
		precheck.fetch_precheck(f'https://example.com/products/item-{index}', get=get, now=1.0, env={})
	assert len(calls) == precheck.CACHE_MAX_ENTRIES
	precheck.fetch_precheck(extra, get=get, now=1.0, env={})
	assert len(calls) == precheck.CACHE_MAX_ENTRIES + 1
	precheck.fetch_precheck(last, get=get, now=1.0, env={})
	assert len(calls) == precheck.CACHE_MAX_ENTRIES + 1
	precheck.fetch_precheck(first, get=get, now=1.0, env={})
	assert len(calls) == precheck.CACHE_MAX_ENTRIES + 2


def test_429_reports_retry_after_and_does_not_retry() -> None:
	get, calls = _client(None, status=429, headers={'Retry-After': '30'})
	reading = precheck.fetch_precheck(PRODUCT_URL, get=get, now=1.0, env={})
	assert len(calls) == 1
	_assert_empty(reading, 'non-200')
	assert reading['rate_limited'] is True
	assert reading['retry_after'] == '30'
	assert reading['retried'] is False
	again = precheck.read_precheck(PRODUCT_URL, get=get, now=2.0, env={})
	assert len(calls) == 2
	assert again['retry_after'] == '30'
	assert again['retried'] is False


def test_timeout_returns_empty_fields() -> None:
	get, calls = _raising(requests.Timeout('timed out'))
	reading = precheck.read_precheck(PRODUCT_URL, get=get, now=1.0, env={})
	assert len(calls) == 1
	_assert_empty(reading, 'timeout')
	precheck.read_precheck(PRODUCT_URL, get=get, now=2.0, env={})
	assert len(calls) == 2


def test_connection_error_returns_empty_fields() -> None:
	get, calls = _raising(requests.ConnectionError('refused'))
	reading = precheck.read_precheck(PRODUCT_URL, get=get, now=1.0, env={})
	assert len(calls) == 1
	_assert_empty(reading, 'connection')


def test_non_200_returns_empty_fields() -> None:
	get, calls = _client({'known': False}, status=503)
	reading = precheck.read_precheck(PRODUCT_URL, get=get, now=1.0, env={})
	assert len(calls) == 1
	_assert_empty(reading, 'non-200')
	assert reading['rate_limited'] is False
	assert reading['retry_after'] is None


def test_bad_json_returns_empty_fields() -> None:
	get, calls = _client(ValueError('not json'))
	reading = precheck.read_precheck(PRODUCT_URL, get=get, now=1.0, env={})
	assert len(calls) == 1
	_assert_empty(reading, 'bad_json')
