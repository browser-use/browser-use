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
from .experiment_presets import DailyExperimentId, build_configs_from_args, describe_experiments_text, experiment_preset
from .models import (
	AgentRunSummary,
	ComparisonRecord,
	ExperimentResourceReport,
	FailureMode,
	HumanRunRecord,
	TaskCard,
)
from .navigator import NavigatorConfig, NavigatorPlanProvider, build_navigator_chat_model
from .runner import build_experiment_resource_report, compare_all, init_experiment, run_agent_task

__all__ = [
	'AgentRunSummary',
	'ComparisonRecord',
	'DailyExperimentId',
	'ExecutorConfig',
	'build_navigator_chat_model',
	'ExperimentResourceReport',
	'FailureMode',
	'HumanRunRecord',
	'NavigatorConfig',
	'NavigatorPlanProvider',
	'TaskCard',
	'build_configs_from_args',
	'build_experiment_resource_report',
	'build_executor_llm',
	'compare_all',
	'default_max_actions_per_step_for_executor',
	'default_use_vision_for_executor',
	'describe_experiments_text',
	'experiment_preset',
	'infer_volcengine_ark_executor_model',
	'init_experiment',
	'resolve_openai_compatible_credentials',
	'run_agent_task',
]

