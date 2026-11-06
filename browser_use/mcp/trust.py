"""Optional MCP server trust verification before browser tool execution.

This module provides a pluggable trust gate that browser-use agents can
use to verify an MCP server's reliability before granting it browser
access — a significant security gap noted in #4903.

The trust check is pluggable: pass any callable that takes a server URL
and returns a trust verdict. The default implementation queries a public
trust API, but users can substitute their own (local, cached, or
air-gapped) verifier.

Usage:

	from browser_use.mcp.trust import TrustChecker

	checker = TrustChecker(min_score=0.7)
	verdict = await checker.check('https://example.com/mcp/sse')
	if not verdict.is_trusted:
		raise ValueError(f'MCP server not trusted: {verdict.reason}')

	# Or filter before connecting
	trusted_servers = await checker.filter_trusted(server_urls)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, List, Optional
from urllib.parse import urlsplit, urlunsplit

import httpx

logger = logging.getLogger(__name__)


@dataclass
class TrustVerdict:
	"""The result of a trust check on one MCP server."""

	server_url: str
	score: Optional[float]  # 0.0 to 1.0, or None if unknown
	total_calls: Optional[int] = None
	is_trusted: bool = False
	reason: str = ''


# Default trust API endpoint (free tier, 50 queries/day, no key needed)
_DEFAULT_TRUST_API = 'https://dominionobservatory.com/api/trust'


def _strip_credentials_from_url(url: str) -> str:
	"""Strip userinfo and secret query parameters before sending a URL to a
	third-party trust API.

	Embedded basic-auth credentials (`https://user:pass@host/...`) and query
	parameters that commonly carry tokens (`?api_key=`, `?token=`, `?access_token=`)
	are removed. The lookup API only needs the server's identity (scheme +
	host + port + path); everything else is sensitive.
	"""
	try:
		parts = urlsplit(url)
	except (ValueError, TypeError):
		# Unparseable URL — return as-is rather than crash; the lookup will
		# fail downstream and the caller gets a fail-closed verdict.
		return url
	# Drop userinfo (user:pass@ prefix)
	safe_netloc = parts.hostname or ''
	if parts.port:
		safe_netloc = f'{safe_netloc}:{parts.port}'
	# Drop the query entirely if it contains known secret parameter names,
	# otherwise keep it. Most MCP server URLs have no query, but some carry
	# session tokens or api keys.
	safe_query = parts.query
	if parts.query:
		secret_markers = ('api_key', 'apikey', 'token', 'access_token', 'secret', 'password', 'auth')
		lower_query = parts.query.lower()
		if any(f'{m}=' in lower_query for m in secret_markers):
			safe_query = ''
	# Reassemble, dropping fragment too
	return urlunsplit((parts.scheme, safe_netloc, parts.path or '', safe_query, ''))


async def _default_trust_lookup(
	server_url: str,
	api_url: str = _DEFAULT_TRUST_API,
	timeout: float = 5.0,
) -> TrustVerdict:
	"""Query the default public trust API for a server's trust score.

	Users can pass their own lookup callable to TrustChecker for local
	or air-gapped verification.
	"""
	# Strip credentials before sending to a third-party API
	safe_url = _strip_credentials_from_url(server_url)
	try:
		async with httpx.AsyncClient(timeout=timeout) as client:
			resp = await client.get(api_url, params={'url': safe_url})
			if resp.status_code != 200:
				return TrustVerdict(
					server_url=server_url,
					score=None,
					reason=f'Trust API returned {resp.status_code}',
				)
			# Parse JSON defensively: a 200 with malformed JSON or wrong
			# shape must not crash check() — return a fail-closed verdict.
			try:
				data = resp.json()
			except (ValueError, TypeError) as e:
				logger.debug('Trust API returned malformed body for %s: %s', safe_url, e)
				return TrustVerdict(
					server_url=server_url,
					score=None,
					reason=f'Trust API returned malformed body: {e}',
				)
			# Reject non-dict responses (some APIs return arrays or bare strings)
			if not isinstance(data, dict):
				return TrustVerdict(
					server_url=server_url,
					score=None,
					reason='Trust API returned non-object body',
				)
			score = data.get('trust_score')
			total_calls = data.get('total_calls', 0)
			# Validate the score: must be a finite number. Strings like '0.85'
			# are accepted; None stays None; anything else (lists, NaN, inf)
			# is rejected as malformed.
			if isinstance(score, str):
				try:
					score = float(score)
				except (ValueError, TypeError):
					return TrustVerdict(
						server_url=server_url,
						score=None,
						reason=f'Trust API returned non-numeric score: {score!r}',
					)
			if score is not None:
				if not isinstance(score, (int, float)) or not isinstance(score, float):
					# int → cast to float for normalization below
					if isinstance(score, int):
						score = float(score)
					else:
						return TrustVerdict(
							server_url=server_url,
							score=None,
							reason=f'Trust API returned non-numeric score: {score!r}',
						)
				# Reject NaN / inf
				if score != score or score in (float('inf'), float('-inf')):
					return TrustVerdict(
						server_url=server_url,
						score=None,
						reason='Trust API returned non-finite score',
					)
				# Reject out-of-range: a score of 200 would otherwise normalize
				# to 2.0 and pass any threshold ≤ 1.0.
				if score < 0.0 or score > 100.0:
					return TrustVerdict(
						server_url=server_url,
						score=None,
						reason=f'Trust API returned out-of-range score: {score}',
					)
				# Normalize: some APIs return 0-100, some return 0-1.
				# Values > 1 are treated as 0-100 scale.
				if score > 1:
					score = score / 100.0
			return TrustVerdict(
				server_url=server_url,
				score=score,
				total_calls=total_calls,
			)
	except (httpx.RequestError, asyncio.TimeoutError, ValueError, TypeError, AttributeError) as e:
		logger.debug('Trust check failed for %s: %s', safe_url, e)
		return TrustVerdict(
			server_url=server_url,
			score=None,
			reason=f'Trust API unreachable: {e}',
		)


# Type for a pluggable trust lookup function
TrustLookup = Callable[[str], Awaitable[TrustVerdict]]


class TrustChecker:
	"""Optional pre-call trust gate for MCP server connections.

	Args:
		min_score: Minimum trust score to consider a server trusted (default 0.7).
		lookup: Custom trust lookup function. Defaults to the public Dominion
			 Observatory API (free tier, 50 queries/day, no key needed).
		allow_unknown: If True, servers with unknown trust scores are considered
					   trusted (fail-open). If False (default), unknown servers
					   are considered untrusted (fail-closed). This is the
					   recommended setting for browser-use, where a malicious
					   MCP server could inject harmful actions.

		Note on `allow_unknown`: it applies ONLY to explicit
		`TrustVerdict(score=None)` results returned by `lookup`. Lookup
		exceptions (network errors, malformed responses, unhandled bugs) are
		ALWAYS fail-closed — a lookup that raised did not produce a verdict,
		so the server must not be trusted.
	"""

	def __init__(
		self,
		min_score: float = 0.7,
		lookup: Optional[TrustLookup] = None,
		allow_unknown: bool = False,
	) -> None:
		self.min_score = min_score
		self._lookup = lookup or _default_trust_lookup
		self.allow_unknown = allow_unknown

	async def check(self, server_url: str) -> TrustVerdict:
		"""Check the trust score of a single MCP server.

		Returns a TrustVerdict with the score and whether it's trusted.
		"""
		verdict = await self._lookup(server_url)
		if verdict.score is None:
			verdict.is_trusted = self.allow_unknown
			if not verdict.is_trusted and not verdict.reason:
				verdict.reason = 'Trust score unknown (fail-closed)'
		else:
			verdict.is_trusted = verdict.score >= self.min_score
			if not verdict.is_trusted:
				verdict.reason = f'Score {verdict.score:.2f} below threshold {self.min_score:.2f}'
		return verdict

	async def filter_trusted(self, server_urls: List[str]) -> List[str]:
		"""Filter a list of server URLs, keeping only the trusted ones.

		Lookup exceptions are ALWAYS fail-closed, regardless of
		`allow_unknown`: a server whose lookup raised did not produce a
		verdict, so it must not be trusted. `allow_unknown` only applies to
		lookups that explicitly returned `TrustVerdict(score=None)`.
		"""
		results = await asyncio.gather(
			*[self.check(url) for url in server_urls],
			return_exceptions=True,
		)
		trusted: List[str] = []
		for url, result in zip(server_urls, results):
			if isinstance(result, Exception):
				# Lookup itself raised (network, unhandled bug). Fail-closed
				# even if allow_unknown is True — the lookup did not return
				# a verdict, so we have no signal to trust on.
				logger.warning(
					'Trust check raised for %s: %s (excluding — allow_unknown does not apply to lookup exceptions)',
					url,
					result,
				)
				continue
			if result.is_trusted:
				trusted.append(url)
			else:
				logger.info('Skipping untrusted MCP server %s: %s', url, result.reason)
		return trusted
