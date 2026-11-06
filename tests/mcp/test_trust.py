"""Tests for the MCP trust verification module."""

import asyncio

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


@pytest.mark.asyncio
async def test_strip_credentials_preserves_ipv6_brackets():
	"""IPv6 hostnames must keep their brackets so urlunsplit doesn't produce
	a malformed URL (cubic-dev-ai P2 #1, review 2026-11-06 01:54).
	"""
	from browser_use.mcp.trust import _strip_credentials_from_url

	# IPv6 with port — brackets must be re-added
	stripped = _strip_credentials_from_url('https://user:pass@[::1]:8443/path')
	assert stripped == 'https://[::1]:8443/path'
	# IPv6 without port
	stripped = _strip_credentials_from_url('https://[2001:db8::1]/path')
	assert stripped == 'https://[2001:db8::1]/path'


@pytest.mark.asyncio
async def test_strip_credentials_handles_invalid_port():
	"""A malformed port (e.g. 'abc') must not crash the sanitizer and must
	not produce a URL that httpx rejects with a raised exception (cubic-dev-ai
	P2 #2, review 2026-11-06 01:54).
	"""
	from browser_use.mcp.trust import _strip_credentials_from_url

	# Invalid port 'abc' — should not raise, should produce a URL with no port
	stripped = _strip_credentials_from_url('https://host:abc/path')
	# The malformed port is dropped; the path is preserved
	assert 'host' in stripped
	assert ':abc' not in stripped


@pytest.mark.asyncio
async def test_default_lookup_rejects_boolean_score():
	"""A JSON `true` in the trust_score field must not be coerced to 1.0
	and pass the threshold (cubic-dev-ai P2 #3, review 2026-11-06 01:54).
	bool is a subclass of int in Python, so isinstance(True, int) is True —
	the validator must explicitly reject bool before numeric coercion.
	"""
	from unittest.mock import patch, AsyncMock, MagicMock

	fake_response = MagicMock()
	fake_response.status_code = 200
	fake_response.json.return_value = {'trust_score': True, 'total_calls': 5}

	fake_client = MagicMock()
	fake_client.__aenter__ = AsyncMock(return_value=fake_client)
	fake_client.__aexit__ = AsyncMock(return_value=None)
	fake_client.get = AsyncMock(return_value=fake_response)

	with patch('browser_use.mcp.trust.httpx.AsyncClient', return_value=fake_client):
		from browser_use.mcp.trust import _default_trust_lookup

		verdict = await _default_trust_lookup('https://example.com/sse')
		assert verdict.score is None
		assert 'boolean' in verdict.reason.lower()


@pytest.mark.asyncio
async def test_filter_trusted_logs_redacted_url_on_exception(caplog):
	"""filter_trusted's warning log on a lookup exception must NOT include
	the raw server_url, which may contain credentials (cubic-dev-ai P1 #4,
	review 2026-11-06 01:54).
	"""
	import logging

	async def mock_lookup(url):
		raise RuntimeError('boom')

	checker = TrustChecker(min_score=0.7, lookup=mock_lookup, allow_unknown=True)
	url_with_creds = 'https://user:secret@host.com/path?api_key=abc'
	with caplog.at_level(logging.WARNING, logger='browser_use.mcp.trust'):
		trusted = await checker.filter_trusted([url_with_creds])
	assert trusted == []
	# The raw URL with credentials must not appear in any log line
	log_text = caplog.text
	assert 'secret' not in log_text
	assert 'api_key=abc' not in log_text
	# But the redacted form (host without creds) should appear so we can debug
	assert 'host.com' in log_text


@pytest.mark.asyncio
async def test_filter_trusted_logs_redacted_url_on_skip(caplog):
	"""filter_trusted's info log on a skipped untrusted server must also
	redact credentials from the URL (cubic-dev-ai P1 #4, review 2026-11-06 01:54).
	"""
	import logging

	async def mock_lookup(url):
		return TrustVerdict(server_url=url, score=0.1)

	checker = TrustChecker(min_score=0.7, lookup=mock_lookup, allow_unknown=False)
	url_with_creds = 'https://user:pass@bad.com/path?token=secret_token_value'
	with caplog.at_level(logging.INFO, logger='browser_use.mcp.trust'):
		trusted = await checker.filter_trusted([url_with_creds])
	assert trusted == []
	log_text = caplog.text
	# Credentials must not leak to logs
	assert 'pass' not in log_text
	assert 'secret_token_value' not in log_text


@pytest.mark.asyncio
async def test_filter_trusted_propagates_cancelled_error():
	"""A CancelledError raised by a lookup must propagate, not be swallowed
	as fail-closed (cubic-dev-ai P2 #5, review 2026-11-06 02:05).

	asyncio.CancelledError is a BaseException, not an Exception. The
	isinstance(result, Exception) check would not catch it, and the cast to
	TrustVerdict would crash with AttributeError on `verdict.is_trusted`.
	We re-raise CancelledError so the caller's cancellation propagates.
	"""

	async def mock_lookup(url):
		raise asyncio.CancelledError()

	checker = TrustChecker(min_score=0.7, lookup=mock_lookup, allow_unknown=True)
	with pytest.raises(asyncio.CancelledError):
		await checker.filter_trusted(['https://example.com/sse'])
