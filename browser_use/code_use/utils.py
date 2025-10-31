"""Utility functions for code-use agent."""

import re


def truncate_message_content(content: str, max_length: int = 10000) -> str:
	"""Truncate message content to max_length characters for history."""
	if len(content) <= max_length:
		return content
	# Truncate and add marker
	return content[:max_length] + f'\n\n[... truncated {len(content) - max_length} characters for history]'


def detect_token_limit_issue(
	completion: str,
	completion_tokens: int | None,
	max_tokens: int | None,
	stop_reason: str | None,
) -> tuple[bool, str | None]:
	"""
	Detect if the LLM response hit token limits or is repetitive garbage.

	Returns: (is_problematic, error_message)
	"""
	# Check 1: Stop reason indicates max_tokens
	if stop_reason == 'max_tokens':
		return True, f'Response terminated due to max_tokens limit (stop_reason: {stop_reason})'

	# Check 2: Used 90%+ of max_tokens (if we have both values)
	if completion_tokens is not None and max_tokens is not None and max_tokens > 0:
		usage_ratio = completion_tokens / max_tokens
		if usage_ratio >= 0.9:
			return True, f'Response used {usage_ratio:.1%} of max_tokens ({completion_tokens}/{max_tokens})'

	# Check 3: Last 6 characters repeat 40+ times (repetitive garbage)
	if len(completion) >= 6:
		last_6 = completion[-6:]
		repetition_count = completion.count(last_6)
		if repetition_count >= 40:
			return True, f'Repetitive output detected: last 6 chars "{last_6}" appears {repetition_count} times'

	return False, None


def extract_url_from_task(task: str) -> str | None:
	"""Extract URL from task string using naive pattern matching."""
	# Remove email addresses from task before looking for URLs
	task_without_emails = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '', task)

	# Look for common URL patterns
	patterns = [
		r'https?://[^\s<>"\']+',  # Full URLs with http/https
		r'(?:www\.)?[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*\.[a-zA-Z]{2,}(?:/[^\s<>"\']*)?',  # Domain names with subdomains and optional paths
	]

	found_urls = []
	for pattern in patterns:
		matches = re.finditer(pattern, task_without_emails)
		for match in matches:
			url = match.group(0)

			# Remove trailing punctuation that's not part of URLs
			url = re.sub(r'[.,;:!?()\[\]]+$', '', url)
			# Add https:// if missing
			if not url.startswith(('http://', 'https://')):
				url = 'https://' + url
			found_urls.append(url)

	unique_urls = list(set(found_urls))
	# If multiple URLs found, skip auto-navigation to avoid ambiguity
	if len(unique_urls) > 1:
		return None

	# If exactly one URL found, return it
	if len(unique_urls) == 1:
		return unique_urls[0]

	return None


def extract_code_blocks(text: str) -> dict[str, str]:
	"""Extract all code blocks from markdown response.

	Supports:
	- ```python, ```js, ```javascript, ```bash, ```markdown, ```md
	- Named blocks: ```js variable_name → saved as 'variable_name' in namespace
	- Nested blocks: Use 4+ backticks for outer block when inner content has 3 backticks

	Returns dict mapping block_name -> content

	Note: Python blocks are NO LONGER COMBINED. Each python block executes separately
	to allow sequential execution with JS/bash blocks in between.
	"""
	# Pattern to match code blocks with language identifier and optional variable name
	# Matches: ```lang\n or ```lang varname\n or ````+lang\n (4+ backticks for nested blocks)
	# Uses non-greedy matching and backreferences to match opening/closing backticks
	pattern = r'(`{3,})(\w+)(?:\s+(\w+))?\n(.*?)\1(?:\n|$)'
	matches = re.findall(pattern, text, re.DOTALL)

	blocks: dict[str, str] = {}
	python_block_counter = 0

	for backticks, lang, var_name, content in matches:
		lang = lang.lower()

		# Normalize language names
		if lang in ('javascript', 'js'):
			lang_normalized = 'js'
		elif lang in ('markdown', 'md'):
			lang_normalized = 'markdown'
		elif lang in ('sh', 'shell'):
			lang_normalized = 'bash'
		elif lang == 'python':
			lang_normalized = 'python'
		else:
			# Unknown language, skip
			continue

		# Only process supported types
		if lang_normalized in ('python', 'js', 'bash', 'markdown'):
			content = content.rstrip()  # Only strip trailing whitespace, preserve leading for indentation
			if content:
				# Determine the key to use
				if var_name:
					# Named block - use the variable name
					block_key = var_name
					blocks[block_key] = content
				elif lang_normalized == 'python':
					# Unnamed Python blocks - give each a unique key to preserve order
					block_key = f'python_{python_block_counter}'
					blocks[block_key] = content
					python_block_counter += 1
				else:
					# Other unnamed blocks (js, bash, markdown) - keep last one only
					blocks[lang_normalized] = content

	# If we have multiple python blocks, mark the first one as 'python' for backward compat
	if python_block_counter > 0:
		blocks['python'] = blocks['python_0']

	# Fallback: if no python block but there's generic ``` block, treat as python
	if python_block_counter == 0 and 'python' not in blocks:
		generic_pattern = r'```\n(.*?)```'
		generic_matches = re.findall(generic_pattern, text, re.DOTALL)
		if generic_matches:
			combined = '\n\n'.join(m.strip() for m in generic_matches if m.strip())
			if combined:
				blocks['python'] = combined

	return blocks
