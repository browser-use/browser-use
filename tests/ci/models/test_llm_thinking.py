from browser_use.llm.utils import clean_and_extract_json


def test_clean_and_extract_json_plain():
	raw = '{"action": "search"}'
	content, thinking = clean_and_extract_json(raw)
	assert content == '{"action": "search"}'
	assert thinking is None


def test_clean_and_extract_json_only_thinking():
	raw = '<think>I should search for the product.</think>{"action": "search"}'
	content, thinking = clean_and_extract_json(raw)
	assert content == '{"action": "search"}'
	assert thinking == 'I should search for the product.'


def test_clean_and_extract_json_markdown():
	raw = '```json\n{"action": "search"}\n```'
	content, thinking = clean_and_extract_json(raw)
	assert content == '{"action": "search"}'
	assert thinking is None


def test_clean_and_extract_json_both():
	raw = '<think>Thinking deep thoughts...</think>\n```json\n{"action": "search"}\n```'
	content, thinking = clean_and_extract_json(raw)
	assert content == '{"action": "search"}'
	assert thinking == 'Thinking deep thoughts...'


def test_clean_and_extract_json_unclosed_tags():
	raw = '<think>Truncated thought process without closing tag...'
	content, thinking = clean_and_extract_json(raw)
	assert thinking == 'Truncated thought process without closing tag...'
	assert content == ''
