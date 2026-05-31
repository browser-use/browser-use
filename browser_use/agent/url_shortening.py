import hashlib
import re

from pydantic import BaseModel

from browser_use.llm.messages import AssistantMessage, BaseMessage, ContentPartTextParam, UserMessage
from browser_use.utils import URL_PATTERN


def replace_urls_in_text(text: str, shortening_limit: int) -> tuple[str, dict[str, str]]:
	"""Replace long URL query/fragment suffixes with stable short forms."""
	replaced_urls: dict[str, str] = {}

	def replace_url(match: re.Match) -> str:
		original_url = match.group(0)
		query_start = original_url.find('?')
		fragment_start = original_url.find('#')

		after_path_start = len(original_url)
		if query_start != -1:
			after_path_start = min(after_path_start, query_start)
		if fragment_start != -1:
			after_path_start = min(after_path_start, fragment_start)

		base_url = original_url[:after_path_start]
		after_path = original_url[after_path_start:]

		if len(after_path) <= shortening_limit:
			return original_url

		if after_path:
			truncated_after_path = after_path[:shortening_limit]
			short_hash = hashlib.md5(after_path.encode('utf-8')).hexdigest()[:7]
			shortened = f'{base_url}{truncated_after_path}...{short_hash}'
			if len(shortened) < len(original_url):
				replaced_urls[shortened] = original_url
				return shortened

		return original_url

	return URL_PATTERN.sub(replace_url, text), replaced_urls


def process_messages_and_replace_long_urls(input_messages: list[BaseMessage], shortening_limit: int) -> dict[str, str]:
	"""Shorten long URLs inside user/assistant messages in place."""
	urls_replaced: dict[str, str] = {}

	for message in input_messages:
		if isinstance(message, (UserMessage, AssistantMessage)):
			if isinstance(message.content, str):
				message.content, replaced_urls = replace_urls_in_text(message.content, shortening_limit)
				urls_replaced.update(replaced_urls)
			elif isinstance(message.content, list):
				for part in message.content:
					if isinstance(part, ContentPartTextParam):
						part.text, replaced_urls = replace_urls_in_text(part.text, shortening_limit)
						urls_replaced.update(replaced_urls)

	return urls_replaced


def restore_shortened_urls_in_model(model: BaseModel, url_replacements: dict[str, str]) -> None:
	"""Restore original URLs throughout a Pydantic model in place."""
	for field_name, field_value in model.__dict__.items():
		if isinstance(field_value, str):
			setattr(model, field_name, replace_shortened_urls_in_string(field_value, url_replacements))
		elif isinstance(field_value, BaseModel):
			restore_shortened_urls_in_model(field_value, url_replacements)
		elif isinstance(field_value, dict):
			restore_shortened_urls_in_dict(field_value, url_replacements)
		elif isinstance(field_value, (list, tuple)):
			setattr(model, field_name, restore_shortened_urls_in_sequence(field_value, url_replacements))


def restore_shortened_urls_in_dict(dictionary: dict, url_replacements: dict[str, str]) -> None:
	"""Restore original URLs throughout dictionary values in place."""
	for key, value in dictionary.items():
		if isinstance(value, str):
			dictionary[key] = replace_shortened_urls_in_string(value, url_replacements)
		elif isinstance(value, BaseModel):
			restore_shortened_urls_in_model(value, url_replacements)
		elif isinstance(value, dict):
			restore_shortened_urls_in_dict(value, url_replacements)
		elif isinstance(value, (list, tuple)):
			dictionary[key] = restore_shortened_urls_in_sequence(value, url_replacements)


def restore_shortened_urls_in_sequence(container: list | tuple, url_replacements: dict[str, str]) -> list | tuple:
	"""Restore original URLs throughout list/tuple items."""
	if isinstance(container, tuple):
		processed_items = []
		for item in container:
			processed_items.append(_restore_shortened_urls_in_value(item, url_replacements))
		return tuple(processed_items)

	for index, item in enumerate(container):
		container[index] = _restore_shortened_urls_in_value(item, url_replacements)
	return container


def _restore_shortened_urls_in_value(value, url_replacements: dict[str, str]):
	if isinstance(value, str):
		return replace_shortened_urls_in_string(value, url_replacements)
	if isinstance(value, BaseModel):
		restore_shortened_urls_in_model(value, url_replacements)
		return value
	if isinstance(value, dict):
		restore_shortened_urls_in_dict(value, url_replacements)
		return value
	if isinstance(value, (list, tuple)):
		return restore_shortened_urls_in_sequence(value, url_replacements)
	return value


def replace_shortened_urls_in_string(text: str, url_replacements: dict[str, str]) -> str:
	"""Replace all shortened URLs in a string with their original URLs."""
	result = text
	for shortened_url, original_url in url_replacements.items():
		result = result.replace(shortened_url, original_url)
	return result
