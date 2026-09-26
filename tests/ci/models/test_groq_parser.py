"""Regression tests for Groq failed-generation JSON recovery."""

import httpx
import pytest
from groq import APIStatusError
from pydantic import BaseModel

from browser_use.llm.groq.parser import try_parse_groq_failed_generation


class Action(BaseModel):
	selector: str


class Name(BaseModel):
	first: str
	last: str


class Nested(BaseModel):
	name: Name


def _failed_generation_error(content: str) -> APIStatusError:
	return APIStatusError(
		'Invalid',
		response=httpx.Response(400, request=httpx.Request('POST', 'https://api.groq.com/openai/v1/chat/completions')),
		body={'error': {'failed_generation': content}},
	)


def test_string_aware_brace_recovery():
	"""A '}' inside a JSON string value (CSS attribute selector) must not break balance recovery."""
	content = '{"selector": "div[class*=\'}\']"} The first matching element will be clicked.'
	result = try_parse_groq_failed_generation(_failed_generation_error(content), Action)
	assert result.selector == "div[class*='}']"


def test_trailing_commentary_not_ending_with_brace():
	"""Trailing text that doesn't end with '}' previously skipped the recovery path entirely."""
	content = '{"selector": "div.item"} The first matching element will be clicked.'
	result = try_parse_groq_failed_generation(_failed_generation_error(content), Action)
	assert result.selector == 'div.item'


def test_nested_json_with_trailing_text():
	content = '{"name": {"first": "Ada", "last": "Lovelace"}} Some trailing commentary.'
	result = try_parse_groq_failed_generation(_failed_generation_error(content), Nested)
	assert result.name.first == 'Ada'


def test_trailing_braces_garbage():
	content = '{"selector": "div.item"}}} extra garbage'
	result = try_parse_groq_failed_generation(_failed_generation_error(content), Action)
	assert result.selector == 'div.item'


def test_pure_json_unchanged():
	result = try_parse_groq_failed_generation(_failed_generation_error('{"selector": "div.item"}'), Action)
	assert result.selector == 'div.item'


def test_code_block_wrapped_json():
	content = '```json\n{"selector": "div.item"}\n```'
	result = try_parse_groq_failed_generation(_failed_generation_error(content), Action)
	assert result.selector == 'div.item'


def test_html_like_tags_stripped():
	content = "<|header_start|>assistant<|header_end|>{'selector': 'div.item'}".replace("'", '"')
	result = try_parse_groq_failed_generation(_failed_generation_error(content), Action)
	assert result.selector == 'div.item'


def test_single_element_list_flattened():
	content = '[{"selector": "div.item"}] trailing note'
	result = try_parse_groq_failed_generation(_failed_generation_error(content), Action)
	assert result.selector == 'div.item'


def test_no_json_raises():
	with pytest.raises(ValueError, match='Could not parse response'):
		try_parse_groq_failed_generation(_failed_generation_error('I am not JSON at all'), Action)
