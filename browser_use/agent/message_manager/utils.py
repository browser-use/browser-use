from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import anyio

from browser_use.llm.messages import BaseMessage

logger = logging.getLogger(__name__)

_NAVIGATOR_FOCUS_OPEN = '<current_step_focus>'
_NAVIGATOR_FOCUS_CLOSE = '</current_step_focus>'


def extract_navigator_step_focus(text: str, *, max_inner_chars: int = 800) -> tuple[str | None, str]:
	"""Parse optional navigator ``<current_step_focus>`` block; return (inner_text_or_None, text_with_block_removed).

	Used so the executor can show a short sub-goal at the top of ``<agent_state>`` without duplicating the block
	in the long navigator plan / guidance message.
	"""
	if not text:
		return None, text
	i = text.find(_NAVIGATOR_FOCUS_OPEN)
	if i < 0:
		return None, text
	j = text.find(_NAVIGATOR_FOCUS_CLOSE, i + len(_NAVIGATOR_FOCUS_OPEN))
	if j < 0:
		return None, text
	raw = text[i + len(_NAVIGATOR_FOCUS_OPEN) : j].strip()
	if not raw:
		cleaned = (text[:i].rstrip() + '\n\n' + text[j + len(_NAVIGATOR_FOCUS_CLOSE) :].lstrip()).strip()
		return None, cleaned
	inner = raw[:max_inner_chars] + ('…' if len(raw) > max_inner_chars else '')
	left = text[:i].rstrip()
	right = text[j + len(_NAVIGATOR_FOCUS_CLOSE) :].lstrip()
	cleaned = (left + ('\n\n' if left and right else '') + right).strip()
	return inner, cleaned


async def save_conversation(
	input_messages: list[BaseMessage],
	response: Any,
	target: str | Path,
	encoding: str | None = None,
) -> None:
	"""Save conversation history to file asynchronously."""
	target_path = Path(target)
	# create folders if not exists
	if target_path.parent:
		await anyio.Path(target_path.parent).mkdir(parents=True, exist_ok=True)

	await anyio.Path(target_path).write_text(
		await _format_conversation(input_messages, response),
		encoding=encoding or 'utf-8',
	)


async def _format_conversation(messages: list[BaseMessage], response: Any) -> str:
	"""Format the conversation including messages and response."""
	lines = []

	# Format messages
	for message in messages:
		lines.append(f' {message.role} ')

		lines.append(message.text)
		lines.append('')  # Empty line after each message

	# Format response
	lines.append(json.dumps(json.loads(response.model_dump_json(exclude_unset=True)), indent=2, ensure_ascii=False))

	return '\n'.join(lines)


def _format_messages_for_trace(messages: list[BaseMessage]) -> str:
	lines: list[str] = []
	for message in messages:
		lines.append(f'--- {message.role} ---')
		lines.append(message.text)
		lines.append('')
	return '\n'.join(lines)


def _format_action_results_summary(results: list[Any]) -> str:
	lines: list[str] = []
	for i, r in enumerate(results):
		lines.append(f'--- action_result[{i}] ---')
		if r is None:
			lines.append('<None>')
			lines.append('')
			continue
		err = getattr(r, 'error', None)
		if err:
			lines.append(f'error: {err}')
		extracted = getattr(r, 'extracted_content', None)
		if extracted:
			text = str(extracted)
			lines.append(f'extracted_content: {text[:4000]}{"…" if len(text) > 4000 else ""}')
		if getattr(r, 'is_done', False):
			lines.append(f'is_done=True success={getattr(r, "success", None)}')
		lines.append('')
	return '\n'.join(lines)


async def save_step_trace(
	target: str | Path,
	*,
	step_index: int,
	agent_id: str,
	llm_model: str | None,
	page_url: str | None,
	page_title: str | None,
	input_messages: list[BaseMessage] | None,
	model_output: Any | None,
	action_results: list[Any] | None,
	status_note: str | None = None,
	encoding: str = 'utf-8',
) -> None:
	"""Write one human-readable file per agent step (including timeouts before LLM returns).

	Uses ``step_index`` captured at step entry (same as ``Agent.state.n_steps`` when ``step()`` begins)
	so filenames align with ``📍 Step N`` even when ``conversation_*_{n}.txt`` is skipped.
	"""
	target_path = Path(target)
	if target_path.parent:
		await anyio.Path(target_path.parent).mkdir(parents=True, exist_ok=True)

	header: list[str] = [
		f'step_index={step_index}',
		f'agent_id={agent_id}',
		f'llm_model={llm_model or "?"}',
		f'page_url={page_url or "<none>"}',
		f'page_title={(page_title or "<none>")[:500]}',
	]
	if status_note:
		header.append(f'status_note: {status_note}')
	header.append('')
	header.append('=== Messages snapshot (taken when entering LLM for this step) ===')
	if input_messages:
		header.append(_format_messages_for_trace(input_messages))
	else:
		header.append('<none — timed out or failed before _get_next_action, or no messages>')
	header.append('')
	header.append('=== Model output (if any) ===')
	if model_output is not None:
		try:
			header.append(
				json.dumps(json.loads(model_output.model_dump_json(exclude_unset=True)), indent=2, ensure_ascii=False)
			)
		except Exception as e:
			header.append(f'<serialization failed: {e}>')
	else:
		header.append('<none>')
	header.append('')
	header.append('=== Action results (if any) ===')
	if action_results:
		header.append(_format_action_results_summary(action_results))
	else:
		header.append('<none>')

	await anyio.Path(target_path).write_text('\n'.join(header), encoding=encoding)


# Note: _write_messages_to_file and _write_response_to_file have been merged into _format_conversation
# This is more efficient for async operations and reduces file I/O
