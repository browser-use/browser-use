"""
Regression tests for issue #6028: one FileDownloadedEvent per downloaded file.

A click on a Content-Disposition: attachment link used to be reported twice in tabs with
network monitoring: once by Chrome's browser-level download path (Browser.downloadProgress)
and once by the Network.responseReceived -> download_file_from_url path. Chrome's download
path now owns attachments; the network path only handles inline PDFs.

Usage:
	uv run pytest tests/ci/browser/test_attachment_download_events.py -v -s
"""

import asyncio

import pytest
from pytest_httpserver import HTTPServer

from browser_use.browser import BrowserSession
from browser_use.browser.events import FileDownloadedEvent, NavigateToUrlEvent
from browser_use.browser.profile import BrowserProfile
from browser_use.browser.watchdogs.downloads_watchdog import _should_auto_download_network_response

PDF_BYTES = b'%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n'


@pytest.fixture(scope='session')
def http_server():
	server = HTTPServer()
	server.start()

	server.expect_request('/page').respond_with_data(
		'<html><body><a id="dl" href="/f.zip">zip</a></body></html>',
		content_type='text/html',
	)
	server.expect_request('/pdf-attachment-page').respond_with_data(
		'<html><body><a id="dl" href="/report.pdf">pdf</a></body></html>',
		content_type='text/html',
	)
	server.expect_request('/inline-pdf-page').respond_with_data(
		'<html><body><a id="dl" href="/inline.pdf">pdf</a></body></html>',
		content_type='text/html',
	)
	server.expect_request('/f.zip').respond_with_data(
		b'PK\x05\x06' + b'\x00' * 18,
		content_type='application/zip',
		headers={'Content-Disposition': 'attachment; filename="f.zip"'},
	)
	server.expect_request('/report.pdf').respond_with_data(
		PDF_BYTES,
		content_type='application/pdf',
		headers={'Content-Disposition': 'attachment; filename="report.pdf"'},
	)
	server.expect_request('/inline.pdf').respond_with_data(PDF_BYTES, content_type='application/pdf')

	yield server
	server.stop()


@pytest.fixture(scope='session')
def base_url(http_server):
	return f'http://{http_server.host}:{http_server.port}'


@pytest.fixture(scope='function')
async def browser_session(tmp_path):
	session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			user_data_dir=None,
			keep_alive=True,
			downloads_path=str(tmp_path),
		)
	)
	await session.start()
	yield session
	await session.kill()


async def _click_and_collect_downloads(session: BrowserSession, page_url: str, tab: str) -> list[FileDownloadedEvent]:
	"""Open page_url in the first or a second tab, click #dl, and collect FileDownloadedEvents."""
	events: list[FileDownloadedEvent] = []

	def record(event: FileDownloadedEvent) -> None:
		events.append(event)

	session.event_bus.on(FileDownloadedEvent, record)

	await session.event_bus.dispatch(NavigateToUrlEvent(url=page_url))
	if tab == 'second':
		# The first tab is no longer blank, so this opens (and focuses) a real second tab
		await session.event_bus.dispatch(NavigateToUrlEvent(url=page_url, new_tab=True))
		assert len(session.session_manager.get_all_page_targets()) == 2
	cdp_session = await session.get_or_create_cdp_session()
	await cdp_session.cdp_client.send.Runtime.evaluate(
		params={'expression': "document.getElementById('dl').click()"},
		session_id=cdp_session.session_id,
	)

	# Wait for the first event, then leave time for a duplicate from the other path to arrive
	for _ in range(100):
		if events:
			break
		await asyncio.sleep(0.1)
	await asyncio.sleep(3.0)
	return events


@pytest.mark.parametrize('tab', ['first', 'second'])
async def test_attachment_click_fires_one_download_event(browser_session, base_url, tab, tmp_path):
	events = await _click_and_collect_downloads(browser_session, f'{base_url}/page', tab)
	assert len(events) == 1, [(e.file_name, e.auto_download) for e in events]
	assert events[0].file_name == 'f.zip'
	assert [p.name for p in tmp_path.iterdir()] == ['f.zip']


@pytest.mark.parametrize('tab', ['first', 'second'])
async def test_pdf_attachment_click_fires_one_download_event(browser_session, base_url, tab, tmp_path):
	events = await _click_and_collect_downloads(browser_session, f'{base_url}/pdf-attachment-page', tab)
	assert len(events) == 1, [(e.file_name, e.auto_download) for e in events]
	assert events[0].file_name == 'report.pdf'
	assert [p.name for p in tmp_path.iterdir()] == ['report.pdf']


async def test_inline_pdf_click_fires_one_download_event(browser_session, base_url):
	events = await _click_and_collect_downloads(browser_session, f'{base_url}/inline-pdf-page', 'first')
	assert len(events) == 1, [(e.file_name, e.auto_download) for e in events]
	assert events[0].file_type == 'pdf'


@pytest.mark.parametrize(
	'content_type,is_pdf,filename', [('application/zip', False, 'f.zip'), ('application/pdf', True, 'report.pdf')]
)
@pytest.mark.parametrize('cdp_download_listener_active', [False, True])
def test_network_path_skips_attachments_owned_by_cdp_download_listener(
	content_type, is_pdf, filename, cdp_download_listener_active
):
	assert _should_auto_download_network_response(
		url=f'http://127.0.0.1/{filename}',
		content_type=content_type,
		is_pdf=is_pdf,
		is_download_attachment=True,
		suggested_filename=filename,
		cdp_download_listener_active=cdp_download_listener_active,
	) is (not cdp_download_listener_active)


def test_network_path_keeps_inline_pdf_when_cdp_download_listener_active():
	assert _should_auto_download_network_response(
		url='http://127.0.0.1/inline.pdf',
		content_type='application/pdf',
		is_pdf=True,
		is_download_attachment=False,
		suggested_filename=None,
		cdp_download_listener_active=True,
	)
