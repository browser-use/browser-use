from __future__ import annotations

import json
import logging
import traceback
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

import anyio
from pydantic import BaseModel

from browser_use.config import CONFIG
from browser_use.llm.messages import BaseMessage

LLM_DEBUG_TRACE_FILENAME = 'llm_trace.jsonl'
MODEL_INPUT_SNAPSHOTS_DIRNAME = 'model_inputs'
RUN_MANIFEST_FILENAME = 'run_manifest.json'
RUN_SUMMARY_FILENAME = 'run_summary.json'
TOOL_TRACE_FILENAME = 'tool_traces.jsonl'
STEP_SUMMARY_FILENAME = 'step_summaries.jsonl'
RUNTIME_EVENTS_FILENAME = 'runtime_events.jsonl'
BROWSER_STATE_SNAPSHOTS_DIRNAME = 'browser_states'
DOM_SNAPSHOTS_DIRNAME = 'dom_snapshots'
CDP_SUMMARIES_DIRNAME = 'cdp_summaries'


def is_llm_debug_trace_enabled(logger: logging.Logger | None = None) -> bool:
	"""Return whether local LLM traces should be written for the current process."""
	if CONFIG.BROWSER_USE_LOGGING_LEVEL == 'debug':
		return True

	return logger.isEnabledFor(logging.DEBUG) if logger is not None else False


def llm_debug_trace_path(agent_directory: str | Path) -> Path:
	return Path(agent_directory) / LLM_DEBUG_TRACE_FILENAME


def run_manifest_path(agent_directory: str | Path) -> Path:
	return Path(agent_directory) / RUN_MANIFEST_FILENAME


def run_summary_path(agent_directory: str | Path) -> Path:
	return Path(agent_directory) / RUN_SUMMARY_FILENAME


def tool_trace_path(agent_directory: str | Path) -> Path:
	return Path(agent_directory) / TOOL_TRACE_FILENAME


def step_summary_path(agent_directory: str | Path) -> Path:
	return Path(agent_directory) / STEP_SUMMARY_FILENAME


def runtime_events_path(agent_directory: str | Path) -> Path:
	return Path(agent_directory) / RUNTIME_EVENTS_FILENAME


def model_input_snapshot_paths(agent_directory: str | Path, step: int) -> tuple[Path, Path]:
	output_dir = Path(agent_directory) / MODEL_INPUT_SNAPSHOTS_DIRNAME
	stem = f'step_{step:04d}'
	return output_dir / f'{stem}.json', output_dir / f'{stem}.txt'


def browser_state_snapshot_path(agent_directory: str | Path, step: int) -> Path:
	return Path(agent_directory) / BROWSER_STATE_SNAPSHOTS_DIRNAME / f'step_{step:04d}.json'


def dom_snapshot_paths(agent_directory: str | Path, step: int) -> tuple[Path, Path]:
	output_dir = Path(agent_directory) / DOM_SNAPSHOTS_DIRNAME
	stem = f'step_{step:04d}'
	return output_dir / f'{stem}.json', output_dir / f'{stem}.txt'


def cdp_summary_path(agent_directory: str | Path, step: int) -> Path:
	return Path(agent_directory) / CDP_SUMMARIES_DIRNAME / f'step_{step:04d}.json'


def _jsonable(value: Any) -> Any:
	if isinstance(value, type) and issubclass(value, BaseModel):
		return {
			'name': value.__name__,
			'json_schema': _model_json_schema(value),
		}

	if isinstance(value, BaseModel):
		try:
			return value.model_dump(mode='json')
		except Exception:
			return _jsonable(value.model_dump(mode='python'))

	if is_dataclass(value) and not isinstance(value, type):
		return _jsonable(asdict(value))

	if isinstance(value, BaseException):
		return {
			'type': type(value).__name__,
			'message': str(value),
			'traceback': ''.join(traceback.format_exception(type(value), value, value.__traceback__)),
		}

	if isinstance(value, list | tuple):
		return [_jsonable(item) for item in value]

	if isinstance(value, dict):
		return {str(key): _jsonable(item) for key, item in value.items()}

	try:
		json.dumps(value)
		return value
	except TypeError:
		return repr(value)


def _model_json_schema(model: type[BaseModel]) -> dict[str, Any] | None:
	try:
		return model.model_json_schema()
	except Exception as exc:
		return {'error': f'{type(exc).__name__}: {exc}'}


def _tool_registry_snapshot(tools: Any) -> list[dict[str, Any]]:
	actions = getattr(getattr(tools, 'registry', None), 'registry', None)
	registered_actions = getattr(actions, 'actions', {})

	snapshot = []
	for action_name, action in registered_actions.items():
		param_model = getattr(action, 'param_model', None)
		snapshot.append(
			{
				'name': action_name,
				'description': getattr(action, 'description', None),
				'terminates_sequence': getattr(action, 'terminates_sequence', False),
				'domains': getattr(action, 'domains', None),
				'params_schema': _model_json_schema(param_model) if param_model is not None else None,
			}
		)
	return snapshot


def _message_snapshot_text(messages: list[BaseMessage]) -> str:
	sections = []
	for index, message in enumerate(messages):
		header = f'[{index}] role={message.role}'
		if getattr(message, 'tool_call_id', None):
			header += f' tool_call_id={getattr(message, "tool_call_id")}'
		sections.append(header)
		tool_calls = getattr(message, 'tool_calls', None)
		if tool_calls:
			sections.append('tool_calls:')
			for tool_call in tool_calls:
				sections.append(f'  - {tool_call.function.name} id={tool_call.id} args={tool_call.function.arguments}')
		sections.append(message.text)
	return '\n\n'.join(sections).strip() + '\n'


def _utc_timestamp() -> str:
	return datetime.now(timezone.utc).isoformat()


async def _write_json(path: Path, payload: dict[str, Any]) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	async with await anyio.open_file(path, 'w', encoding='utf-8') as output_file:
		await output_file.write(json.dumps(_jsonable(payload), ensure_ascii=False, indent=2) + '\n')


async def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	async with await anyio.open_file(path, 'a', encoding='utf-8') as output_file:
		await output_file.write(json.dumps(_jsonable(payload), ensure_ascii=False) + '\n')


def _record_base(event: str, *, step: int | None = None, session_id: str | None = None) -> dict[str, Any]:
	record: dict[str, Any] = {
		'schema_version': 1,
		'event': event,
		'timestamp': _utc_timestamp(),
	}
	if step is not None:
		record['step'] = step
	if session_id is not None:
		record['session_id'] = session_id
	return record


def _llm_snapshot(llm: Any) -> dict[str, Any]:
	return {
		'provider': getattr(llm, 'provider', None),
		'model': getattr(llm, 'model', None),
		'name': getattr(llm, 'name', None),
	}


def _browser_session_handles(browser_session: Any | None) -> dict[str, Any]:
	if browser_session is None:
		return {'available': False}

	handles: dict[str, Any] = {
		'available': True,
		'browser_session_id': getattr(browser_session, 'id', None),
		'agent_focus_target_id': str(getattr(browser_session, 'agent_focus_target_id', None))
		if getattr(browser_session, 'agent_focus_target_id', None) is not None
		else None,
		'is_cdp_connected': getattr(browser_session, 'is_cdp_connected', None),
	}

	session_manager = getattr(browser_session, 'session_manager', None)
	if session_manager is None:
		handles['session_manager'] = {'available': False}
		return handles

	targets = []
	for target_id, target in session_manager.get_all_targets().items():
		targets.append(
			{
				'target_id': str(target_id),
				'type': getattr(target, 'target_type', None),
				'url': getattr(target, 'url', None),
				'title': getattr(target, 'title', None),
				'is_agent_focus': target_id == getattr(browser_session, 'agent_focus_target_id', None),
			}
		)

	sessions = []
	for session_id, cdp_session in session_manager.get_all_sessions().items():
		sessions.append(
			{
				'session_id': str(session_id),
				'target_id': str(getattr(cdp_session, 'target_id', '')),
			}
		)

	target_sessions = {
		str(target_id): sorted(str(session_id) for session_id in session_ids)
		for target_id, session_ids in session_manager.get_target_sessions_mapping().items()
	}

	handles['session_manager'] = {
		'available': True,
		'targets': targets,
		'sessions': sessions,
		'target_sessions': target_sessions,
	}
	return handles


def _tab_snapshot(tab: Any) -> dict[str, Any]:
	return {
		'url': getattr(tab, 'url', None),
		'title': getattr(tab, 'title', None),
		'target_id': str(getattr(tab, 'target_id', None)) if getattr(tab, 'target_id', None) is not None else None,
		'parent_target_id': str(getattr(tab, 'parent_target_id', None))
		if getattr(tab, 'parent_target_id', None) is not None
		else None,
	}


def _selector_node_snapshot(index: int, node: Any) -> dict[str, Any]:
	text = ''
	try:
		text = node.get_meaningful_text_for_llm()
	except Exception:
		try:
			text = node.get_all_children_text(max_depth=3)
		except Exception:
			text = ''

	ax_node = getattr(node, 'ax_node', None)
	absolute_position = getattr(node, 'absolute_position', None)
	return {
		'index': index,
		'backend_node_id': getattr(node, 'backend_node_id', None),
		'node_id': getattr(node, 'node_id', None),
		'tag_name': getattr(node, 'tag_name', None),
		'node_name': getattr(node, 'node_name', None),
		'attributes': getattr(node, 'attributes', None),
		'text': text[:500],
		'is_visible': getattr(node, 'is_visible', None),
		'is_scrollable': getattr(node, 'is_scrollable', None),
		'target_id': str(getattr(node, 'target_id', None)) if getattr(node, 'target_id', None) is not None else None,
		'session_id': str(getattr(node, 'session_id', None)) if getattr(node, 'session_id', None) is not None else None,
		'frame_id': getattr(node, 'frame_id', None),
		'xpath': getattr(node, 'xpath', None),
		'absolute_position': absolute_position.to_dict() if absolute_position is not None else None,
		'accessibility': {
			'role': getattr(ax_node, 'role', None),
			'name': getattr(ax_node, 'name', None),
			'description': getattr(ax_node, 'description', None),
		}
		if ax_node is not None
		else None,
	}


def _browser_state_payload(browser_state_summary: Any, browser_session: Any | None) -> dict[str, Any]:
	screenshot = getattr(browser_state_summary, 'screenshot', None)
	screenshot_meta = None
	if screenshot:
		screenshot_meta = {
			'base64_chars': len(screenshot),
			'sha256': sha256(screenshot.encode('utf-8')).hexdigest(),
		}

	return {
		'url': getattr(browser_state_summary, 'url', None),
		'title': getattr(browser_state_summary, 'title', None),
		'tabs': [_tab_snapshot(tab) for tab in getattr(browser_state_summary, 'tabs', [])],
		'pixels_above': getattr(browser_state_summary, 'pixels_above', None),
		'pixels_below': getattr(browser_state_summary, 'pixels_below', None),
		'page_info': _jsonable(getattr(browser_state_summary, 'page_info', None)),
		'browser_errors': list(getattr(browser_state_summary, 'browser_errors', []) or []),
		'is_pdf_viewer': getattr(browser_state_summary, 'is_pdf_viewer', None),
		'recent_events': getattr(browser_state_summary, 'recent_events', None),
		'pending_network_requests': _jsonable(getattr(browser_state_summary, 'pending_network_requests', []) or []),
		'pagination_buttons': _jsonable(getattr(browser_state_summary, 'pagination_buttons', []) or []),
		'closed_popup_messages': list(getattr(browser_state_summary, 'closed_popup_messages', []) or []),
		'screenshot': screenshot_meta,
		'selector_count': len(getattr(getattr(browser_state_summary, 'dom_state', None), 'selector_map', {}) or {}),
		'cdp_handles': _browser_session_handles(browser_session),
	}


def _dom_snapshot_payload(browser_state_summary: Any, include_attributes: list[str] | None = None) -> dict[str, Any]:
	dom_state = getattr(browser_state_summary, 'dom_state', None)
	selector_map = getattr(dom_state, 'selector_map', {}) or {}
	try:
		llm_dom = dom_state.llm_representation(include_attributes=include_attributes) if dom_state is not None else ''
	except Exception as exc:
		llm_dom = f'Failed to render DOM snapshot: {type(exc).__name__}: {exc}'

	return {
		'url': getattr(browser_state_summary, 'url', None),
		'title': getattr(browser_state_summary, 'title', None),
		'llm_representation': llm_dom,
		'selector_map': [_selector_node_snapshot(index, node) for index, node in sorted(selector_map.items())],
	}


async def write_debug_run_manifest(
	*,
	agent_directory: str | Path,
	logger: logging.Logger | None,
	session_id: str,
	agent_id: str,
	task_id: str,
	task: str,
	llm: Any,
	settings: Any,
	browser_session: Any | None,
	max_steps: int,
) -> None:
	"""Write the top-level run manifest for local debugging."""
	if not is_llm_debug_trace_enabled(logger):
		return

	record = _record_base('run_manifest', session_id=session_id)
	record.update(
		{
			'agent_id': agent_id,
			'task_id': task_id,
			'task': task,
			'agent_directory': str(agent_directory),
			'max_steps': max_steps,
			'llm': _llm_snapshot(llm),
			'settings': _jsonable(settings),
			'browser': _browser_session_handles(browser_session),
		}
	)
	await _write_json(run_manifest_path(agent_directory), record)


async def write_browser_debug_snapshot(
	*,
	agent_directory: str | Path,
	logger: logging.Logger | None,
	step: int,
	session_id: str,
	browser_state_summary: Any,
	browser_session: Any | None,
	include_attributes: list[str] | None = None,
) -> None:
	"""Write browser state, DOM/selector, and CDP handle snapshots for a step."""
	if not is_llm_debug_trace_enabled(logger):
		return

	base = _record_base('browser_state_snapshot', step=step, session_id=session_id)
	await _write_json(
		browser_state_snapshot_path(agent_directory, step),
		{**base, 'browser_state': _browser_state_payload(browser_state_summary, browser_session)},
	)

	dom_payload = _dom_snapshot_payload(browser_state_summary, include_attributes=include_attributes)
	dom_json_path, dom_text_path = dom_snapshot_paths(agent_directory, step)
	await _write_json(dom_json_path, {**_record_base('dom_snapshot', step=step, session_id=session_id), **dom_payload})
	dom_text_path.parent.mkdir(parents=True, exist_ok=True)
	async with await anyio.open_file(dom_text_path, 'w', encoding='utf-8') as dom_file:
		await dom_file.write(str(dom_payload['llm_representation']).rstrip() + '\n')

	await _write_json(
		cdp_summary_path(agent_directory, step),
		{
			**_record_base('cdp_summary', step=step, session_id=session_id),
			'cdp_handles': _browser_session_handles(browser_session),
		},
	)


async def append_tool_debug_trace(
	*,
	agent_directory: str | Path,
	logger: logging.Logger | None,
	event: str,
	step: int,
	session_id: str,
	tool_name: str,
	tool_call_id: str | None = None,
	arguments: dict[str, Any] | None = None,
	provider_tool_call: Any | None = None,
	result: Any | None = None,
	action_result: Any | None = None,
	error: BaseException | None = None,
	duration_ms: float | None = None,
	browser_session: Any | None = None,
) -> None:
	"""Append one native or legacy tool call/result record to the debug run folder."""
	if not is_llm_debug_trace_enabled(logger):
		return

	record = _record_base(event, step=step, session_id=session_id)
	record.update(
		{
			'tool_name': tool_name,
			'tool_call_id': tool_call_id,
			'arguments': arguments or {},
			'browser': _browser_session_handles(browser_session),
		}
	)
	if provider_tool_call is not None:
		record['provider_tool_call'] = _jsonable(provider_tool_call)
	if result is not None:
		record['result'] = _jsonable(result)
	if action_result is not None:
		record['action_result'] = _jsonable(action_result)
	if error is not None:
		record['error'] = _jsonable(error)
	if duration_ms is not None:
		record['duration_ms'] = duration_ms

	await _append_jsonl(tool_trace_path(agent_directory), record)


async def append_step_debug_summary(
	*,
	agent_directory: str | Path,
	logger: logging.Logger | None,
	step: int,
	session_id: str,
	model_output: Any | None,
	results: list[Any],
	metadata: Any | None,
	browser_state_summary: Any | None,
) -> None:
	"""Append timing and result metadata for one completed step."""
	if not is_llm_debug_trace_enabled(logger):
		return

	actions = []
	native_tool_calls = []
	native_tool_results = []
	if model_output is not None:
		actions = [action.model_dump(exclude_none=True, mode='json') for action in getattr(model_output, 'action', [])]
		native_tool_calls = _jsonable(getattr(model_output, 'native_tool_calls', []) or [])
		native_tool_results = _jsonable(getattr(model_output, 'native_tool_results', []) or [])

	errors = [getattr(result, 'error', None) for result in results if getattr(result, 'error', None)]
	record = _record_base('step_summary', step=step, session_id=session_id)
	record.update(
		{
			'metadata': _jsonable(metadata),
			'browser_state': _browser_state_payload(browser_state_summary, None) if browser_state_summary is not None else None,
			'actions': actions,
			'native_tool_calls': native_tool_calls,
			'native_tool_results': native_tool_results,
			'results': _jsonable(results),
			'errors': errors,
			'is_done': any(bool(getattr(result, 'is_done', False)) for result in results),
		}
	)
	await _append_jsonl(step_summary_path(agent_directory), record)


async def write_runtime_events_debug_snapshot(
	*,
	agent_directory: str | Path,
	logger: logging.Logger | None,
	runtime_session: Any | None,
) -> None:
	"""Write the runtime event stream as local JSONL for debugging."""
	if not is_llm_debug_trace_enabled(logger) or runtime_session is None:
		return

	events = getattr(getattr(runtime_session, 'event_stream', None), 'events', []) or []
	path = runtime_events_path(agent_directory)
	path.parent.mkdir(parents=True, exist_ok=True)
	async with await anyio.open_file(path, 'w', encoding='utf-8') as events_file:
		for event in events:
			await events_file.write(json.dumps(_jsonable(event), ensure_ascii=False) + '\n')


async def write_run_debug_summary(
	*,
	agent_directory: str | Path,
	logger: logging.Logger | None,
	session_id: str,
	agent_id: str,
	task_id: str,
	agent_run_error: str | None,
	history: Any | None,
	runtime_session: Any | None,
) -> None:
	"""Write final outcome, usage, costs, and runtime artifacts for the run."""
	if not is_llm_debug_trace_enabled(logger):
		return

	usage = getattr(history, 'usage', None)
	record = _record_base('run_summary', session_id=session_id)
	record.update(
		{
			'agent_id': agent_id,
			'task_id': task_id,
			'agent_run_error': agent_run_error,
			'history_length': len(getattr(history, 'history', []) or []) if history is not None else 0,
			'is_done': history.is_done() if history is not None else False,
			'is_successful': history.is_successful() if history is not None else None,
			'has_errors': history.has_errors() if history is not None else False,
			'final_result': history.final_result() if history is not None else None,
			'total_duration_seconds': history.total_duration_seconds() if history is not None else None,
			'usage': _jsonable(usage),
			'artifacts': _jsonable(getattr(runtime_session, 'artifact_store', None)),
		}
	)
	await _write_json(run_summary_path(agent_directory), record)
	await write_runtime_events_debug_snapshot(
		agent_directory=agent_directory,
		logger=logger,
		runtime_session=runtime_session,
	)


async def write_model_input_snapshot(
	*,
	agent_directory: str | Path,
	logger: logging.Logger | None,
	step: int,
	session_id: str,
	messages: list[BaseMessage],
	typed_context: Any | None = None,
) -> None:
	"""Write per-step model input snapshots in debug mode."""
	if not is_llm_debug_trace_enabled(logger):
		return

	json_path, text_path = model_input_snapshot_paths(agent_directory, step)
	json_path.parent.mkdir(parents=True, exist_ok=True)
	rendered_typed_context = typed_context.render() if typed_context is not None else None
	typed_context_snapshot = (
		typed_context.model_dump(mode='json') if typed_context is not None and hasattr(typed_context, 'model_dump') else None
	)

	record: dict[str, Any] = {
		'schema_version': 1,
		'event': 'model_input_snapshot',
		'timestamp': datetime.now(timezone.utc).isoformat(),
		'step': step,
		'session_id': session_id,
		'messages': [message.model_dump(mode='json') for message in messages],
		'typed_context': typed_context_snapshot,
		'rendered_typed_context': rendered_typed_context,
	}

	async with await anyio.open_file(json_path, 'w', encoding='utf-8') as snapshot_file:
		await snapshot_file.write(json.dumps(record, ensure_ascii=False, indent=2))

	text_parts = [
		f'step={step}',
		f'session_id={session_id}',
		'',
		'# Messages',
		_message_snapshot_text(messages),
	]
	if rendered_typed_context is not None:
		text_parts.extend(['', '# Rendered Typed Context', rendered_typed_context])
	async with await anyio.open_file(text_path, 'w', encoding='utf-8') as snapshot_file:
		await snapshot_file.write('\n'.join(text_parts).rstrip() + '\n')


async def append_llm_debug_trace(
	*,
	agent_directory: str | Path,
	logger: logging.Logger | None,
	event: str,
	step: int,
	session_id: str,
	llm: Any,
	messages: list[BaseMessage] | None = None,
	output_format: type[BaseModel] | None = None,
	native_tools: list[dict[str, Any]] | None = None,
	tools: Any | None = None,
	invoke_kwargs: dict[str, Any] | None = None,
	response: Any | None = None,
	error: BaseException | None = None,
) -> None:
	"""Append one local JSONL record with the exact model boundary data for debugging."""
	if not is_llm_debug_trace_enabled(logger):
		return

	trace_path = llm_debug_trace_path(agent_directory)
	trace_path.parent.mkdir(parents=True, exist_ok=True)

	record: dict[str, Any] = {
		'schema_version': 1,
		'event': event,
		'timestamp': datetime.now(timezone.utc).isoformat(),
		'step': step,
		'session_id': session_id,
		'llm': {
			'provider': getattr(llm, 'provider', None),
			'model': getattr(llm, 'model', None),
			'name': getattr(llm, 'name', None),
		},
	}

	if messages is not None:
		record['messages'] = [message.model_dump(mode='json') for message in messages]

	if output_format is not None:
		record['output_format'] = {
			'name': output_format.__name__,
			'json_schema': _model_json_schema(output_format),
		}

	if native_tools is not None:
		record['native_tools'] = _jsonable(native_tools)

	if tools is not None:
		record['registered_actions'] = _tool_registry_snapshot(tools)

	if invoke_kwargs is not None:
		record['invoke_kwargs'] = _jsonable(invoke_kwargs)

	if response is not None:
		record['response'] = _jsonable(response)

	if error is not None:
		record['error'] = {
			'type': type(error).__name__,
			'message': str(error),
		}

	async with await anyio.open_file(trace_path, 'a', encoding='utf-8') as trace_file:
		await trace_file.write(json.dumps(record, ensure_ascii=False) + '\n')
