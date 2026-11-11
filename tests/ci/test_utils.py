"""Unit tests for the pure path helpers in browser_use.utils.

These cover ``file_names`` and ``singleton``, which previously had no unit
coverage despite carrying non-trivial edge cases (255-byte filesystem limits,
multi-byte names, over-long "extensions" that are really part of the name, and
the never-overwrite counter sequence).
"""

from pathlib import PurePosixPath

from browser_use.utils import file_names, singleton


def _first(dest: str, name: str, n: int):
	gen = file_names(PurePosixPath(dest), name)
	return [str(p) for p in (next(gen) for _ in range(n))]


def test_file_names_basic_sequence():
	out = _first('/d', 'report.csv', 4)
	assert out == [
		'/d/report.csv',
		'/d/report (1).csv',
		'/d/report (2).csv',
		'/d/report (3).csv',
	]


def test_file_names_no_extension():
	out = _first('/x', 'notes', 2)
	assert out == ['/x/notes', '/x/notes (1)']


def test_file_names_sequence_is_unique():
	out = _first('/d', 'a.txt', 6)
	assert len(set(out)) == 6


def test_file_names_long_suffix_is_treated_as_name():
	# An "extension" longer than 32 bytes is not a real extension, so it stays
	# part of the stem and no counter is added to the first path.
	name = 'f.' + 'x' * 40
	first = str(next(file_names(PurePosixPath('/d'), name)))
	assert first == '/d/' + name
	assert ' (' not in first


def test_file_names_truncates_ascii_to_filesystem_limit():
	out = next(file_names(PurePosixPath('/d'), 'a' * 300 + '.txt'))
	name = PurePosixPath(str(out)).name
	assert len(name.encode()) <= 255
	assert name.endswith('.txt')


def test_file_names_truncates_multibyte_without_losing_suffix():
	out = next(file_names(PurePosixPath('/d'), '年' * 200 + '.csv'))
	name = PurePosixPath(str(out)).name
	assert len(name.encode()) <= 255
	assert name.endswith('.csv')
	assert name.startswith('年')


def test_singleton_returns_same_instance():
	@singleton
	class Counter:
		def __init__(self, v):
			self.v = v

	a = Counter(1)
	b = Counter(2)
	assert a is b
	assert a.v == 1  # the second construction is ignored
