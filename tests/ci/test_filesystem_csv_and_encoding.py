"""Regression tests for FileSystem CSV normalization and text encoding.

Bugs pinned here:

1. `CsvFile._normalize_csv` treated any single-line content containing a literal
   `\\n` as double-escaped JSON and turned it into a real newline. That corrupted
   ordinary fields such as Windows paths (`C:\\new`) or regexes by splitting one
   field across rows. The un-escape is now only applied when it yields a
   consistent multi-column table.

2. Text files were written/read without an explicit encoding, so on a non-UTF-8
   locale (e.g. Windows cp1252) non-ASCII content (CJK, emoji) failed to encode
   and was lost. All text I/O now uses `encoding='utf-8'`.
"""

import csv
import io
import tempfile

from browser_use.filesystem.file_system import CsvFile, FileSystem


def _rows(content: str) -> list[list[str]]:
	return list(csv.reader(io.StringIO(content)))


def test_csv_field_with_backslash_n_is_not_split():
	f = CsvFile(name='paths')
	f.write_file_content('col1,col2')
	f.append_file_content('tool,C:\\new')  # field value is  C:\new
	assert _rows(f.content) == [['col1', 'col2'], ['tool', 'C:\\new']]


def test_csv_single_column_backslash_n_is_preserved():
	f = CsvFile(name='paths')
	f.write_file_content('C:\\new')
	assert f.content == 'C:\\new'


def test_csv_double_escaped_table_is_still_unescaped():
	# The intended feature: a genuinely double-escaped rectangular table (no real
	# newlines, literal \n as row separators) is still expanded into rows.
	f = CsvFile(name='data')
	f.write_file_content('a,b\\nc,d\\ne,f')
	assert _rows(f.content) == [['a', 'b'], ['c', 'd'], ['e', 'f']]


async def test_non_ascii_text_persists_as_utf8():
	# Contract test: content is stored as UTF-8 regardless of locale. On a
	# non-UTF-8 default (Windows cp1252) this used to error and write 0 bytes.
	fs = FileSystem(tempfile.mkdtemp(), create_default_files=False)
	content = '你好世界 😀 café'

	result = await fs.write_file('notes.md', content)
	assert 'Error' not in result

	on_disk = fs.get_dir() / 'notes.md'
	assert on_disk.read_bytes().decode('utf-8') == content
