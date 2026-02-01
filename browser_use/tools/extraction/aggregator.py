"""Multi-page extraction aggregator — merges results from repeated extract_with_script calls."""

import json
import logging
from typing import Any

from browser_use.tools.extraction.views import ExtractionResult

logger = logging.getLogger(__name__)


class ExtractionAggregator:
	"""Accumulates extraction results keyed by extraction_id, with deduplication."""

	def __init__(self) -> None:
		self._collections: dict[str, list[Any]] = {}
		self._page_counts: dict[str, int] = {}

	def add(self, extraction_id: str, result: ExtractionResult) -> None:
		"""Add an extraction result to the collection for this extraction_id."""
		if extraction_id not in self._collections:
			self._collections[extraction_id] = []
			self._page_counts[extraction_id] = 0

		self._page_counts[extraction_id] += 1

		if result.data is None:
			return

		data = result.data
		if isinstance(data, list):
			# Merge list items, deduplicating
			for item in data:
				if not self._is_duplicate(extraction_id, item):
					self._collections[extraction_id].append(item)
		elif isinstance(data, dict):
			# Collect all list-valued fields first
			has_list_fields = False
			list_items: list[Any] = []
			for value in data.values():
				if isinstance(value, list):
					has_list_fields = True
					list_items.extend(value)

			if has_list_fields:
				# Dict contains list fields — extract and merge list items only
				for item in list_items:
					if not self._is_duplicate(extraction_id, item):
						self._collections[extraction_id].append(item)
			else:
				# Dict has no list fields — store as a single item
				if not self._is_duplicate(extraction_id, data):
					self._collections[extraction_id].append(data)
		else:
			if not self._is_duplicate(extraction_id, data):
				self._collections[extraction_id].append(data)

	def aggregate(self, extraction_id: str) -> ExtractionResult:
		"""Get the merged result for an extraction_id."""
		items = self._collections.get(extraction_id, [])
		pages = self._page_counts.get(extraction_id, 0)

		return ExtractionResult(
			data=items,
			schema_used=False,
			is_partial=False,
			source_url=None,
			content_stats={
				'total_items': len(items),
				'pages_aggregated': pages,
				'extraction_id': extraction_id,
			},
		)

	def summary(self, extraction_id: str) -> str:
		"""Get a human-readable summary for the agent's long_term_memory."""
		items = self._collections.get(extraction_id, [])
		pages = self._page_counts.get(extraction_id, 0)
		return f'{len(items)} unique items from {pages} page{"s" if pages != 1 else ""}. extraction_id={extraction_id}'

	def has_data(self, extraction_id: str) -> bool:
		return extraction_id in self._collections and len(self._collections[extraction_id]) > 0

	def clear(self, extraction_id: str | None = None) -> None:
		"""Clear a specific collection or all collections."""
		if extraction_id:
			self._collections.pop(extraction_id, None)
			self._page_counts.pop(extraction_id, None)
		else:
			self._collections.clear()
			self._page_counts.clear()

	def _is_duplicate(self, extraction_id: str, item: Any) -> bool:
		"""Check if item already exists in the collection via exact JSON match."""
		existing = self._collections.get(extraction_id, [])
		try:
			item_json = json.dumps(item, sort_keys=True, ensure_ascii=False)
			for existing_item in existing:
				if json.dumps(existing_item, sort_keys=True, ensure_ascii=False) == item_json:
					return True
		except (TypeError, ValueError):
			# Non-serializable items — fall back to equality
			return item in existing
		return False
