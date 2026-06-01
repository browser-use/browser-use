"""Tests for download filename sanitization (GHSA-rv9j-wqjp-2fv4,
GHSA-66xh-g88g-2h8j, GHSA-hpr4-fqgr-xhj9).

`DownloadsWatchdog` historically joined attacker-controlled filenames from CDP
(`Page.downloadWillBegin.suggestedFilename`) and `Content-Disposition` headers
directly into the configured `downloads_path`. Strings like `../../escape.bin`
or `/etc/shadow.bak` would `os.path.join` outside the downloads directory,
writing the fetched bytes (also attacker-controlled — the response body is the
exploit content) to an arbitrary location with the agent's process privileges.

`download_file_from_url` triggers passively for any
`Content-Disposition: attachment` response, so this is reachable from any
visited site — `allowed_domains` does not mitigate it.

The fix funnels every attacker-controlled filename through
`DownloadsWatchdog._sanitize_download_filename`, which keeps only the basename
and rejects pure-traversal names. Each on-disk sink additionally verifies
containment via `os.path.realpath`.
"""

from __future__ import annotations

from pathlib import Path

from browser_use.browser.watchdogs.downloads_watchdog import DownloadsWatchdog


class TestSanitizeDownloadFilename:
	def test_strips_relative_traversal(self) -> None:
		assert DownloadsWatchdog._sanitize_download_filename('../../etc/passwd') == 'passwd'

	def test_strips_absolute_unix_path(self) -> None:
		assert DownloadsWatchdog._sanitize_download_filename('/etc/shadow') == 'shadow'

	def test_strips_windows_backslash_paths(self) -> None:
		assert DownloadsWatchdog._sanitize_download_filename('..\\..\\Windows\\System32\\config.txt') == 'config.txt'

	def test_strips_mixed_separators(self) -> None:
		assert DownloadsWatchdog._sanitize_download_filename('a/b\\c/../d.pdf') == 'd.pdf'

	def test_pure_traversal_falls_back_to_download(self) -> None:
		for malicious in ('..', '.', '/', '\\', '../', '..\\', '/.', '\\.', '/..'):
			assert DownloadsWatchdog._sanitize_download_filename(malicious) == 'download', (
				f'{malicious!r} should fall back to default'
			)

	def test_null_byte_stripped(self) -> None:
		# Null bytes can be used to confuse path handling on some platforms.
		assert DownloadsWatchdog._sanitize_download_filename('file.txt\x00.exe') == 'file.txt.exe'

	def test_empty_or_none_falls_back(self) -> None:
		assert DownloadsWatchdog._sanitize_download_filename('') == 'download'
		assert DownloadsWatchdog._sanitize_download_filename(None) == 'download'

	def test_normal_filenames_preserved(self) -> None:
		# Make sure we don't over-sanitize legitimate names.
		assert DownloadsWatchdog._sanitize_download_filename('report.pdf') == 'report.pdf'
		assert DownloadsWatchdog._sanitize_download_filename('file with spaces.pdf') == 'file with spaces.pdf'
		assert DownloadsWatchdog._sanitize_download_filename('file-with_underscores.csv') == 'file-with_underscores.csv'
		# Dotfiles are allowed as long as they're not just dots.
		assert DownloadsWatchdog._sanitize_download_filename('.bashrc') == '.bashrc'

	def test_unicode_preserved(self) -> None:
		# Filenames with non-ASCII characters should survive (common for i18n filenames).
		assert DownloadsWatchdog._sanitize_download_filename('résumé.pdf') == 'résumé.pdf'
		assert DownloadsWatchdog._sanitize_download_filename('文档.pdf') == '文档.pdf'


class TestIsPathContained:
	def test_file_inside_dir_returns_true(self, tmp_path: Path) -> None:
		f = tmp_path / 'a.txt'
		f.write_text('x')
		assert DownloadsWatchdog._is_path_contained(f, tmp_path) is True

	def test_nested_file_inside_dir_returns_true(self, tmp_path: Path) -> None:
		nested = tmp_path / 'sub' / 'a.txt'
		nested.parent.mkdir()
		nested.write_text('x')
		assert DownloadsWatchdog._is_path_contained(nested, tmp_path) is True

	def test_escaping_path_returns_false(self, tmp_path: Path) -> None:
		escape = tmp_path / '..' / 'a.txt'
		assert DownloadsWatchdog._is_path_contained(escape, tmp_path) is False

	def test_dir_itself_returns_true(self, tmp_path: Path) -> None:
		assert DownloadsWatchdog._is_path_contained(tmp_path, tmp_path) is True

	def test_sibling_dir_returns_false(self, tmp_path: Path) -> None:
		sibling = tmp_path.parent / (tmp_path.name + '_sibling')
		sibling.mkdir(exist_ok=True)
		try:
			f = sibling / 'a.txt'
			f.write_text('x')
			assert DownloadsWatchdog._is_path_contained(f, tmp_path) is False
		finally:
			f.unlink(missing_ok=True)
			sibling.rmdir()


class TestUniqueFilenameOperatesOnSanitizedBasename:
	"""`_get_unique_filename` must only ever receive a sanitized basename; if a
	traversal string slips through, the (1)/(2) collision-avoidance logic
	silently writes outside the intended directory."""

	async def test_unique_filename_on_basename_stays_inside_dir(self, tmp_path: Path) -> None:
		# Pre-sanitized name — what the caller should always pass.
		result = await DownloadsWatchdog._get_unique_filename(str(tmp_path), 'report.pdf')
		assert result == 'report.pdf'
		# The resolved path lives inside tmp_path.
		assert DownloadsWatchdog._is_path_contained(tmp_path / result, tmp_path)

	async def test_unique_filename_collision_handling_stays_inside_dir(self, tmp_path: Path) -> None:
		(tmp_path / 'report.pdf').write_text('x')
		result = await DownloadsWatchdog._get_unique_filename(str(tmp_path), 'report.pdf')
		assert result == 'report (1).pdf'
		assert DownloadsWatchdog._is_path_contained(tmp_path / result, tmp_path)
