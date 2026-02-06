import hashlib
import json
from typing import Any


def _canonical_hash(item: Any) -> str:
	"""SHA-256 of a deterministic JSON serialization (sorted keys, compact separators)."""
	canonical = json.dumps(item, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
	return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


class ResultDeduplicator:
	"""Tracks seen extraction rows per script_id. Strips duplicates from JSON arrays."""

	def __init__(self) -> None:
		self._seen: dict[str, set[str]] = {}

	def dedup(self, data: Any, script_id: str) -> tuple[Any, int, int]:
		"""Returns (deduped_data, duplicates_removed, total_seen).

		If data is not a dedupable array, returns (data, 0, 0).
		"""
		items, wrapper_key = self._extract_array(data)
		if items is None:
			return data, 0, 0

		seen = self._seen.setdefault(script_id, set())
		new_items: list[Any] = []
		for item in items:
			h = _canonical_hash(item)
			if h not in seen:
				seen.add(h)
				new_items.append(item)

		removed = len(items) - len(new_items)
		if wrapper_key is not None:
			return {wrapper_key: new_items}, removed, len(seen)
		return new_items, removed, len(seen)

	def _extract_array(self, data: Any) -> tuple[list[dict] | None, str | None]:
		"""Extract a list of dicts from bare arrays or single-key wrapper dicts."""
		if isinstance(data, list) and len(data) > 0 and all(isinstance(x, dict) for x in data):
			return data, None
		if isinstance(data, dict) and len(data) == 1:
			key = next(iter(data))
			val = data[key]
			if isinstance(val, list) and len(val) > 0 and all(isinstance(x, dict) for x in val):
				return val, key
		return None, None

	def reset(self, script_id: str | None = None) -> None:
		"""Clear seen hashes for one script_id, or all if None."""
		if script_id is not None:
			self._seen.pop(script_id, None)
		else:
			self._seen.clear()
