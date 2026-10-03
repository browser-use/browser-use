import pytest

from browser_use.browser.watchdogs.downloads_watchdog import (
	_download_info_from_headers,
	_filename_from_content_disposition,
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


@pytest.mark.parametrize(
	('header', 'expected'),
	[
		('attachment; filename="report.csv"', 'report.csv'),
		('attachment; filename=Report.CSV', 'Report.CSV'),
		("attachment; filename*=UTF-8''r%C3%A9sum%C3%A9.pdf", 'résumé.pdf'),
		("attachment; filename*=utf-8''%E6%97%A5%E6%9C%AC%E8%AA%9E.pdf", '日本語.pdf'),
		('attachment; filename="fallback.pdf"; filename*=UTF-8\'\'r%C3%A9sum%C3%A9.pdf', 'résumé.pdf'),
		("attachment; filename*=UTF-8'en'My%20File.txt", 'My File.txt'),
		('attachment; filename*=UTF-8\'\'%FF.pdf; filename="fallback.pdf"', 'fallback.pdf'),
		('attachment; filename*=bogus\'\'r%C3%A9sum%C3%A9.pdf; filename="fallback.pdf"', 'fallback.pdf'),
		('attachment; filename*=UTF-8\'\'bad%zz.pdf; filename="fallback.pdf"', 'fallback.pdf'),
		('attachment; filename*=UTF-8\'\'bad%.pdf; filename="fallback.pdf"', 'fallback.pdf'),
		('attachment; filename*=UTF-8\'\'bad%4.pdf; filename="fallback.pdf"', 'fallback.pdf'),
		('attachment; filename*="UTF-8\'\'r%C3%A9sum%C3%A9.pdf"', 'résumé.pdf'),
		("attachment; filename*=UTF-8''x%0Aadmin-login.log", 'xadmin-login.log'),
		("attachment; filename*=UTF-8''x%0D%09y.log", 'xy.log'),
		('attachment', None),
	],
)
def test_filename_from_content_disposition(header, expected):
	assert _filename_from_content_disposition(header) == expected


def test_download_info_from_headers_keeps_filename_case():
	is_attachment, filename = _download_info_from_headers({'content-disposition': 'ATTACHMENT; filename=Report.CSV'})

	assert is_attachment
	assert filename == 'Report.CSV'


def test_download_info_from_headers_without_content_disposition():
	assert _download_info_from_headers({}) == (False, None)
