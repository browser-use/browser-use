"""Element budget / top-N selection via 3-way merge.

Selects elements by importance score, dominant group membership,
and document position, then unions and deduplicates.
"""

from __future__ import annotations

from dataclasses import dataclass

from browser_use.dom.reduction.dominant_group import DominantGroup
from browser_use.dom.views import EnhancedDOMTreeNode


@dataclass
class BudgetConfig:
	top_by_importance: int = 60
	top_from_dominant_group: int = 15
	top_by_position: int = 10


def select_elements(
	selector_map: dict[int, EnhancedDOMTreeNode],
	scores: dict[int, float],
	dominant_group: DominantGroup | None,
	config: BudgetConfig = BudgetConfig(),
) -> dict[int, EnhancedDOMTreeNode]:
	"""Return a filtered selector_map containing only the budgeted elements."""
	assert isinstance(selector_map, dict), 'selector_map must be a dict'
	assert isinstance(scores, dict), 'scores must be a dict'

	if not selector_map:
		return {}

	selected_ids: set[int] = set()

	# 1. Top N by importance score
	by_score = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
	for bid, _ in by_score[: config.top_by_importance]:
		if bid in selector_map:
			selected_ids.add(bid)

	# 2. Top N from dominant group (by document order, i.e. ordinal rank)
	if dominant_group is not None:
		for bid in dominant_group.element_ids[: config.top_from_dominant_group]:
			if bid in selector_map:
				selected_ids.add(bid)

	# 3. Top N by document position (lowest bounds.y)
	def _doc_y(bid: int) -> float:
		node = selector_map[bid]
		bounds = node.snapshot_node.bounds if node.snapshot_node else None
		if bounds is None:
			return float('inf')
		return bounds.y

	by_position = sorted(selector_map.keys(), key=_doc_y)
	for bid in by_position[: config.top_by_position]:
		selected_ids.add(bid)

	# Build filtered map preserving only selected elements
	return {bid: selector_map[bid] for bid in selected_ids if bid in selector_map}
