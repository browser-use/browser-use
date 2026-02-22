"""Cloud task SDK wrappers and CLI handlers.

This module provides:
- SDK wrapper functions for the Browser-Use Cloud Task API
- CLI command handlers for `browser-use task <command>`
"""

import argparse
import json
import logging
import sys
from typing import Any

from browser_use_sdk.types.task_created_response import TaskCreatedResponse
from browser_use_sdk.types.task_item_view import TaskItemView
from browser_use_sdk.types.task_log_file_response import TaskLogFileResponse
from browser_use_sdk.types.task_view import TaskView

from browser_use.skill_cli.commands.utils import format_duration, get_sdk_client

logger = logging.getLogger(__name__)


def _filter_none(kwargs: dict[str, Any]) -> dict[str, Any]:
	"""Filter out None values from kwargs (SDK passes them as null, API rejects)."""
	return {k: v for k, v in kwargs.items() if v is not None}


# ============ SDK Wrappers ============


def create_task(task: str, **kwargs: Any) -> TaskCreatedResponse:
	"""Create a cloud task via API.

	Args:
		task: Task description for the agent
		llm: LLM model identifier
		session_id: Existing session ID to use
		max_steps: Maximum agent steps
		flash_mode: Enable flash mode for faster execution
		thinking: Enable extended reasoning mode
		vision: Enable/disable vision
		start_url: URL to start the task from
		metadata: Task metadata key-value pairs
		secrets: Task secrets key-value pairs
		allowed_domains: Restrict navigation to these domains
		skill_ids: Enable specific skill IDs
		structured_output: JSON schema for structured output
		judge: Enable judge mode
		judge_ground_truth: Expected answer for judge evaluation

	Returns:
		TaskCreatedResponse with task ID and session ID
	"""
	params = _filter_none(kwargs)
	params['task'] = task
	return get_sdk_client().tasks.create_task(**params)


def get_task(task_id: str) -> TaskView:
	"""Get full task details including steps."""
	return get_sdk_client().tasks.get_task(task_id)


def list_tasks(
	limit: int = 10,
	status: str | None = None,
	session_id: str | None = None,
) -> list[TaskItemView]:
	"""List recent tasks."""
	client = get_sdk_client()
	response = client.tasks.list_tasks(
		page_size=limit,
		**_filter_none({'filter_by': status, 'session_id': session_id}),
	)
	return list(response.items) if response.items else []


def stop_task(task_id: str) -> TaskView:
	"""Stop a running task."""
	return get_sdk_client().tasks.update_task(task_id, action='stop')


def get_task_logs(task_id: str) -> TaskLogFileResponse:
	"""Get task execution logs."""
	return get_sdk_client().tasks.get_task_logs(task_id)


async def poll_until_complete(
	task_id: str,
	stream: bool = False,
	poll_interval: float = 1.0,
) -> TaskView:
	"""Poll task status until finished."""
	import asyncio

	client = get_sdk_client()
	last_status = None

	while True:
		# Run blocking SDK call in thread to avoid blocking event loop
		task = await asyncio.to_thread(client.tasks.get_task, task_id)
		current_status = task.status

		if stream and current_status != last_status:
			print(f'Status: {current_status}')
			last_status = current_status

		if current_status in ('finished', 'stopped', 'failed'):
			return task

		await asyncio.sleep(poll_interval)


# ============ CLI Handlers ============


def handle_task_command(args: argparse.Namespace) -> int:
	"""Handle task subcommands.

	Task commands manage cloud tasks and always require the cloud API.

	Args:
		args: Parsed command-line arguments

	Returns:
		Exit code (0 for success, 1 for error)
	"""
	from browser_use.skill_cli.api_key import APIKeyRequired, require_api_key
	from browser_use.skill_cli.install_config import is_mode_available

	# Check if remote mode is available
	if not is_mode_available('remote'):
		print(
			'Error: Task management requires remote mode.\n'
			'Remote mode is not installed. Reinstall to enable:\n'
			'  curl -fsSL https://browser-use.com/cli/install.sh | bash -s -- --remote-only\n'
			'  curl -fsSL https://browser-use.com/cli/install.sh | bash -s -- --full',
			file=sys.stderr,
		)
		return 1

	# Check API key
	try:
		require_api_key('Cloud tasks')
	except APIKeyRequired as e:
		print(f'Error: {e}', file=sys.stderr)
		return 1

	if args.task_command == 'list':
		return _handle_list(args)
	elif args.task_command == 'status':
		return _handle_status(args)
	elif args.task_command == 'stop':
		return _handle_stop(args)
	elif args.task_command == 'logs':
		return _handle_logs(args)
	else:
		print('Usage: browser-use task <command>')
		print('Commands: list, status <task_id>, stop <task_id>, logs <task_id>')
		return 1


# ============ CLI Helper Functions ============


def _task_item_to_dict(task: Any) -> dict[str, Any]:
	"""Convert SDK TaskItemView to dict for JSON output."""
	return {
		'id': task.id,
		'status': task.status,
		'task': task.task,
		'sessionId': task.session_id,
	}


def _task_to_dict(task: Any) -> dict[str, Any]:
	"""Convert SDK TaskView to dict for JSON output."""
	return {
		'id': task.id,
		'status': task.status,
		'task': task.task,
		'output': task.output,
		'cost': task.cost,
		'sessionId': task.session_id,
		'startedAt': task.started_at.isoformat() if task.started_at else None,
		'finishedAt': task.finished_at.isoformat() if task.finished_at else None,
		'steps': [_step_to_dict(s) for s in (task.steps or [])],
	}


def _step_to_dict(step: Any) -> dict[str, Any]:
	"""Convert SDK step to dict for JSON output."""
	return {
		'number': step.number,
		'url': step.url,
		'memory': step.memory,
		'actions': step.actions,
	}


def _handle_list(args: argparse.Namespace) -> int:
	"""Handle 'task list' command."""
	try:
		status_filter = getattr(args, 'status', None)
		session_filter = getattr(args, 'session', None)
		tasks = list_tasks(
			limit=args.limit,
			status=status_filter,
			session_id=session_filter,
		)
	except Exception as e:
		print(f'Error: {e}', file=sys.stderr)
		return 1

	if getattr(args, 'json', False):
		print(json.dumps([_task_item_to_dict(t) for t in tasks]))
	else:
		if not tasks:
			status_msg = f' with status "{status_filter}"' if status_filter else ''
			session_msg = f' in session "{session_filter}"' if session_filter else ''
			print(f'No tasks found{status_msg}{session_msg}')
		else:
			header = f'Tasks ({len(tasks)})'
			if status_filter:
				header = f'{status_filter.capitalize()} tasks ({len(tasks)})'
			print(f'{header}:')
			for t in tasks:
				task_id = t.id or 'unknown'
				status = t.status or 'unknown'
				task_desc = t.task or ''
				# Truncate long task descriptions
				if len(task_desc) > 50:
					task_desc = task_desc[:47] + '...'

				# Status emoji
				status_emoji = {
					'started': '🔄',
					'running': '🔄',
					'finished': '✅',
					'stopped': '⏹️',
					'failed': '❌',
				}.get(status, '❓')

				print(f'  {status_emoji} {task_id[:8]}... [{status}] {task_desc}')

	return 0


def _handle_status(args: argparse.Namespace) -> int:
	"""Handle 'task status <task_id>' command."""
	try:
		# Use get_task() for full details including steps
		task = get_task(args.task_id)
	except Exception as e:
		print(f'Error: {e}', file=sys.stderr)
		return 1

	if getattr(args, 'json', False):
		print(json.dumps(_task_to_dict(task)))
	else:
		task_id = task.id or args.task_id
		task_status = task.status or 'unknown'
		output = task.output
		cost = task.cost
		steps = task.steps or []
		started_at = task.started_at
		finished_at = task.finished_at

		compact = getattr(args, 'compact', False)
		verbose = getattr(args, 'verbose', False)
		last_n = getattr(args, 'last', None)
		reverse = getattr(args, 'reverse', False)
		specific_step = getattr(args, 'step', None)

		# Determine display mode:
		# - Default: show only latest step
		# - --compact: show all steps with reasoning
		# - --verbose: show all steps with full details
		show_all_steps = compact or verbose

		# Status emoji
		status_emoji = {
			'started': '🔄',
			'running': '🔄',
			'finished': '✅',
			'stopped': '⏹️',
			'failed': '❌',
		}.get(task_status, '❓')

		# Build header line: status, cost, duration
		parts = [f'{status_emoji} {task_id[:8]}... [{task_status}]']
		if cost is not None:
			parts.append(f'${cost}')
		duration = format_duration(started_at, finished_at)
		if duration:
			parts.append(duration)
		print(' '.join(parts))

		# Show steps
		if steps:
			total_steps = len(steps)

			# Filter to specific step if requested
			if specific_step is not None:
				steps = [s for s in steps if s.number == specific_step]
				if not steps:
					print(f'  Step {specific_step} not found (task has {total_steps} steps)')
				else:
					print(f'  (showing step {specific_step} of {total_steps})')
				# Display the specific step
				for step in steps:
					_print_step(step, verbose)
			elif not show_all_steps:
				# Default mode: show only the latest step
				latest_step = steps[-1]
				earlier_count = total_steps - 1
				if earlier_count > 0:
					print(f'  ... {earlier_count} earlier steps')
				_print_step(latest_step, verbose=False)
			else:
				# --compact or --verbose: show all steps (with optional filters)
				skipped_earlier = 0
				if last_n is not None and last_n < total_steps:
					skipped_earlier = total_steps - last_n
					steps = steps[-last_n:]

				# Apply --reverse
				if reverse:
					steps = list(reversed(steps))

				# Show count info
				if skipped_earlier > 0:
					print(f'  ... {skipped_earlier} earlier steps')

				# Display steps
				for step in steps:
					_print_step(step, verbose)

		if output:
			print(f'\nOutput: {output}')

	return 0


def _print_step(step: Any, verbose: bool) -> None:
	"""Print a single step in compact or verbose format."""
	step_num = step.number if step.number is not None else '?'
	memory = step.memory or ''

	if verbose:
		url = step.url or ''
		actions = step.actions or []

		# Truncate URL for display
		short_url = url[:60] + '...' if len(url) > 60 else url

		print(f'  [{step_num}] {short_url}')
		if memory:
			# Truncate memory/reasoning for display
			short_memory = memory[:100] + '...' if len(memory) > 100 else memory
			print(f'      Reasoning: {short_memory}')
		if actions:
			for action in actions[:2]:  # Show max 2 actions per step
				# Truncate action for display
				short_action = action[:70] + '...' if len(action) > 70 else action
				print(f'      Action: {short_action}')
			if len(actions) > 2:
				print(f'      ... and {len(actions) - 2} more actions')
	else:
		# Compact mode: just step number and reasoning
		if memory:
			# Truncate reasoning for compact display
			short_memory = memory[:80] + '...' if len(memory) > 80 else memory
			print(f'  {step_num}. {short_memory}')
		else:
			print(f'  {step_num}. (no reasoning)')


def _handle_stop(args: argparse.Namespace) -> int:
	"""Handle 'task stop <task_id>' command."""
	try:
		stop_task(args.task_id)
	except Exception as e:
		print(f'Error: {e}', file=sys.stderr)
		return 1

	if getattr(args, 'json', False):
		print(json.dumps({'stopped': args.task_id}))
	else:
		print(f'Stopped task: {args.task_id}')

	return 0


def _handle_logs(args: argparse.Namespace) -> int:
	"""Handle 'task logs <task_id>' command."""
	try:
		result = get_task_logs(args.task_id)
	except Exception as e:
		print(f'Error: {e}', file=sys.stderr)
		return 1

	if getattr(args, 'json', False):
		print(json.dumps({'downloadUrl': result.download_url}))
	else:
		download_url = result.download_url
		if download_url:
			print(f'Download logs: {download_url}')
		else:
			print('No logs available for this task')

	return 0
