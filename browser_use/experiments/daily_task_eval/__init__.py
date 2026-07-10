"""Daily task evaluation utilities (task cards, navigator plans, runners).

This module is intentionally self-contained so that evaluation experiments can be
enabled/disabled via configuration without modifying the core Agent runtime.

Code map:
- `experiment_presets.py` — A/B/C/D presets and `build_configs_from_args` (CLI)
- `executor.py` — executor LLM factory (`ExecutorConfig`, `build_executor_llm`)
- `navigator.py` — navigator plan providers (`NavigatorConfig`, `build_navigator_chat_model`, `LLMNavigator`)
- `runner.py` — `run_agent_task`, `compare_all`, `build_experiment_resource_report`, `init_experiment`
- `models.py` — `TaskCard`, `AgentRunSummary`, etc.
"""

from .executor import (
	ExecutorConfig,
	build_executor_llm,
	default_max_actions_per_step_for_executor,
	default_use_vision_for_executor,
	infer_volcengine_ark_executor_model,
	resolve_openai_compatible_credentials,
)
from .experiment_presets import (
	DailyExperimentId,
	ExperimentRunFlags,
	PAPER_CONDITION_ADAPTIVE,
	PAPER_EXPERIMENT_CA,
	build_configs_from_args,
	describe_experiments_text,
	experiment_preset,
	experiment_run_flags_from_args,
	paper_experiment_preset,
)
from .human_reference import (
	EligibilityResult,
	HumanRunAuditWarning,
	audit_human_run_record,
	is_human_reference_eligible,
	validate_reference_eligibility,
)
from .models import (
	AgentRunSummary,
	ComparisonRecord,
	ExperimentResourceReport,
	FailureMode,
	HumanRunRecord,
	TaskCard,
)
from .navigator import NavigatorConfig, NavigatorPlanProvider, build_navigator_chat_model
from .reference_comparison import compare_agent_to_human_references, get_reference_human_runs
from .runner import adjudicate_agent_summary, build_experiment_resource_report, compare_all, init_experiment, run_agent_task
from .task_registry import (
	TaskTierMetadata,
	get_archived_tasks,
	get_main_tasks,
	get_stress_tasks,
	get_tasks_for_aggregate_metrics,
	task_metadata_for,
)

__all__ = [
	'AgentRunSummary',
	'ComparisonRecord',
	'DailyExperimentId',
	'ExperimentRunFlags',
	'ExecutorConfig',
	'build_navigator_chat_model',
	'ExperimentResourceReport',
	'FailureMode',
	'HumanRunRecord',
	'NavigatorConfig',
	'PAPER_CONDITION_ADAPTIVE',
	'PAPER_EXPERIMENT_CA',
	'EligibilityResult',
	'HumanRunAuditWarning',
	'TaskTierMetadata',
	'TaskCard',
	'audit_human_run_record',
	'build_configs_from_args',
	'experiment_run_flags_from_args',
	'adjudicate_agent_summary',
	'build_experiment_resource_report',
	'build_executor_llm',
	'compare_agent_to_human_references',
	'compare_all',
	'default_max_actions_per_step_for_executor',
	'default_use_vision_for_executor',
	'describe_experiments_text',
	'experiment_preset',
	'paper_experiment_preset',
	'get_reference_human_runs',
	'infer_volcengine_ark_executor_model',
	'init_experiment',
	'is_human_reference_eligible',
	'get_main_tasks',
	'get_stress_tasks',
	'get_archived_tasks',
	'get_tasks_for_aggregate_metrics',
	'resolve_openai_compatible_credentials',
	'run_agent_task',
	'task_metadata_for',
	'validate_reference_eligibility',
]
