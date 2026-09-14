"""Regression tests for GIF overlay unicode-escape decoding.

Covers https://github.com/browser-use/browser-use/issues/5638: a literal
``\\uXXXX`` escape next to an already-decoded non-Latin-1 character (emoji, CJK)
must still be decoded instead of aborting the whole decode.

The properties the fallback is written against are that a caption decodes the same
way regardless of whether the rest of it happens to be Latin-1 encodable, that a
single escape the codec rejects does not keep the valid ones beside it raw, and that
the overlay path runs the decoder once per text.
"""

from browser_use.agent import gif
from browser_use.agent.gif import decode_unicode_escapes_to_utf8

EMOJI = ' \U0001f600'

# Escape families the fast path handles today. The fallback has to return the
# identical result, because it runs the same codec over each Latin-1 stretch.
FAST_PATH_FORMS = [
	r'\u4f60',
	r'\U0001F600',
	r'\u0041',
	r'\\u4f60',
	r'\\\\u4f60',
	r'C:\\path \u4f60',
	r'\x5cu0041 \u0042',
	r'\134u0041 \u0042',
	r'newline \u4f60 and \n',
	r'tab \t \u4f60',
	'price ' + r'\u0024' + ' and ' + r'\U0001F602',
]

# Forms neither branch can decode, which have to survive untouched either way.
NEITHER_BRANCH_DECODES = [
	r'\uZZZZ',
	r'\U0011F600',
	r'truncated \u4f',
]


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


def test_uppercase_escape_with_emoji():
	assert decode_unicode_escapes_to_utf8('\\U0001F602\U0001f600') == '\U0001f602\U0001f600'


def test_escaped_backslash_keeps_the_text_behind_it_literal():
	# `\\u4f60` is an escaped backslash followed by literal text, not an escape, and
	# collapses to one backslash exactly as it does without the emoji.
	assert decode_unicode_escapes_to_utf8('\\\\u4f60\U0001f600') == '\\u4f60\U0001f600'


def test_windows_path_and_cjk_keep_one_backslash():
	# The escaped pairs in the path collapse the same way the fast path collapses them,
	# and the sibling `\\u6587` decodes whether or not the caption holds more CJK.
	text = 'C:\\\\Users\\\\demo \\u6587'
	assert decode_unicode_escapes_to_utf8(text) == 'C:\\Users\\demo \u6587'
	assert decode_unicode_escapes_to_utf8(text + ' 打开') == 'C:\\Users\\demo \u6587 打开'


def test_decoding_does_not_depend_on_the_rest_of_the_caption():
	# The bug generalizes: a non-Latin-1 character anywhere in the string used to abort
	# the decode, so the same caption rendered two different ways. Appending an emoji
	# must not change how any escape decodes.
	for form in FAST_PATH_FORMS:
		fast_path = form.encode('latin1').decode('unicode_escape')
		assert decode_unicode_escapes_to_utf8(form) == fast_path
		assert decode_unicode_escapes_to_utf8(form + EMOJI) == fast_path + EMOJI
		assert decode_unicode_escapes_to_utf8(form + ' \u4f60') == fast_path + ' \u4f60'


def test_undecodable_escape_stays_untouched_either_way():
	for form in NEITHER_BRANCH_DECODES:
		assert decode_unicode_escapes_to_utf8(form) == form
		assert decode_unicode_escapes_to_utf8(form + EMOJI) == form + EMOJI


def test_hex_octal_and_c_escapes_decode_the_same_with_an_emoji_present():
	# Boundary check on the fallback: it is not limited to `\\uXXXX`, so the escape
	# families only the codec knows about behave the way they do without the emoji.
	assert decode_unicode_escapes_to_utf8(r'\x5cu0041 \u0042' + EMOJI) == '\\u0041 B' + EMOJI
	assert decode_unicode_escapes_to_utf8(r'\134u0041 \u0042' + EMOJI) == '\\u0041 B' + EMOJI
	assert decode_unicode_escapes_to_utf8(r'\u0041\n' + EMOJI) == 'A\n' + EMOJI


def test_a_malformed_escape_does_not_poison_the_valid_ones_beside_it():
	# The codec gives up on the first escape it cannot read, so a malformed one used to keep
	# a valid `\\uXXXX` in the same Latin-1 stretch raw as collateral. Only the rejected
	# escape stays literal now, which is the same failure #5638 reports in a smaller radius.
	assert decode_unicode_escapes_to_utf8(r'\u0041 \uZZZZ') == 'A ' + r'\uZZZZ'
	assert decode_unicode_escapes_to_utf8(r'\u0041 \U0011F600 next \u4f60') == 'A ' + r'\U0011F600 next ' + '你'
	assert decode_unicode_escapes_to_utf8(r'\u0041 \uZZZZ' + EMOJI) == 'A ' + r'\uZZZZ' + EMOJI
	assert decode_unicode_escapes_to_utf8(r'\u0041 \u0042: \u4f' + EMOJI) == 'A B: ' + r'\u4f' + EMOJI


def test_a_caption_ending_mid_escape_decodes_the_same_with_or_without_an_emoji():
	# The shape where an appended character used to change the answer on its own: with the
	# emoji the trailing backslash escapes its space instead of the end of the caption.
	for form in (r'\u0041', r'\u4f60', r'\U0001F600', r'\x5c'):
		truncated = form + '\\'
		assert decode_unicode_escapes_to_utf8(truncated + EMOJI) == decode_unicode_escapes_to_utf8(truncated) + EMOJI


def test_overlay_path_decodes_the_goal_text_once(monkeypatch):
	from PIL import Image, ImageFont

	calls = []
	real = gif.decode_unicode_escapes_to_utf8

	def spy(text: str) -> str:
		calls.append(text)
		return real(text)

	monkeypatch.setattr(gif, 'decode_unicode_escapes_to_utf8', spy)
	gif._add_overlay_to_image(
		image=Image.new('RGB', (400, 400)),
		step_number=1,
		goal_text=r'open \u4f60',
		regular_font=ImageFont.load_default(),  # type: ignore
		title_font=ImageFont.load_default(),  # type: ignore
		margin=10,
	)
	# Wrapping is where the decode happens; a second call would unescape the result of
	# the first, which is how an escaped `\\u0041` used to end up rendered as `A`.
	assert calls == [r'open \u4f60']
