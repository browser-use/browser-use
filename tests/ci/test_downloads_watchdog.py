from browser_use.browser.watchdogs.downloads_watchdog import (
	_ensure_downloads_directory,
	_should_auto_download_network_response,
)


def test_downloads_watchdog_skips_generic_text_attachment_without_file_url():
	assert not _should_auto_download_network_response(
		url='https://www.google.com/complete/search?q=test&client=gws-wiz&xssi=t',
		content_type='text/plain',
		is_pdf=False,
		is_download_attachment=True,
		suggested_filename='f.txt',
	)


def test_downloads_watchdog_keeps_pdf_network_response():
	assert _should_auto_download_network_response(
		url='https://example.com/view?id=123',
		content_type='application/pdf',
		is_pdf=True,
		is_download_attachment=False,
		suggested_filename=None,
	)


def test_downloads_watchdog_keeps_named_file_attachment():
	assert _should_auto_download_network_response(
		url='https://example.com/download?id=123',
		content_type='text/csv',
		is_pdf=False,
		is_download_attachment=True,
		suggested_filename='report.csv',
	)


def test_downloads_watchdog_keeps_text_attachment_with_file_url():
	assert _should_auto_download_network_response(
		url='https://example.com/files/summary.txt?download=1',
		content_type='text/plain',
		is_pdf=False,
		is_download_attachment=True,
		suggested_filename='f.txt',
	)


def test_downloads_watchdog_keeps_attachment_without_known_extension():
	assert _should_auto_download_network_response(
		url='https://example.com/download?id=123',
		content_type='application/vnd.example.custom',
		is_pdf=False,
		is_download_attachment=True,
		suggested_filename='statement',
	)


def test_ensure_downloads_directory_creates_missing_dir(tmp_path):
	downloads_dir = tmp_path / 'downloads' / 'nested'
	result = _ensure_downloads_directory(downloads_dir)
	assert result == downloads_dir.resolve()
	assert downloads_dir.is_dir()


def test_ensure_downloads_directory_accepts_existing_dir(tmp_path):
	downloads_dir = tmp_path / 'downloads'
	downloads_dir.mkdir()
	result = _ensure_downloads_directory(downloads_dir)
	assert result == downloads_dir.resolve()
	assert downloads_dir.is_dir()


def test_ensure_downloads_directory_returns_none_when_uncreatable(tmp_path):
	# Parent path is occupied by a regular file, so no directory tree can be
	# created under it (mirrors Windows virtualized folders that reject
	# child creation with OSError despite parents=True).
	blocker = tmp_path / 'blocker'
	blocker.write_text('not a directory')
	result = _ensure_downloads_directory(blocker / 'sub' / 'downloads')
	assert result is None
