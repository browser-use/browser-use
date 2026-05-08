from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

SuccessStatus = Literal['success', 'partial', 'failed', 'blocked']
TaskCategory = Literal['read_only_query', 'form_workflow', 'download_export']
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
	experiment_id: str | None = None
	executor_backend: str | None = None
	executor_model: str | None = None
	navigator_backend: str | None = None  # 'deepseek' | 'openai_compatible' when navigator_enabled
	navigator_enabled: bool = False
	navigator_model: str | None = None
	navigator_plan_path: str | None = None
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


class ComparisonRecord(BaseModel):
	"""Human-vs-agent comparison for one task/scenario."""

	model_config = ConfigDict(extra='forbid')

	task_id: str
	scenario_id: str
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

