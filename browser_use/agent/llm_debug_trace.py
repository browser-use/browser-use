from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import anyio
from pydantic import BaseModel

from browser_use.config import CONFIG
from browser_use.llm.messages import BaseMessage

LLM_DEBUG_TRACE_FILENAME = 'llm_trace.jsonl'
MODEL_INPUT_SNAPSHOTS_DIRNAME = 'model_inputs'


def is_llm_debug_trace_enabled(logger: logging.Logger | None = None) -> bool:
	"""Return whether local LLM traces should be written for the current process."""
	if CONFIG.BROWSER_USE_LOGGING_LEVEL == 'debug':
		return True

	return logger.isEnabledFor(logging.DEBUG) if logger is not None else False


def llm_debug_trace_path(agent_directory: str | Path) -> Path:
	return Path(agent_directory) / LLM_DEBUG_TRACE_FILENAME


def model_input_snapshot_paths(agent_directory: str | Path, step: int) -> tuple[Path, Path]:
	output_dir = Path(agent_directory) / MODEL_INPUT_SNAPSHOTS_DIRNAME
	stem = f'step_{step:04d}'
	return output_dir / f'{stem}.json', output_dir / f'{stem}.txt'


def _jsonable(value: Any) -> Any:
	if isinstance(value, type) and issubclass(value, BaseModel):
		return {
			'name': value.__name__,
			'json_schema': _model_json_schema(value),
		}

	if isinstance(value, BaseModel):
		return value.model_dump(mode='json')

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
