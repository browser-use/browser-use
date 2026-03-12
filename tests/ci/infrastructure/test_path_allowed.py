"""
Tests for _is_path_allowed utility function in tools/service.py.

This function supports directory entries in available_file_paths, allowing
users to whitelist entire directories instead of individual files.
See: https://github.com/browser-use/browser-use/issues/4120
"""

from browser_use.tools.service import _is_path_allowed


class TestIsPathAllowed:
	"""Test _is_path_allowed with exact paths, directories, and edge cases."""

	def test_exact_file_match(self):
		"""Exact file path should match."""
		assert _is_path_allowed('/tmp/test.txt', ['/tmp/test.txt']) is True

	def test_exact_file_no_match(self):
		"""Non-matching exact file path should not match."""
		assert _is_path_allowed('/tmp/other.txt', ['/tmp/test.txt']) is False

	def test_empty_allowed_paths(self):
		"""Empty allowed_paths should never match."""
		assert _is_path_allowed('/tmp/test.txt', []) is False

	def test_directory_with_trailing_slash(self):
		"""Directory entry with trailing slash should allow files under it."""
		assert _is_path_allowed('/tmp/uploads/file.txt', ['/tmp/uploads/']) is True

	def test_directory_with_trailing_slash_nested(self):
		"""Directory entry with trailing slash should allow nested files."""
		assert _is_path_allowed('/tmp/uploads/subdir/file.txt', ['/tmp/uploads/']) is True

	def test_directory_with_trailing_slash_no_match(self):
		"""File outside the directory should not match."""
		assert _is_path_allowed('/tmp/other/file.txt', ['/tmp/uploads/']) is False

	def test_real_directory_without_trailing_slash(self, tmp_path):
		"""A real directory (detected via os.path.isdir) should allow files under it."""
		subdir = tmp_path / 'mydir'
		subdir.mkdir()
		test_file = subdir / 'test.txt'
		test_file.write_text('hello')

		assert _is_path_allowed(str(test_file), [str(subdir)]) is True

	def test_real_directory_nested_files(self, tmp_path):
		"""A real directory should allow deeply nested files."""
		subdir = tmp_path / 'mydir' / 'nested'
		subdir.mkdir(parents=True)
		test_file = subdir / 'deep.txt'
		test_file.write_text('hello')

		assert _is_path_allowed(str(test_file), [str(tmp_path / 'mydir')]) is True

	def test_real_directory_rejects_outside_files(self, tmp_path):
		"""A real directory should reject files outside it."""
		subdir = tmp_path / 'mydir'
		subdir.mkdir()
		other_file = tmp_path / 'outside.txt'
		other_file.write_text('hello')

		assert _is_path_allowed(str(other_file), [str(subdir)]) is False

	def test_mixed_files_and_directories(self, tmp_path):
		"""Mix of exact file paths and directory entries should work."""
		subdir = tmp_path / 'uploads'
		subdir.mkdir()
		file_in_dir = subdir / 'uploaded.txt'
		file_in_dir.write_text('data')
		exact_file = tmp_path / 'specific.txt'
		exact_file.write_text('data')

		allowed = [str(exact_file), str(subdir)]

		assert _is_path_allowed(str(exact_file), allowed) is True
		assert _is_path_allowed(str(file_in_dir), allowed) is True
		assert _is_path_allowed(str(tmp_path / 'random.txt'), allowed) is False

	def test_directory_prefix_attack(self):
		"""Directory /tmp/up should NOT match /tmp/uploads/file.txt."""
		# Using trailing slash explicitly
		assert _is_path_allowed('/tmp/uploads/file.txt', ['/tmp/up/']) is False

	def test_directory_name_prefix_attack_no_trailing_slash(self, tmp_path):
		"""Ensure /foo/bar does not match /foo/bar_extra/file.txt via prefix."""
		dir_a = tmp_path / 'bar'
		dir_a.mkdir()
		dir_b = tmp_path / 'bar_extra'
		dir_b.mkdir()
		test_file = dir_b / 'file.txt'
		test_file.write_text('data')

		assert _is_path_allowed(str(test_file), [str(dir_a)]) is False

	def test_relative_path_resolved(self, tmp_path, monkeypatch):
		"""Relative paths should be resolved to absolute for matching."""
		monkeypatch.chdir(tmp_path)
		test_file = tmp_path / 'test.txt'
		test_file.write_text('hello')

		assert _is_path_allowed('test.txt', [str(tmp_path) + '/']) is True

	def test_set_input(self):
		"""Should work with set input as well as list."""
		assert _is_path_allowed('/tmp/test.txt', {'/tmp/test.txt'}) is True
		assert _is_path_allowed('/tmp/other.txt', {'/tmp/test.txt'}) is False

	def test_multiple_directories(self, tmp_path):
		"""Multiple directory entries should all be checked."""
		dir_a = tmp_path / 'a'
		dir_b = tmp_path / 'b'
		dir_a.mkdir()
		dir_b.mkdir()
		file_a = dir_a / 'file.txt'
		file_a.write_text('a')
		file_b = dir_b / 'file.txt'
		file_b.write_text('b')

		allowed = [str(dir_a), str(dir_b)]
		assert _is_path_allowed(str(file_a), allowed) is True
		assert _is_path_allowed(str(file_b), allowed) is True
		assert _is_path_allowed(str(tmp_path / 'c' / 'file.txt'), allowed) is False
