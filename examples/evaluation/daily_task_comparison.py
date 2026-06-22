"""CLI wrapper for the daily task evaluation module.

The implementation lives in `browser_use.experiments.daily_task_eval` so it can be reused
as a pluggable module without editing core agent code.

Experiment presets (A–D) are defined in `browser_use.experiments.daily_task_eval.experiment_presets`.
"""

import argparse
import asyncio
import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import Literal

sys.path.append(str(Path(__file__).resolve().parents[2]))

from browser_use.experiments.daily_task_eval.experiment_presets import build_configs_from_args, describe_experiments_text
from browser_use.experiments.daily_task_eval.models import AgentRunSummary, HumanRunRecord, TaskCard, load_json_model_list, write_json
from browser_use.experiments.daily_task_eval.run_csv import aggregate_method_metrics, plot_method_comparison
from browser_use.experiments.daily_task_eval.runner import (
	compare_all,
	export_agent_runs_to_csv,
	export_experiment_resource_report_to_csv,
	index_by_task_and_scenario,
	init_experiment,
	run_agent_task,
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


async def run_agent_command(args: argparse.Namespace) -> None:
	_apply_log_level(getattr(args, 'log_level', None))
	try:
		executor_cfg, navigator_cfg, experiment_id = build_configs_from_args(args)
	except ValueError as exc:
		print(str(exc), file=sys.stderr)
		raise SystemExit(2) from exc
	if getattr(args, 'executor_use_vision', None) is not None:
		executor_cfg = replace(
			executor_cfg,
			use_vision=_parse_use_vision_cli(args.executor_use_vision),
		)

	tasks = load_json_model_list(Path(args.task_cards), TaskCard)
	selected_tasks = [task for task in tasks if args.task_id in (None, task.id)]
	if not selected_tasks:
		raise ValueError(f'No task card matched task id: {args.task_id}')

	csv_dir = Path(args.output_dir) / 'csv_out'
	csv_dir.mkdir(parents=True, exist_ok=True)
	human_runs = index_by_task_and_scenario(load_json_model_list(Path(args.human_runs), HumanRunRecord))

	agent_runs_path = Path(args.output_dir) / 'agent_runs.json'
	existing_runs = []
	if agent_runs_path.exists():
		existing_runs = json.loads(agent_runs_path.read_text(encoding='utf-8'))

	record_doc_path = Path(__file__).resolve().parent / 'EXPERIMENT_RECORD.md'
	results_this_batch: list[AgentRunSummary] = []

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
			continuous_navigation=getattr(args, 'continuous_navigation', False),
			human=human,
			csv_dir=csv_dir,
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
	run_parser.add_argument('--scenario-id', default='normal')
	run_parser.add_argument('--max-steps', type=int, default=30)
	run_parser.add_argument(
		'--llm-timeout',
		type=int,
		default=180,
		help='Seconds per LLM request (default 180). Raise if DashScope/Qwen often exceeds Agent auto 75s.',
	)
	run_parser.add_argument(
		'--max-actions-per-step',
		type=int,
		default=None,
		help='Override actions per Agent step. Default: 1 for OpenAI-compatible (Qwen) to avoid malformed multi-action JSON; 3 for ChatBrowserUse.',
	)
	run_parser.add_argument(
		'--step-timeout',
		type=int,
		default=None,
		help='Per-step total timeout (seconds, includes LLM + browser + DOM). None keeps Agent default 180s. Lower (e.g. 60) when diagnosing where a step hangs so failures fire faster.',
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
			'that enables the navigator.'
		),
	)

	run_parser.add_argument(
		'--experiment',
		choices=['A', 'B', 'C', 'D'],
		default=None,
		help='Preset A–D (sets executor + navigator). Use custom flags instead when omitted.',
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
		paths = init_experiment(args.output_dir, overwrite=args.overwrite)
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
	else:
		raise ValueError(f'Unknown command: {args.command}')


if __name__ == '__main__':
	main()
