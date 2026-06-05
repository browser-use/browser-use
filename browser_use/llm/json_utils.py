"""Shared JSON parsing utilities for LLM providers."""

from __future__ import annotations

import json
import logging
from typing import TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar('T', bound=BaseModel)

logger = logging.getLogger(__name__)


def _extract_first_json_object(text: str) -> str | None:
	"""Extract the first complete JSON object from text that may contain trailing garbage.

	Some reasoning models (GPT-5, o-series, DeepSeek-R1, etc.) return valid
	JSON followed by extraneous trailing bracket characters (e.g. ']}}]').
	This helper walks the string character-by-character with a bracket stack,
	and returns just the first complete JSON object or array.

	Returns ``None`` if no balanced JSON object is found.
	"""
	start = None
	for i, ch in enumerate(text):
		if ch in ('{', '['):
			start = i
			break
	if start is None:
		return None

	stack: list[str] = []
	in_string = False
	escaped = False

	for i in range(start, len(text)):
		ch = text[i]

		if escaped:
			escaped = False
			continue

		if ch == '\\' and in_string:
			escaped = True
			continue

		if ch == '"' and not escaped:
			in_string = not in_string
			continue

		if in_string:
			continue

		if ch in ('{', '['):
			stack.append(ch)
		elif ch == '}':
			if stack and stack[-1] == '{':
				stack.pop()
				if not stack:
					return text[start : i + 1]
		elif ch == ']':
			if stack and stack[-1] == '[':
				stack.pop()
				if not stack:
					return text[start : i + 1]

	return None


def safe_validate_json(output_format: type[T], content: str) -> T:
	"""Validate *content* as JSON against *output_format*, with trailing-garbage recovery.

	Tries ``output_format.model_validate_json(content)`` first.  If that
	fails because the JSON is malformed (e.g. trailing bracket characters
	from reasoning models), attempts to extract the first balanced JSON
	object and re-validate.  Raises the original error if recovery also
	fails.
	"""
	try:
		return output_format.model_validate_json(content)
	except (json.JSONDecodeError, ValidationError) as err:
		# Only attempt recovery for JSON syntax errors, not schema mismatches
		if isinstance(err, ValidationError) and not _is_json_syntax_error(err):
			raise
		extracted = _extract_first_json_object(content)
		if extracted is not None and extracted != content:
			logger.debug('Recovered JSON by stripping trailing garbage (%d → %d chars)', len(content), len(extracted))
			return output_format.model_validate_json(extracted)
		raise


def _is_json_syntax_error(err: ValidationError) -> bool:
	"""Return True if the ValidationError is about invalid JSON syntax (not schema)."""
	for e in err.errors():
		if e.get('type') == 'json_invalid':
			return True
	return False
