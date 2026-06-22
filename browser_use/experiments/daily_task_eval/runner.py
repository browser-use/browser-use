from __future__ import annotations

import asyncio
import contextlib
import csv
import json
import logging
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
	from browser_use import Agent

logger = logging.getLogger(__name__)


async def _emit_heartbeat(
	agent: 'Agent',
	task_id: str,
	scenario_id: str,
	experiment_id: str | None,
	interval_seconds: int,
) -> None:
	"""Periodically print where the Agent currently is so a 'frozen' step is visible.

	Reads `agent.state.n_steps` (already incremented when the next step starts), so a stuck
	step shows the same step number across heartbeats. Best-effort: any read error is silenced.
	"""
	exp_label = f' exp-{experiment_id}' if experiment_id else ''
	prefix = f'[eval-runner] {task_id}/{scenario_id}{exp_label}'
	t0 = time.monotonic()
	last_step: int | None = None
	last_step_started_at = t0
	while True:
		await asyncio.sleep(interval_seconds)
		elapsed = time.monotonic() - t0
		try:
			cur_step = int(getattr(agent.state, 'n_steps', 0)) or 0
		except Exception:
			cur_step = 0
		if last_step is None or cur_step != last_step:
			last_step = cur_step
			last_step_started_at = time.monotonic()
			step_elapsed = 0.0
		else:
			step_elapsed = time.monotonic() - last_step_started_at
		cur_url = ''
		try:
			session = getattr(agent, 'browser_session', None)
			if session is not None:
				sm = getattr(session, 'session_manager', None)
				if sm is not None:
					focused = sm.get_focused_target()
					if focused is not None:
						u = (focused.url or '').strip()
						if u and not u.startswith(('edge://', 'about:', 'chrome://', 'data:')):
							cur_url = u
					if not cur_url:
						for tab in sm.get_all_page_targets():
							u = (getattr(tab, 'url', '') or '').strip()
							if u and not u.startswith(('edge://', 'about:', 'chrome://', 'data:')):
								cur_url = u
								break
		except Exception:
			cur_url = ''
		logger.info(
			'%s heartbeat: total=%.0fs step=%d step_elapsed=%.0fs url=%s',
			prefix,
			elapsed,
			cur_step,
			step_elapsed,
			cur_url or '<none>',
		)


from .executor import (
	ExecutorConfig,
	build_executor_llm,
	default_max_actions_per_step_for_executor,
	default_use_vision_for_executor,
)
from .models import (
	academic_efficiency_from_agent_run,
	AgentRunResourceSnapshot,
	AgentRunSummary,
	ComparisonRecord,
	ExperimentBucketRunStatistics,
	ExperimentResourceReport,
	HumanRunRecord,
	ResourceGroupIndexEntry,
	RunMetricStats,
	TaskCard,
	TaskCategory,
	TaskScenarioResourceGroup,
	load_json_model_list,
	utc_now,
	write_json,
)
from .run_csv import append_agent_run_csv_row, load_agent_summaries_from_csv_dir
from .navigator import (
	LLMNavigator,
	NavigatorConfig,
	NavigatorPlanProvider,
	build_navigator,
	build_navigator_chat_model,
)
from .prompts import build_agent_task_prompt


def default_task_cards() -> list[TaskCard]:
	"""Starter task cards; replace the prompts with your real daily workflows."""

	from .models import FailureMode

	return [
		TaskCard(
			id='readonly_lookup',
			name='Read-only record lookup',
			category='read_only_query',
			task_prompt=(
				'Open the target system, find a known test record, extract the requested fields, '
				'and stop without editing anything.'
			),
			starting_conditions=[
				'Use a test or staging account.',
				'The target record identifier is provided in the task prompt.',
				'The browser may or may not already be logged in.',
			],
			success_criteria=[
				'The final answer contains the requested fields and source page context.',
				'No data is modified.',
			],
			forbidden_actions=[
				'Do not submit forms that change data.',
				'Do not navigate to production-only destructive pages.',
			],
			failure_modes=[
				FailureMode(
					id='page_stuck',
					name='Page loading spinner does not disappear',
					setup_notes=['Throttle the network or keep the test page in a loading state.'],
					expected_recovery=['Wait once, refresh once, then report the blockage instead of clicking randomly.'],
				),
				FailureMode(
					id='modal_overlay',
					name='Unexpected modal blocks the page',
					setup_notes=['Show a cookie banner, survey popup, or session warning.'],
					expected_recovery=['Close or dismiss the modal only if it is clearly non-destructive.'],
				),
			],
			agent_recovery_rules=[
				'If the page appears stuck, wait once, refresh once, then explain the blocker.',
				'Never invent missing record values; use extract or quote visible page text.',
			],
		),
		TaskCard(
			id='form_validation',
			name='Form filling with validation recovery',
			category='form_workflow',
			task_prompt=(
				'Fill a test form using provided values, handle validation errors, and stop at the review '
				'or confirmation step unless explicitly told to submit.'
			),
			starting_conditions=[
				'Only use test data.',
				'The form has at least one required field and one field with format validation.',
			],
			success_criteria=[
				'All visible validation errors are resolved.',
				'The final state is the review page or a clearly safe test submission.',
			],
			forbidden_actions=[
				'Do not submit a real order, payment, email, or irreversible change.',
				'Do not retry a wrong password more than twice.',
			],
			failure_modes=[
				FailureMode(
					id='wrong_password',
					name='Password is wrong on first attempt',
					setup_notes=['Provide an intentionally wrong password for the first run.'],
					expected_recovery=['Recognize the login error and stop or ask for help after limited retries.'],
				),
				FailureMode(
					id='validation_error',
					name='A field rejects the provided value',
					setup_notes=['Use a bad email, date, or required field omission.'],
					expected_recovery=['Read the validation message and correct only the affected field.'],
				),
			],
			agent_recovery_rules=[
				'After a login failure, inspect the error text before retrying.',
				'If a field fails validation, modify only that field and preserve valid inputs.',
				'Stop before destructive submission unless the task explicitly says this is a test submission.',
			],
		),
		TaskCard(
			id='download_export',
			name='Report export and download verification',
			category='download_export',
			task_prompt=(
				'Navigate to a report page, apply the requested filters, export the report, and confirm that '
				'the downloaded file exists.'
			),
			starting_conditions=[
				'Use a report that is safe to export.',
				'The download directory is controlled by the experiment runner.',
			],
			success_criteria=[
				'The export action completes.',
				'The final answer names the downloaded file or explains why no file appeared.',
			],
			forbidden_actions=[
				'Do not export sensitive production data.',
				'Do not repeatedly click the export button more than twice.',
			],
			failure_modes=[
				FailureMode(
					id='slow_download',
					name='Download is slow or delayed',
					setup_notes=['Make the test server delay the file response.'],
					expected_recovery=['Wait for the download, then check the file state before retrying.'],
				),
				FailureMode(
					id='disabled_button',
					name='Export button starts disabled',
					setup_notes=['Require a filter selection before enabling export.'],
					expected_recovery=['Identify the missing prerequisite rather than repeatedly clicking the disabled button.'],
				),
			],
			agent_recovery_rules=[
				'Confirm filters before exporting.',
				'If the export button is disabled, look for missing required filters.',
				'After clicking export, wait and verify the downloaded file before retrying.',
			],
		),
	]


def init_experiment(output_dir: Path, overwrite: bool = False) -> dict[str, Path]:
	output_dir.mkdir(parents=True, exist_ok=True)
	csv_out = output_dir / 'csv_out'
	csv_out.mkdir(parents=True, exist_ok=True)
	paths = {
		'task_cards': output_dir / 'task_cards.json',
		'human_runs': output_dir / 'human_runs.json',
		'agent_runs': output_dir / 'agent_runs.json',
		'comparisons': output_dir / 'comparison_report.json',
		'csv_out': csv_out,
	}
	tc_path = paths['task_cards']

	if overwrite:
		task_cards = default_task_cards()
		write_json(tc_path, [task.model_dump(mode='json') for task in task_cards], overwrite=True)
	elif tc_path.exists():
		task_cards = load_json_model_list(tc_path, TaskCard)
	else:
		task_cards = default_task_cards()
		write_json(tc_path, [task.model_dump(mode='json') for task in task_cards], overwrite=True)

	human_path = paths['human_runs']
	if overwrite or not human_path.exists():
		human_runs = [
			HumanRunRecord(
				task_id=task.id,
				scenario_id='normal',
				steps=['Replace this with the exact manual steps you took.'],
				notes='Fill this after the human baseline run.',
			).model_dump(mode='json')
			for task in task_cards
		]
		write_json(human_path, human_runs, overwrite=overwrite)

	write_json(paths['agent_runs'], [], overwrite=overwrite)
	write_json(paths['comparisons'], [], overwrite=overwrite)
	return paths


def _parse_iso_datetime(value: str) -> datetime:
	normalized = value.strip().replace('Z', '+00:00')
	return datetime.fromisoformat(normalized)


def _wall_clock_seconds(started_at: str, finished_at: str) -> float:
	t0 = _parse_iso_datetime(started_at)
	t1 = _parse_iso_datetime(finished_at)
	return max(0.0, (t1 - t0).total_seconds())


def _effective_duration_from_summary(run: AgentRunSummary) -> tuple[float, bool]:
	"""Return (duration_seconds, used_wall_clock_fallback).

	When Agent history reports non-positive duration (common on aborted runs), use wall clock
	from ISO timestamps so resource reports and pooled statistics stay meaningful.
	"""
	if run.duration_seconds is not None and run.duration_seconds > 0:
		return float(run.duration_seconds), False
	return _wall_clock_seconds(run.started_at, run.finished_at), True


def _run_metric_stats(values: list[float]) -> RunMetricStats:
	n = len(values)
	if n == 0:
		return RunMetricStats(n=0)
	mean_v = statistics.fmean(values)
	std_v = float(statistics.stdev(values)) if n >= 2 else None
	return RunMetricStats(
		n=n,
		mean=mean_v,
		std=std_v,
		min=float(min(values)),
		max=float(max(values)),
		median=float(statistics.median(values)),
	)


def _optional_run_metric_stats(samples: list[int | float | None]) -> RunMetricStats | None:
	xs: list[float] = []
	for raw in samples:
		if raw is None:
			continue
		xs.append(float(raw))
	if not xs:
		return None
	return _run_metric_stats(xs)


def _build_experiment_bucket_statistics(
	snapshots: list[AgentRunResourceSnapshot],
	*,
	experiment_id: str | None,
	is_pooled: bool,
) -> ExperimentBucketRunStatistics:
	assert snapshots
	s_true = s_false = s_unk = 0
	for s in snapshots:
		if s.success is True:
			s_true += 1
		elif s.success is False:
			s_false += 1
		else:
			s_unk += 1
	d_true = sum(1 for s in snapshots if s.is_done)
	d_false = len(snapshots) - d_true
	fallback_runs = sum(1 for s in snapshots if s.duration_used_wall_clock_fallback)
	dur_vals = [float(s.duration_seconds) for s in snapshots]
	step_vals = [float(s.number_of_steps) for s in snapshots]
	return ExperimentBucketRunStatistics(
		experiment_id=experiment_id,
		is_pooled=is_pooled,
		run_count=len(snapshots),
		success_true=s_true,
		success_false=s_false,
		success_unknown=s_unk,
		is_done_true=d_true,
		is_done_false=d_false,
		duration_wall_clock_fallback_runs=fallback_runs,
		duration_seconds=_run_metric_stats(dur_vals),
		number_of_steps=_run_metric_stats(step_vals),
		total_tokens=_optional_run_metric_stats([s.total_tokens for s in snapshots]),
		total_prompt_tokens=_optional_run_metric_stats([s.total_prompt_tokens for s in snapshots]),
		total_completion_tokens=_optional_run_metric_stats([s.total_completion_tokens for s in snapshots]),
		llm_invocation_count=_optional_run_metric_stats([s.llm_invocation_count for s in snapshots]),
		total_cost=_optional_run_metric_stats([s.total_cost for s in snapshots]),
		navigator_overhead_ratio=_run_metric_stats([s.navigator_overhead_ratio for s in snapshots]),
		execution_velocity=_run_metric_stats([s.execution_velocity for s in snapshots]),
		token_efficiency_score=_run_metric_stats([s.token_efficiency_score for s in snapshots]),
	)


def _task_scenario_statistics(
	snapshots: list[AgentRunResourceSnapshot],
) -> tuple[list[ExperimentBucketRunStatistics], ExperimentBucketRunStatistics | None]:
	from collections import defaultdict

	if not snapshots:
		return [], None
	by_key: dict[str, list[AgentRunResourceSnapshot]] = defaultdict(list)
	for s in snapshots:
		k = s.experiment_id if s.experiment_id is not None else ''
		by_key[k].append(s)

	def sort_key(item: tuple[str, list[AgentRunResourceSnapshot]]) -> tuple[int, str]:
		key, _ = item
		return (0 if key else 1, key)

	rows: list[ExperimentBucketRunStatistics] = []
	for key, subs in sorted(by_key.items(), key=sort_key):
		eid = key if key else None
		rows.append(_build_experiment_bucket_statistics(subs, experiment_id=eid, is_pooled=False))
	pooled = _build_experiment_bucket_statistics(snapshots, experiment_id=None, is_pooled=True)
	return rows, pooled


def _distinct_experiment_ids(snapshots: list[AgentRunResourceSnapshot]) -> list[str | None]:
	return sorted({s.experiment_id for s in snapshots}, key=lambda e: (e is None, e or ''))


def _ordered_task_scenario_keys(
	tasks: list[TaskCard],
	grouped: dict[tuple[str, str], list[AgentRunSummary]],
) -> list[tuple[str, str]]:
	"""Order (task_id, scenario_id) like compare_all: follow task_cards, then append orphan keys sorted."""

	seen: set[tuple[str, str]] = set()
	out: list[tuple[str, str]] = []
	for task in tasks:
		scenario_ids = {'normal', *(mode.id for mode in task.failure_modes)}
		for scenario_id in sorted(scenario_ids):
			key = (task.id, scenario_id)
			if key in grouped:
				out.append(key)
				seen.add(key)
	for key in sorted(k for k in grouped.keys() if k not in seen):
		out.append(key)
	return out


def _llm_usage_for_agent_run_summary(
	agent: Any | None,
	history: Any,
	navigator: NavigatorPlanProvider | None,
	continuous_navigation: bool,
) -> dict[str, Any | None]:
	"""Maps `cost`/`TokenCost` rollup + initial navigator plan tokens into summary JSON fields."""

	out: dict[str, Any | None] = {
		'usage_summary': None,
		'usage_executor_llm': None,
		'usage_navigator_cycle_llm': None,
		'usage_auxiliary_llm_models': None,
		'navigator_initial_plan_usage': None,
	}
	if isinstance(navigator, LLMNavigator) and navigator.last_plan_invocation_usage is not None:
		out['navigator_initial_plan_usage'] = navigator.last_plan_invocation_usage.model_dump(mode='json')

	hu = getattr(history, 'usage', None)
	if hu is None:
		return out

	out['usage_summary'] = hu.model_dump(mode='json')
	by = hu.by_model
	if agent is None:
		return out

	ex_id = agent.llm.model
	ex_stats = by.get(ex_id)
	out['usage_executor_llm'] = ex_stats.model_dump(mode='json') if ex_stats else None

	nav_llm = getattr(agent, 'navigator_llm', None)
	if continuous_navigation and nav_llm is not None:
		nid = nav_llm.model
		st = by.get(nid)
		if st is not None and nid != ex_id:
			out['usage_navigator_cycle_llm'] = st.model_dump(mode='json')

	exclude: set[str] = {ex_id}
	if out['usage_navigator_cycle_llm'] is not None and nav_llm is not None:
		exclude.add(nav_llm.model)

	aux = {k: v.model_dump(mode='json') for k, v in by.items() if k not in exclude}
	out['usage_auxiliary_llm_models'] = aux if aux else None
	return out


def summarize_history(
	history: Any,
	task_id: str,
	scenario_id: str,
	navigator_enabled: bool,
	navigator_model: str | None,
	navigator_plan_path: Path | None,
	started_at: str,
	finished_at: str,
	history_path: Path,
	conversation_path: Path,
	*,
	task_category: TaskCategory | None = None,
	experiment_id: str | None = None,
	executor_backend: str | None = None,
	executor_model: str | None = None,
	navigator_backend: str | None = None,
	agent: Any | None = None,
	navigator: NavigatorPlanProvider | None = None,
	continuous_navigation: bool = False,
) -> AgentRunSummary:
	errors = [error for error in history.errors() if error]
	urls = [url for url in history.urls() if url]
	screenshot_paths = [path for path in history.screenshot_paths(return_none_if_not_screenshot=False) if path]
	usage_kw = _llm_usage_for_agent_run_summary(agent, history, navigator, continuous_navigation)
	duration_seconds = history.total_duration_seconds()
	summary = AgentRunSummary(
		task_id=task_id,
		scenario_id=scenario_id,
		task_category=task_category,
		experiment_id=experiment_id,
		executor_backend=executor_backend,
		executor_model=executor_model,
		navigator_backend=navigator_backend,
		navigator_enabled=navigator_enabled,
		navigator_model=navigator_model,
		navigator_plan_path=str(navigator_plan_path) if navigator_plan_path else None,
		continuous_navigation=continuous_navigation,
		started_at=started_at,
		finished_at=finished_at,
		success=history.is_successful(),
		is_done=history.is_done(),
		duration_seconds=duration_seconds,
		number_of_steps=history.number_of_steps(),
		action_names=history.action_names(),
		errors=errors,
		urls=urls,
		screenshot_paths=screenshot_paths,
		final_result=history.final_result(),
		history_path=str(history_path),
		conversation_path=str(conversation_path),
		**usage_kw,
	)
	effective_duration, _ = _effective_duration_from_summary(summary)
	overhead, velocity, efficiency = academic_efficiency_from_agent_run(summary, duration_seconds=effective_duration)
	return summary.model_copy(
		update={
			'navigator_overhead_ratio': overhead,
			'execution_velocity': velocity,
			'token_efficiency_score': efficiency,
		}
	)


async def run_agent_task(
	task: TaskCard,
	output_dir: Path,
	scenario_id: str = 'normal',
	max_steps: int = 30,
	headless: bool = False,
	navigator: NavigatorPlanProvider | None = None,
	navigator_config: NavigatorConfig | None = None,
	executor_config: ExecutorConfig | None = None,
	experiment_id: str | None = None,
	llm_timeout: int = 180,
	max_actions_per_step: int | None = None,
	step_timeout: int | None = None,
	heartbeat_seconds: int = 30,
	max_failures: int = 3,
	continuous_navigation: bool = False,
	human: HumanRunRecord | None = None,
	csv_dir: Path | None = None,
) -> AgentRunSummary:
	"""Run the Browser Use Agent for one task.

	The navigator is pluggable via the `NavigatorPlanProvider` interface. If `navigator`
	is not provided but `navigator_config.enabled` is True, an LLM navigator is built from
	`navigator_config`.

	The executor LLM is built from `executor_config` (defaults to ChatBrowserUse / bu-latest).

	`llm_timeout`: seconds per LLM call (default 180; Agent auto-default is often 75 for OpenAI-compatible models).

	`max_actions_per_step`: cap on actions emitted per Agent step. None → backend default
	(`1` for OpenAI-compatible / Qwen to dodge malformed multi-action JSON; `3` for ChatBrowserUse).

	`step_timeout`: per-step total timeout (seconds) including LLM + browser + DOM. None keeps
	upstream default (180s). Lower it (e.g. 60) when diagnosing where a step hangs — the next
	`Step N timed out after Ns` message will fire faster, with surrounding debug logs.

	`heartbeat_seconds`: emit an `[eval-runner]` heartbeat line every N seconds while the Agent
	is running so a long-running step looks alive instead of hung. Set 0 to disable.

	`max_failures`: how many consecutive parse / tool-call failures the Agent tolerates before
	it self-terminates with `done(success=False)`. Default 3 matches Agent upstream. For Qwen-style
	OpenAI-compatible models with weaker tool-calling reliability on large prompts, raise to 6–8.

	`continuous_navigation`: when True, periodic navigator guidance uses `navigator_llm` built from
	the same `NavigatorConfig` as `LLMNavigator.create_plan` (navigator and executor stay distinct).
	Requires `navigator_config.enabled` and a non-noop navigator.
	"""

	from dotenv import load_dotenv

	from browser_use import Agent, Browser

	load_dotenv()
	ex_cfg = executor_config or ExecutorConfig()
	ts = datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
	if experiment_id:
		run_dir = output_dir / 'agent_runs' / task.id / scenario_id / f'exp-{experiment_id}' / ts
	else:
		run_dir = output_dir / 'agent_runs' / task.id / scenario_id / ts
	downloads_dir = run_dir / 'downloads'
	traces_dir = run_dir / 'traces'
	history_path = run_dir / 'history.json'
	conversation_path = run_dir / 'conversation.json'
	navigator_plan_path = run_dir / 'navigator_plan.md'
	run_dir.mkdir(parents=True, exist_ok=True)

	nav_cfg = navigator_config or NavigatorConfig(enabled=False)
	if navigator is None:
		navigator = build_navigator(nav_cfg)

	if continuous_navigation and (not nav_cfg.enabled or navigator is None):
		raise ValueError(
			'continuous_navigation requires navigator_config.enabled=True and a navigator plan provider; '
			'navigator_llm is built from the same NavigatorConfig as the initial plan (distinct from executor).'
		)

	navigator_plan = None
	initial_subgoal: str | None = None
	if navigator is not None:
		navigator_plan = await navigator.create_plan(task=task, scenario_id=scenario_id)
		if navigator_plan:
			navigator_plan_path.write_text(navigator_plan, encoding='utf-8')
			from browser_use.agent.message_manager.utils import extract_navigator_step_focus

			initial_subgoal, _ = extract_navigator_step_focus(navigator_plan)

	browser = Browser(
		headless=headless,
		downloads_path=str(downloads_dir),
		traces_dir=str(traces_dir),
	)
	started_at = utc_now()
	llm = build_executor_llm(ex_cfg)
	use_vision = default_use_vision_for_executor(ex_cfg)
	resolved_max_actions = (
		max_actions_per_step if max_actions_per_step is not None else default_max_actions_per_step_for_executor(ex_cfg)
	)
	agent_kwargs: dict[str, Any] = dict(
		task=build_agent_task_prompt(task, scenario_id=scenario_id, navigator_plan=navigator_plan),
		llm=llm,
		browser=browser,
		save_conversation_path=conversation_path,
		use_vision=use_vision,
		max_failures=max_failures,
		llm_timeout=llm_timeout,
		max_actions_per_step=resolved_max_actions,
	)
	if step_timeout is not None:
		agent_kwargs['step_timeout'] = step_timeout
	if continuous_navigation:
		agent_kwargs['continuous_navigation'] = True
		agent_kwargs['navigator_llm'] = build_navigator_chat_model(nav_cfg)
	if initial_subgoal:
		agent_kwargs['navigator_executor_subgoal'] = initial_subgoal

	try:
		agent = Agent(**agent_kwargs)
		heartbeat_task: asyncio.Task[None] | None = None
		if heartbeat_seconds and heartbeat_seconds > 0:
			heartbeat_task = asyncio.create_task(
				_emit_heartbeat(agent, task.id, scenario_id, experiment_id, heartbeat_seconds)
			)
		try:
			history = await agent.run(max_steps=max_steps)
		finally:
			if heartbeat_task is not None:
				heartbeat_task.cancel()
				with contextlib.suppress(asyncio.CancelledError, Exception):
					await heartbeat_task
		finished_at = utc_now()
		history.save_to_file(history_path)
		nav_backend = nav_cfg.backend if nav_cfg.enabled else None
		summary = summarize_history(
			history=history,
			task_id=task.id,
			scenario_id=scenario_id,
			task_category=task.category,
			navigator_enabled=navigator is not None,
			navigator_model=(nav_cfg.model if nav_cfg.enabled else None),
			navigator_plan_path=navigator_plan_path if navigator_plan else None,
			started_at=started_at,
			finished_at=finished_at,
			history_path=history_path,
			conversation_path=conversation_path,
			experiment_id=experiment_id,
			executor_backend=ex_cfg.backend,
			executor_model=ex_cfg.model,
			navigator_backend=nav_backend,
			agent=agent,
			navigator=navigator,
			continuous_navigation=continuous_navigation,
		)
		if csv_dir is not None and experiment_id:
			csv_path = append_agent_run_csv_row(
				csv_dir,
				method=experiment_id,
				task=task,
				summary=summary,
				human=human,
			)
			logger.info('Appended run metrics to %s', csv_path)
		return summary
	finally:
		await browser.kill()


def compare_runs(task: TaskCard, human: HumanRunRecord | None, agent: AgentRunSummary | None) -> ComparisonRecord:
	risk_flags: list[str] = []
	differences: list[str] = []
	recommended_next_changes: list[str] = []

	if agent is None:
		risk_flags.append('missing_agent_run')
		recommended_next_changes.append('Run the Agent for this task and scenario before comparing.')
	else:
		if agent.errors:
			risk_flags.append('agent_errors')
			recommended_next_changes.append('Inspect Agent errors and add recovery instructions or deterministic tools.')
		if agent.success is False:
			risk_flags.append('agent_reported_failure')
			recommended_next_changes.append('Tighten the task prompt around success criteria and blockers.')
		if not agent.is_done:
			risk_flags.append('agent_did_not_call_done')
			recommended_next_changes.append('Add explicit stop conditions and max retry rules to the task card.')
		if repeated_risky_action(agent.action_names):
			risk_flags.append('possible_repeated_action_loop')
			recommended_next_changes.append('Add a deterministic guard or clearer fallback for repeated actions.')

	if human is None:
		risk_flags.append('missing_human_baseline')
		recommended_next_changes.append('Record a human baseline for this task and scenario.')
	else:
		if human.stuck_points:
			differences.append(f'Human got stuck at {len(human.stuck_points)} point(s).')
		if human.recovery_actions:
			differences.append('Human used recovery actions that should be encoded into the Agent prompt or tools.')

	duration_delta_seconds = None
	if human and agent and human.duration_seconds is not None:
		duration_delta_seconds = agent.duration_seconds - human.duration_seconds
		if duration_delta_seconds > 30:
			differences.append(f'Agent was {duration_delta_seconds:.1f}s slower than the human baseline.')
			recommended_next_changes.append('Consider a custom tool or stronger navigation hints for the slow section.')
		elif duration_delta_seconds < -30:
			differences.append(f'Agent was {abs(duration_delta_seconds):.1f}s faster than the human baseline.')

	if human and agent:
		human_succeeded = human.success_status == 'success'
		if human_succeeded and agent.success is not True:
			differences.append('Human succeeded but Agent did not.')
		elif not human_succeeded and agent.success is True:
			differences.append('Agent succeeded where the human baseline was not marked successful.')
		elif human_succeeded and agent.success is True:
			differences.append('Both human and Agent succeeded; compare quality, speed, and recovery behavior.')

	if not recommended_next_changes:
		recommended_next_changes.append('Keep this task card as a regression case and add one harder failure scenario.')

	return ComparisonRecord(
		task_id=task.id,
		scenario_id=(human.scenario_id if human else agent.scenario_id if agent else 'normal'),
		task_category=task.category,
		experiment_id=agent.experiment_id if agent else None,
		navigator_enabled=agent.navigator_enabled if agent else None,
		navigator_model=agent.navigator_model if agent else None,
		human_status=human.success_status if human else None,
		agent_success=agent.success if agent else None,
		duration_delta_seconds=duration_delta_seconds,
		agent_step_count=agent.number_of_steps if agent else None,
		human_intervention_count=human.intervention_count if human else None,
		agent_error_count=len(agent.errors) if agent else 0,
		risk_flags=dedupe(risk_flags),
		differences=dedupe(differences),
		recommended_next_changes=dedupe(recommended_next_changes),
	)


def repeated_risky_action(action_names: list[str]) -> bool:
	if not action_names:
		return False
	for action_name in set(action_names):
		if action_names.count(action_name) >= 5 and action_name in {'click', 'input', 'navigate', 'wait'}:
			return True
	return False


def dedupe(items: list[str]) -> list[str]:
	seen: set[str] = set()
	result: list[str] = []
	for item in items:
		if item not in seen:
			seen.add(item)
			result.append(item)
	return result


def index_by_task_and_scenario(records: list[Any]) -> dict[tuple[str, str], Any]:
	index: dict[tuple[str, str], Any] = {}
	for record in records:
		task_id = getattr(record, 'task_id')
		scenario_id = getattr(record, 'scenario_id')
		index[(task_id, scenario_id)] = record
	return index


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


def _usage_dict_float(usage: dict[str, Any] | None, key: str) -> float | None:
	if not isinstance(usage, dict):
		return None
	val = usage.get(key)
	if val is None:
		return None
	try:
		return float(val)
	except (TypeError, ValueError):
		return None


def resource_snapshot_from_agent(agent: AgentRunSummary) -> AgentRunResourceSnapshot:
	usage = agent.usage_summary if isinstance(agent.usage_summary, dict) else None
	duration_seconds, wall_fb = _effective_duration_from_summary(agent)
	overhead, velocity, efficiency = academic_efficiency_from_agent_run(agent, duration_seconds=duration_seconds)
	return AgentRunResourceSnapshot(
		experiment_id=agent.experiment_id,
		started_at=agent.started_at,
		finished_at=agent.finished_at,
		success=agent.success,
		is_done=agent.is_done,
		duration_seconds=duration_seconds,
		duration_used_wall_clock_fallback=wall_fb,
		number_of_steps=agent.number_of_steps,
		executor_backend=agent.executor_backend,
		executor_model=agent.executor_model,
		navigator_enabled=agent.navigator_enabled,
		navigator_model=agent.navigator_model,
		history_path=agent.history_path,
		conversation_path=agent.conversation_path,
		total_tokens=_usage_dict_int(usage, 'total_tokens'),
		total_cost=_usage_dict_float(usage, 'total_cost'),
		total_prompt_tokens=_usage_dict_int(usage, 'total_prompt_tokens'),
		total_completion_tokens=_usage_dict_int(usage, 'total_completion_tokens'),
		llm_invocation_count=_usage_dict_int(usage, 'entry_count'),
		navigator_overhead_ratio=overhead,
		execution_velocity=velocity,
		token_efficiency_score=efficiency,
	)


def _resource_analysis_hints(snapshots: list[AgentRunResourceSnapshot]) -> list[str]:
	"""Heuristic one-liners for comparing runs in the same (task_id, scenario_id) bucket."""

	hints: list[str] = []
	if len(snapshots) < 2:
		hints.append(
			'Fewer than two Agent runs in this bucket: re-run with different --experiment (A/B/C/D) '
			'to compare cost, tokens, wall time, and step counts side-by-side.'
		)
		return hints

	with_cost = [s for s in snapshots if s.total_cost is not None]
	if len(with_cost) >= 2:
		lo = min(with_cost, key=lambda s: s.total_cost or 0.0)
		hi = max(with_cost, key=lambda s: s.total_cost or 0.0)
		if lo.total_cost == hi.total_cost:
			hints.append(
				f'All runs with cost data share total_cost={lo.total_cost}; trajectories or pricing may be identical.'
			)
		else:
			hints.append(
				f'Lowest total_cost: experiment_id={lo.experiment_id!r} total_cost={lo.total_cost} '
				f'steps={lo.number_of_steps} started_at={lo.started_at}; '
				f'highest: experiment_id={hi.experiment_id!r} total_cost={hi.total_cost} steps={hi.number_of_steps}'
			)
	else:
		hints.append(
			'Missing usage_summary.total_cost on most runs: compare duration_seconds and number_of_steps only, '
			'or ensure runs record usage (see DAILY_TASK_EXPERIMENT_GUIDE §1.1).'
		)

	lo_d = min(snapshots, key=lambda s: s.duration_seconds)
	hi_d = max(snapshots, key=lambda s: s.duration_seconds)
	if lo_d.duration_seconds != hi_d.duration_seconds:
		hints.append(
			f'Wall-clock: fastest experiment_id={lo_d.experiment_id!r} duration_seconds={lo_d.duration_seconds}; '
			f'slowest experiment_id={hi_d.experiment_id!r} duration_seconds={hi_d.duration_seconds}'
		)

	lo_st = min(snapshots, key=lambda s: s.number_of_steps)
	hi_st = max(snapshots, key=lambda s: s.number_of_steps)
	if lo_st.number_of_steps != hi_st.number_of_steps:
		hints.append(
			f'Steps: fewest experiment_id={lo_st.experiment_id!r} number_of_steps={lo_st.number_of_steps}; '
			f'most experiment_id={hi_st.experiment_id!r} number_of_steps={hi_st.number_of_steps}'
		)

	with_tok = [s for s in snapshots if s.total_tokens is not None]
	if len(with_tok) >= 2:
		lo_t = min(with_tok, key=lambda s: s.total_tokens or 0)
		hi_t = max(with_tok, key=lambda s: s.total_tokens or 0)
		if lo_t.total_tokens != hi_t.total_tokens:
			hints.append(
				f'Total LLM tokens: min experiment_id={lo_t.experiment_id!r} total_tokens={lo_t.total_tokens}; '
				f'max experiment_id={hi_t.experiment_id!r} total_tokens={hi_t.total_tokens}'
			)

	return hints


def _stat_mean(stats: RunMetricStats | None) -> float | None:
	return stats.mean if stats is not None and stats.n > 0 else None


def format_academic_efficiency_frontier_analysis(report: ExperimentResourceReport) -> str:
	"""Human-readable C vs D comparison for navigator overhead and token efficiency."""

	lines: list[str] = [
		'',
		'═' * 72,
		'【学术效率前沿分析 / Academic Efficiency Frontier Analysis】',
		'═' * 72,
		'Anchor: Experiment C (no navigator) vs Experiment D (navigator + executor).',
		'Metrics: navigator_overhead_ratio (↑ = more navigator tax on executor tokens),',
		'         token_efficiency_score (↑ = more successes per 1k tokens).',
		'',
	]
	any_pair = False
	for group in report.groups:
		row_c = next(
			(b for b in group.statistics_by_experiment if b.experiment_id == 'C' and not b.is_pooled),
			None,
		)
		row_d = next(
			(b for b in group.statistics_by_experiment if b.experiment_id == 'D' and not b.is_pooled),
			None,
		)
		if row_c is None or row_d is None:
			continue
		any_pair = True
		oh_c = _stat_mean(row_c.navigator_overhead_ratio)
		oh_d = _stat_mean(row_d.navigator_overhead_ratio)
		te_c = _stat_mean(row_c.token_efficiency_score)
		te_d = _stat_mean(row_d.token_efficiency_score)
		ev_c = _stat_mean(row_c.execution_velocity)
		ev_d = _stat_mean(row_d.execution_velocity)
		lines.append(f'── {group.task_id} / {group.scenario_id} ({group.task_category or "?"}) ──')
		lines.append(
			f'  runs: C={row_c.run_count} success={row_c.success_true} | '
			f'D={row_d.run_count} success={row_d.success_true}'
		)

		def fmt(v: float | None) -> str:
			return f'{v:.4f}' if v is not None else 'n/a'

		lines.append(f'  navigator_overhead_ratio (mean): C={fmt(oh_c)}  D={fmt(oh_d)}')
		if oh_c is not None and oh_d is not None:
			if oh_d > oh_c:
				lines.append('    → D pays higher navigator overhead (expected when navigator is enabled).')
			elif oh_d == 0.0 and oh_c == 0.0:
				lines.append('    → Both zero (no token usage recorded or no navigator cycle split).')
		lines.append(f'  token_efficiency_score (mean):   C={fmt(te_c)}  D={fmt(te_d)}')
		if te_c is not None and te_d is not None:
			if te_d > te_c:
				lines.append('    → D achieves better thousand-token success efficiency on this task.')
			elif te_c > te_d:
				lines.append('    → C is more token-efficient here; navigator cost may exceed benefit.')
			else:
				lines.append('    → Tie on mean thousand-token efficiency.')
		lines.append(f'  execution_velocity (mean tok/s):   C={fmt(ev_c)}  D={fmt(ev_d)}')
		lines.append('')

	if not any_pair:
		lines.append(
			'No (task, scenario) group contains both experiment C and D runs. '
			'Re-run compare after collecting paired C/D agent_runs.json entries.'
		)
		lines.append('')
	else:
		lines.append(
			'Interpretation: On hard tasks, a positive D advantage on token_efficiency_score '
			'with bounded navigator_overhead_ratio supports the navigator as cost-effective guidance.'
		)
		lines.append('')
	lines.append('═' * 72)
	return '\n'.join(lines)


def print_academic_efficiency_frontier_analysis(report: ExperimentResourceReport) -> None:
	"""Emit the frontier block to stdout (used by `compare` CLI)."""

	print(format_academic_efficiency_frontier_analysis(report))


def build_experiment_resource_report(
	agent_runs: list[AgentRunSummary],
	tasks: list[TaskCard],
) -> ExperimentResourceReport:
	"""Group `agent_runs` by (task_id, scenario_id) for A/B/C/D-style resource comparison without human data."""

	from collections import defaultdict

	task_cat: dict[str, TaskCategory] = {t.id: t.category for t in tasks}
	grouped: dict[tuple[str, str], list[AgentRunSummary]] = defaultdict(list)
	for run in agent_runs:
		grouped[(run.task_id, run.scenario_id)].append(run)

	groups: list[TaskScenarioResourceGroup] = []
	groups_index: list[ResourceGroupIndexEntry] = []
	for task_id, scenario_id in _ordered_task_scenario_keys(tasks, grouped):
		runs = sorted(grouped[(task_id, scenario_id)], key=lambda r: r.started_at)
		category = task_cat.get(task_id)
		if category is None and runs:
			category = runs[0].task_category
		snapshots = [resource_snapshot_from_agent(r) for r in runs]
		stats_rows, pooled = _task_scenario_statistics(snapshots)
		group = TaskScenarioResourceGroup(
			task_id=task_id,
			scenario_id=scenario_id,
			task_category=category,
			snapshots=snapshots,
			statistics_by_experiment=stats_rows,
			pooled_statistics=pooled,
			analysis_hints=_resource_analysis_hints(snapshots),
		)
		groups.append(group)
		groups_index.append(
			ResourceGroupIndexEntry(
				task_id=task_id,
				scenario_id=scenario_id,
				task_category=category,
				snapshot_count=len(snapshots),
				experiment_ids=_distinct_experiment_ids(snapshots),
			)
		)
	return ExperimentResourceReport(generated_at=utc_now(), groups_index=groups_index, groups=groups)


def compare_all(
	task_cards_path: Path,
	human_runs_path: Path,
	output_path: Path,
	*,
	csv_dir: Path | None = None,
	agent_runs_path: Path | None = None,
	resource_report_path: Path | None = None,
	skip_resource_report: bool = False,
) -> list[ComparisonRecord]:
	tasks = load_json_model_list(task_cards_path, TaskCard)
	human_runs = index_by_task_and_scenario(load_json_model_list(human_runs_path, HumanRunRecord))
	if csv_dir is not None:
		agent_runs = load_agent_summaries_from_csv_dir(csv_dir)
	elif agent_runs_path is not None:
		agent_runs = load_json_model_list(agent_runs_path, AgentRunSummary)
	else:
		raise ValueError('compare_all requires csv_dir or agent_runs_path')
	comparisons: list[ComparisonRecord] = []

	for task in tasks:
		scenario_ids = {'normal', *(mode.id for mode in task.failure_modes)}
		for scenario_id in sorted(scenario_ids):
			human = human_runs.get((task.id, scenario_id))
			matching_agents = [agent for agent in agent_runs if agent.task_id == task.id and agent.scenario_id == scenario_id]
			if matching_agents:
				for agent in matching_agents:
					comparisons.append(compare_runs(task, human, agent))
			elif human:
				comparisons.append(compare_runs(task, human, None))

	write_json(output_path, [comparison.model_dump(mode='json') for comparison in comparisons])
	if not skip_resource_report:
		res_path = resource_report_path or output_path.with_name('experiment_resource_report.json')
		res_report = build_experiment_resource_report(agent_runs, tasks)
		write_json(res_path, res_report.model_dump(mode='json'))
		print_academic_efficiency_frontier_analysis(res_report)
	return comparisons


def _csv_cell(v: object) -> str:
	if v is None:
		return ''
	if isinstance(v, bool):
		return 'true' if v else 'false'
	return str(v)


def _stats_bucket_experiment_label_csv(bucket: ExperimentBucketRunStatistics) -> str:
	"""Label for `stats_experiment_id` in CSV (non-empty so Excel does not shift `read_only_query` into wrong columns)."""

	if bucket.is_pooled:
		return '(pooled)'
	if bucket.experiment_id is None:
		return '(unlabeled)'
	return str(bucket.experiment_id)


def _run_metric_stat_cells(stats: RunMetricStats | None) -> list[str]:
	if stats is None:
		return [''] * 6

	def cell_num(v: float | None) -> str:
		if v is None:
			return ''
		return str(v)

	return [
		str(stats.n),
		cell_num(stats.mean),
		cell_num(stats.std),
		cell_num(stats.min),
		cell_num(stats.max),
		cell_num(stats.median),
	]


def _metric_csv_headers(prefix: str) -> list[str]:
	return [
		f'{prefix}_n',
		f'{prefix}_mean',
		f'{prefix}_std',
		f'{prefix}_min',
		f'{prefix}_max',
		f'{prefix}_median',
	]


def export_experiment_resource_report_to_csv(
	report_path: Path,
	runs_csv: Path,
	stats_csv: Path,
) -> tuple[Path, Path]:
	"""Write flattened per-run rows and per-bucket statistics from ``experiment_resource_report.json``."""

	report = ExperimentResourceReport.model_validate(json.loads(report_path.read_text(encoding='utf-8')))
	runs_csv.parent.mkdir(parents=True, exist_ok=True)
	stats_csv.parent.mkdir(parents=True, exist_ok=True)

	run_headers = [
		'task_id',
		'scenario_id',
		'task_category',
		'experiment_id',
		'started_at',
		'finished_at',
		'success',
		'is_done',
		'duration_seconds',
		'duration_used_wall_clock_fallback',
		'number_of_steps',
		'executor_backend',
		'executor_model',
		'navigator_enabled',
		'navigator_model',
		'total_tokens',
		'total_cost',
		'total_prompt_tokens',
		'total_completion_tokens',
		'llm_invocation_count',
		'navigator_overhead_ratio',
		'execution_velocity',
		'token_efficiency_score',
		'history_path',
		'conversation_path',
	]

	stat_headers = [
		'task_id',
		'scenario_id',
		'task_category',
		'stats_experiment_id',
		'stats_is_pooled',
		'run_count',
		'success_true',
		'success_false',
		'success_unknown',
		'is_done_true',
		'is_done_false',
		'duration_wall_clock_fallback_runs',
		*_metric_csv_headers('duration_seconds'),
		*_metric_csv_headers('number_of_steps'),
		*_metric_csv_headers('total_tokens'),
		*_metric_csv_headers('total_prompt_tokens'),
		*_metric_csv_headers('total_completion_tokens'),
		*_metric_csv_headers('llm_invocation_count'),
		*_metric_csv_headers('total_cost'),
		*_metric_csv_headers('navigator_overhead_ratio'),
		*_metric_csv_headers('execution_velocity'),
		*_metric_csv_headers('token_efficiency_score'),
	]

	with runs_csv.open('w', encoding='utf-8', newline='') as run_f:
		run_writer = csv.writer(run_f)
		run_writer.writerow(run_headers)
		for group in report.groups:
			for snap in group.snapshots:
				run_writer.writerow(
					[
						group.task_id,
						group.scenario_id,
						_csv_cell(group.task_category),
						_csv_cell(snap.experiment_id),
						snap.started_at,
						snap.finished_at,
						_csv_cell(snap.success),
						_csv_cell(snap.is_done),
						_csv_cell(snap.duration_seconds),
						_csv_cell(snap.duration_used_wall_clock_fallback),
						snap.number_of_steps,
						_csv_cell(snap.executor_backend),
						_csv_cell(snap.executor_model),
						_csv_cell(snap.navigator_enabled),
						_csv_cell(snap.navigator_model),
						_csv_cell(snap.total_tokens),
						_csv_cell(snap.total_cost),
						_csv_cell(snap.total_prompt_tokens),
						_csv_cell(snap.total_completion_tokens),
						_csv_cell(snap.llm_invocation_count),
						_csv_cell(snap.navigator_overhead_ratio),
						_csv_cell(snap.execution_velocity),
						_csv_cell(snap.token_efficiency_score),
						snap.history_path,
						snap.conversation_path,
					]
				)

	with stats_csv.open('w', encoding='utf-8', newline='') as stat_f:
		stat_writer = csv.writer(stat_f)
		stat_writer.writerow(stat_headers)
		for group in report.groups:
			for bucket in group.statistics_by_experiment:
				stat_writer.writerow(
					[
						group.task_id,
						group.scenario_id,
						_csv_cell(group.task_category),
						_stats_bucket_experiment_label_csv(bucket),
						_csv_cell(bucket.is_pooled),
						bucket.run_count,
						bucket.success_true,
						bucket.success_false,
						bucket.success_unknown,
						bucket.is_done_true,
						bucket.is_done_false,
						bucket.duration_wall_clock_fallback_runs,
						*_run_metric_stat_cells(bucket.duration_seconds),
						*_run_metric_stat_cells(bucket.number_of_steps),
						*_run_metric_stat_cells(bucket.total_tokens),
						*_run_metric_stat_cells(bucket.total_prompt_tokens),
						*_run_metric_stat_cells(bucket.total_completion_tokens),
						*_run_metric_stat_cells(bucket.llm_invocation_count),
						*_run_metric_stat_cells(bucket.total_cost),
						*_run_metric_stat_cells(bucket.navigator_overhead_ratio),
						*_run_metric_stat_cells(bucket.execution_velocity),
						*_run_metric_stat_cells(bucket.token_efficiency_score),
					]
				)
			if group.pooled_statistics is not None:
				p = group.pooled_statistics
				stat_writer.writerow(
					[
						group.task_id,
						group.scenario_id,
						_csv_cell(group.task_category),
						_stats_bucket_experiment_label_csv(p),
						_csv_cell(p.is_pooled),
						p.run_count,
						p.success_true,
						p.success_false,
						p.success_unknown,
						p.is_done_true,
						p.is_done_false,
						p.duration_wall_clock_fallback_runs,
						*_run_metric_stat_cells(p.duration_seconds),
						*_run_metric_stat_cells(p.number_of_steps),
						*_run_metric_stat_cells(p.total_tokens),
						*_run_metric_stat_cells(p.total_prompt_tokens),
						*_run_metric_stat_cells(p.total_completion_tokens),
						*_run_metric_stat_cells(p.llm_invocation_count),
						*_run_metric_stat_cells(p.total_cost),
						*_run_metric_stat_cells(p.navigator_overhead_ratio),
						*_run_metric_stat_cells(p.execution_velocity),
						*_run_metric_stat_cells(p.token_efficiency_score),
					]
				)

	return runs_csv, stats_csv


def export_agent_runs_to_csv(agent_runs_path: Path, output_csv: Path) -> Path:
	"""One row per ``AgentRunSummary`` in ``agent_runs.json`` (wide scalar columns; lists joined with ``|``)."""

	agents = load_json_model_list(agent_runs_path, AgentRunSummary)
	output_csv.parent.mkdir(parents=True, exist_ok=True)

	headers = [
		'task_id',
		'scenario_id',
		'task_category',
		'experiment_id',
		'executor_backend',
		'executor_model',
		'navigator_backend',
		'navigator_enabled',
		'navigator_model',
		'navigator_plan_path',
		'started_at',
		'finished_at',
		'success',
		'is_done',
		'duration_seconds',
		'number_of_steps',
		'action_names',
		'errors',
		'urls',
		'screenshot_paths',
		'final_result',
		'history_path',
		'conversation_path',
		'usage_total_tokens',
		'usage_total_cost',
		'usage_entry_count',
		'navigator_overhead_ratio',
		'execution_velocity',
		'token_efficiency_score',
	]

	with output_csv.open('w', encoding='utf-8', newline='') as f:
		w = csv.writer(f)
		w.writerow(headers)
		for a in agents:
			usage = a.usage_summary if isinstance(a.usage_summary, dict) else None
			ut = usage.get('total_tokens') if usage else None
			uc = usage.get('total_cost') if usage else None
			ue = usage.get('entry_count') if usage else None
			effective_dur, _ = _effective_duration_from_summary(a)
			oh, vel, eff = academic_efficiency_from_agent_run(a, duration_seconds=effective_dur)
			w.writerow(
				[
					a.task_id,
					a.scenario_id,
					_csv_cell(a.task_category),
					_csv_cell(a.experiment_id),
					_csv_cell(a.executor_backend),
					_csv_cell(a.executor_model),
					_csv_cell(a.navigator_backend),
					_csv_cell(a.navigator_enabled),
					_csv_cell(a.navigator_model),
					_csv_cell(a.navigator_plan_path),
					a.started_at,
					a.finished_at,
					_csv_cell(a.success),
					_csv_cell(a.is_done),
					_csv_cell(a.duration_seconds),
					a.number_of_steps,
					'|'.join(a.action_names),
					'|'.join(a.errors),
					'|'.join(a.urls),
					'|'.join(a.screenshot_paths),
					_csv_cell(a.final_result),
					a.history_path,
					a.conversation_path,
					_csv_cell(ut),
					_csv_cell(uc),
					_csv_cell(ue),
					_csv_cell(oh),
					_csv_cell(vel),
					_csv_cell(eff),
				]
			)

	return output_csv

