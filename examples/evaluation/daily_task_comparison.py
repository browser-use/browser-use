"""CLI wrapper for the daily task evaluation module.

The implementation lives in `browser_use.experiments.daily_task_eval` so it can be reused
as a pluggable module without editing core agent code.

Experiment presets (A–D) are defined in `browser_use.experiments.daily_task_eval.experiment_presets`.
"""

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

sys.path.append(str(Path(__file__).resolve().parents[2]))

from browser_use.experiments.daily_task_eval.experiment_presets import (
	build_configs_from_args,
	describe_experiments_text,
	experiment_run_flags_from_args,
)
from browser_use.experiments.daily_task_eval.executor import default_use_vision_for_executor
from browser_use.experiments.daily_task_eval.human_reference import audit_human_run_record, validate_reference_eligibility
from browser_use.experiments.daily_task_eval.models import AgentRunSummary, HumanRunRecord, TaskCard, load_json_model_list, write_json
from browser_use.experiments.daily_task_eval.run_csv import (
	aggregate_method_metrics,
	export_human_reference_set_summary_csv,
	export_task_config_summary_csv,
	plot_method_comparison,
)
from browser_use.experiments.daily_task_eval.runner import (
	adjudicate_agent_summary,
	compare_all,
	export_agent_runs_to_csv,
	export_experiment_resource_report_to_csv,
	index_by_task_and_scenario,
	init_experiment,
	run_agent_task,
)
from browser_use.experiments.daily_task_eval.task_registry import (
	get_archived_tasks,
	get_main_tasks,
	get_stress_tasks,
	task_metadata_for,
)


def _apply_log_level(log_level: str | None) -> None:
	"""Re-run browser-use logging setup with the requested verbosity.

	Setting the env var first matches the canonical `BROWSER_USE_LOGGING_LEVEL` knob, so
	any later imports (CDP, bubus) that consult it pick up the same value.
	"""
	if not log_level:
		return
	os.environ['BROWSER_USE_LOGGING_LEVEL'] = log_level
	from browser_use.logging_config import setup_logging

	setup_logging(log_level=log_level, force_setup=True)


def _parse_use_vision_cli(value: str) -> Literal['auto', True, False]:
	"""Maps ``--use-vision`` string to ``ExecutorConfig.use_vision``."""
	if value == 'auto':
		return 'auto'
	if value == 'true':
		return True
	if value == 'false':
		return False
	raise ValueError(f'Invalid --use-vision: {value!r}')


def _stable_sha256(payload: dict | list | str) -> str:
	if isinstance(payload, str):
		raw = payload
	else:
		raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
	return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _resolve_git_commit_hash() -> str | None:
	try:
		proc = subprocess.run(
			['git', 'rev-parse', 'HEAD'],
			check=True,
			capture_output=True,
			text=True,
			timeout=5,
		)
	except Exception:
		return None
	commit = proc.stdout.strip()
	return commit or None


def _print_task_catalog(tasks: list[TaskCard]) -> None:
	print('Task list (id [tier]):')
	for task in tasks:
		meta = task_metadata_for(task.id)
		note = f' - {meta.benchmark_note}' if meta.benchmark_note else ''
		print(f'  - {task.id} [{meta.tier}]{note}')


def _resolve_selected_tasks(tasks: list[TaskCard], args: argparse.Namespace) -> list[TaskCard]:
	if args.task_id:
		selected = [task for task in tasks if task.id == args.task_id]
		if not selected:
			raise ValueError(f'No task card matched task id: {args.task_id}')
		meta = task_metadata_for(args.task_id)
		if meta.tier == 'archived':
			print(
				f'WARNING: {args.task_id} is archived and excluded from benchmark aggregates. '
				'It can run only as an explicit --task-id case study.'
			)
		elif meta.tier == 'stress':
			print(f'NOTE: {args.task_id} is a stress task ({meta.benchmark_note}).')
		return selected
	allowed_ids = set(get_main_tasks())
	if getattr(args, 'include_stress', False):
		allowed_ids |= set(get_stress_tasks())
	return [task for task in tasks if task.id in allowed_ids]


def _print_human_data_audit(human_runs: list[HumanRunRecord], tasks: list[TaskCard]) -> None:
	task_index = {task.id: task for task in tasks}
	warnings = []
	for run in human_runs:
		warnings.extend(audit_human_run_record(run, task_index.get(run.task_id)))
	if not warnings:
		print('Human-run strict audit: no mismatches detected.')
		return
	print(f'Human-run strict audit: {len(warnings)} warning(s).')
	for warning in warnings:
		fields = ','.join(warning.conflicting_fields)
		print(
			f'  - {warning.run_identifier} [{warning.code}] '
			f'fields={fields} recommend={warning.recommended_status}'
		)


async def run_agent_command(args: argparse.Namespace) -> None:
	_apply_log_level(getattr(args, 'log_level', None))
	try:
		executor_cfg, navigator_cfg, experiment_id = build_configs_from_args(args)
		run_flags = experiment_run_flags_from_args(args)
	except ValueError as exc:
		print(str(exc), file=sys.stderr)
		raise SystemExit(2) from exc
	if getattr(args, 'executor_use_vision', None) is not None:
		executor_cfg = replace(
			executor_cfg,
			use_vision=_parse_use_vision_cli(args.executor_use_vision),
		)

	tasks = load_json_model_list(Path(args.task_cards), TaskCard)
	if getattr(args, 'list_tasks', False):
		_print_task_catalog(tasks)
		return
	selected_tasks = _resolve_selected_tasks(tasks, args)
	if not selected_tasks:
		raise ValueError('No tasks selected. Use --task-id or --include-stress as needed.')
	print('Selected tasks:')
	_print_task_catalog(selected_tasks)

	csv_dir = Path(args.output_dir) / 'csv_out'
	csv_dir.mkdir(parents=True, exist_ok=True)
	human_runs_list = load_json_model_list(Path(args.human_runs), HumanRunRecord)
	_print_human_data_audit(human_runs_list, tasks)
	human_runs = index_by_task_and_scenario(human_runs_list)

	agent_runs_path = Path(args.output_dir) / 'agent_runs.json'
	existing_runs = []
	if agent_runs_path.exists():
		existing_runs = json.loads(agent_runs_path.read_text(encoding='utf-8'))

	record_doc_path = Path(__file__).resolve().parent / 'EXPERIMENT_RECORD.md'
	results_this_batch: list[AgentRunSummary] = []
	batch_id = f"batch-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
	git_commit_hash = _resolve_git_commit_hash()
	task_card_hash_by_id = {task.id: _stable_sha256(task.model_dump(mode='json')) for task in selected_tasks}
	batch_manifest = {
		'batch_id': batch_id,
		'started_at_utc': datetime.now(UTC).isoformat(),
		'execution_mode': 'sequential_single_condition',
		'condition_order_mode': 'not_applicable',
		'experiment_id': experiment_id,
		'scenario_id': args.scenario_id,
		'task_ids': [task.id for task in selected_tasks],
		'task_card_hash_by_id': task_card_hash_by_id,
		'git_commit_hash': git_commit_hash,
		'executor_model': executor_cfg.model,
		'executor_temperature': executor_cfg.temperature,
		'executor_use_vision': default_use_vision_for_executor(executor_cfg),
		'navigator_enabled': navigator_cfg.enabled,
		'navigator_model': navigator_cfg.model if navigator_cfg.enabled else None,
		'navigator_temperature': navigator_cfg.temperature if navigator_cfg.enabled else None,
		'continuous_navigation': run_flags.continuous_navigation or getattr(args, 'continuous_navigation', False),
		'navigator_replan_interval': run_flags.navigator_replan_interval,
		'replan_policy': run_flags.replan_policy,
		'paper_condition': run_flags.paper_condition,
		'max_steps': args.max_steps,
		'max_failures': args.max_failures,
		'llm_timeout': args.llm_timeout,
		'step_timeout': args.step_timeout,
		'max_actions_per_step': args.max_actions_per_step,
		'headless': args.headless,
		'heartbeat_seconds': args.heartbeat_seconds,
		'browser_profile_mode': 'ephemeral_incognito',
		'browser_viewport': {'width': 1280, 'height': 720},
		'browser_locale': None,
		'browser_timezone': None,
	}
	manifest_dir = Path(args.output_dir) / 'batch_manifests'
	manifest_dir.mkdir(parents=True, exist_ok=True)
	batch_manifest_path = manifest_dir / f'{batch_id}.json'
	write_json(batch_manifest_path, batch_manifest)
	print(f'已写入 batch manifest → {batch_manifest_path}')

	for task in selected_tasks:
		human = human_runs.get((task.id, args.scenario_id))
		summary = await run_agent_task(
			task=task,
			output_dir=Path(args.output_dir),
			scenario_id=args.scenario_id,
			max_steps=args.max_steps,
			headless=args.headless,
			navigator_config=navigator_cfg,
			executor_config=executor_cfg,
			experiment_id=experiment_id,
			llm_timeout=args.llm_timeout,
			max_actions_per_step=args.max_actions_per_step,
			step_timeout=args.step_timeout,
			heartbeat_seconds=args.heartbeat_seconds,
			max_failures=args.max_failures,
			continuous_navigation=run_flags.continuous_navigation or getattr(args, 'continuous_navigation', False),
			navigator_replan_interval=run_flags.navigator_replan_interval,
			replan_policy=run_flags.replan_policy,
			adaptive_replan_settings=run_flags.adaptive_replan_settings,
			batch_id=batch_id,
			git_commit_hash=git_commit_hash,
			human=human,
			csv_dir=csv_dir,
			human_runs=human_runs_list,
		)
		results_this_batch.append(summary)
		existing_runs.append(summary.model_dump(mode='json'))
		write_json(agent_runs_path, existing_runs)
		exp_note = f' [{experiment_id}]' if experiment_id else ''
		method_csv = csv_dir / f'exp-{experiment_id}_runs.csv' if experiment_id else None
		if method_csv is not None:
			print(f'已为 {task.id}/{args.scenario_id}{exp_note} 追加 CSV → {method_csv}')
		print(f'已为 {task.id}/{args.scenario_id}{exp_note} 追加摘要 → {agent_runs_path}')

	has_success = any(r.success is True for r in results_this_batch)
	if has_success:
		print(f'成功跑次的结构化结果已保存至上述文件（{agent_runs_path.resolve()}）。')
		print('其中含 LLM 用量字段：usage_summary / usage_executor_llm / usage_navigator_cycle_llm / navigator_initial_plan_usage 等（见 DAILY_TASK_EXPERIMENT_GUIDE §1.1）。')
		print(f'人读实验记录模板（按 A/B/C/D 分类表）请参考：{record_doc_path.resolve()}（请与本趟成功的跑次对齐后手工更新）。')


def _audit_preflight(args: argparse.Namespace) -> int:
	tasks = load_json_model_list(Path(args.task_cards), TaskCard)
	humans = load_json_model_list(Path(args.human_runs), HumanRunRecord)
	agents = load_json_model_list(Path(args.agent_runs), AgentRunSummary) if Path(args.agent_runs).exists() else []
	task_by_id = {task.id: task for task in tasks}
	main_ids = get_main_tasks()
	critical: list[str] = []
	warnings: list[str] = []
	per_run_suggestions: list[dict[str, str | bool | None]] = []

	# 1) Main task cards frozen
	for task_id in main_ids:
		task = task_by_id.get(task_id)
		if task is None:
			critical.append(f'missing main task card: {task_id}')
			continue
		if not task.expected_primary_domain or not task.primary_site_flow:
			critical.append(f'{task_id}: expected_primary_domain / primary_site_flow not frozen')
		if task_id == 'shopping_price_compare':
			query = str(task.frozen_task_parameters.get('product_query', '')).strip()
			if not query:
				critical.append('shopping_price_compare: frozen product_query is missing')

	# 2/3/4) Human strict eligibility + task-card hash + shopping query
	for task_id in main_ids:
		task = task_by_id.get(task_id)
		if task is None:
			continue
		task_hash = _stable_sha256(task.model_dump(mode='json'))
		records = [run for run in humans if run.task_id == task_id and run.scenario_id == 'normal']
		if not records:
			critical.append(f'{task_id}: missing human reference run')
			continue
		for run in records:
			eligibility = validate_reference_eligibility(run, task)
			if not eligibility.eligible:
				critical.append(f'{task_id}: human reference not strict-eligible ({eligibility.reasons})')
			if run.task_card_hash != task_hash:
				critical.append(f'{task_id}: human task_card_hash mismatch (expected {task_hash})')
			if task_id == 'shopping_price_compare':
				query = str(task.frozen_task_parameters.get('product_query', '')).strip()
				blob = '\n'.join([*(run.final_evidence or []), str((run.final_answer or {}).get('text', ''))])
				if query and query not in blob:
					critical.append(f'{task_id}: human baseline evidence does not contain frozen query `{query}`')

	# 5) Hospital distinct-facility rule present
	hospital = task_by_id.get('nearby_hospital_phone_lookup')
	if hospital is None or 'distinct' not in ' '.join(hospital.success_criteria).lower():
		critical.append('nearby_hospital_phone_lookup: distinct-facility rule missing in task card criteria')

	# 6) Hugging Face verified_not_visible support
	hf = task_by_id.get('huggingface_model_constrained_selection')
	if hf is None:
		critical.append('missing huggingface task card')
	else:
		hf_blob = ' '.join([*hf.success_criteria, *hf.agent_recovery_rules]).lower()
		if 'verified not visible' not in hf_blob and 'verified_not_visible' not in hf_blob:
			critical.append('huggingface task card does not support verified_not_visible rubric')

	# 7) Contradiction audit
	for run in humans:
		if run.task_id not in main_ids:
			continue
		warns = audit_human_run_record(run, task_by_id.get(run.task_id))
		for warn in warns:
			message = f'human contradiction {warn.run_identifier}: {warn.code}'
			if warn.code == 'huggingface_verified_not_visible_strict_success':
				warnings.append(message)
			else:
				critical.append(message)

	# 8) Agent runs have final_domain / trajectory_comparable + adjudication fields
	for run in agents:
		if run.task_id not in main_ids:
			continue
		task = task_by_id.get(run.task_id)
		if task is None:
			continue
		expected_hash = _stable_sha256(task.model_dump(mode='json'))
		adjudicated = adjudicate_agent_summary(task, run)
		per_run_suggestions.append(
			{
				'task_id': run.task_id,
				'experiment_id': run.experiment_id,
				'adjudicated_outcome_label': adjudicated.adjudicated_outcome_label,
				'strict_success': adjudicated.strict_success,
				'trajectory_comparable': adjudicated.trajectory_comparable,
				'adjudication_reason': adjudicated.adjudication_reason,
			}
		)
		if not adjudicated.final_domain or not adjudicated.trajectory_comparable:
			critical.append(f'{run.task_id}/{run.experiment_id}: missing final_domain or trajectory_comparable')
		if not adjudicated.criteria_checks:
			critical.append(f'{run.task_id}/{run.experiment_id}: criteria_checks missing')
		if run.task_card_hash != expected_hash:
			critical.append(
				f'{run.task_id}/{run.experiment_id}: agent task_card_hash mismatch (run={run.task_card_hash}, expected={expected_hash})'
			)

	print('=== Preflight Audit ===')
	if critical:
		print(f'CRITICAL: {len(critical)}')
		for item in critical:
			print(f'  - {item}')
	else:
		print('CRITICAL: 0')
	if warnings:
		print(f'WARNINGS: {len(warnings)}')
		for item in warnings:
			print(f'  - {item}')
	else:
		print('WARNINGS: 0')

	print('=== Current Run Suggestions ===')
	for item in per_run_suggestions:
		if args.experiment and item.get('experiment_id') != args.experiment:
			continue
		print(
			f"- {item['task_id']} exp-{item['experiment_id']}: outcome={item['adjudicated_outcome_label']} "
			f"strict={item['strict_success']} comparable={item['trajectory_comparable']} reason={item['adjudication_reason']}"
		)
	if critical:
		return 1
	return 0


def build_parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(
		description='Run human-vs-Agent daily task comparison experiments.',
		formatter_class=argparse.RawDescriptionHelpFormatter,
		epilog=describe_experiments_text(),
	)
	subparsers = parser.add_subparsers(dest='command', required=True)

	init_parser = subparsers.add_parser('init', help='Create starter task cards and result files.')
	init_parser.add_argument('--output-dir', type=Path, default=Path('./tmp/daily_task_eval'))
	init_parser.add_argument('--overwrite', action='store_true')
	init_parser.add_argument(
		'--include-stress',
		action='store_true',
		help='Also include stress tasks during init (default init keeps only main-tier tasks).',
	)
	init_parser.add_argument(
		'--include-archived',
		action='store_true',
		help='Also include archived tasks during init (not used in default benchmark aggregates).',
	)

	run_parser = subparsers.add_parser(
		'run-agent',
		help='Run Browser Use Agent for one or more task cards.',
		formatter_class=argparse.RawDescriptionHelpFormatter,
		epilog=describe_experiments_text(),
	)
	run_parser.add_argument('--task-cards', type=Path, default=Path('./tmp/daily_task_eval/task_cards.json'))
	run_parser.add_argument('--output-dir', type=Path, default=Path('./tmp/daily_task_eval'))
	run_parser.add_argument(
		'--human-runs',
		type=Path,
		default=Path('./tmp/daily_task_eval/human_runs.json'),
		help='Human baseline for trajectory LCS and compare (default: output-dir/human_runs.json).',
	)
	run_parser.add_argument('--task-id', default=None)
	run_parser.add_argument(
		'--include-stress',
		action='store_true',
		help='Opt in stress tasks for batch runs (default runs only main tasks).',
	)
	run_parser.add_argument(
		'--list-tasks',
		action='store_true',
		help='Print task ids with tiers and exit.',
	)
	run_parser.add_argument('--scenario-id', default='normal')
	run_parser.add_argument('--max-steps', type=int, default=35)
	run_parser.add_argument(
		'--llm-timeout',
		type=int,
		default=120,
		help='Seconds per LLM request (default 120, frozen formal eval setting).',
	)
	run_parser.add_argument(
		'--max-actions-per-step',
		type=int,
		default=1,
		help='Actions per Agent step (default 1 for frozen formal eval setting).',
	)
	run_parser.add_argument(
		'--step-timeout',
		type=int,
		default=150,
		help='Per-step total timeout in seconds (default 150, frozen formal eval setting).',
	)
	run_parser.add_argument(
		'--heartbeat-seconds',
		type=int,
		default=30,
		help='Print [eval-runner] heartbeat every N seconds (current step number, step elapsed, current URL). 0 disables.',
	)
	run_parser.add_argument(
		'--max-failures',
		type=int,
		default=3,
		help='Consecutive LLM parse / tool-call failures tolerated before Agent self-terminates. Default 3. Raise to 6–8 for Qwen tool-calling on large DOMs (the "failed to output in correct format for three consecutive attempts" symptom).',
	)
	run_parser.add_argument(
		'--use-vision',
		dest='executor_use_vision',
		choices=['auto', 'true', 'false'],
		default=None,
		help=(
			'Override executor screenshot/vision preset for this run (after --experiment resolution). '
			'false: text-only Agent (recommended for heavy map SPAs). '
			'auto: no per-step CDP state screenshots unless the screenshot tool was used (ChatBrowserUse); '
			'OpenAI-compatible executors map auto→false anyway. '
			'true: always capture state screenshots each step.'
		),
	)
	run_parser.add_argument(
		'--log-level',
		choices=['debug', 'info', 'warning', 'result'],
		default=None,
		help='Override BROWSER_USE_LOGGING_LEVEL for this run. Use debug to see DOM/CDP/bubus event timings when steps stall.',
	)
	run_parser.add_argument('--headless', action='store_true')

	run_parser.add_argument(
		'--continuous-navigation',
		action='store_true',
		help=(
			'Enable Agent periodic navigator guidance. Uses the same NavigatorConfig as the '
			'initial LLM navigator plan (distinct executor LLM). Requires a preset/navigator '
			'that enables the navigator. Preset CA enables this automatically (adaptive stall replan).'
		),
	)

	run_parser.add_argument(
		'--navigator-replan-interval',
		type=int,
		default=None,
		help=(
			'Navigator LLM runs every N agent steps after the opening plan (0 = stall-triggered only). '
			'Preset CA defaults to 0 (adaptive); R-* cadence presets use 1/3/5.'
		),
	)

	run_parser.add_argument(
		'--experiment',
		choices=['A', 'B', 'C', 'D', 'CA'],
		default=None,
		help='Preset A–D or CA (Doubao adaptive navigator + Doubao executor). Use custom flags when omitted.',
	)
	run_parser.add_argument(
		'--executor-backend',
		choices=['chat_browser_use', 'openai_compatible', 'google'],
		default=None,
		help=(
			'Executor LLM backend. Without --experiment: default chat_browser_use. '
			'With --experiment: only overrides preset when this flag is passed (e.g. --experiment D --executor-backend google).'
		),
	)
	run_parser.add_argument(
		'--executor-model',
		default=None,
		help='Executor model id (bu-latest, qwen3-max, gemini-2.5-flash, etc.).',
	)
	run_parser.add_argument(
		'--executor-api-key-env',
		default=None,
		help=(
			'Env var for executor API key. If omitted: inferred from --executor-model '
			'(豆包 doubao-* / ep-* → ARK_API_KEY; else DASHSCOPE for Qwen; google → GOOGLE_API_KEY).'
		),
	)
	run_parser.add_argument(
		'--executor-base-url',
		default=None,
		help=(
			'OpenAI-compatible executor base URL. If omitted: inferred from --executor-model '
			'(豆包 doubao-* / ep-* → Volcengine Ark Beijing; else DashScope CN). '
			'Override for Singapore DashScope or custom gateways.'
		),
	)

	run_parser.add_argument(
		'--navigator-backend',
		choices=['none', 'deepseek', 'openai_compatible'],
		default='none',
		help='Ignored when --experiment is set. Planner backend before the Agent runs.',
	)
	run_parser.add_argument(
		'--use-navigator',
		action='store_true',
		help='Shorthand for --navigator-backend openai_compatible (Qwen). Not allowed with --experiment.',
	)
	run_parser.add_argument('--navigator-model', default=None, help='Navigator model (default depends on backend).')
	run_parser.add_argument(
		'--navigator-api-key-env',
		default='DASHSCOPE_API_KEY',
		help='Env var for OpenAI-compatible navigator (Qwen). Default: DASHSCOPE_API_KEY.',
	)
	run_parser.add_argument(
		'--navigator-base-url',
		default='https://dashscope.aliyuncs.com/compatible-mode/v1',
		help='OpenAI-compatible navigator base URL (Qwen). Must match API key region.',
	)
	run_parser.add_argument(
		'--navigator-deepseek-api-key-env',
		default='DEEPSEEK_API_KEY',
		help='Env var for DeepSeek navigator key when --navigator-backend deepseek.',
	)
	run_parser.add_argument(
		'--navigator-deepseek-base-url',
		default='https://api.deepseek.com/v1',
		help='DeepSeek OpenAI-compatible base URL for navigator.',
	)

	compare_parser = subparsers.add_parser(
		'compare',
		help='Compare human baselines with Agent runs (loads csv_out/exp-*_runs.csv).',
	)
	compare_parser.add_argument('--task-cards', type=Path, default=Path('./tmp/daily_task_eval/task_cards.json'))
	compare_parser.add_argument('--human-runs', type=Path, default=Path('./tmp/daily_task_eval/human_runs.json'))
	compare_parser.add_argument(
		'--csv-dir',
		type=Path,
		default=Path('./tmp/daily_task_eval/csv_out'),
		help='Directory of exp-{method}_runs.csv files (glob + pandas concat).',
	)
	compare_parser.add_argument(
		'--agent-runs',
		type=Path,
		default=None,
		help='Deprecated fallback: load agent_runs.json instead of --csv-dir when set.',
	)
	compare_parser.add_argument('--output-path', type=Path, default=Path('./tmp/daily_task_eval/comparison_report.json'))
	compare_parser.add_argument(
		'--resource-report',
		type=Path,
		default=None,
		metavar='PATH',
		help=(
			'Where to write cross-experiment resource JSON (grouped by task/scenario, no human baseline needed). '
			'Default: sibling of --output-path named experiment_resource_report.json'
		),
	)
	compare_parser.add_argument(
		'--no-resource-report',
		action='store_true',
		help='Skip writing experiment_resource_report.json.',
	)

	audit_parser = subparsers.add_parser(
		'audit-preflight',
		help='Run strict preflight audit before formal batch.',
	)
	audit_parser.add_argument('--task-cards', type=Path, default=Path('./tmp/daily_task_eval/task_cards.json'))
	audit_parser.add_argument('--human-runs', type=Path, default=Path('./tmp/daily_task_eval/human_runs.json'))
	audit_parser.add_argument('--agent-runs', type=Path, default=Path('./tmp/daily_task_eval/agent_runs.json'))
	audit_parser.add_argument(
		'--experiment',
		default='C',
		help='Filter suggested statuses by experiment id (default C).',
	)

	export_csv_parser = subparsers.add_parser(
		'export-csv',
		help='Export experiment_resource_report.json or agent_runs.json to CSV for spreadsheets.',
		epilog=(
			'Windows: put all flags on one line, or in PowerShell use a backtick (`) at line end for continuation '
			'(not ^, which is for cmd.exe). Example: export-csv --input tmp/daily_task_eval/experiment_resource_report.json'
		),
		formatter_class=argparse.RawDescriptionHelpFormatter,
	)
	export_csv_parser.add_argument(
		'--mode',
		choices=['resource-report', 'agent-runs'],
		default='resource-report',
		help='resource-report: two CSVs (runs + stats). agent-runs: one flattened summary CSV.',
	)
	export_csv_parser.add_argument(
		'--input',
		type=Path,
		required=True,
		help='Path to experiment_resource_report.json or agent_runs.json (see --mode).',
	)
	export_csv_parser.add_argument(
		'--output-dir',
		type=Path,
		default=None,
		help='Directory for output files (default: same directory as --input).',
	)
	export_csv_parser.add_argument(
		'--runs-csv',
		type=Path,
		default=None,
		help='resource-report mode only: path for per-run rows (default: <input-stem>_runs.csv in output-dir).',
	)
	export_csv_parser.add_argument(
		'--stats-csv',
		type=Path,
		default=None,
		help='resource-report mode only: path for statistics rows (default: <input-stem>_stats.csv in output-dir).',
	)
	export_csv_parser.add_argument(
		'--agent-runs-csv',
		type=Path,
		default=None,
		help='agent-runs mode only: output CSV path (default: <input-stem>_export.csv in output-dir).',
	)

	return parser


def main() -> None:
	parser = build_parser()
	args = parser.parse_args()

	if args.command == 'init':
		paths = init_experiment(
			args.output_dir,
			overwrite=args.overwrite,
			include_stress=args.include_stress,
			include_archived=args.include_archived,
		)
		for name, path in paths.items():
			print(f'{name}: {path}')
	elif args.command == 'run-agent':
		asyncio.run(run_agent_command(args))
	elif args.command == 'compare':
		csv_dir = args.csv_dir
		if args.agent_runs is not None:
			comparisons = compare_all(
				args.task_cards,
				args.human_runs,
				args.output_path,
				agent_runs_path=args.agent_runs,
				resource_report_path=args.resource_report,
				skip_resource_report=args.no_resource_report,
			)
		else:
			comparisons = compare_all(
				args.task_cards,
				args.human_runs,
				args.output_path,
				csv_dir=csv_dir,
				resource_report_path=args.resource_report,
				skip_resource_report=args.no_resource_report,
			)
		print(f'Wrote {len(comparisons)} comparison record(s) to {args.output_path}')
		if not args.no_resource_report:
			res_path = args.resource_report or args.output_path.with_name('experiment_resource_report.json')
			print(f'Wrote cross-experiment resource report to {res_path}')
		if args.agent_runs is None and csv_dir.exists():
			_, agg_path = aggregate_method_metrics(csv_dir, csv_dir)
			print(f'Wrote method aggregate stats to {agg_path.resolve()}')
			note_path = csv_dir / 'stress_case_note.txt'
			if note_path.exists():
				print(note_path.read_text(encoding='utf-8').strip())
			task_summary = export_task_config_summary_csv(csv_dir, csv_dir / 'task_config_summary.csv')
			print(f'Wrote task/config summary to {task_summary.resolve()}')
			human_ref_summary = export_human_reference_set_summary_csv(
				load_json_model_list(args.human_runs, HumanRunRecord),
				csv_dir / 'human_reference_set_summary.csv',
			)
			print(f'Wrote human reference set summary to {human_ref_summary.resolve()}')
			plot_path = plot_method_comparison(csv_dir, csv_dir)
			if plot_path is not None:
				print(f'Wrote method comparison plot to {plot_path.resolve()}')
			else:
				print('Skipped plot (install pandas + matplotlib in eval extras for charts).')
	elif args.command == 'export-csv':
		out_dir = args.output_dir or args.input.parent
		out_dir.mkdir(parents=True, exist_ok=True)
		if args.mode == 'resource-report':
			stem = args.input.stem
			runs_path = args.runs_csv or (out_dir / f'{stem}_runs.csv')
			stats_path = args.stats_csv or (out_dir / f'{stem}_stats.csv')
			export_experiment_resource_report_to_csv(args.input, runs_path, stats_path)
			print(f'Wrote runs CSV to {runs_path.resolve()}')
			print(f'Wrote stats CSV to {stats_path.resolve()}')
		else:
			stem = args.input.stem
			agent_csv = args.agent_runs_csv or (out_dir / f'{stem}_export.csv')
			export_agent_runs_to_csv(args.input, agent_csv)
			print(f'Wrote agent runs CSV to {agent_csv.resolve()}')
	elif args.command == 'audit-preflight':
		raise SystemExit(_audit_preflight(args))
	else:
		raise ValueError(f'Unknown command: {args.command}')


if __name__ == '__main__':
	main()
