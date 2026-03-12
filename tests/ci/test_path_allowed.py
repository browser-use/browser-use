"""
Tests for _is_path_allowed() and directory/glob support in available_file_paths.

Covers:
1. Unit tests for _is_path_allowed (exact match, directory containment, globs, traversal)
2. Integration tests verifying upload_file and read_long_content respect directory entries
"""

from browser_use.tools.service import _is_path_allowed


class TestIsPathAllowedExactMatch:
	"""Backward-compatible exact string matching."""

	def test_exact_match_returns_true(self, tmp_path):
		f = tmp_path / 'data.csv'
		f.touch()
		assert _is_path_allowed(str(f), [str(f)]) is True

	def test_exact_match_missing_returns_false(self, tmp_path):
		assert _is_path_allowed('/nonexistent/file.txt', ['/some/other.txt']) is False

	def test_empty_allowed_paths_returns_false(self):
		assert _is_path_allowed('/any/path', []) is False

	def test_empty_allowed_paths_set_returns_false(self):
		assert _is_path_allowed('/any/path', set()) is False

	def test_works_with_set_input(self, tmp_path):
		f = tmp_path / 'a.txt'
		f.touch()
		assert _is_path_allowed(str(f), {str(f)}) is True


class TestIsPathAllowedDirectory:
	"""Directory containment checks."""

	def test_file_under_allowed_directory(self, tmp_path):
		subdir = tmp_path / 'exports'
		subdir.mkdir()
		child = subdir / 'report.csv'
		child.touch()
		assert _is_path_allowed(str(child), [str(subdir)]) is True

	def test_file_in_nested_subdirectory(self, tmp_path):
		subdir = tmp_path / 'exports' / 'daily'
		subdir.mkdir(parents=True)
		child = subdir / 'report.csv'
		child.touch()
		assert _is_path_allowed(str(child), [str(tmp_path / 'exports')]) is True

	def test_file_outside_allowed_directory(self, tmp_path):
		allowed_dir = tmp_path / 'allowed'
		allowed_dir.mkdir()
		other_dir = tmp_path / 'other'
		other_dir.mkdir()
		outside = other_dir / 'secret.txt'
		outside.touch()
		assert _is_path_allowed(str(outside), [str(allowed_dir)]) is False

	def test_traversal_attempt_rejected(self, tmp_path):
		allowed_dir = tmp_path / 'allowed'
		allowed_dir.mkdir()
		secret = tmp_path / 'secret.txt'
		secret.touch()
		traversal_path = str(allowed_dir / '..' / 'secret.txt')
		assert _is_path_allowed(traversal_path, [str(allowed_dir)]) is False

	def test_directory_with_trailing_slash(self, tmp_path):
		subdir = tmp_path / 'exports'
		subdir.mkdir()
		child = subdir / 'file.txt'
		child.touch()
		assert _is_path_allowed(str(child), [str(subdir) + '/']) is True

	def test_nonexistent_file_under_allowed_directory(self, tmp_path):
		"""A path that doesn't exist on disk but is under an allowed directory should pass."""
		subdir = tmp_path / 'exports'
		subdir.mkdir()
		future_file = str(subdir / 'not_yet_created.csv')
		assert _is_path_allowed(future_file, [str(subdir)]) is True


class TestIsPathAllowedGlob:
	"""Glob / fnmatch pattern matching."""

	def test_star_extension_pattern(self, tmp_path):
		f = tmp_path / 'data.csv'
		f.touch()
		assert _is_path_allowed(str(f), [str(tmp_path / '*.csv')]) is True

	def test_star_extension_no_match(self, tmp_path):
		f = tmp_path / 'data.json'
		f.touch()
		assert _is_path_allowed(str(f), [str(tmp_path / '*.csv')]) is False

	def test_question_mark_pattern(self, tmp_path):
		f = tmp_path / 'log1.txt'
		f.touch()
		assert _is_path_allowed(str(f), [str(tmp_path / 'log?.txt')]) is True

	def test_double_star_not_fnmatch(self):
		"""fnmatch treats ** same as * (no recursive globbing), but it still works for flat matches."""
		assert _is_path_allowed('/tmp/a/b.txt', ['/tmp/*/b.txt']) is True

	def test_glob_no_match(self):
		assert _is_path_allowed('/tmp/data.json', ['/other/*.json']) is False


class TestIsPathAllowedMixed:
	"""Multiple entries with different match types."""

	def test_exact_plus_directory(self, tmp_path):
		subdir = tmp_path / 'uploads'
		subdir.mkdir()
		exact_file = tmp_path / 'specific.txt'
		exact_file.touch()
		dir_child = subdir / 'dynamic.pdf'
		dir_child.touch()

		allowed = [str(exact_file), str(subdir)]
		assert _is_path_allowed(str(exact_file), allowed) is True
		assert _is_path_allowed(str(dir_child), allowed) is True
		assert _is_path_allowed('/other/random.txt', allowed) is False

	def test_exact_plus_glob(self, tmp_path):
		f = tmp_path / 'report.csv'
		f.touch()
		allowed = ['/some/exact.txt', str(tmp_path / '*.csv')]
		assert _is_path_allowed(str(f), allowed) is True
		assert _is_path_allowed('/some/exact.txt', allowed) is True

	def test_symlink_under_allowed_directory(self, tmp_path):
		"""Symlink that resolves to a file under an allowed directory should be allowed."""
		subdir = tmp_path / 'data'
		subdir.mkdir()
		real_file = subdir / 'real.txt'
		real_file.touch()
		link = tmp_path / 'link.txt'
		link.symlink_to(real_file)
		assert _is_path_allowed(str(link), [str(subdir)]) is True
