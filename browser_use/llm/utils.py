from __future__ import annotations

import json
import re

THINK_PATTERN = re.compile(r'<think>(.*?)</think>', re.DOTALL)
OPEN_THINK_PATTERN = re.compile(r'<think>(.*)', re.DOTALL)
JSON_FENCE_PATTERN = re.compile(r'^\s*```[ \t]*(?:json)?[ \t]*(.*?)\s*```\s*$', re.DOTALL | re.IGNORECASE)


def clean_and_extract_json(content: str, strip_fences: bool = True) -> tuple[str, str | None]:
	"""Extract <think> tags (including multiple or unclosed tags) and sanitize markdown JSON code blocks.

	Args:
		content: The raw text completion or tool call argument from the LLM.
		strip_fences: If True, strips markdown code fences when parsing structured JSON.
					If False, preserves markdown fences (used for plain text completions).

	Returns:
		A tuple of (cleaned_content, thinking_content_or_none).
	"""
	if not content or not isinstance(content, str):
		return content or '', None

	thinking_parts: list[str] = []

	# 1. Extract all closed <think>...</think> blocks first
	for match in THINK_PATTERN.finditer(content):
		thinking_parts.append(match.group(1).strip())
	content = THINK_PATTERN.sub('', content).strip()

	# 2. Extract any remaining unclosed <think>... block (e.g. truncated by max_tokens)
	open_match = OPEN_THINK_PATTERN.search(content)
	if open_match:
		thinking_parts.append(open_match.group(1).strip())
		content = content[: open_match.start()].strip()

	# Strip isolated stray closing tags
	content = re.sub(r'</think>', '', content).strip()

	thinking = '\n\n'.join(p for p in thinking_parts if p) if thinking_parts else None

	# 3. Handle markdown code fences ONLY when strip_fences=True
	if strip_fences:
		# If content is already valid JSON, do not modify inner fenced strings
		try:
			json.loads(content)
		except Exception:
			# Only strip fences if they wrap the WHOLE response
			fence_match = JSON_FENCE_PATTERN.match(content)
			if fence_match:
				content = fence_match.group(1).strip()
			elif content.startswith('```') and content.endswith('```'):
				lines = content.splitlines()
				if len(lines) >= 2:
					content = '\n'.join(lines[1:-1]).strip()

	return content, thinking
