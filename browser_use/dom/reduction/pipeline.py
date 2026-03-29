"""Reduction pipeline orchestrator — ties scoring, grouping, budgeting, diffing, and serialization together."""

from __future__ import annotations

from dataclasses import dataclass, field

from browser_use.dom.reduction.budget import BudgetConfig, select_elements
from browser_use.dom.reduction.compact_serializer import serialize_compact
from browser_use.dom.reduction.dominant_group import DominantGroup, detect_dominant_group
from browser_use.dom.reduction.goal_filter import apply_goal_scoring
from browser_use.dom.reduction.scoring import score_elements
from browser_use.dom.reduction.snapshot_diff import ElementDiff, compute_snapshot_diff
from browser_use.dom.views import EnhancedDOMTreeNode


@dataclass
class ReductionConfig:
	enabled: bool = False
	budget: BudgetConfig = field(default_factory=BudgetConfig)
	goal: str | None = None
	use_compact_format: bool = False
	page_url: str | None = None


@dataclass
class ReductionResult:
	filtered_selector_map: dict[int, EnhancedDOMTreeNode]
	scores: dict[int, float]
	dominant_group: DominantGroup | None
	diffs: dict[int, ElementDiff] | None
	compact_representation: str | None  # Only if use_compact_format=True


def apply_reduction(
	selector_map: dict[int, EnhancedDOMTreeNode],
	config: ReductionConfig,
	previous_selector_map: dict[int, EnhancedDOMTreeNode] | None = None,
	viewport_height: float = 900,
) -> ReductionResult:
	"""Run the full reduction pipeline.

	Pipeline order:
	1. Score all elements
	2. If goal is set, apply goal-based scoring
	3. Detect dominant group
	4. Apply budget selection
	5. If previous_selector_map provided, compute diffs
	6. If use_compact_format, generate compact serialization
	7. Return ReductionResult
	"""
	assert isinstance(selector_map, dict), 'selector_map must be a dict'
	assert isinstance(config, ReductionConfig), 'config must be a ReductionConfig'

	# 1. Score all elements
	scores = score_elements(selector_map, viewport_height)

	# 2. Goal-based scoring
	if config.goal:
		scores = apply_goal_scoring(scores, selector_map, config.goal)

	# 3. Detect dominant group
	dominant_group = detect_dominant_group(selector_map)

	# 4. Apply budget selection
	filtered_map = select_elements(selector_map, scores, dominant_group, config.budget)

	# 5. Compute diffs if previous state available
	diffs: dict[int, ElementDiff] | None = None
	if previous_selector_map is not None:
		diffs = compute_snapshot_diff(filtered_map, previous_selector_map)

	# 6. Compact serialization
	compact_repr: str | None = None
	if config.use_compact_format:
		# Use scores only for elements in filtered map
		filtered_scores = {bid: scores[bid] for bid in filtered_map if bid in scores}
		compact_repr = serialize_compact(
			filtered_map,
			filtered_scores,
			dominant_group=dominant_group,
			diffs=diffs,
			page_url=config.page_url,
		)

	return ReductionResult(
		filtered_selector_map=filtered_map,
		scores=scores,
		dominant_group=dominant_group,
		diffs=diffs,
		compact_representation=compact_repr,
	)
