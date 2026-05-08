from __future__ import annotations

import asyncio
import contextlib
import logging
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
				focus = getattr(session, 'agent_focus', None)
				if focus is not None:
					cur_url = getattr(focus, 'url', '') or ''
				if not cur_url:
					tabs = getattr(session, 'tabs', None) or []
					for tab in tabs:
						url = getattr(tab, 'url', '') or ''
						if url and not url.startswith(('edge://', 'about:', 'chrome://', 'data:')):
							cur_url = url
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


from .models import (
	AgentRunSummary,
	ComparisonRecord,
	HumanRunRecord,
	TaskCard,
	load_json_model_list,
	utc_now,
	write_json,
)
from .executor import (
	ExecutorConfig,
	build_executor_llm,
	default_max_actions_per_step_for_executor,
	default_use_vision_for_executor,
)
from .navigator import NavigatorConfig, NavigatorPlanProvider, build_navigator
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
	task_cards = default_task_cards()
	human_runs = [
		HumanRunRecord(
			task_id=task.id,
			scenario_id='normal',
			steps=['Replace this with the exact manual steps you took.'],
			notes='Fill this after the human baseline run.',
		).model_dump(mode='json')
		for task in task_cards
	]
	paths = {
		'task_cards': output_dir / 'task_cards.json',
		'human_runs': output_dir / 'human_runs.json',
		'agent_runs': output_dir / 'agent_runs.json',
		'comparisons': output_dir / 'comparison_report.json',
	}
	write_json(paths['task_cards'], [task.model_dump(mode='json') for task in task_cards], overwrite=overwrite)
	write_json(paths['human_runs'], human_runs, overwrite=overwrite)
	write_json(paths['agent_runs'], [], overwrite=overwrite)
	write_json(paths['comparisons'], [], overwrite=overwrite)
	return paths


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
	experiment_id: str | None = None,
	executor_backend: str | None = None,
	executor_model: str | None = None,
	navigator_backend: str | None = None,
) -> AgentRunSummary:
	errors = [error for error in history.errors() if error]
	urls = [url for url in history.urls() if url]
	screenshot_paths = [path for path in history.screenshot_paths(return_none_if_not_screenshot=False) if path]
	return AgentRunSummary(
		task_id=task_id,
		scenario_id=scenario_id,
		experiment_id=experiment_id,
		executor_backend=executor_backend,
		executor_model=executor_model,
		navigator_backend=navigator_backend,
		navigator_enabled=navigator_enabled,
		navigator_model=navigator_model,
		navigator_plan_path=str(navigator_plan_path) if navigator_plan_path else None,
		started_at=started_at,
		finished_at=finished_at,
		success=history.is_successful(),
		is_done=history.is_done(),
		duration_seconds=history.total_duration_seconds(),
		number_of_steps=history.number_of_steps(),
		action_names=history.action_names(),
		errors=errors,
		urls=urls,
		screenshot_paths=screenshot_paths,
		final_result=history.final_result(),
		history_path=str(history_path),
		conversation_path=str(conversation_path),
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

	navigator_plan = None
	if navigator is not None:
		navigator_plan = await navigator.create_plan(task=task, scenario_id=scenario_id)
		if navigator_plan:
			navigator_plan_path.write_text(navigator_plan, encoding='utf-8')

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
		return summarize_history(
			history=history,
			task_id=task.id,
			scenario_id=scenario_id,
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
		)
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


def compare_all(task_cards_path: Path, human_runs_path: Path, agent_runs_path: Path, output_path: Path) -> list[ComparisonRecord]:
	tasks = load_json_model_list(task_cards_path, TaskCard)
	human_runs = index_by_task_and_scenario(load_json_model_list(human_runs_path, HumanRunRecord))
	agent_runs = load_json_model_list(agent_runs_path, AgentRunSummary)
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
	return comparisons

