"""A browser_exec cell that outlives its call must not retain unbounded output."""

from browser_use.mcp.cli_mcp import MAX_OUTPUT_CHARS, _Cell
from browser_use.repl.session import MAX_OUTPUT_CHARS as SESSION_MAX_OUTPUT_CHARS


def test_cell_buffer_keeps_only_a_bounded_tail():
	from browser_use.mcp.cli_mcp import _CellBuffer

	buffer = _CellBuffer(limit=10)
	for chunk in ('abc', 'defghijklmno', 'pqrst'):
		buffer.write(chunk)

	assert len(buffer.getvalue()) == 10
	assert buffer.getvalue() == 'klmnopqrst'
	assert buffer.dropped == 10
	# Writes keep appending at the end rather than overwriting the retained tail.
	buffer.write('uv')
	assert buffer.getvalue() == 'mnopqrstuv'


def test_long_running_cell_does_not_grow_without_bound():
	cell = _Cell()
	for _ in range(10_000):
		cell.buffer.write('x' * 1024)

	assert len(cell.buffer.getvalue()) == MAX_OUTPUT_CHARS
	assert MAX_OUTPUT_CHARS == SESSION_MAX_OUTPUT_CHARS
	first = cell.new_output()
	assert 'chars dropped' in first
	assert first.count('x') == MAX_OUTPUT_CHARS
	# Subsequent polls return only new output, and the offset stays correct.
	assert cell.new_output() == ''
	cell.buffer.write('DONE')
	assert cell.new_output() == 'DONE'


def test_cell_without_dropped_output_is_unchanged():
	cell = _Cell()
	cell.buffer.write('hello')
	assert cell.new_output() == 'hello'
	assert cell.new_output() == ''
	cell.buffer.write(' world')
	assert cell.new_output() == ' world'
