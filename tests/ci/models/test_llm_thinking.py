"""Tests for thinking tags extraction and markdown code block cleaning."""

from browser_use.llm.utils import clean_and_extract_json


def test_clean_and_extract_json_plain():
	"""Test with normal JSON string without thinking tags or code blocks."""
	content = '{"action": "test"}'
	cleaned, thinking = clean_and_extract_json(content)
	assert cleaned == '{"action": "test"}'
	assert thinking is None


def test_clean_and_extract_json_only_thinking():
	"""Test extracting thinking block and leaving raw JSON."""
	content = '<think>I should navigate</think>{"action": "navigate"}'
	cleaned, thinking = clean_and_extract_json(content)
	assert cleaned == '{"action": "navigate"}'
	assert thinking == 'I should navigate'


def test_clean_and_extract_json_markdown():
	"""Test stripping markdown formatting code blocks."""
	content = '```json\n{"action": "click"}\n```'
	cleaned, thinking = clean_and_extract_json(content)
	assert cleaned == '{"action": "click"}'
	assert thinking is None


def test_clean_and_extract_json_both():
	"""Test both thinking tag and markdown code blocks together."""
	content = '<think>\nThinking hard...\n</think>\n```json\n{"action": "done"}\n```'
	cleaned, thinking = clean_and_extract_json(content)
	assert cleaned == '{"action": "done"}'
	assert thinking == 'Thinking hard...'


def test_clean_and_extract_json_stray_tags():
	"""Test recovery from stray/unmatched closing think tags."""
	content = 'stale thought</think>{"action": "done"}'
	cleaned, thinking = clean_and_extract_json(content)
	assert cleaned == '{"action": "done"}'
	assert thinking is None


def test_clean_and_extract_json_prose_wrapped():
	"""Test that fenced blocks are extracted even when surrounded by prose text."""
	content = 'Here is the result:\n```json\n{"action": "click"}\n```\nLet me know if this helps.'
	cleaned, thinking = clean_and_extract_json(content)
	assert cleaned == '{"action": "click"}'
	assert thinking is None
