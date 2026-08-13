from __future__ import annotations

import re

THINK_PATTERN = re.compile(r'<think>(.*?)</think>', re.DOTALL)
OPEN_THINK_PATTERN = re.compile(r'<think>(.*)', re.DOTALL)
JSON_FENCE_PATTERN = re.compile(r'```json\s*(.*?)\s*```', re.DOTALL)
GENERIC_FENCE_PATTERN = re.compile(r'```\s*(.*?)\s*```', re.DOTALL)


def clean_and_extract_json(content: str) -> tuple[str, str | None]:
	"""
	Extract <think> tags (including unclosed tags) and sanitize markdown JSON code blocks.
	Returns a tuple of (cleaned_json_content, thinking_content_or_none).
	"""
	if not content or not isinstance(content, str):
		return content or '', None

	thinking: str | None = None

	# 1. Extract <think> tags
	match = THINK_PATTERN.search(content)
	if match:
		thinking = match.group(1).strip()
		content = THINK_PATTERN.sub('', content).strip()
	else:
		# Fallback for unclosed <think> tags (e.g. truncated by max_tokens)
		open_match = OPEN_THINK_PATTERN.search(content)
		if open_match:
			thinking = open_match.group(1).strip()
			content = content[: open_match.start()].strip()

	# Strip isolated stray closing tags
	content = re.sub(r'</think>', '', content).strip()

	# 2. Extract JSON code block (preferring ```json over generic ```)
	json_match = JSON_FENCE_PATTERN.search(content)
	if json_match:
		content = json_match.group(1).strip()
	else:
		generic_match = GENERIC_FENCE_PATTERN.search(content)
		if generic_match:
			content = generic_match.group(1).strip()

	return content, thinking
