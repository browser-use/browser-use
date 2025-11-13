"""Utilities for sanitizing sensitive data from logs and error messages."""

import re
from typing import Any


def sanitize_api_key(value: str | None, show_chars: int = 3) -> str:
	"""
	Sanitize an API key by showing only the first few characters.
	
	Args:
		value: The API key to sanitize
		show_chars: Number of characters to show from the start (default: 3)
	
	Returns:
		Sanitized string like 'csk-c9m…' or '<not set>' if None
	"""
	if value is None:
		return '<not set>'
	if not isinstance(value, str):
		return '<invalid>'
	if len(value) <= show_chars:
		return '***'
	return f'{value[:show_chars]}…'


def sanitize_dict(data: dict[str, Any], sensitive_keys: set[str] | None = None) -> dict[str, Any]:
	"""
	Recursively sanitize a dictionary by masking sensitive keys.
	
	Args:
		data: Dictionary to sanitize
		sensitive_keys: Set of key names to sanitize (default: api_key, auth_token, password, secret)
	
	Returns:
		New dictionary with sensitive values masked
	"""
	if sensitive_keys is None:
		sensitive_keys = {'api_key', 'auth_token', 'password', 'secret', 'token', 'authorization'}
	
	result = {}
	for key, value in data.items():
		key_lower = key.lower()
		
		# Check if key matches any sensitive pattern
		is_sensitive = any(sensitive in key_lower for sensitive in sensitive_keys)
		
		if is_sensitive:
			result[key] = sanitize_api_key(value) if isinstance(value, str) else '<redacted>'
		elif isinstance(value, dict):
			result[key] = sanitize_dict(value, sensitive_keys)
		elif isinstance(value, list):
			result[key] = [sanitize_dict(item, sensitive_keys) if isinstance(item, dict) else item for item in value]
		else:
			result[key] = value
	
	return result


def sanitize_string(text: str, patterns: list[str] | None = None) -> str:
	"""
	Sanitize a string by replacing API key patterns with masked versions.
	
	Args:
		text: Text to sanitize
		patterns: List of regex patterns to match API keys (default: common API key formats)
	
	Returns:
		Sanitized text with API keys masked
	"""
	if patterns is None:
		# Common API key patterns
		patterns = [
			# OpenAI style: sk-... or sk-proj-...
			r'sk-[a-zA-Z0-9_-]{20,}',
			# Anthropic style: sk-ant-...
			r'sk-ant-[a-zA-Z0-9_-]{20,}',
			# Google API keys (alphanumeric, 39+ chars)
			r'AIza[a-zA-Z0-9_-]{35,}',
			# Generic API keys (key=value patterns)
			r'(?i)(api[_-]?key|apikey|auth[_-]?token|token)["\']?\s*[:=]\s*["\']?([a-zA-Z0-9_-]{20,})',
			# Cerebras/OpenRouter style: csk-..., or-...
			r'csk-[a-zA-Z0-9_-]{20,}',
			r'or-[a-zA-Z0-9_-]{20,}',
			# AWS style
			r'AKIA[a-zA-Z0-9]{16,}',
			# Browser Use API keys
			r'bu-[a-zA-Z0-9_-]{20,}',
		]
	
	sanitized = text
	for pattern in patterns:
		# Find all matches
		matches = re.finditer(pattern, sanitized)
		for match in matches:
			matched_text = match.group(0)
			# If this is a key=value match, only mask the value part
			if match.lastindex and match.lastindex >= 2:
				key_part = match.group(1)
				value_part = match.group(2)
				masked_value = sanitize_api_key(value_part)
				replacement = f'{key_part}={masked_value}'
			else:
				replacement = sanitize_api_key(matched_text)
			
			sanitized = sanitized.replace(matched_text, replacement)
	
	return sanitized


def sanitize_exception_message(exc: Exception) -> str:
	"""
	Sanitize an exception message by removing sensitive data.
	
	Args:
		exc: Exception to sanitize
	
	Returns:
		Sanitized exception message
	"""
	message = str(exc)
	return sanitize_string(message)
