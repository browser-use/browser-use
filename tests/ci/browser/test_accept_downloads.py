"""
Test that BrowserProfile.accept_downloads controls whether the browser saves downloads.

Usage:
	uv run pytest tests/ci/browser/test_accept_downloads.py -v -s
"""

import asyncio

import pytest
from pytest_httpserver import HTTPServer

from browser_use.browser import BrowserSession
from browser_use.browser.profile import BrowserProfile


@pytest.fixture
def download_server(httpserver: HTTPServer):
	httpserver.expect_request('/report.csv').respond_with_data(
		'name,value\nalpha,1\nbeta,2\n',
		content_type='text/csv',
		headers={'Content-Disposition': 'attachment; filename="report.csv"'},
	)
	httpserver.expect_request('/document.pdf').respond_with_data(
		b'%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n',
		content_type='application/pdf',
	)
	return httpserver


async def _visit_and_list_downloads(server: HTTPServer, tmp_path, accept_downloads: bool, path: str) -> list[str]:
	downloads_path = tmp_path / 'downloads'
	session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			user_data_dir=None,
			keep_alive=False,
			enable_default_extensions=False,
			accept_downloads=accept_downloads,
			downloads_path=downloads_path,
		)
	)
	await session.start()
	try:
		try:
			await session.navigate_to(server.url_for(path))
		except RuntimeError as e:
			# Navigating to a download (allowed or denied) aborts the navigation; anything else is a real failure
			if 'net::ERR_ABORTED' not in str(e):
				raise
		await asyncio.sleep(3)
	finally:
		await session.kill()
		await session.event_bus.stop(clear=True, timeout=5)
	return sorted(f.name for f in downloads_path.iterdir() if f.is_file()) if downloads_path.exists() else []


async def test_attachment_is_saved_when_downloads_accepted(download_server, tmp_path):
	files = await _visit_and_list_downloads(download_server, tmp_path, accept_downloads=True, path='/report.csv')
	assert 'report.csv' in files


async def test_attachment_is_not_saved_when_downloads_disabled(download_server, tmp_path):
	files = await _visit_and_list_downloads(download_server, tmp_path, accept_downloads=False, path='/report.csv')
	assert files == []


async def test_pdf_is_auto_downloaded_when_downloads_accepted(download_server, tmp_path):
	files = await _visit_and_list_downloads(download_server, tmp_path, accept_downloads=True, path='/document.pdf')
	assert 'document.pdf' in files


async def test_pdf_is_not_auto_downloaded_when_downloads_disabled(download_server, tmp_path):
	files = await _visit_and_list_downloads(download_server, tmp_path, accept_downloads=False, path='/document.pdf')
	assert files == []
