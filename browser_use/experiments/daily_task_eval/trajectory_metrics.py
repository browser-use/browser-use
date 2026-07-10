"""Trajectory normalization, action classification, and LCS similarity metrics."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

ACTION_ALIASES = MappingProxyType(
	{
		'go_to_url': 'navigate',
		'open_url': 'navigate',
		'navigate': 'navigate',
		'search': 'search',
		'search_query': 'search',
		'web_search': 'search',
		'search_page': 'search',
		'input': 'input',
		'input_text': 'input',
		'type': 'input',
		'type_text': 'input',
		'send_keys': 'input',
		'click': 'click',
		'click_element': 'click',
		'submit': 'submit',
		'press_enter': 'submit',
		'extract': 'extract',
		'extract_content': 'extract',
		'extract_structured_data': 'extract',
		'scroll': 'scroll',
		'scroll_down': 'scroll',
		'scroll_up': 'scroll',
		'wait': 'wait',
		'page_load_wait': 'wait',
		'find_text': 'browser_find',
		'find_elements': 'find_elements',
		'go_back': 'go_back',
		'back': 'go_back',
		'switch_tab': 'switch_tab',
		'close_tab': 'close_tab',
		'select_dropdown': 'select_dropdown',
		'upload_file': 'upload_file',
		'screenshot': 'screenshot',
		'dropdown_options': 'dropdown_options',
		'done': 'done',
		'answer': 'done',
		'read_file': 'read_file',
		'write_file': 'write_file',
		'replace_file': 'replace_file',
		'save_as_pdf': 'save_as_pdf',
		'evaluate': 'evaluate',
	}
)

_STATE_CHANGING: frozenset[str] = frozenset(
	{
		'navigate',
		'search',
		'input',
		'click',
		'submit',
		'select_dropdown',
		'upload_file',
		'go_back',
		'switch_tab',
		'close_tab',
	}
)

_VIEWPORT_ADAPTATION: frozenset[str] = frozenset({'scroll', 'browser_find', 'wait'})

_PERCEPTION: frozenset[str] = frozenset({'extract', 'screenshot', 'find_elements', 'dropdown_options'})

_AUXILIARY: frozenset[str] = frozenset({'read_file', 'write_file', 'replace_file', 'save_as_pdf', 'evaluate'})

_TERMINAL: frozenset[str] = frozenset({'done'})


class ActionCategory(StrEnum):
	STATE_CHANGING = 'state_changing'
	VIEWPORT_ADAPTATION = 'viewport_adaptation'
	PERCEPTION = 'perception'
	AUXILIARY = 'auxiliary'
	TERMINAL = 'terminal'
	UNKNOWN = 'unknown'


@dataclass(frozen=True, slots=True)
class PairwiseTrajectoryComparison:
	raw_lcs: float | None
	canonical_lcs: float | None
	navigation_lcs: float | None

	raw_lcs_length: int
	canonical_lcs_length: int
	navigation_lcs_length: int

	raw_agent_length: int
	raw_human_length: int
	canonical_agent_length: int
	canonical_human_length: int
	navigation_agent_length: int
	navigation_human_length: int

	agent_unknown_actions: tuple[str, ...]
	human_unknown_actions: tuple[str, ...]


def normalize_action_token(name: str) -> str:
	"""Map a raw action name to a canonical token or ``unknown:<name>``."""

	low = name.lower().strip()
	if not low:
		return ''
	if any(low == p or low.startswith(f'{p}_') for p in ('extract',)):
		return 'extract'
	if low in ACTION_ALIASES:
		return ACTION_ALIASES[low]
	return f'unknown:{low}'


def classify_action(canonical_token: str) -> ActionCategory:
	"""Classify a canonical action token by functional role."""

	if not canonical_token:
		return ActionCategory.UNKNOWN
	if canonical_token.startswith('unknown:'):
		return ActionCategory.UNKNOWN
	if canonical_token in _STATE_CHANGING:
		return ActionCategory.STATE_CHANGING
	if canonical_token in _VIEWPORT_ADAPTATION:
		return ActionCategory.VIEWPORT_ADAPTATION
	if canonical_token in _PERCEPTION:
		return ActionCategory.PERCEPTION
	if canonical_token in _AUXILIARY:
		return ActionCategory.AUXILIARY
	if canonical_token in _TERMINAL:
		return ActionCategory.TERMINAL
	return ActionCategory.UNKNOWN


def raw_trajectory(actions: Sequence[str]) -> list[str]:
	"""Preserve raw-LCS semantics: lower + strip only."""

	return [s.lower().strip() for s in actions if s and str(s).strip()]


def canonical_trajectory(actions: Sequence[str]) -> list[str]:
	"""Normalize aliases into canonical action tokens, without filtering."""

	out: list[str] = []
	for raw in actions:
		token = normalize_action_token(str(raw))
		if token:
			out.append(token)
	return out


def navigation_trajectory(actions: Sequence[str]) -> list[str]:
	"""Retain only state-changing and terminal actions from the canonical trajectory."""

	out: list[str] = []
	for token in canonical_trajectory(actions):
		category = classify_action(token)
		if category in (ActionCategory.STATE_CHANGING, ActionCategory.TERMINAL):
			out.append(token)
	return out


def collect_unknown_actions(actions: Sequence[str]) -> tuple[str, ...]:
	"""Return sorted unique ``unknown:*`` tokens present in ``actions``."""

	seen: set[str] = set()
	for token in canonical_trajectory(actions):
		if token.startswith('unknown:'):
			seen.add(token)
	return tuple(sorted(seen))


def lcs_length(left: Sequence[str], right: Sequence[str]) -> int:
	"""Classic O(m*n) longest common subsequence length."""

	m, n = len(left), len(right)
	if m == 0 or n == 0:
		return 0
	prev = [0] * (n + 1)
	for i in range(1, m + 1):
		cur = [0] * (n + 1)
		for j in range(1, n + 1):
			if left[i - 1] == right[j - 1]:
				cur[j] = prev[j - 1] + 1
			else:
				cur[j] = max(prev[j], cur[j - 1])
		prev = cur
	return prev[n]


def normalized_lcs_score(left: Sequence[str], right: Sequence[str]) -> float | None:
	"""Return normalized LCS score, or ``None`` when both trajectories are empty."""

	if not left and not right:
		return None
	if not left or not right:
		return 0.0
	lcs = lcs_length(left, right)
	denom = max(len(left), len(right))
	return float(lcs) / float(denom)


def _legacy_raw_lcs_score(left: Sequence[str], right: Sequence[str]) -> float:
	"""Backward-compatible raw LCS: both empty → 1.0 (legacy CSV/tests)."""

	if not left and not right:
		return 1.0
	score = normalized_lcs_score(left, right)
	assert score is not None
	return score


def compare_trajectories(
	agent_actions: Sequence[str],
	human_actions: Sequence[str],
) -> PairwiseTrajectoryComparison:
	"""Compare agent and human trajectories at raw, canonical, and navigation layers."""

	raw_a = raw_trajectory(agent_actions)
	raw_h = raw_trajectory(human_actions)
	can_a = canonical_trajectory(agent_actions)
	can_h = canonical_trajectory(human_actions)
	nav_a = navigation_trajectory(agent_actions)
	nav_h = navigation_trajectory(human_actions)

	return PairwiseTrajectoryComparison(
		raw_lcs=normalized_lcs_score(raw_a, raw_h),
		canonical_lcs=normalized_lcs_score(can_a, can_h),
		navigation_lcs=normalized_lcs_score(nav_a, nav_h),
		raw_lcs_length=lcs_length(raw_a, raw_h),
		canonical_lcs_length=lcs_length(can_a, can_h),
		navigation_lcs_length=lcs_length(nav_a, nav_h),
		raw_agent_length=len(raw_a),
		raw_human_length=len(raw_h),
		canonical_agent_length=len(can_a),
		canonical_human_length=len(can_h),
		navigation_agent_length=len(nav_a),
		navigation_human_length=len(nav_h),
		agent_unknown_actions=collect_unknown_actions(agent_actions),
		human_unknown_actions=collect_unknown_actions(human_actions),
	)


def trajectory_lcs_similarity(agent_actions: Sequence[str], human_steps: Sequence[str]) -> float:
	"""Legacy raw-LCS wrapper (both empty → 1.0)."""

	return _legacy_raw_lcs_score(raw_trajectory(agent_actions), raw_trajectory(human_steps))


def trajectory_lcs_canonical(agent_actions: Sequence[str], human_steps: Sequence[str]) -> float | None:
	"""Canonical-token LCS normalized by max trajectory length."""

	return normalized_lcs_score(
		canonical_trajectory(agent_actions),
		canonical_trajectory(human_steps),
	)


def trajectory_lcs_navigation(agent_actions: Sequence[str], human_steps: Sequence[str]) -> float | None:
	"""Navigation-skeleton LCS after canonical normalization and category filtering."""

	return normalized_lcs_score(
		navigation_trajectory(agent_actions),
		navigation_trajectory(human_steps),
	)


def get_filtered_trajectory(steps: Sequence[str]) -> list[str]:
	"""Backward-compatible alias for navigation trajectory tokens."""

	return navigation_trajectory(steps)


# Kept for tests that assert membership; navigation filtering uses categories now.
FILTERED_OUT_TOOLS: frozenset[str] = frozenset(
	{
		'scroll',
		'browser_find',
		'find_text',
		'dropdown_options',
		'extract',
		'find_elements',
		'screenshot',
		'evaluate',
		'write_file',
		'read_file',
		'replace_file',
		'wait',
		'save_as_pdf',
	}
)


# ============================================================================
# Milestone-Based Process Metrics (Step 3)
# ============================================================================


@dataclass(frozen=True, slots=True)
class MilestoneEvent:
	"""A single milestone occurrence in a run's trajectory."""

	milestone_id: str
	step_number: int
	url: str | None = None
	action_name: str | None = None


@dataclass(frozen=True, slots=True)
class MilestoneProcessMetrics:
	"""Process metrics for a single run based on milestone achievement."""

	run_id: str
	task_id: str
	total_steps: int
	milestones_achieved: tuple[str, ...]
	milestone_steps: dict[str, int]  # milestone_id -> first step achieved
	milestone_coverage: float  # fraction of expected milestones achieved
	order_score: float | None  # Kendall tau: correlation with expected order
	stall_burden: float  # fraction of steps without new milestones
	state_revisit_rate: float  # fraction of steps revisiting previous URLs
	post_intervention_recovery_yield: float | None  # R-* only: recovery within 2 steps


def _url_domain_path(url: str | None) -> str:
	"""Extract domain + path from URL for state comparison, ignoring query params."""
	if not url:
		return ''
	from urllib.parse import urlparse

	parsed = urlparse(url)
	return f'{parsed.netloc}{parsed.path}'.lower()


def _compute_kendall_tau(achieved: Sequence[str], expected: Sequence[str]) -> float | None:
	"""
	Compute Kendall tau-b correlation between achieved and expected milestone orders.

	Returns None if fewer than 2 milestones overlap.
	"""
	if len(achieved) < 2 or len(expected) < 2:
		return None

	# Build expected rank map
	expected_rank = {m: i for i, m in enumerate(expected)}

	# Filter achieved to only those in expected, preserving order
	ranked_achieved = [(m, expected_rank[m]) for m in achieved if m in expected_rank]

	if len(ranked_achieved) < 2:
		return None

	# Count concordant and discordant pairs
	n = len(ranked_achieved)
	concordant = 0
	discordant = 0

	for i in range(n):
		for j in range(i + 1, n):
			rank_i = ranked_achieved[i][1]
			rank_j = ranked_achieved[j][1]
			if rank_i < rank_j:
				concordant += 1
			elif rank_i > rank_j:
				discordant += 1

	total_pairs = n * (n - 1) // 2
	if total_pairs == 0:
		return None

	tau = (concordant - discordant) / total_pairs
	return tau


def _compute_stall_burden(
	total_steps: int, milestone_steps: dict[str, int], first_done_step: int | None
) -> float:
	"""
	Compute fraction of steps that did not achieve a new milestone.

	Only counts steps up to first 'done' action or total_steps.
	"""
	if total_steps == 0:
		return 0.0

	effective_steps = first_done_step if first_done_step is not None else total_steps
	milestone_step_set = set(milestone_steps.values())
	non_milestone_steps = sum(1 for s in range(1, effective_steps + 1) if s not in milestone_step_set)

	return non_milestone_steps / effective_steps


def _compute_state_revisit_rate(urls: Sequence[str | None]) -> float:
	"""
	Compute fraction of steps that revisit a URL (domain+path) seen in a prior step.
	"""
	if len(urls) == 0:
		return 0.0

	seen: set[str] = set()
	revisits = 0

	for url in urls:
		normalized = _url_domain_path(url)
		if not normalized:
			continue
		if normalized in seen:
			revisits += 1
		else:
			seen.add(normalized)

	return revisits / len(urls) if len(urls) > 0 else 0.0


def _compute_post_intervention_recovery(
	history: Sequence[dict], navigator_injection_step: int | None, milestone_steps: dict[str, int]
) -> float | None:
	"""
	For R-* runs only: did the agent achieve a new milestone within 2 steps of navigator injection?

	Returns None for non-R-* runs or if no injection occurred.
	"""
	if navigator_injection_step is None:
		return None

	milestones_after = [s for s in milestone_steps.values() if s > navigator_injection_step]
	if not milestones_after:
		return 0.0

	earliest_new = min(milestones_after)
	return 1.0 if (earliest_new - navigator_injection_step) <= 2 else 0.0


def parse_history_for_milestones(
	history: Sequence[dict], task_id: str, run_id: str, experiment_id: str | None = None
) -> MilestoneProcessMetrics:
	"""
	Parse a run's history.json and extract milestone achievement metrics.

	Args:
	    history: List of step dicts from history.json
	    task_id: Task identifier (e.g., 'shopping_price_compare')
	    run_id: Unique run identifier
	    experiment_id: Experiment condition (E/I/R-1/R-3/R-5/C/C1/etc.)

	Returns:
	    MilestoneProcessMetrics with coverage, order, stall, revisit, and recovery metrics
	"""
	from browser_use.experiments.daily_task_eval.task_registry import get_task_milestones

	expected_milestones = get_task_milestones(task_id)

	# Extract step data
	urls: list[str | None] = []
	action_names: list[str] = []
	milestone_events: list[MilestoneEvent] = []
	achieved_set: set[str] = set()
	milestone_steps_map: dict[str, int] = {}
	first_done_step: int | None = None

	for step_idx, step in enumerate(history, start=1):
		# Extract state
		state = step.get('state', {})
		if state is None:
			state = {}
		url = state.get('url')
		urls.append(url)

		# Extract actions
		model_output = step.get('model_output', {})
		if model_output is None:
			model_output = {}
		actions = model_output.get('action', [])
		if actions is None:
			actions = []

		step_action_names = []
		for action in actions:
			if isinstance(action, dict):
				action_name = next(iter(action.keys()), None)
				if action_name:
					step_action_names.append(action_name)

		action_name = step_action_names[0] if step_action_names else None
		action_names.append(action_name or '')

		if action_name == 'done' and first_done_step is None:
			first_done_step = step_idx

		# Check each expected milestone
		for milestone in expected_milestones:
			if milestone.milestone_id in achieved_set:
				continue  # Already achieved

			if milestone.check(step, url, action_name):
				achieved_set.add(milestone.milestone_id)
				milestone_steps_map[milestone.milestone_id] = step_idx
				milestone_events.append(
					MilestoneEvent(
						milestone_id=milestone.milestone_id,
						step_number=step_idx,
						url=url,
						action_name=action_name,
					)
				)

	# Sort achieved milestones by step order
	achieved_ordered = tuple(
		sorted(achieved_set, key=lambda m: milestone_steps_map.get(m, float('inf')))
	)

	# Compute metrics
	expected_ids = [m.milestone_id for m in expected_milestones]
	coverage = len(achieved_set) / len(expected_ids) if expected_ids else 0.0
	order_score = _compute_kendall_tau(achieved_ordered, expected_ids)
	stall_burden = _compute_stall_burden(len(history), milestone_steps_map, first_done_step)
	state_revisit_rate = _compute_state_revisit_rate(urls)

	# Post-intervention recovery (R-* only)
	navigator_injection_step = None
	if experiment_id and experiment_id.startswith('R-'):
		# Detect first navigator injection (simplified heuristic: first step with navigator_current_step)
		for step_idx, step in enumerate(history, start=1):
			state_message = step.get('state_message', '')
			if 'navigator_current_step' in state_message:
				navigator_injection_step = step_idx
				break

	recovery_yield = _compute_post_intervention_recovery(
		history, navigator_injection_step, milestone_steps_map
	)

	return MilestoneProcessMetrics(
		run_id=run_id,
		task_id=task_id,
		total_steps=len(history),
		milestones_achieved=achieved_ordered,
		milestone_steps=milestone_steps_map,
		milestone_coverage=coverage,
		order_score=order_score,
		stall_burden=stall_burden,
		state_revisit_rate=state_revisit_rate,
		post_intervention_recovery_yield=recovery_yield,
	)
