from browser_use.browser.events import FileDownloadedEvent
from browser_use.browser.session import BrowserSession
from browser_use.browser.watchdogs.downloads_watchdog import DownloadsWatchdog, _should_auto_download_network_response


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


async def test_remote_cdp_download_completion_notifies_direct_callback(tmp_path):
	browser_session = BrowserSession(downloads_path=tmp_path)
	watchdog = DownloadsWatchdog(event_bus=browser_session.event_bus, browser_session=browser_session)
	watchdog._cdp_downloads_info = {
		'guid-123': {
			'url': 'https://example.test/report.csv',
			'suggested_filename': 'report.csv',
		}
	}

	try:
		completed = []
		watchdog.register_download_callbacks(on_complete=completed.append)

		watchdog._handle_remote_cdp_download_completed(guid='guid-123', file_path=None)

		assert completed == [
			{
				'guid': 'guid-123',
				'url': 'https://example.test/report.csv',
				'path': str(tmp_path / 'report.csv'),
				'file_name': 'report.csv',
				'file_size': 0,
				'file_type': 'csv',
				'auto_download': False,
			}
		]
		assert watchdog._cdp_downloads_info == {}
		file_downloaded_events = [
			event for event in browser_session.event_bus.event_history.values() if isinstance(event, FileDownloadedEvent)
		]
		assert len(file_downloaded_events) == 1
		file_downloaded_event = file_downloaded_events[0]
		assert file_downloaded_event.guid == 'guid-123'
		assert file_downloaded_event.url == 'https://example.test/report.csv'
		assert file_downloaded_event.path == str(tmp_path / 'report.csv')
		assert file_downloaded_event.file_name == 'report.csv'
		assert file_downloaded_event.file_size == 0
		assert file_downloaded_event.file_type == 'csv'
	finally:
		await browser_session.event_bus.stop(clear=True, timeout=1)
