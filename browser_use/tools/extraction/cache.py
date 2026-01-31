"""Extraction strategy cache for reusing JS scripts across similar pages."""

import fnmatch
import logging
from urllib.parse import urlparse

from browser_use.tools.extraction.views import ExtractionStrategy

logger = logging.getLogger(__name__)


class ExtractionCache:
	"""In-memory cache of extraction strategies, keyed by ID and matchable by URL pattern."""

	def __init__(self) -> None:
		self._strategies: dict[str, ExtractionStrategy] = {}

	def register(self, strategy: ExtractionStrategy) -> str:
		"""Register a strategy and return its ID."""
		self._strategies[strategy.id] = strategy
		logger.debug(f'Registered extraction strategy {strategy.id} for pattern "{strategy.url_pattern}"')
		return strategy.id

	def get(self, extraction_id: str) -> ExtractionStrategy | None:
		"""Look up a strategy by ID."""
		return self._strategies.get(extraction_id)

	def find_matching(self, url: str) -> ExtractionStrategy | None:
		"""Find a cached strategy whose url_pattern matches the given URL.

		Returns the strategy with the highest success_count among matches,
		or None if no match is found.
		"""
		best: ExtractionStrategy | None = None
		for strategy in self._strategies.values():
			if not strategy.url_pattern or not strategy.js_script:
				continue
			if self._url_matches_pattern(url, strategy.url_pattern):
				if best is None or strategy.success_count > best.success_count:
					best = strategy
		return best

	def record_success(self, extraction_id: str) -> None:
		"""Increment success count for a strategy."""
		strategy = self._strategies.get(extraction_id)
		if strategy:
			strategy.success_count += 1

	def record_failure(self, extraction_id: str) -> None:
		"""Increment failure count for a strategy."""
		strategy = self._strategies.get(extraction_id)
		if strategy:
			strategy.failure_count += 1

	def remove(self, extraction_id: str) -> None:
		"""Remove a strategy from the cache."""
		self._strategies.pop(extraction_id, None)

	def clear(self) -> None:
		"""Clear all cached strategies."""
		self._strategies.clear()

	@property
	def size(self) -> int:
		return len(self._strategies)

	@staticmethod
	def _url_matches_pattern(url: str, pattern: str) -> bool:
		"""Check if a URL matches a glob-style pattern.

		Patterns can use * for wildcards. Matching is done on the full URL
		or on the path component if the pattern starts with '/'.
		"""
		if not pattern:
			return False

		# Direct glob match on full URL
		if fnmatch.fnmatch(url, pattern):
			return True

		# Try matching on path only
		try:
			parsed = urlparse(url)
			parsed_pattern = urlparse(pattern)

			# If pattern has a scheme, match full URL structure
			if parsed_pattern.scheme and parsed_pattern.netloc:
				# Match scheme + host + path pattern
				if parsed.scheme != parsed_pattern.scheme:
					return False
				if not fnmatch.fnmatch(parsed.netloc, parsed_pattern.netloc):
					return False
				return fnmatch.fnmatch(parsed.path, parsed_pattern.path)
		except Exception:
			pass

		return False
