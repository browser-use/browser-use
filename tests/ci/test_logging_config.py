"""The terminal-safety sanitizer in browser_use.logging_config: control characters and lone surrogates escaped."""

import logging

from browser_use.logging_config import printable, setup_logging


def test_printable_escapes_control_characters():
	assert printable('ESC\x1b[31m') == 'ESC\\x1b[31m'
	assert printable('a\x00b') == 'a\\x00b'


def test_printable_escapes_lone_surrogates():
	# A lone surrogate is a valid Python str character but cannot be encoded as UTF-8.
	out = printable('step 3: \ud800bad')
	assert out == 'step 3: \\ud800bad'
	out.encode('utf-8')  # must not raise UnicodeEncodeError


def test_printable_keeps_valid_text_untouched():
	for text in ('hello \U0001f600 world', '中文测试', 'tab\there', 'line1\nline2'):
		assert printable(text) == text


def test_stderr_handler_formats_a_lone_surrogate_as_utf8():
	# The browser_use logger writes UTF-8 to stderr with the sanitizer installed: a record carrying a lone
	# surrogate must survive formatting instead of raising UnicodeEncodeError on the write.
	logger = setup_logging()
	handler = next(h for h in logger.handlers if h.formatter is not None)
	formatter = handler.formatter
	assert formatter is not None
	record = logging.LogRecord('browser_use', logging.INFO, __file__, 1, 'page says \ud800', None, None)
	out = formatter.format(record)
	assert '\\ud800' in out
	out.encode('utf-8')  # must not raise UnicodeEncodeError
