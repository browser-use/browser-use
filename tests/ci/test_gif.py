import pytest

from browser_use.agent.gif import decode_unicode_escapes_to_utf8


@pytest.mark.parametrize(
	'text, expected',
	[
		(r'\u4f60', '你'),
		(r'Next: open \u4f60 😀', 'Next: open 你 😀'),
		(r'C:\\Users\\demo \u6587', r'C:\Users\demo 文'),
		(r'\U0001F600', '😀'),
		(r'\u0041\n 😀', 'A\n 😀'),
		(r'\u0041 \uZZZZ', r'A \uZZZZ'),
		(r'\uZZZZ \u0041', r'\uZZZZ A'),
		(r'\x5cu0041 \u0042', r'\u0041 B'),
		(r'escaped \\u0041 back', r'escaped \u0041 back'),
		(r'hello 😀 中文 \u4f60', 'hello 😀 中文 你'),
	],
)
def test_decode_unicode_escapes(text: str, expected: str) -> None:
	assert decode_unicode_escapes_to_utf8(text) == expected


def test_text_without_unicode_escapes_is_unchanged() -> None:
	text = 'hello 😀 中文 العربية'
	assert decode_unicode_escapes_to_utf8(text) == text
