import pytest

from browser_use.agent.gif import decode_unicode_escapes_to_utf8


@pytest.mark.parametrize(
	('text', 'expected'),
	[
		(
			r'Next: open \u4f60',
			'Next: open 你',
		),
		(
			r'Next: open \u4f60 😀',
			'Next: open 你 😀',
		),
		(
			r'已完成; next: \u963f',
			'已完成; next: 阿',
		),
		(
			r'Next: \U0001f600',
			'Next: 😀',
		),
		(
			'Plain text without escapes',
			'Plain text without escapes',
		),
		(
			r'Invalid escape \u123z remains',
			r'Invalid escape \u123z remains',
		),
	],
)
def test_gif_text_decodes_embedded_unicode_escapes(text, expected):
	assert decode_unicode_escapes_to_utf8(text) == expected
