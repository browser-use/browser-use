from __future__ import annotations

import logging

from browser_use.llm.messages import BaseMessage, ContentPartTextParam
from browser_use.utils import collect_sensitive_data_values, match_url_with_domain_pattern, redact_sensitive_string

logger = logging.getLogger(__name__)

SensitiveData = dict[str, str | dict[str, str]]


def get_sensitive_data_description(sensitive_data: SensitiveData | None, current_page_url: str | None) -> str:
	if not sensitive_data:
		return ''

	placeholders: set[str] = set()
	for key, value in sensitive_data.items():
		if isinstance(value, dict):
			if current_page_url and match_url_with_domain_pattern(current_page_url, key, True):
				placeholders.update(value.keys())
		else:
			placeholders.add(key)

	if not placeholders:
		return ''

	placeholder_list = sorted(list(placeholders))
	formatted_placeholders = '\n'.join(f'  - {p}' for p in placeholder_list)

	info = 'SENSITIVE DATA - Use these placeholders for secure input:\n'
	info += f'{formatted_placeholders}\n\n'
	info += 'IMPORTANT: When entering sensitive values, you MUST wrap the placeholder name in <secret> tags.\n'
	info += f'Example: To enter the value for "{placeholder_list[0]}", use: <secret>{placeholder_list[0]}</secret>\n'
	info += 'The system will automatically replace these tags with the actual secret values.'
	return info


def filter_sensitive_data_message(message: BaseMessage, sensitive_data: SensitiveData | None) -> BaseMessage:
	if isinstance(message.content, str):
		message.content = redact_sensitive_text(message.content, sensitive_data)
	elif isinstance(message.content, list):
		for i, item in enumerate(message.content):
			if isinstance(item, ContentPartTextParam):
				item.text = redact_sensitive_text(item.text, sensitive_data)
				message.content[i] = item
	return message


def redact_sensitive_text(value: str, sensitive_data: SensitiveData | None) -> str:
	if not sensitive_data:
		return value

	sensitive_values = collect_sensitive_data_values(sensitive_data)
	if not sensitive_values:
		logger.warning('No valid entries found in sensitive_data dictionary')
		return value

	return redact_sensitive_string(value, sensitive_values)
