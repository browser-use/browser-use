from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

SuccessStatus = Literal['success', 'partial', 'failed', 'blocked']
TaskCategory = Literal[
	'read_only_query',
	'form_workflow',
	'download_export',
	'multi_step_transaction_query',
	'complex_hierarchical_search',
	'multi_constraint_optimization',
]
ModelT = TypeVar('ModelT', bound=BaseModel)


def utc_now() -> str:
	return datetime.now(UTC).isoformat()


class FailureMode(BaseModel):
	"""A realistic failure scenario to exercise alongside the happy path."""

	model_config = ConfigDict(extra='forbid')

	id: str
	name: str
	setup_notes: list[str] = Field(default_factory=list)
	expected_recovery: list[str] = Field(default_factory=list)


class TaskCard(BaseModel):
	"""A repeatable task definition shared by the human and agent runs."""

	model_config = ConfigDict(extra='forbid')

	id: str
	name: str
	category: TaskCategory
	task_prompt: str
	starting_conditions: list[str] = Field(default_factory=list)
	success_criteria: list[str] = Field(default_factory=list)
	forbidden_actions: list[str] = Field(default_factory=list)
	failure_modes: list[FailureMode] = Field(default_factory=list)
	agent_recovery_rules: list[str] = Field(default_factory=list)


class HumanRunRecord(BaseModel):
	"""Manual baseline for one task/scenario."""

	model_config = ConfigDict(extra='forbid')

	task_id: str
	scenario_id: str = 'normal'
	operator: str = 'human'
	success_status: SuccessStatus = 'blocked'
	duration_seconds: float | None = None
	steps: list[str] = Field(default_factory=list)
	stuck_points: list[str] = Field(default_factory=list)
	recovery_actions: list[str] = Field(default_factory=list)
	final_evidence: list[str] = Field(default_factory=list)
	intervention_count: int = 0
	notes: str = ''


class AgentRunSummary(BaseModel):
	"""Compact, comparable summary extracted from AgentHistoryList."""

	model_config = ConfigDict(extra='forbid')

	task_id: str
	scenario_id: str = 'normal'
	task_category: TaskCategory | None = Field(
		default=None,
		description='`TaskCard.category` at run time; use for grouping and cross-class comparison.',
	)
	experiment_id: str | None = None
	executor_backend: str | None = None
	executor_model: str | None = None
	navigator_backend: str | None = None  # 'deepseek' | 'openai_compatible' when navigator_enabled
	navigator_enabled: bool = False
	navigator_model: str | None = None
	navigator_plan_path: str | None = None
	continuous_navigation: bool = False  # whether --continuous-navigation periodic re-plan was on
	started_at: str
	finished_at: str
	success: bool | None
	is_done: bool
	duration_seconds: float
	number_of_steps: int
	action_names: list[str] = Field(default_factory=list)
	errors: list[str] = Field(default_factory=list)
	urls: list[str] = Field(default_factory=list)
	screenshot_paths: list[str] = Field(default_factory=list)
	final_result: str | None = None
	history_path: str
	conversation_path: str

	usage_summary: dict[str, Any] | None = Field(
		default=None,
		description='Agent `history.usage`: totals + `by_model` (see `tokens.views.UsageSummary`).',
	)
	usage_executor_llm: dict[str, Any] | None = Field(
		default=None,
		description='Subset of `by_model` for `Agent.llm` (executor loop; merges judge/extract if same model id).',
	)
	usage_navigator_cycle_llm: dict[str, Any] | None = Field(
		default=None,
		description=(
			'Subset of `by_model` for in-Agent periodic `navigator_llm` when `--continuous-navigation`. '
			'If navigator and executor share the same model string, omitted (ambiguous).'
		),
	)
	usage_auxiliary_llm_models: dict[str, dict[str, Any]] | None = Field(
		default=None,
		description='Remaining `by_model` keys (e.g. extraction/judge/other registered LLMs).',
	)
	navigator_initial_plan_usage: dict[str, Any] | None = Field(
		default=None,
		description='Navigator `create_plan()` first LLM call (not in Agent TokenCost): raw `ChatInvokeUsage` dump.',
	)
	navigator_overhead_ratio: float = Field(
		default=0.0,
		description=(
			'Academic metric: (navigator cycle tokens + initial plan tokens) / executor tokens. '
			'0.0 when executor tokens are 0 or navigator is disabled.'
		),
	)
	execution_velocity: float = Field(
		default=0.0,
		description='Academic metric: total_tokens / duration_seconds (cognitive density during browser interaction).',
	)
	token_efficiency_score: float = Field(
		default=0.0,
		description=(
			'Academic metric: success indicator (1 if success else 0) / (total_tokens / 1000). '
			'Thousand-token efficiency substitute when API cost is unavailable.'
		),
	)


def _usage_dict_int(usage: dict[str, Any] | None, key: str) -> int | None:
	if not isinstance(usage, dict):
		return None
	val = usage.get(key)
	if val is None:
		return None
	try:
		return int(val)
	except (TypeError, ValueError):
		return None


def compute_navigator_overhead_ratio(
	*,
	navigator_enabled: bool,
	executor_tokens: int | None,
	navigator_cycle_tokens: int | None,
	navigator_initial_tokens: int | None,
) -> float:
	"""(Navigator cycle + initial plan tokens) / executor tokens; 0.0 if no navigator or executor tokens <= 0."""

	if not navigator_enabled:
		return 0.0
	executor = executor_tokens or 0
	if executor <= 0:
		return 0.0
	navigator_total = (navigator_cycle_tokens or 0) + (navigator_initial_tokens or 0)
	return float(navigator_total) / float(executor)


def compute_execution_velocity(*, total_tokens: int | None, duration_seconds: float) -> float:
	"""Total tokens per second of wall time; 0.0 when duration <= 0."""

	if duration_seconds is None or duration_seconds <= 0:
		return 0.0
	tokens = total_tokens or 0
	return float(tokens) / float(duration_seconds)


def compute_token_efficiency_score(*, success: bool | None, total_tokens: int | None) -> float:
	"""Success weight (1 or 0) divided by (total_tokens / 1000); 0.0 when token denominator <= 0."""

	success_weight = 1.0 if success is True else 0.0
	tokens = total_tokens or 0
	denom_k = float(tokens) / 1000.0
	if denom_k <= 0.0:
		return 0.0
	return success_weight / denom_k


def academic_efficiency_from_agent_run(agent: AgentRunSummary, *, duration_seconds: float) -> tuple[float, float, float]:
	"""Derive the three academic efficiency metrics from usage fields on an `AgentRunSummary`."""

	usage = agent.usage_summary if isinstance(agent.usage_summary, dict) else None
	total_tokens = _usage_dict_int(usage, 'total_tokens')
	executor_tokens = _usage_dict_int(agent.usage_executor_llm, 'total_tokens')
	nav_cycle_tokens = _usage_dict_int(agent.usage_navigator_cycle_llm, 'total_tokens')
	nav_initial_tokens = _usage_dict_int(agent.navigator_initial_plan_usage, 'total_tokens')
	overhead = compute_navigator_overhead_ratio(
		navigator_enabled=agent.navigator_enabled,
		executor_tokens=executor_tokens,
		navigator_cycle_tokens=nav_cycle_tokens,
		navigator_initial_tokens=nav_initial_tokens,
	)
	velocity = compute_execution_velocity(total_tokens=total_tokens, duration_seconds=duration_seconds)
	efficiency = compute_token_efficiency_score(success=agent.success, total_tokens=total_tokens)
	return overhead, velocity, efficiency


class RunMetricStats(BaseModel):
	"""Descriptive stats for one numeric series (e.g. wall time or token totals)."""

	model_config = ConfigDict(extra='forbid')

	n: int = Field(ge=0, description='Sample count (values present for this metric).')
	mean: float | None = None
	std: float | None = Field(default=None, description='Sample standard deviation; omitted when n < 2.')
	min: float | None = None
	max: float | None = None
	median: float | None = None


class ExperimentBucketRunStatistics(BaseModel):
	"""Aggregates for one experiment id (or pooled bucket) inside a (task_id, scenario_id) group."""

	model_config = ConfigDict(extra='forbid')

	experiment_id: str | None = None
	is_pooled: bool = Field(
		default=False,
		description='True when this row aggregates all runs in the task/scenario regardless of experiment_id.',
	)
	run_count: int = Field(ge=0)
	success_true: int = Field(default=0, ge=0)
	success_false: int = Field(default=0, ge=0)
	success_unknown: int = Field(default=0, ge=0)
	is_done_true: int = Field(default=0, ge=0)
	is_done_false: int = Field(default=0, ge=0)
	duration_wall_clock_fallback_runs: int = Field(
		default=0,
		ge=0,
		description='Runs where `AgentRunSummary.duration_seconds` was <= 0 and wall-clock span was used instead.',
	)
	duration_seconds: RunMetricStats
	number_of_steps: RunMetricStats
	total_tokens: RunMetricStats | None = None
	total_prompt_tokens: RunMetricStats | None = None
	total_completion_tokens: RunMetricStats | None = None
	llm_invocation_count: RunMetricStats | None = None
	total_cost: RunMetricStats | None = None
	navigator_overhead_ratio: RunMetricStats | None = Field(
		default=None,
		description='Descriptive stats for per-run navigator overhead ratio.',
	)
	execution_velocity: RunMetricStats | None = Field(
		default=None,
		description='Descriptive stats for per-run tokens-per-second.',
	)
	token_efficiency_score: RunMetricStats | None = Field(
		default=None,
		description='Descriptive stats for per-run thousand-token efficiency score.',
	)


class AgentRunResourceSnapshot(BaseModel):
	"""Per-run metrics for cross-experiment resource comparison (no human baseline required)."""

	model_config = ConfigDict(extra='forbid')

	experiment_id: str | None = None
	started_at: str
	finished_at: str
	success: bool | None = None
	is_done: bool = False
	duration_seconds: float = 0.0
	duration_used_wall_clock_fallback: bool = Field(
		default=False,
		description='True when `duration_seconds` was taken from finished_at−started_at because history duration was <= 0.',
	)
	number_of_steps: int = 0
	executor_backend: str | None = None
	executor_model: str | None = None
	navigator_enabled: bool = False
	navigator_model: str | None = None
	history_path: str = ''
	conversation_path: str = ''
	total_tokens: int | None = Field(default=None, description='From `usage_summary.total_tokens` when present.')
	total_cost: float | None = Field(default=None, description='From `usage_summary.total_cost` when present.')
	total_prompt_tokens: int | None = None
	total_completion_tokens: int | None = None
	llm_invocation_count: int | None = Field(default=None, description='From `usage_summary.entry_count` when present.')
	navigator_overhead_ratio: float = Field(
		default=0.0,
		description='(Navigator cycle + initial plan tokens) / executor tokens; 0.0 without navigator or executor usage.',
	)
	execution_velocity: float = Field(
		default=0.0,
		description='total_tokens / duration_seconds.',
	)
	token_efficiency_score: float = Field(
		default=0.0,
		description='Success indicator / (total_tokens / 1000).',
	)


class TaskScenarioResourceGroup(BaseModel):
	"""All Agent runs for one (task_id, scenario_id), sorted by `started_at`, plus heuristic hints."""

	model_config = ConfigDict(extra='forbid')

	task_id: str
	scenario_id: str
	task_category: TaskCategory | None = None
	snapshots: list[AgentRunResourceSnapshot] = Field(default_factory=list)
	statistics_by_experiment: list[ExperimentBucketRunStatistics] = Field(
		default_factory=list,
		description='Per-experiment_id descriptive stats (duration, steps, tokens, costs) within this task/scenario.',
	)
	pooled_statistics: ExperimentBucketRunStatistics | None = Field(
		default=None,
		description='Same metrics as `statistics_by_experiment` but pooled over all runs in this task/scenario.',
	)
	analysis_hints: list[str] = Field(
		default_factory=list,
		description='English one-liners comparing runs in this group (cost, time, steps, tokens).',
	)


class ResourceGroupIndexEntry(BaseModel):
	"""One row in `ExperimentResourceReport.groups_index`: which task/scenario each `groups[]` item is."""

	model_config = ConfigDict(extra='forbid')

	task_id: str
	scenario_id: str
	task_category: TaskCategory | None = None
	snapshot_count: int = Field(ge=0, description='Number of Agent runs in the matching `groups[]` entry.')
	experiment_ids: list[str | None] = Field(
		default_factory=list,
		description='Distinct `experiment_id` values in that group (sorted; null = unlabeled).',
	)


class ExperimentResourceReport(BaseModel):
	"""Cross-experiment resource view derived from `agent_runs.json` (independent of human baselines)."""

	model_config = ConfigDict(extra='forbid')

	generated_at: str
	groups_index: list[ResourceGroupIndexEntry] = Field(
		default_factory=list,
		description=(
			'Table of contents with the same order as `groups`: scan this first to jump by task_id. '
			'Order follows `task_cards` when that list is passed to the report builder; orphan runs use sorted keys.'
		),
	)
	groups: list[TaskScenarioResourceGroup] = Field(default_factory=list)


class ComparisonRecord(BaseModel):
	"""Human-vs-agent comparison for one task/scenario."""

	model_config = ConfigDict(extra='forbid')

	task_id: str
	scenario_id: str
	task_category: TaskCategory | None = Field(
		default=None,
		description='From `TaskCard.category` for filtering comparison reports by task class.',
	)
	experiment_id: str | None = None
	navigator_enabled: bool | None = None
	navigator_model: str | None = None
	human_status: SuccessStatus | None
	agent_success: bool | None
	duration_delta_seconds: float | None
	agent_step_count: int | None
	human_intervention_count: int | None
	agent_error_count: int
	risk_flags: list[str] = Field(default_factory=list)
	differences: list[str] = Field(default_factory=list)
	recommended_next_changes: list[str] = Field(default_factory=list)


def load_json_model_list(path: Path, model: type[ModelT]) -> list[ModelT]:
	raw_items = json_load(path)
	return [model.model_validate(item) for item in raw_items]


def json_load(path: Path) -> Any:
	import json

	with path.open(encoding='utf-8') as file:
		return json.load(file)


def write_json(path: Path, payload: Any, overwrite: bool = True) -> None:
	import json

	if path.exists() and not overwrite:
		return
	path.parent.mkdir(parents=True, exist_ok=True)
	with path.open('w', encoding='utf-8') as file:
		json.dump(payload, file, indent=2, ensure_ascii=False)
		file.write('\n')

