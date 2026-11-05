"""Small, dependency-free helpers for atomic browser-tab state handoff."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

TabEntry = dict[str, Any]


@dataclass(frozen=True)
class PinnedTabSnapshot:
	"""One member call's immutable-by-copy tab inventory."""

	context: object
	tabs: tuple[TabEntry, ...]


def pin_tabs(context: object, tabs: list[TabEntry]) -> PinnedTabSnapshot:
	"""Copy a full inventory so its member result and browser-state block cannot drift."""
	return PinnedTabSnapshot(context=context, tabs=tuple(dict(tab) for tab in tabs))


def consume_pinned_tabs(snapshot: PinnedTabSnapshot | None, context: object) -> list[TabEntry] | None:
	"""Return a copied snapshot only to the call that created it."""
	if snapshot is None or snapshot.context is not context:
		return None
	return [dict(tab) for tab in snapshot.tabs]


def converged_active_tab(
	context: object,
	tabs: list[TabEntry],
	actual_active_tab_id: str | None,
	expected_tab_id: str,
) -> tuple[TabEntry, PinnedTabSnapshot] | None:
	"""Accept a tab action only when Browser Use and the full inventory agree on focus."""
	if actual_active_tab_id != expected_tab_id:
		return None
	active = [tab for tab in tabs if tab.get('active')]
	if len(active) != 1 or active[0].get('tab_id') != expected_tab_id:
		return None
	snapshot = pin_tabs(context, tabs)
	selected = next(tab for tab in snapshot.tabs if tab['tab_id'] == expected_tab_id)
	return dict(selected), snapshot
