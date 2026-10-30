"""Tests for the MCP trust verification module."""

import pytest
from browser_use.mcp.trust import TrustChecker, TrustVerdict


@pytest.mark.asyncio
async def test_trusted_server_passes():
	"""A server with score >= threshold is trusted."""
	async def mock_lookup(url):
		return TrustVerdict(server_url=url, score=0.85)

	checker = TrustChecker(min_score=0.7, lookup=mock_lookup)
	verdict = await checker.check("https://example.com/sse")
	assert verdict.is_trusted is True
	assert verdict.score == 0.85


@pytest.mark.asyncio
async def test_untrusted_server_fails():
	"""A server with score < threshold is not trusted."""
	async def mock_lookup(url):
		return TrustVerdict(server_url=url, score=0.3)

	checker = TrustChecker(min_score=0.7, lookup=mock_lookup)
	verdict = await checker.check("https://bad.com/sse")
	assert verdict.is_trusted is False
	assert "below threshold" in verdict.reason


@pytest.mark.asyncio
async def test_unknown_score_fail_closed():
	"""Unknown score (None) is fail-closed by default — important for browser security."""
	async def mock_lookup(url):
		return TrustVerdict(server_url=url, score=None)

	checker = TrustChecker(min_score=0.7, lookup=mock_lookup, allow_unknown=False)
	verdict = await checker.check("https://unknown.com/sse")
	assert verdict.is_trusted is False
	assert "unknown" in verdict.reason.lower()


@pytest.mark.asyncio
async def test_unknown_score_fail_open():
	"""Unknown score (None) can be allowed with allow_unknown=True."""
	async def mock_lookup(url):
		return TrustVerdict(server_url=url, score=None)

	checker = TrustChecker(min_score=0.7, lookup=mock_lookup, allow_unknown=True)
	verdict = await checker.check("https://unknown.com/sse")
	assert verdict.is_trusted is True


@pytest.mark.asyncio
async def test_filter_trusted_keeps_good_servers():
	"""filter_trusted returns only trusted server URLs."""
	async def mock_lookup(url):
		if "good" in url:
			return TrustVerdict(server_url=url, score=0.9)
		return TrustVerdict(server_url=url, score=0.1)

	checker = TrustChecker(min_score=0.7, lookup=mock_lookup)
	urls = ["https://good1.com/sse", "https://bad1.com/sse", "https://good2.com/sse"]
	trusted = await checker.filter_trusted(urls)
	assert len(trusted) == 2
	assert "good1.com" in trusted[0]
	assert "good2.com" in trusted[1]


@pytest.mark.asyncio
async def test_default_threshold_is_strict():
	"""Default threshold is 0.7 — stricter than a general 0.5, for browser security."""
	checker = TrustChecker()
	assert checker.min_score == 0.7
	assert checker.allow_unknown is False
