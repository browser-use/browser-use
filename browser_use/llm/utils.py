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
	if cleaned.startswith('```json') and cleaned.endswith('```'):
		cleaned = cleaned[7:-3].strip()
	elif cleaned.startswith('```') and cleaned.endswith('```'):
		cleaned = cleaned[3:-3].strip()

	return cleaned, thinking
