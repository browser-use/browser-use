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


def test_latin1_only_escaped_backslash_uppercase_preserved():
	# P2 finding on PR #5748: a Latin-1-only `\\UXXXXXXXX` (escaped backslash,
	# not an escape) must not lose a backslash via the fast path, which would
	# expose it as a live escape to the next decoder call in the overlay path
	# (`_add_overlay_to_image` decodes, then `_wrap_text` decodes again).
	assert decode_unicode_escapes_to_utf8('\\\\U00000041') == '\\\\U00000041'


def test_latin1_only_escaped_backslash_lowercase_preserved():
	# Same hazard for the lowercase form (pre-existing, same root cause).
	assert decode_unicode_escapes_to_utf8('\\\\u0041') == '\\\\u0041'


def test_escaped_backslash_decode_is_idempotent():
	# The overlay path calls the decoder twice; a second pass must be a no-op
	# so literal text can never collapse into a decoded character.
	for text in ('\\\\U00000041', '\\\\u0041'):
		once = decode_unicode_escapes_to_utf8(text)
		assert decode_unicode_escapes_to_utf8(once) == once


def test_mixed_real_escape_and_escaped_backslash_latin1_only():
	# A real escape still decodes while the escaped backslash next to it is
	# preserved, and the result is stable under a second decode pass.
	once = decode_unicode_escapes_to_utf8('open \\u4f60 \\\\u0041')
	assert once == 'open \u4f60 \\\\u0041'
	assert decode_unicode_escapes_to_utf8(once) == once


def test_escaped_backslash_away_from_unicode_escape_keeps_other_escapes():
	# P2 follow-up on PR #5748: the guard tests the decoded result, so an escaped
	# backslash that leaves no live escape behind keeps the fast path and every escape
	# it has always decoded (`\\` collapses, `\n` becomes a newline).
	text = r'\\\n \u4f60'
	once = decode_unicode_escapes_to_utf8(text)
	assert once == '\\\n \u4f60'
	assert decode_unicode_escapes_to_utf8(once) == once


def test_windows_path_keeps_fast_path_decode():
	text = r'C:\\path \u4f60'
	once = decode_unicode_escapes_to_utf8(text)
	assert once == 'C:\\path \u4f60'
	assert decode_unicode_escapes_to_utf8(once) == once


def test_hex_escape_minting_a_backslash_is_not_double_decoded():
	# P3 follow-up on PR #5748: `\x5c` decodes to a backslash, so the `u0041` right
	# after it turns into a live `\uXXXX` escape for the next overlay decode. The
	# unrelated `\u0042` is what carries the string past the early bail-out.
	text = r'\x5cu0041 \u0042'
	once = decode_unicode_escapes_to_utf8(text)
	assert once == '\\x5cu0041 B'
	assert decode_unicode_escapes_to_utf8(once) == once


def test_octal_escape_minting_a_backslash_is_not_double_decoded():
	# Same hazard through the octal form (`\134` is 0x5c), which no input-side pattern
	# match could have anticipated.
	text = r'\134u0041 \u0042'
	once = decode_unicode_escapes_to_utf8(text)
	assert once == '\\134u0041 B'
	assert decode_unicode_escapes_to_utf8(once) == once


def test_invalid_escape_tail_keeps_its_backslashes():
	# `\uZZZZ` is not a decodable escape, but the fast path still eats one backslash of
	# `\\\\uZZZZ` per pass, so the text keeps shrinking while the overlay path decodes
	# it. Rejecting any `\\u`/`\\U` left in the result, not only valid escapes, is what
	# makes the second pass a no-op.
	text = r'\\\\uZZZZ'
	once = decode_unicode_escapes_to_utf8(text)
	assert once == text
	assert decode_unicode_escapes_to_utf8(once) == once
