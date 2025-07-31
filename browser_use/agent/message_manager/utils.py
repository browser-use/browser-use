from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import anyio

from browser_use.llm.messages import BaseMessage

logger = logging.getLogger(__name__)


# Original save_conversation function (deprecated)
# async def save_conversation(
# 	input_messages: list[BaseMessage], response: Any, target: str | Path, encoding: str | None = None
# ) -> None:
# 	"""Save conversation history to file asynchronously."""
# 	target_path = Path(target)
#
# 	# create folders if not exists
# 	if target_path.parent:
# 		await anyio.Path(target_path.parent).mkdir(parents=True, exist_ok=True)
#
# 	await anyio.Path(target_path).write_text(await _format_conversation(input_messages, response), encoding=encoding or 'utf-8')

async def save_conversation(
	input_messages: list[BaseMessage],
	response: Any,
	target: str | Path,
	encoding: str | None = None,
	raw_response: Any = None, tool_calling_method: str | None = None, available_tools: str | None = None
) -> None:
	"""Save conversation history to file asynchronously, including raw LLM response and tools."""
	target_path = Path(target)
	# create folders if not exists
	if target_path.parent:
		await anyio.Path(target_path.parent).mkdir(parents=True, exist_ok=True)

	await anyio.Path(target_path).write_text(
		await _format_conversation_full(input_messages, response, raw_response, tool_calling_method, available_tools),
		encoding=encoding or 'utf-8'
	)


async def _format_conversation(messages: list[BaseMessage], response: Any) -> str:
	"""Original format method for backward compatibility."""
	lines = []

	# Format messages
	for message in messages:
		lines.append(f' {message.role} ')

		lines.append(message.text)
		lines.append('')  # Empty line after each message

	# Format response
	lines.append(' RESPONSE')
	lines.append(json.dumps(json.loads(response.model_dump_json(exclude_unset=True)), indent=2))

	return '\n'.join(lines)


async def _format_conversation_full(messages: list[BaseMessage], response: Any, raw_response: Any = None,
                              tool_calling_method: str | None = None, available_tools: str | None = None) -> str:
	"""Format the conversation including messages, response, raw LLM output and tools."""
	lines = []

	# Add available tools/actions if provided (this was missing in original)
	if available_tools:
		lines.append(' AVAILABLE TOOLS/ACTIONS ')
		lines.append(available_tools)
		lines.append('')

	# Format messages (same as original)
	for message in messages:
		lines.append(f' {message.__class__.__name__} ')

		if isinstance(message.content, list):
			for item in message.content:
				if isinstance(item, dict) and item.get('type') == 'text':
					lines.append(item['text'].strip())
		elif isinstance(message.content, str):
			try:
				content = json.loads(message.content)
				lines.append(json.dumps(content, indent=2))
			except json.JSONDecodeError:
				lines.append(message.content.strip())

		lines.append('')  # Empty line after each message

	# Add raw LLM output if provided
	if raw_response is not None:
		lines.append(' RAW LLM OUTPUT ')
		if isinstance(raw_response, dict):
			# Function calling mode: format the structured response
			if 'tool_calls' in raw_response:
				lines.append(f"Content: {raw_response.get('content', '')}")
				lines.append(f"Tool Calls: {json.dumps(raw_response.get('tool_calls', []), indent=2, ensure_ascii=False)}")
				if raw_response.get('additional_kwargs'):
					lines.append(f"Additional Info: {json.dumps(raw_response.get('additional_kwargs', {}), indent=2, ensure_ascii=False)}")
				if raw_response.get('response_metadata'):
					lines.append(f"Metadata: {json.dumps(raw_response.get('response_metadata', {}), indent=2, ensure_ascii=False)}")
			else:
				lines.append(json.dumps(raw_response, indent=2, ensure_ascii=False))
		elif hasattr(raw_response, 'content'):
			lines.append(str(raw_response.content))
		else:
			lines.append(str(raw_response))
		lines.append('')

	# Format parsed response (same as original)
	lines.append(' RESPONSE')
	lines.append(json.dumps(json.loads(response.model_dump_json(exclude_unset=True)), indent=2))

	return '\n'.join(lines)


# Note: _write_messages_to_file and _write_response_to_file have been merged into _format_conversation
# This is more efficient for async operations and reduces file I/O
