"""Regression tests for GIF overlay unicode-escape decoding.

Covers https://github.com/browser-use/browser-use/issues/5638: a literal
``\\uXXXX`` escape next to an already-decoded non-Latin-1 character (emoji,
CJK) must still be decoded instead of aborting the whole decode.
"""

from browser_use.agent.gif import decode_unicode_escapes_to_utf8


def test_mixed_emoji_and_escape_decodes_escape():
	# Exact repro from the issue: the escape must decode even though the
	# string also contains an emoji outside Latin-1.
	assert decode_unicode_escapes_to_utf8('Next: open \\u4f60 \U0001f600') == 'Next: open \u4f60 \U0001f600'


def test_ascii_only_control_still_decodes():
	# Fast path (whole string Latin-1 encodable) behavior is unchanged.
	assert decode_unicode_escapes_to_utf8(r'Next: open \u4f60') == 'Next: open \u4f60'


def test_cjk_text_plus_escape():
	assert decode_unicode_escapes_to_utf8('\u6d4b\u8bd5 escape \\u6d4b') == '\u6d4b\u8bd5 escape \u6d4b'


def test_no_escapes_passthrough():
	text = 'plain \U0001f600 no escapes'
	assert decode_unicode_escapes_to_utf8(text) == text


def test_escaped_backslash_is_not_double_decoded():
	# `\\\\u4f60` is an escaped backslash followed by literal text, not an escape.
	assert decode_unicode_escapes_to_utf8('\\\\u4f60\U0001f600') == '\\\\u4f60\U0001f600'


def test_invalid_escape_left_untouched():
	assert decode_unicode_escapes_to_utf8('\\uZZZZ\U0001f600') == '\\uZZZZ\U0001f600'


def test_uppercase_escape_with_emoji():
	assert decode_unicode_escapes_to_utf8('\\U0001F602\U0001f600') == '\U0001f602\U0001f600'
