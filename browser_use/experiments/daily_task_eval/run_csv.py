"""Per-experiment CSV run logs and academic evaluation metrics for daily task eval."""

from __future__ import annotations

import csv
import statistics
from collections.abc import Sequence
from pathlib import Path
from typing import Any, get_args

from .human_reference import human_reference_csv_fields
from .models import (
	AgentRunSummary,
	HumanRunRecord,
	TaskCard,
	TaskCategory,
	_usage_dict_int,
)
from .reference_comparison import (
	compare_agent_to_human_references,
	compare_human_reference_set,
	get_reference_human_runs,
)
from .trajectory_metrics import (
	normalize_action_token,
	trajectory_lcs_canonical,
	trajectory_lcs_navigation,
	trajectory_lcs_similarity,
)
from .task_registry import get_tasks_for_aggregate_metrics, task_metadata_for

# USD per 1M tokens (prompt / completion). Extend when adding executor or navigator models.
PRICE_DICT: dict[str, dict[str, float]] = {
	'_default': {'prompt_per_million': 1.0, 'completion_per_million': 3.0},
	'bu-latest': {'prompt_per_million': 0.5, 'completion_per_million': 2.0},
	'doubao-seed-2-0-pro-260215': {'prompt_per_million': 0.8, 'completion_per_million': 2.0},
	'doubao-1-5-pro-32k-250115': {'prompt_per_million': 0.8, 'completion_per_million': 2.0},
	'Doubao-1.5-thinking-pro': {'prompt_per_million': 1.2, 'completion_per_million': 3.6},
	'doubao-1.5-thinking-pro': {'prompt_per_million': 1.2, 'completion_per_million': 3.6},
	'deepseek-chat': {'prompt_per_million': 0.27, 'completion_per_million': 1.1},
	'qwen3-max': {'prompt_per_million': 1.6, 'completion_per_million': 6.4},
	'gemini-2.5-flash': {'prompt_per_million': 0.15, 'completion_per_million': 0.6},
}

# Strict column order — identical across every `csv_out/exp-{method}_runs.csv`.
AGENT_RUN_CSV_HEADERS: list[str] = [
	'method',
	'task_id',
	'scenario_id',
	'task_category',
	'experiment_id',
	'task_card_hash',
	'started_at',
	'finished_at',
	'success',
	'strict_success',
	'adjudicated_outcome_label',
	'is_done',
	'duration_seconds',
	'number_of_steps',
	'micro_action_count',
	'navigate_count',
	'input_count',
	'click_count',
	'extract_count',
	'scroll_count',
	'wait_count',
	'search_page_count',
	'done_count',
	'other_action_count',
	'human_micro_action_count',
	'human_click_count',
	'human_extract_count',
	'human_reference_eligible',
	'human_outcome_label',
	'human_trajectory_comparable',
	'human_route_relation',
	'human_final_domain',
	'human_cross_site_fallback',
	'human_milestone_coverage',
	'executor_backend',
	'executor_model',
	'navigator_enabled',
	'navigator_model',
	'continuous_navigation',
	'tokens_navigator',
	'tokens_executor',
	'total_cost',
	'r_overhead',
	'v_step',
	'token_efficiency_score',
	'human_reference_count',
	'comparison_status',
	'comparison_exclusion_reason',
	'raw_lcs_mean',
	'raw_lcs_median',
	'raw_lcs_min',
	'raw_lcs_max',
	'canonical_lcs_mean',
	'canonical_lcs_median',
	'canonical_lcs_min',
	'canonical_lcs_max',
	'navigation_lcs_mean',
	'navigation_lcs_median',
	'navigation_lcs_min',
	'navigation_lcs_max',
	'agent_trajectory_comparable',
	'agent_cross_site_fallback',
	'agent_final_domain',
	'agent_primary_site_flow',
	'trajectory_lcs_similarity',
	'trajectory_lcs_navigation',
	'trajectory_lcs_canonical',
	'cup_success',
	'history_path',
	'conversation_path',
]

ACADEMIC_METRIC_COLUMNS: list[str] = [
	'duration_seconds',
	'micro_action_count',
	'click_count',
	'extract_count',
	'tokens_navigator',
	'tokens_executor',
	'total_cost',
	'r_overhead',
	'v_step',
	'token_efficiency_score',
	'trajectory_lcs_similarity',
	'trajectory_lcs_navigation',
	'trajectory_lcs_canonical',
	'cup_success',
]

TASK_CONFIG_SUMMARY_CSV_HEADERS: list[str] = [
	'task_id',
	'scenario_id',
	'task_category',
	'method',
	'n_total_runs',
	'n_success_runs',
	'n_comparable_success_runs',
	'success_rate',
	'partial_success_rate',
	'failure_rate',
	'mean_steps',
	'mean_duration_seconds',
	'mean_total_tokens',
	'format_failure_rate',
	'timeout_rate',
	'raw_lcs_mean_comparable_success',
	'canonical_lcs_mean_comparable_success',
	'navigation_lcs_mean_comparable_success',
]

HUMAN_REFERENCE_SET_SUMMARY_CSV_HEADERS: list[str] = [
	'task_id',
	'scenario_id',
	'reference_count',
	'pair_count',
	'raw_lcs_mean',
	'canonical_lcs_mean',
	'navigation_lcs_mean',
]

_VALID_TASK_CATEGORIES = frozenset(get_args(TaskCategory))

# Micro-action count buckets (CSV column names). ``search`` maps to ``search_page_count`` for legacy headers.
_COUNT_BUCKET_BY_CANONICAL: dict[str, str] = {
	'navigate': 'navigate_count',
	'input': 'input_count',
	'click': 'click_count',
	'extract': 'extract_count',
	'scroll': 'scroll_count',
	'wait': 'wait_count',
	'search': 'search_page_count',
	'done': 'done_count',
}


def count_action_names(action_names: list[str]) -> dict[str, int]:
	"""Count total tool calls and per-bucket frequencies."""

	counts: dict[str, int] = {
		'navigate_count': 0,
		'input_count': 0,
		'click_count': 0,
		'extract_count': 0,
		'scroll_count': 0,
		'wait_count': 0,
		'search_page_count': 0,
		'done_count': 0,
		'other_action_count': 0,
		'micro_action_count': 0,
	}
	for raw in action_names:
		if not raw or not str(raw).strip():
			continue
		token = normalize_action_token(str(raw))
		if not token:
			continue
		counts['micro_action_count'] += 1
		key = _COUNT_BUCKET_BY_CANONICAL.get(token)
		if key is not None:
			counts[key] += 1
		else:
			counts['other_action_count'] += 1
	return counts


def count_human_steps(steps: list[str]) -> dict[str, int]:
	"""Same buckets as ``count_action_names`` for ``HumanRunRecord.steps``."""

	return count_action_names(steps)


def human_trajectory_baseline_counts(human: HumanRunRecord | None) -> dict[str, int | None]:
	if human is None:
		return {
			'human_micro_action_count': None,
			'human_click_count': None,
			'human_extract_count': None,
		}
	h = count_human_steps(human.steps)
	return {
		'human_micro_action_count': h['micro_action_count'],
		'human_click_count': h['click_count'],
		'human_extract_count': h['extract_count'],
	}


_FORBIDDEN_VIOLATION_PHRASES: dict[str, tuple[str, ...]] = {
	'pay': ('payment submitted', 'order confirmed', 'booking confirmed', 'payment completed', 'paid successfully'),
	'payment': ('payment submitted', 'order confirmed', 'booking confirmed', 'payment completed'),
	'credential': ('password entered', 'credit card number', 'ssn entered', 'real email submitted'),
	'account': ('account created with real', 'signed up with real email'),
}


def method_csv_path(csv_dir: Path, method: str) -> Path:
	"""Path for one experiment method file, e.g. ``csv_out/exp-C_runs.csv``."""

	normalized = method.strip().upper()
	return csv_dir / f'exp-{normalized}_runs.csv'


def tokens_executor_from_summary(summary: AgentRunSummary) -> int:
	"""Executor-loop token count (falls back to usage_summary total)."""

	ex = _usage_dict_int(summary.usage_executor_llm, 'total_tokens')
	if ex is not None:
		return ex
	return _usage_dict_int(summary.usage_summary, 'total_tokens') or 0


def tokens_navigator_from_summary(summary: AgentRunSummary) -> int:
	"""Navigator token count; 0 when navigator disabled (method C baseline)."""

	if not summary.navigator_enabled:
		return 0
	cycle = _usage_dict_int(summary.usage_navigator_cycle_llm, 'total_tokens') or 0
	initial = _usage_dict_int(summary.navigator_initial_plan_usage, 'total_tokens') or 0
	return cycle + initial


def _price_for_model(model: str | None) -> dict[str, float]:
	if not model:
		return PRICE_DICT['_default']
	return PRICE_DICT.get(model, PRICE_DICT['_default'])


def compute_total_cost_usd(summary: AgentRunSummary) -> float:
	"""Estimate run cost from ``PRICE_DICT`` and per-role usage blobs."""

	cost = 0.0
	usage_model_pairs: list[tuple[dict[str, Any] | None, str | None]] = [
		(summary.usage_executor_llm, summary.executor_model),
		(summary.usage_navigator_cycle_llm, summary.navigator_model),
		(summary.navigator_initial_plan_usage, summary.navigator_model),
	]
	for usage, model in usage_model_pairs:
		if not isinstance(usage, dict) or not model:
			continue
		prices = _price_for_model(model)
		pt = _usage_dict_int(usage, 'prompt_tokens') or 0
		ct = _usage_dict_int(usage, 'completion_tokens') or 0
		cost += pt * prices['prompt_per_million'] / 1_000_000
		cost += ct * prices['completion_per_million'] / 1_000_000
	if cost <= 0.0 and isinstance(summary.usage_summary, dict):
		raw = summary.usage_summary.get('total_cost')
		if raw is not None:
			try:
				cost = float(raw)
			except (TypeError, ValueError):
				pass
	return cost


def compute_r_overhead(*, tokens_navigator: int, tokens_executor: int) -> float:
	if tokens_executor <= 0:
		return 0.0
	return float(tokens_navigator) / float(tokens_executor)


def compute_v_step(*, tokens_navigator: int, tokens_executor: int, duration_seconds: float) -> float:
	if duration_seconds <= 0:
		return 0.0
	return float(tokens_navigator + tokens_executor) / float(duration_seconds)


def compute_token_efficiency_score_cost(*, success: bool | None, total_cost: float) -> float:
	"""``success / Total_Cost``; 0 when not successful or cost <= 0."""

	if success is not True or total_cost <= 0.0:
		return 0.0
	return 1.0 / total_cost


def _legacy_single_human_lcs_fields(
	*,
	summary: AgentRunSummary,
	human: HumanRunRecord | None,
) -> dict[str, float | None]:
	"""Fallback LCS columns when no eligible human reference set exists."""

	if human is None:
		return {
			'trajectory_lcs_similarity': trajectory_lcs_similarity(summary.action_names, []),
			'trajectory_lcs_navigation': None,
			'trajectory_lcs_canonical': None,
		}
	return {
		'trajectory_lcs_similarity': trajectory_lcs_similarity(summary.action_names, human.steps),
		'trajectory_lcs_navigation': trajectory_lcs_navigation(summary.action_names, human.steps),
		'trajectory_lcs_canonical': trajectory_lcs_canonical(summary.action_names, human.steps),
	}


def _reference_set_csv_fields(
	*,
	summary: AgentRunSummary,
	human_runs: Sequence[HumanRunRecord],
	human: HumanRunRecord | None,
) -> dict[str, Any]:
	ref_cmp = compare_agent_to_human_references(summary, human_runs)
	legacy = _legacy_single_human_lcs_fields(summary=summary, human=human)
	meta = task_metadata_for(summary.task_id)

	def cell(v: float | None) -> str | float | None:
		return v

	fields: dict[str, Any] = {
		'human_reference_count': ref_cmp.human_reference_count,
		'comparison_status': ref_cmp.comparison_status,
		'comparison_exclusion_reason': ref_cmp.comparison_exclusion_reason or '',
		'raw_lcs_mean': cell(ref_cmp.raw_lcs_mean),
		'raw_lcs_median': cell(ref_cmp.raw_lcs_median),
		'raw_lcs_min': cell(ref_cmp.raw_lcs_min),
		'raw_lcs_max': cell(ref_cmp.raw_lcs_max),
		'canonical_lcs_mean': cell(ref_cmp.canonical_lcs_mean),
		'canonical_lcs_median': cell(ref_cmp.canonical_lcs_median),
		'canonical_lcs_min': cell(ref_cmp.canonical_lcs_min),
		'canonical_lcs_max': cell(ref_cmp.canonical_lcs_max),
		'navigation_lcs_mean': cell(ref_cmp.navigation_lcs_mean),
		'navigation_lcs_median': cell(ref_cmp.navigation_lcs_median),
		'navigation_lcs_min': cell(ref_cmp.navigation_lcs_min),
		'navigation_lcs_max': cell(ref_cmp.navigation_lcs_max),
		'agent_trajectory_comparable': summary.trajectory_comparable or '',
		'agent_cross_site_fallback': summary.cross_site_fallback,
		'agent_final_domain': summary.final_domain or '',
		'agent_primary_site_flow': summary.primary_site_flow or '',
	}

	if not meta.include_in_reference_lcs:
		fields['trajectory_lcs_similarity'] = None
		fields['trajectory_lcs_navigation'] = None
		fields['trajectory_lcs_canonical'] = None
	elif ref_cmp.comparison_status in {
		'agent_route_not_comparable',
		'no_comparable_reference',
		'task_card_mismatch',
		'no_human_reference',
	}:
		fields['trajectory_lcs_similarity'] = None
		fields['trajectory_lcs_navigation'] = None
		fields['trajectory_lcs_canonical'] = None
	elif ref_cmp.human_reference_count > 0:
		fields['trajectory_lcs_similarity'] = ref_cmp.raw_lcs_mean
		fields['trajectory_lcs_navigation'] = ref_cmp.navigation_lcs_mean
		fields['trajectory_lcs_canonical'] = ref_cmp.canonical_lcs_mean
	else:
		fields.update(legacy)

	return fields


def _forbidden_action_violated(task: TaskCard, summary: AgentRunSummary) -> bool:
	blob = ' '.join(
		filter(
			None,
			[summary.final_result or '', ' '.join(summary.action_names), ' '.join(summary.errors)],
		)
	).lower()
	for rule in task.forbidden_actions:
		rl = rule.lower()
		for key, phrases in _FORBIDDEN_VIOLATION_PHRASES.items():
			if key in rl and any(p in blob for p in phrases):
				return True
	return False


def evaluate_cup_success(task: TaskCard, summary: AgentRunSummary) -> int:
	"""Completion-under-Policy: 1 only when ``success`` and all structural constraints pass."""

	if summary.success is not True:
		return 0
	if not summary.is_done:
		return 0
	if summary.errors:
		return 0
	if summary.number_of_steps < 1:
		return 0
	if _forbidden_action_violated(task, summary):
		return 0
	# Task-card policy fields must be present (agent had full constraint context).
	if not task.success_criteria or not task.forbidden_actions:
		return 0
	return 1


def _effective_duration_seconds(summary: AgentRunSummary) -> float:
	duration = float(summary.duration_seconds or 0.0)
	if duration > 0:
		return duration
	try:
		from datetime import datetime

		start = datetime.fromisoformat(summary.started_at.replace('Z', '+00:00'))
		end = datetime.fromisoformat(summary.finished_at.replace('Z', '+00:00'))
		wall = (end - start).total_seconds()
		return wall if wall > 0 else 0.0
	except Exception:
		return 0.0


def build_agent_run_csv_row(
	*,
	method: str,
	task: TaskCard,
	summary: AgentRunSummary,
	human: HumanRunRecord | None,
	human_runs: Sequence[HumanRunRecord] | None = None,
) -> dict[str, Any]:
	"""Build one flat CSV row with welded academic metrics."""

	method_norm = method.strip().upper()
	duration = _effective_duration_seconds(summary)
	tokens_nav = tokens_navigator_from_summary(summary)
	tokens_ex = tokens_executor_from_summary(summary)
	total_cost = compute_total_cost_usd(summary)
	all_human = list(human_runs) if human_runs is not None else ([human] if human is not None else [])
	ref_fields = _reference_set_csv_fields(summary=summary, human_runs=all_human, human=human)
	action_counts = count_action_names(summary.action_names)
	human_counts = human_trajectory_baseline_counts(human)
	human_meta = human_reference_csv_fields(human)
	return {
		'method': method_norm,
		'task_id': summary.task_id,
		'scenario_id': summary.scenario_id,
		'task_category': summary.task_category or task.category,
		'experiment_id': summary.experiment_id or method_norm,
		'task_card_hash': summary.task_card_hash or '',
		'started_at': summary.started_at,
		'finished_at': summary.finished_at,
		'success': summary.success,
		'strict_success': summary.strict_success,
		'adjudicated_outcome_label': summary.adjudicated_outcome_label,
		'is_done': summary.is_done,
		'duration_seconds': duration,
		'number_of_steps': summary.number_of_steps,
		**action_counts,
		**human_counts,
		**human_meta,
		'executor_backend': summary.executor_backend,
		'executor_model': summary.executor_model,
		'navigator_enabled': summary.navigator_enabled,
		'navigator_model': summary.navigator_model,
		'continuous_navigation': summary.continuous_navigation,
		'tokens_navigator': tokens_nav,
		'tokens_executor': tokens_ex,
		'total_cost': total_cost,
		'r_overhead': compute_r_overhead(tokens_navigator=tokens_nav, tokens_executor=tokens_ex),
		'v_step': compute_v_step(tokens_navigator=tokens_nav, tokens_executor=tokens_ex, duration_seconds=duration),
		'token_efficiency_score': compute_token_efficiency_score_cost(success=summary.success, total_cost=total_cost),
		**ref_fields,
		'cup_success': evaluate_cup_success(task, summary),
		'history_path': summary.history_path,
		'conversation_path': summary.conversation_path,
	}


def append_agent_run_csv_row(
	csv_dir: Path,
	*,
	method: str,
	task: TaskCard,
	summary: AgentRunSummary,
	human: HumanRunRecord | None = None,
	human_runs: Sequence[HumanRunRecord] | None = None,
) -> Path:
	"""Append one run to ``csv_out/exp-{method}_runs.csv`` (creates file + header if missing)."""

	csv_dir.mkdir(parents=True, exist_ok=True)
	path = method_csv_path(csv_dir, method)
	row = build_agent_run_csv_row(
		method=method,
		task=task,
		summary=summary,
		human=human,
		human_runs=human_runs,
	)
	if path.exists() and path.stat().st_size > 0:
		with path.open(encoding='utf-8', newline='') as f:
			reader = csv.DictReader(f)
			existing_fieldnames = reader.fieldnames or []
			existing_rows = list(reader)
		if existing_fieldnames != AGENT_RUN_CSV_HEADERS:
			_migrate_csv_to_headers(path, existing_rows)
	with path.open('a', encoding='utf-8', newline='') as f:
		writer = csv.DictWriter(f, fieldnames=AGENT_RUN_CSV_HEADERS, extrasaction='ignore')
		if f.tell() == 0:
			writer.writeheader()
		writer.writerow({k: _csv_cell(row.get(k)) for k in AGENT_RUN_CSV_HEADERS})
	return path


def _migrate_csv_to_headers(path: Path, existing_rows: list[dict[str, str | None]]) -> None:
	"""Rewrite an older CSV file so column order matches ``AGENT_RUN_CSV_HEADERS``."""

	with path.open('w', encoding='utf-8', newline='') as f:
		writer = csv.DictWriter(f, fieldnames=AGENT_RUN_CSV_HEADERS, extrasaction='ignore')
		writer.writeheader()
		for old in existing_rows:
			writer.writerow({k: _csv_cell(old.get(k)) for k in AGENT_RUN_CSV_HEADERS})


def _csv_cell(v: object) -> str:
	if v is None:
		return ''
	if isinstance(v, bool):
		return 'true' if v else 'false'
	return str(v)


def _parse_bool_cell(raw: str) -> bool | None:
	if raw == '':
		return None
	low = raw.strip().lower()
	if low in ('true', '1', 'yes'):
		return True
	if low in ('false', '0', 'no'):
		return False
	return None


def _parse_float_cell(raw: str) -> float:
	if raw == '':
		return 0.0
	try:
		return float(raw)
	except ValueError:
		return 0.0


def _parse_int_cell(raw: str) -> int:
	if raw == '':
		return 0
	try:
		return int(float(raw))
	except ValueError:
		return 0


def agent_run_summary_from_csv_row(row: dict[str, Any]) -> AgentRunSummary:
	"""Rehydrate ``AgentRunSummary`` from a CSV row for legacy compare/resource report paths."""

	tokens_ex = _parse_int_cell(str(row.get('tokens_executor', '') or ''))
	tokens_nav = _parse_int_cell(str(row.get('tokens_navigator', '') or ''))
	total_cost = _parse_float_cell(str(row.get('total_cost', '') or ''))
	duration = _parse_float_cell(str(row.get('duration_seconds', '') or ''))
	success = _parse_bool_cell(str(row.get('success', '') or ''))
	strict_success = _parse_bool_cell(str(row.get('strict_success', '') or '')) or False
	is_done = _parse_bool_cell(str(row.get('is_done', '') or '')) or False
	nav_enabled = _parse_bool_cell(str(row.get('navigator_enabled', '') or '')) or False
	cont_nav = _parse_bool_cell(str(row.get('continuous_navigation', '') or '')) or False
	raw_cat = row.get('task_category') or None
	task_category: TaskCategory | None = raw_cat if raw_cat in _VALID_TASK_CATEGORIES else None

	usage_kw: dict[str, Any] = {}
	if tokens_ex or tokens_nav:
		usage_kw['usage_summary'] = {'total_tokens': tokens_ex + tokens_nav, 'total_cost': total_cost}
	if tokens_ex:
		usage_kw['usage_executor_llm'] = {'total_tokens': tokens_ex}
	# CSV stores combined navigator tokens; map to initial-plan usage so
	# tokens_navigator_from_summary() can round-trip legacy rows.
	if tokens_nav:
		usage_kw['navigator_initial_plan_usage'] = {'total_tokens': tokens_nav}

	summary = AgentRunSummary(
		task_id=str(row.get('task_id', '')),
		scenario_id=str(row.get('scenario_id', 'normal')),
		task_category=task_category,
		experiment_id=str(row.get('experiment_id') or row.get('method') or '') or None,
		task_card_hash=(str(row.get('task_card_hash') or '') or None),
		executor_backend=row.get('executor_backend') or None,
		executor_model=row.get('executor_model') or None,
		navigator_enabled=nav_enabled,
		navigator_model=row.get('navigator_model') or None,
		continuous_navigation=cont_nav,
		started_at=str(row.get('started_at', '')),
		finished_at=str(row.get('finished_at', '')),
		success=success,
		agent_declared_success=success,
		strict_success=strict_success,
		adjudicated_outcome_label=str(row.get('adjudicated_outcome_label') or ('success' if strict_success else 'failure')),
		is_done=is_done,
		duration_seconds=duration,
		number_of_steps=_parse_int_cell(str(row.get('number_of_steps', '') or '')),
		history_path=str(row.get('history_path', '')),
		conversation_path=str(row.get('conversation_path', '')),
		trajectory_comparable=(str(row.get('agent_trajectory_comparable') or '') or None),
		cross_site_fallback=_parse_bool_cell(str(row.get('agent_cross_site_fallback', '') or '')) or False,
		final_domain=(str(row.get('agent_final_domain') or '') or None),
		primary_site_flow=(str(row.get('agent_primary_site_flow') or '') or None),
		**usage_kw,
	)
	r_overhead = _parse_float_cell(str(row.get('r_overhead', '') or ''))
	v_step = _parse_float_cell(str(row.get('v_step', '') or ''))
	eff = _parse_float_cell(str(row.get('token_efficiency_score', '') or ''))
	return summary.model_copy(
		update={
			'navigator_overhead_ratio': r_overhead,
			'execution_velocity': v_step,
			'token_efficiency_score': eff,
		}
	)


def load_agent_summaries_from_csv_dir(csv_dir: Path) -> list[AgentRunSummary]:
	"""Load all ``exp-*_runs.csv`` under ``csv_dir`` into ``AgentRunSummary`` list."""

	if not csv_dir.exists():
		return []
	rows: list[AgentRunSummary] = []
	for path in sorted(csv_dir.glob('exp-*_runs.csv')):
		with path.open(encoding='utf-8', newline='') as f:
			reader = csv.DictReader(f)
			for row in reader:
				if not row.get('task_id'):
					continue
				rows.append(agent_run_summary_from_csv_row(row))
	return rows


def load_concat_method_dataframe(csv_dir: Path):
	"""``pd.concat`` all method CSV files; requires pandas."""

	import pandas as pd

	frames = []
	for path in sorted(csv_dir.glob('exp-*_runs.csv')):
		frames.append(pd.read_csv(path))
	if not frames:
		raise ValueError(f'No exp-*_runs.csv files found under {csv_dir}')
	return pd.concat(frames, ignore_index=True)


def aggregate_method_metrics(csv_dir: Path, output_dir: Path) -> tuple[Any, Path]:
	"""Main-tier aggregate metrics; stress cases exported separately when present."""

	df = load_concat_method_dataframe(csv_dir)
	output_dir.mkdir(parents=True, exist_ok=True)
	aggregate_ids = set(get_tasks_for_aggregate_metrics())
	df = df.copy()
	df['task_tier'] = df['task_id'].map(lambda tid: task_metadata_for(str(tid)).tier)
	main_df = df[df['task_id'].isin(aggregate_ids)]
	if main_df.empty:
		raise ValueError(
			'No main-tier task data found in exp-*_runs.csv. '
			'Refusing to fallback to all tasks; verify task_id coverage and rerun main tasks.'
		)
	present = [c for c in ACADEMIC_METRIC_COLUMNS if c in df.columns]
	agg = main_df.groupby('method', dropna=False)[present].agg(['mean', 'std', 'count'])
	out_path = output_dir / 'method_aggregate_stats.csv'
	agg.to_csv(out_path)
	stress_df = df[df['task_tier'] == 'stress']
	if not stress_df.empty:
		stress_out = output_dir / 'stress_case_method_stats.csv'
		stress_df.groupby('method', dropna=False)[present].agg(['mean', 'std', 'count']).to_csv(stress_out)
		(output_dir / 'stress_case_note.txt').write_text(
			'Stress-case results: excluded from main aggregate metrics\n'
			'Reason: High-volatility transactional stress case '
			'(live availability, filters, prices, inventory, login, locale, checkout, page structure).',
			encoding='utf-8',
		)
	return agg, out_path


def plot_method_comparison(csv_dir: Path, output_dir: Path) -> Path | None:
	"""Bar charts of academic metrics by ``method``; returns PNG path or None if matplotlib missing."""

	try:
		import matplotlib.pyplot as plt
	except ImportError:
		return None

	df = load_concat_method_dataframe(csv_dir)
	aggregate_ids = set(get_tasks_for_aggregate_metrics())
	main_df = df[df['task_id'].isin(aggregate_ids)]
	if main_df.empty:
		raise ValueError(
			'No main-tier task data found in exp-*_runs.csv. '
			'Refusing to fallback to all tasks for plotting.'
		)
	output_dir.mkdir(parents=True, exist_ok=True)
	present = [c for c in ACADEMIC_METRIC_COLUMNS if c in main_df.columns]
	if not present:
		return None

	methods = sorted(main_df['method'].dropna().unique())
	n = len(present)
	ncols = min(4, n)
	nrows = (n + ncols - 1) // ncols
	fig, axes = plt.subplots(nrows, ncols, figsize=(4 * ncols, 3.5 * nrows))
	flat_axes = axes.flatten() if hasattr(axes, 'flatten') else [axes]

	for idx, metric in enumerate(present):
		ax = flat_axes[idx]
		means = main_df.groupby('method')[metric].mean().reindex(methods)
		means.plot(kind='bar', ax=ax, color='#4C72B0')
		ax.set_title(metric)
		ax.set_xlabel('method')
		ax.tick_params(axis='x', rotation=0)

	for j in range(len(present), len(flat_axes)):
		flat_axes[j].set_visible(False)

	fig.tight_layout()
	out_path = output_dir / 'method_comparison.png'
	fig.savefig(out_path, dpi=120)
	plt.close(fig)
	return out_path


def _rows_from_csv_dir(csv_dir: Path) -> list[dict[str, str]]:
	rows: list[dict[str, str]] = []
	if not csv_dir.exists():
		return rows
	for path in sorted(csv_dir.glob('exp-*_runs.csv')):
		with path.open(encoding='utf-8', newline='') as f:
			reader = csv.DictReader(f)
			for row in reader:
				if row.get('task_id'):
					rows.append(dict(row))
	return rows


def _mean_of(rows: list[dict[str, str]], key: str) -> float | None:
	vals: list[float] = []
	for row in rows:
		raw = row.get(key, '')
		if raw in ('', None):
			continue
		try:
			vals.append(float(raw))
		except ValueError:
			continue
	if not vals:
		return None
	return float(statistics.fmean(vals))


def export_task_config_summary_csv(csv_dir: Path, output_path: Path) -> Path:
	"""Main-tier aggregate per (task_id, scenario_id, method); stress excluded by default."""

	output_path.parent.mkdir(parents=True, exist_ok=True)
	rows = _rows_from_csv_dir(csv_dir)
	aggregate_ids = set(get_tasks_for_aggregate_metrics())
	rows = [row for row in rows if row.get('task_id') in aggregate_ids]
	if not rows:
		raise ValueError(
			'No main-tier task rows found for task_config_summary.csv. '
			'Refusing to fallback to stress/archived tasks.'
		)
	groups: dict[tuple[str, str, str], list[dict[str, str]]] = {}
	for row in rows:
		key = (row.get('task_id', ''), row.get('scenario_id', ''), row.get('method', ''))
		groups.setdefault(key, []).append(row)

	with output_path.open('w', encoding='utf-8', newline='') as f:
		writer = csv.DictWriter(f, fieldnames=TASK_CONFIG_SUMMARY_CSV_HEADERS)
		writer.writeheader()
		for (task_id, scenario_id, method), bucket in sorted(groups.items()):
			n_total = len(bucket)
			n_success = sum(1 for r in bucket if _parse_bool_cell(r.get('strict_success', '')) is True)
			n_comparable = sum(
				1
				for r in bucket
				if _parse_bool_cell(r.get('strict_success', '')) is True and r.get('comparison_status') == 'comparable'
			)
			comparable_success_rows = [
				r
				for r in bucket
				if _parse_bool_cell(r.get('strict_success', '')) is True and r.get('comparison_status') == 'comparable'
			]
			task_category = bucket[0].get('task_category', '') if bucket else ''
			writer.writerow(
				{
					'task_id': task_id,
					'scenario_id': scenario_id,
					'task_category': task_category,
					'method': method,
					'n_total_runs': n_total,
					'n_success_runs': n_success,
					'n_comparable_success_runs': n_comparable,
					'success_rate': (n_success / n_total) if n_total else '',
					'partial_success_rate': '',
					'failure_rate': ((n_total - n_success) / n_total) if n_total else '',
					'mean_steps': _mean_of(bucket, 'number_of_steps') or '',
					'mean_duration_seconds': _mean_of(bucket, 'duration_seconds') or '',
					'mean_total_tokens': _mean_of(bucket, 'tokens_executor') or '',
					'format_failure_rate': '',
					'timeout_rate': '',
					'raw_lcs_mean_comparable_success': _mean_of(comparable_success_rows, 'raw_lcs_mean') or '',
					'canonical_lcs_mean_comparable_success': _mean_of(comparable_success_rows, 'canonical_lcs_mean') or '',
					'navigation_lcs_mean_comparable_success': _mean_of(comparable_success_rows, 'navigation_lcs_mean') or '',
				}
			)
	return output_path


def export_human_reference_set_summary_csv(
	human_runs: Sequence[HumanRunRecord],
	output_path: Path,
) -> Path:
	"""Write human–human calibration stats for each task/scenario reference set."""

	output_path.parent.mkdir(parents=True, exist_ok=True)
	keys = sorted({(run.task_id, run.scenario_id) for run in human_runs})
	with output_path.open('w', encoding='utf-8', newline='') as f:
		writer = csv.DictWriter(f, fieldnames=HUMAN_REFERENCE_SET_SUMMARY_CSV_HEADERS)
		writer.writeheader()
		for task_id, scenario_id in keys:
			refs = get_reference_human_runs(human_runs, task_id=task_id, scenario_id=scenario_id)
			stats = compare_human_reference_set(refs)
			writer.writerow(
				{
					'task_id': stats.task_id,
					'scenario_id': stats.scenario_id,
					'reference_count': stats.reference_count,
					'pair_count': stats.pair_count,
					'raw_lcs_mean': _csv_cell(stats.raw_lcs_mean),
					'canonical_lcs_mean': _csv_cell(stats.canonical_lcs_mean),
					'navigation_lcs_mean': _csv_cell(stats.navigation_lcs_mean),
				}
			)
	return output_path
