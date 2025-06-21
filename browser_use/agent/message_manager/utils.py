from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import anyio

from browser_use.llm.messages import BaseMessage

logger = logging.getLogger(__name__)

MODELS_WITHOUT_TOOL_SUPPORT_PATTERNS = [
	'deepseek-reasoner',
	'deepseek-r1',
	'.*gemma.*-it',
]


def is_model_without_tool_support(model_name: str) -> bool:
	return any(re.match(pattern, model_name) for pattern in MODELS_WITHOUT_TOOL_SUPPORT_PATTERNS)


def _fix_control_characters_in_json(content: str) -> str:
	"""Fix control characters in JSON string values to make them valid JSON."""
	try:
		# First try to parse as-is to see if it's already valid
		json.loads(content)
		return content
	except json.JSONDecodeError:
		pass

	# More sophisticated approach: only escape control characters inside string values
	# while preserving JSON structure formatting

	result = []
	i = 0
	in_string = False
	escaped = False

	while i < len(content):
		char = content[i]

		if not in_string:
			# Outside of string - check if we're entering a string
			if char == '"':
				in_string = True
			result.append(char)
		else:
			# Inside string - handle escaping and control characters
			if escaped:
				# Previous character was backslash, so this character is escaped
				result.append(char)
				escaped = False
			elif char == '\\':
				# This is an escape character
				result.append(char)
				escaped = True
			elif char == '"':
				# End of string
				result.append(char)
				in_string = False
			elif char == '\n':
				# Literal newline inside string - escape it
				result.append('\\n')
			elif char == '\r':
				# Literal carriage return inside string - escape it
				result.append('\\r')
			elif char == '\t':
				# Literal tab inside string - escape it
				result.append('\\t')
			elif char == '\b':
				# Literal backspace inside string - escape it
				result.append('\\b')
			elif char == '\f':
				# Literal form feed inside string - escape it
				result.append('\\f')
			elif ord(char) < 32:
				# Other control characters inside string - convert to unicode escape
				result.append(f'\\u{ord(char):04x}')
			else:
				# Normal character inside string
				result.append(char)

		i += 1

	return ''.join(result)


async def save_conversation(
	input_messages: list[BaseMessage], response: Any, target: str | Path, encoding: str | None = None
) -> None:
	"""Save conversation history to file asynchronously."""
	target_path = Path(target)

	# create folders if not exists
	if target_path.parent:
		await anyio.Path(target_path.parent).mkdir(parents=True, exist_ok=True)

	await anyio.Path(target_path).write_text(await _format_conversation(input_messages, response), encoding=encoding or 'utf-8')


async def _format_conversation(messages: list[BaseMessage], response: Any) -> str:
	"""Format the conversation including messages and response."""
	lines = []

	# Format messages
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

	# Format response
	lines.append(' RESPONSE')
	lines.append(json.dumps(json.loads(response.model_dump_json(exclude_unset=True)), indent=2))

	return '\n'.join(lines)


# Note: _write_messages_to_file and _write_response_to_file have been merged into _format_conversation
# This is more efficient for async operations and reduces file I/O
