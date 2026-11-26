import io
import logging

from browser_use.logging_config import _PrintableFormatter, printable


def test_printable_escapes_lone_surrogates_without_altering_valid_text() -> None:
	assert printable('step 3: \ud800bad') == r'step 3: \ud800bad'
	assert printable('\udfff') == r'\udfff'
	assert printable('a\ud800\udfffb') == r'a\ud800\udfffb'

	# Escaped output must be UTF-8 encodable while valid non-BMP/CJK/tab/newline stay intact.
	out = printable('ok 😀 🌎 中文\tline1\nline2 \ud800 \x1b[31m')
	assert out == 'ok 😀 🌎 中文\tline1\nline2 \\ud800 \\x1b[31m'
	out.encode('utf-8')


def test_printable_formatter_streams_lone_surrogate_to_utf8_handler() -> None:
	buf = io.BytesIO()
	stream = io.TextIOWrapper(buf, encoding='utf-8', errors='strict', newline='\n')
	handler = logging.StreamHandler(stream)
	handler.setFormatter(_PrintableFormatter('%(levelname)s %(message)s'))

	record = logging.LogRecord(
		name='browser_use',
		level=logging.WARNING,
		pathname=__file__,
		lineno=1,
		msg='page text: %s',
		args=('bad \ud800\udfff end',),
		exc_info=None,
	)
	handler.emit(record)
	stream.flush()

	assert buf.getvalue() == b'WARNING page text: bad \\ud800\\udfff end\n'
