"""CitationTracker — wraps browser extraction calls with provenance metadata.

Pattern borrowed from Perplexity's source-attribution model:
  every datum extracted from the web carries its origin URL, timestamp,
  confidence estimate, and a content fingerprint for deduplication.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
	pass

from browser_use.research.views import Citation, CitedResult

logger = logging.getLogger(__name__)


def _fingerprint(text: str) -> str:
	"""12-char SHA-256 prefix of the text — cheap deduplication key."""
	return hashlib.sha256(text.encode('utf-8', errors='replace')).hexdigest()[:12]


def _confidence(text: str, element_ref: str | None) -> float:
	"""Heuristic confidence in [0.1, 1.0].

	Longer, element-specific extracts are more trustworthy than short/ambiguous ones.
	Not a calibrated probability — treat as a relative ranking signal.
	"""
	length_score = min(len(text) / 500, 1.0)  # saturates at ~500 chars
	specificity_bonus = 0.1 if element_ref else 0.0
	return round(max(0.1, min(1.0, 0.5 + 0.4 * length_score + specificity_bonus)), 3)


class CitationTracker:
	"""Tags browser extraction results with provenance citations.

	Usage::

		tracker = CitationTracker()
		cited = tracker.cite(
			content="OpenAI was founded in 2015.",
			url="https://en.wikipedia.org/wiki/OpenAI",
			page_title="OpenAI — Wikipedia",
			element_ref="#firstHeading",
		)
		print(cited.as_markdown())
	"""

	def __init__(self) -> None:
		self._store: list[Citation] = []

	def cite(
		self,
		content: str,
		url: str,
		page_title: str = '',
		element_ref: str | None = None,
		extracted_at: datetime | None = None,
	) -> CitedResult:
		"""Wrap *content* in a CitedResult with a single Citation for *url*."""
		ts = extracted_at or datetime.now(timezone.utc)
		fingerprint = _fingerprint(content)

		# Deduplicate: if we already have a citation with the same fingerprint, reuse it
		existing = next((c for c in self._store if c.content_fingerprint == fingerprint), None)
		if existing:
			logger.debug('CitationTracker: deduplicating extract %s', fingerprint)
			return CitedResult(content=content, citations=[existing])

		citation = Citation(
			url=url,
			page_title=page_title,
			extracted_at=ts,
			content_fingerprint=fingerprint,
			confidence=_confidence(content, element_ref),
			extract=content[:500],  # cap stored extract at 500 chars
			element_ref=element_ref,
		)
		self._store.append(citation)
		logger.debug('CitationTracker: recorded citation %s from %s (conf=%.2f)', fingerprint, url, citation.confidence)
		return CitedResult(content=content, citations=[citation])

	def cite_many(self, extracts: list[tuple[str, str, str]], url: str, page_title: str = '') -> list[CitedResult]:
		"""Batch-cite multiple (content, element_ref, label) tuples from the same page."""
		return [self.cite(content, url=url, page_title=page_title, element_ref=ref) for content, ref, _ in extracts]

	def all_citations(self) -> list[Citation]:
		"""Return all unique citations recorded so far."""
		return list(self._store)

	def reset(self) -> None:
		self._store.clear()
