"""Tests for the MCP trust verification module."""

import pytest

from browser_use.mcp.trust import TrustChecker, TrustVerdict


@pytest.mark.asyncio
async def test_trusted_server_passes():
	"""A server with score above threshold is trusted."""

	async def mock_lookup(url):
		return TrustVerdict(server_url=url, score=0.85)

	checker = TrustChecker(min_score=0.7, lookup=mock_lookup)
	verdict = await checker.check('https://example.com/sse')
	assert verdict.is_trusted is True
	assert verdict.score == 0.85


@pytest.mark.asyncio
async def test_threshold_is_inclusive_at_boundary():
	"""A server with score == threshold is trusted (boundary case, locks down >=)."""

	async def mock_lookup(url):
		return TrustVerdict(server_url=url, score=0.7)

	checker = TrustChecker(min_score=0.7, lookup=mock_lookup)
	verdict = await checker.check('https://example.com/sse')
	assert verdict.is_trusted is True
	assert verdict.score == 0.7


@pytest.mark.asyncio
async def test_untrusted_server_fails():
	"""A server with score < threshold is not trusted."""

	async def mock_lookup(url):
		return TrustVerdict(server_url=url, score=0.3)

	checker = TrustChecker(min_score=0.7, lookup=mock_lookup)
	verdict = await checker.check('https://bad.com/sse')
	assert verdict.is_trusted is False
	assert 'below threshold' in verdict.reason


@pytest.mark.asyncio
async def test_unknown_score_fail_closed():
	"""Unknown score (None) is fail-closed by default — important for browser security."""

	async def mock_lookup(url):
		return TrustVerdict(server_url=url, score=None)

	checker = TrustChecker(min_score=0.7, lookup=mock_lookup, allow_unknown=False)
	verdict = await checker.check('https://unknown.com/sse')
	assert verdict.is_trusted is False
	assert 'unknown' in verdict.reason.lower()


@pytest.mark.asyncio
async def test_unknown_score_fail_open():
	"""Unknown score (None) can be allowed with allow_unknown=True."""

	async def mock_lookup(url):
		return TrustVerdict(server_url=url, score=None)

	checker = TrustChecker(min_score=0.7, lookup=mock_lookup, allow_unknown=True)
	verdict = await checker.check('https://unknown.com/sse')
	assert verdict.is_trusted is True


@pytest.mark.asyncio
async def test_lookup_exception_is_fail_closed_even_with_allow_unknown():
	"""Lookup exceptions must not be trusted even when allow_unknown=True.

	This is the critical fix: allow_unknown applies ONLY to explicit
	TrustVerdict(score=None) results. Lookup exceptions (network errors,
	malformed responses, unhandled bugs) are always fail-closed because no
	verdict was produced.
	"""

	async def mock_lookup(url):
		raise RuntimeError('lookup blew up')

	checker = TrustChecker(min_score=0.7, lookup=mock_lookup, allow_unknown=True)
	trusted = await checker.filter_trusted(['https://boom.com/sse'])
	assert trusted == []


@pytest.mark.asyncio
async def test_filter_trusted_keeps_good_servers():
	"""filter_trusted returns only trusted server URLs."""

	async def mock_lookup(url):
		if 'good' in url:
			return TrustVerdict(server_url=url, score=0.9)
		return TrustVerdict(server_url=url, score=0.1)

	checker = TrustChecker(min_score=0.7, lookup=mock_lookup)
	urls = ['https://good1.com/sse', 'https://bad1.com/sse', 'https://good2.com/sse']
	trusted = await checker.filter_trusted(urls)
	assert len(trusted) == 2
	assert 'good1.com' in trusted[0]
	assert 'good2.com' in trusted[1]


@pytest.mark.asyncio
async def test_default_threshold_is_strict():
	"""Default threshold is 0.7 — stricter than a general 0.5, for browser security."""
	checker = TrustChecker()
	assert checker.min_score == 0.7
	assert checker.allow_unknown is False


@pytest.mark.asyncio
async def test_strip_credentials_from_url():
	"""The default lookup strips userinfo and secret query params before
	sending a URL to a third-party API."""
	from browser_use.mcp.trust import _strip_credentials_from_url

	# Basic auth in userinfo
	assert _strip_credentials_from_url('https://user:pass@host/path') == 'https://host/path'
	# Secret query param
	assert _strip_credentials_from_url('https://host/path?api_key=secret') == 'https://host/path'
	assert _strip_credentials_from_url('https://host/path?token=abc') == 'https://host/path'
	# Non-secret query param is preserved
	assert _strip_credentials_from_url('https://host/path?page=2') == 'https://host/path?page=2'
	# Port is preserved
	assert _strip_credentials_from_url('https://host:8443/path') == 'https://host:8443/path'


@pytest.mark.asyncio
async def test_default_lookup_rejects_out_of_range_score():
	"""A 200 response with score=200 (out of range) must be fail-closed, not
	normalized to 2.0 and trusted."""
	from unittest.mock import AsyncMock, MagicMock, patch

	# Build a fake httpx response with score=200
	fake_response = MagicMock()
	fake_response.status_code = 200
	fake_response.json.return_value = {'trust_score': 200, 'total_calls': 5}

	fake_client = MagicMock()
	fake_client.__aenter__ = AsyncMock(return_value=fake_client)
	fake_client.__aexit__ = AsyncMock(return_value=None)
	fake_client.get = AsyncMock(return_value=fake_response)

	with patch('browser_use.mcp.trust.httpx.AsyncClient', return_value=fake_client):
		from browser_use.mcp.trust import _default_trust_lookup

		verdict = await _default_trust_lookup('https://example.com/sse')
		assert verdict.score is None
		assert 'out-of-range' in verdict.reason


@pytest.mark.asyncio
async def test_default_lookup_handles_malformed_200():
	"""A 200 with malformed JSON returns a fail-closed verdict instead of raising."""
	from unittest.mock import AsyncMock, MagicMock, patch

	fake_response = MagicMock()
	fake_response.status_code = 200
	fake_response.json.side_effect = ValueError('not JSON')

	fake_client = MagicMock()
	fake_client.__aenter__ = AsyncMock(return_value=fake_client)
	fake_client.__aexit__ = AsyncMock(return_value=None)
	fake_client.get = AsyncMock(return_value=fake_response)

	with patch('browser_use.mcp.trust.httpx.AsyncClient', return_value=fake_client):
		from browser_use.mcp.trust import _default_trust_lookup

		verdict = await _default_trust_lookup('https://example.com/sse')
		assert verdict.score is None
		assert 'malformed' in verdict.reason
