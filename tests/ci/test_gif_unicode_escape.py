"""Tests for GIF Unicode escape decoding with mixed content."""

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
			'Next: open \\u4f60 \U0001f600',
			'Next: open 你 \U0001f600',
		),
		(
			'\u5df2\u5b8c\u6210; next: \\u963f',
			'\u5df2\u5b8c\u6210; next: 阿',
		),
		(
			r'No escapes here',
			'No escapes here',
		),
		(
			'Already decoded: 你好',
			'Already decoded: 你好',
		),
	],
)
def test_gif_text_decodes_embedded_unicode_escapes(text, expected):
	"""Unicode escape sequences should be decoded even when the string contains non-Latin-1 characters."""
	assert decode_unicode_escapes_to_utf8(text) == expected


def test_malformed_escape_preserved():
	"""Malformed escape sequences should be left unchanged."""
	text = r'Bad escape: \uGGGG'
	assert decode_unicode_escapes_to_utf8(text) == text


def test_multiple_escapes_decoded():
	"""Multiple escape sequences should all be decoded."""
	text = r'\u4f60\u597d'
	assert decode_unicode_escapes_to_utf8(text) == '你好'
