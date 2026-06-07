"""Utilities for LLM response processing and sanitization."""

import re


def clean_and_extract_json(content: str) -> tuple[str, str | None]:
	"""
	Clean the response content and extract thinking block and JSON string.

	Returns:
		tuple[str, str | None]: (cleaned_json_content, thinking_text)
	"""
	thinking = None
	# 1. Extract and remove <think>...</think> tags and contents
	think_match = re.search(r'<think>(.*?)</think>', content, re.DOTALL)
	if think_match:
		thinking = think_match.group(1).strip()

	cleaned = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL)
	cleaned = re.sub(r'.*?</think>', '', cleaned, flags=re.DOTALL)
	cleaned = cleaned.strip()

	# 2. Strip markdown code blocks (e.g. ```json ... ``` or ``` ... ```)
	# Prefer explicitly-labelled ```json blocks; only fall back to a plain ```
	# block when no json-labelled fence is present. This avoids selecting the
	# wrong block when multiple fenced sections exist in the response.
	fence_match = re.search(r'```json\s*\n?([\s\S]*?)\n?```', cleaned)
	if not fence_match:
		fence_match = re.search(r'```\s*\n?([\s\S]*?)\n?```', cleaned)
	if fence_match:
		cleaned = fence_match.group(1).strip()

	return cleaned, thinking
