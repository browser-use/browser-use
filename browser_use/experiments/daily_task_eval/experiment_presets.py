"""Experiment presets A–D and paper conditions (E/I/R-*/R-A) for daily task evaluation.

Layout (all under `browser_use.experiments.daily_task_eval`):
- `experiment_presets.py` — this file: preset table + CLI resolution
- `executor.py` — executor LLM (`ExecutorConfig`, `build_executor_llm`)
- `navigator.py` — navigator plans (`NavigatorConfig`, `NavigatorPlanProvider`)
- `runner.py` — orchestrates Agent + filesystem artifacts

Presets (matches tmp doc intent):
- A: no navigator + ChatBrowserUse executor
- B: DeepSeek navigator + ChatBrowserUse executor
- C: no navigator + Doubao (Volcengine Ark OpenAI-compatible) executor
- D: DeepSeek navigator + Doubao executor

Paper conditions (Doubao executor; navigator model varies):
- C → E (executor only)
- D → I (one-shot opening plan)
- C1/C3/C5 → R-1/R-3/R-5 (fixed-interval continuous navigation; DeepSeek navigator)
- CA → R-A (event-triggered adaptive replan; same DeepSeek navigator as I/R-*)
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Any

from .executor import (
	DEFAULT_GEMINI_MODEL,
	VOLCES_ARK_API_KEY_ENV,
	VOLCES_ARK_CN_OPENAI_COMPAT_BASE_URL,
	ExecutorConfig,
	resolve_openai_compatible_credentials,
)
from .adaptive_replan import AdaptiveReplanSettings, default_adaptive_replan_settings
from .navigator import NavigatorConfig

DEFAULT_QWEN_MODEL = 'qwen3-max'
DEFAULT_DOUBAO_EXECUTOR_MODEL = 'doubao-seed-2-0-pro-260215'
DEFAULT_DEEPSEEK_NAV_MODEL = 'deepseek-chat'

# OpenAI-compatible DashScope base URLs (must match where the API key was issued).
DASHSCOPE_CN_BASE_URL = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
DASHSCOPE_INTL_BASE_URL = 'https://dashscope-intl.aliyuncs.com/compatible-mode/v1'

PAPER_EXPERIMENT_CA = 'CA'
PAPER_CONDITION_ADAPTIVE = 'R-A'


@dataclass(frozen=True)
class ExperimentRunFlags:
	"""Agent/runtime flags tied to a paper experiment id (beyond executor/navigator LLM choice)."""

	continuous_navigation: bool = False
	replan_policy: str = 'scheduled'
	navigator_replan_interval: int = 5
	adaptive_replan_settings: AdaptiveReplanSettings | None = None
	paper_condition: str | None = None


PAPER_EXPERIMENT_RUN_FLAGS: dict[str, ExperimentRunFlags] = {
	'C': ExperimentRunFlags(paper_condition='E'),
	'D': ExperimentRunFlags(paper_condition='I'),
	'C1': ExperimentRunFlags(continuous_navigation=True, navigator_replan_interval=1, paper_condition='R-1'),
	'C3': ExperimentRunFlags(continuous_navigation=True, navigator_replan_interval=3, paper_condition='R-3'),
	'C5': ExperimentRunFlags(continuous_navigation=True, navigator_replan_interval=5, paper_condition='R-5'),
	PAPER_EXPERIMENT_CA: ExperimentRunFlags(
		continuous_navigation=True,
		replan_policy='event_triggered',
		adaptive_replan_settings=default_adaptive_replan_settings(),
		paper_condition=PAPER_CONDITION_ADAPTIVE,
	),
}


class DailyExperimentId(str, Enum):
	A = 'A'
	B = 'B'
	C = 'C'
	D = 'D'


EXPERIMENT_DESCRIPTIONS: dict[DailyExperimentId, str] = {
	DailyExperimentId.A: 'No navigator + ChatBrowserUse executor',
	DailyExperimentId.B: 'DeepSeek navigator + ChatBrowserUse executor',
	DailyExperimentId.C: 'No navigator + Doubao (Volcengine Ark) executor',
	DailyExperimentId.D: 'DeepSeek navigator + Doubao (Volcengine Ark) executor',
}


def describe_experiments_text() -> str:
	lines = ['Daily experiment presets (--experiment):']
	for exp_id in DailyExperimentId:
		lines.append(f'  {exp_id.value}: {EXPERIMENT_DESCRIPTIONS[exp_id]}')
	lines.append(
		f'  {PAPER_EXPERIMENT_CA}: Doubao executor + DeepSeek navigator (same as I/R-*), '
		f'event-triggered adaptive replan (paper condition {PAPER_CONDITION_ADAPTIVE})'
	)
	return '\n'.join(lines)


def doubao_executor_config() -> ExecutorConfig:
	return ExecutorConfig(
		backend='openai_compatible',
		model=DEFAULT_DOUBAO_EXECUTOR_MODEL,
		api_key_env=VOLCES_ARK_API_KEY_ENV,
		base_url=VOLCES_ARK_CN_OPENAI_COMPAT_BASE_URL,
		temperature=0.0,
		use_vision=False,
	)


def deepseek_navigator_config() -> NavigatorConfig:
	return NavigatorConfig(
		enabled=True,
		backend='deepseek',
		model=DEFAULT_DEEPSEEK_NAV_MODEL,
		api_key_env='DEEPSEEK_API_KEY',
		base_url='https://api.deepseek.com/v1',
		temperature=0.0,
	)


def experiment_preset(experiment: DailyExperimentId) -> tuple[ExecutorConfig, NavigatorConfig]:
	"""Return (executor, navigator) configuration for a labeled experiment."""

	if experiment == DailyExperimentId.A:
		return (
			ExecutorConfig(backend='chat_browser_use', model='bu-latest', use_vision='auto'),
			NavigatorConfig(enabled=False),
		)
	if experiment == DailyExperimentId.B:
		return (
			ExecutorConfig(backend='chat_browser_use', model='bu-latest', use_vision='auto'),
			NavigatorConfig(
				enabled=True,
				backend='deepseek',
				model=DEFAULT_DEEPSEEK_NAV_MODEL,
				api_key_env='DEEPSEEK_API_KEY',
				base_url='https://api.deepseek.com/v1',
			),
		)
	if experiment == DailyExperimentId.C:
		return doubao_executor_config(), NavigatorConfig(enabled=False)
	if experiment == DailyExperimentId.D:
		return (
			doubao_executor_config(),
			deepseek_navigator_config(),
		)
	raise ValueError(f'Unknown experiment: {experiment}')


def paper_experiment_preset(experiment_id: str) -> tuple[ExecutorConfig, NavigatorConfig]:
	"""Return (executor, navigator) for paper experiment ids outside DailyExperimentId (e.g. CA)."""

	if experiment_id == PAPER_EXPERIMENT_CA:
		return doubao_executor_config(), deepseek_navigator_config()
	raise ValueError(f'Unknown paper experiment id: {experiment_id}')


def experiment_run_flags_from_args(args: Any) -> ExperimentRunFlags:
	"""Resolve continuous-navigation flags from --experiment preset and optional CLI overrides."""

	exp = getattr(args, 'experiment', None)
	flags = PAPER_EXPERIMENT_RUN_FLAGS.get(exp or '', ExperimentRunFlags())
	if getattr(args, 'continuous_navigation', False):
		flags = replace(flags, continuous_navigation=True)
	interval_override = getattr(args, 'navigator_replan_interval', None)
	if interval_override is not None:
		flags = replace(flags, navigator_replan_interval=int(interval_override))
	return flags


def _executor_config_from_cli(
	executor_backend: str,
	executor_model: str | None,
	raw_executor_api_key_env: str | None,
	raw_executor_base_url: str | None,
) -> ExecutorConfig:
	if executor_backend == 'chat_browser_use':
		return ExecutorConfig(
			backend='chat_browser_use',
			model=executor_model or 'bu-latest',
			use_vision='auto',
		)
	if executor_backend == 'google':
		api_key_env = raw_executor_api_key_env if raw_executor_api_key_env is not None else 'GOOGLE_API_KEY'
		return ExecutorConfig(
			backend='google',
			model=executor_model or DEFAULT_GEMINI_MODEL,
			api_key_env=api_key_env,
			use_vision='auto',
		)
	m = executor_model or DEFAULT_QWEN_MODEL
	api_key_env, base_url = resolve_openai_compatible_credentials(m, raw_executor_api_key_env, raw_executor_base_url)
	return ExecutorConfig(
		backend='openai_compatible',
		model=m,
		api_key_env=api_key_env,
		base_url=base_url,
		use_vision='auto',
	)


def build_configs_from_args(args: Any) -> tuple[ExecutorConfig, NavigatorConfig, str | None]:
	"""Build executor/navigator from CLI. Returns (executor, navigator, experiment_id_or_none)."""

	executor_backend_cli = getattr(args, 'executor_backend', None)
	executor_model = getattr(args, 'executor_model', None)
	raw_executor_api_key_env = getattr(args, 'executor_api_key_env', None)
	raw_executor_base_url = getattr(args, 'executor_base_url', None)

	if getattr(args, 'experiment', None):
		if getattr(args, 'use_navigator', False):
			raise ValueError('--use-navigator cannot be combined with --experiment (preset defines navigator).')
		raw_exp = str(args.experiment)
		if raw_exp == PAPER_EXPERIMENT_CA:
			ex, nav = paper_experiment_preset(raw_exp)
			exp_id = raw_exp
		else:
			exp = DailyExperimentId(raw_exp)
			ex, nav = experiment_preset(exp)
			exp_id = exp.value
		if executor_backend_cli is not None:
			ex = _executor_config_from_cli(
				executor_backend_cli,
				executor_model,
				raw_executor_api_key_env,
				raw_executor_base_url,
			)
		elif executor_model is not None:
			if ex.backend == 'openai_compatible':
				api_key_env, base_url = resolve_openai_compatible_credentials(
					executor_model,
					raw_executor_api_key_env,
					raw_executor_base_url,
				)
				ex = replace(ex, model=executor_model, api_key_env=api_key_env, base_url=base_url)
				if nav.enabled and nav.backend == 'openai_compatible':
					nav = replace(nav, model=executor_model, api_key_env=api_key_env, base_url=base_url)
			else:
				ex = replace(ex, model=executor_model)
		return ex, nav, exp_id

	executor_backend = executor_backend_cli or 'chat_browser_use'
	ex = _executor_config_from_cli(
		executor_backend,
		executor_model,
		raw_executor_api_key_env,
		raw_executor_base_url,
	)

	nav_backend = getattr(args, 'navigator_backend', None) or 'none'
	if getattr(args, 'use_navigator', False) and nav_backend == 'none':
		nav_backend = 'openai_compatible'

	nav_model = getattr(args, 'navigator_model', None)
	nav_api_key_env = getattr(args, 'navigator_api_key_env', None) or 'DASHSCOPE_API_KEY'
	nav_base_url = getattr(args, 'navigator_base_url', None) or DASHSCOPE_CN_BASE_URL

	if nav_backend == 'none':
		nav = NavigatorConfig(enabled=False)
	elif nav_backend == 'openai_compatible':
		nav = NavigatorConfig(
			enabled=True,
			backend='openai_compatible',
			model=nav_model or DEFAULT_QWEN_MODEL,
			api_key_env=nav_api_key_env,
			base_url=nav_base_url,
		)
	elif nav_backend == 'deepseek':
		nav = NavigatorConfig(
			enabled=True,
			backend='deepseek',
			model=nav_model or DEFAULT_DEEPSEEK_NAV_MODEL,
			api_key_env=getattr(args, 'navigator_deepseek_api_key_env', None) or 'DEEPSEEK_API_KEY',
			base_url=getattr(args, 'navigator_deepseek_base_url', None) or 'https://api.deepseek.com/v1',
		)
	else:
		raise ValueError(f'Unknown --navigator-backend: {nav_backend}')

	return ex, nav, None
