"""A browser_exec cell that outlives its call must not retain unbounded output in memory."""

from pathlib import Path

from browser_use.mcp.cli_mcp import MAX_OUTPUT_CHARS, _Cell
from browser_use.repl.session import MAX_OUTPUT_CHARS as SESSION_MAX_OUTPUT_CHARS


def test_cell_buffer_keeps_only_a_bounded_tail_in_memory():
	cell = _Cell()
	for _ in range(10_000):
		cell.buffer.write('x' * 1024)

	# Only a bounded tail stays in the StringIO; the rest is on disk.
	assert len(cell.buffer.getvalue()) == MAX_OUTPUT_CHARS
	assert MAX_OUTPUT_CHARS == SESSION_MAX_OUTPUT_CHARS
	assert cell.buffer.full_path is not None
	assert Path(cell.buffer.full_path).stat().st_size == 10_240_000
	# Writes keep appending at the end of the retained tail.
	cell.buffer.write('DONE')
	assert cell.buffer.getvalue().endswith('DONE')


def test_polls_return_new_output_once_and_then_empty():
	cell = _Cell()
	cell.buffer.write('hello')
	assert cell.new_output() == 'hello'
	assert cell.new_output() == ''
	cell.buffer.write(' world')
	assert cell.new_output() == ' world'


def test_spilled_output_is_returned_in_full_with_its_path():
	cell = _Cell()
	big = 'A\n' * 10_000 + '\U0001f600 \u4e2d'
	cell.buffer.write(big)
	out = cell.new_output()
	assert out == big  # full text is available to _clipped via full_path
	assert cell.new_output() == ''
	assert Path(cell.buffer.full_path).read_text(encoding='utf-8') == big
