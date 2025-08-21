"""Simple test to verify basic download functionality"""

import asyncio
import tempfile
from pathlib import Path

import pytest
from playwright.async_api import async_playwright
from pytest_httpserver import HTTPServer

from browser_use.browser import BrowserSession
from browser_use.browser.profile import BrowserProfile


async def test_simple_playwright_download():
	"""Test basic Playwright download functionality without browser-use - this just validates the browser setup"""

	async with async_playwright() as p:
		# Create temp directory for downloads
		with tempfile.TemporaryDirectory() as tmpdir:
			downloads_path = Path(tmpdir) / 'downloads'
			downloads_path.mkdir()

			# Launch browser
			browser = await p.chromium.launch(headless=True)

			# Create context with downloads enabled
			context = await browser.new_context(accept_downloads=True)

			page = await context.new_page()

			# Create a simple HTML page with download link
			html_content = """
			<!DOCTYPE html>
			<html>
			<body>
				<a href="data:text/plain;base64,SGVsbG8gV29ybGQ=" download="test.txt">Download Test File</a>
			</body>
			</html>
			"""

			await page.set_content(html_content)

			# Set up download handling
			downloads = []
			page.on('download', lambda download: downloads.append(download))

			# Click download link
			await page.click('a[download]')

			# Wait for download to be triggered
			await asyncio.sleep(1)

			# Verify download was triggered
			assert len(downloads) > 0, 'No download was triggered'

			download = downloads[0]

			# Save the download to our test directory
			download_path = downloads_path / download.suggested_filename
			await download.save_as(str(download_path))

			# Verify file was saved and has correct content
			assert download_path.exists(), f'Downloaded file not found at {download_path}'
			assert download_path.read_text() == 'Hello World', 'Downloaded file has incorrect content'

			print('✅ Basic Playwright download test passed!')

			await context.close()
			await browser.close()


@pytest.fixture(scope='function')
def http_server():
	"""Create a test HTTP server with a downloadable file."""
	server = HTTPServer()
	server.start()

	# Add a route that serves a downloadable text file
	server.expect_request('/download/test.txt').respond_with_data(
		'Hello BrowserUse', content_type='text/plain', headers={'Content-Disposition': 'attachment; filename="test.txt"'}
	)

	yield server
	server.stop()


async def test_browser_use_download_with_http_server(http_server):
	"""Test browser-use download with HTTP server and event coordination"""

	with tempfile.TemporaryDirectory() as tmpdir:
		downloads_path = Path(tmpdir) / 'downloads'
		downloads_path.mkdir()

		browser_session = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				downloads_path=str(downloads_path),
				user_data_dir=None,
			)
		)

		await browser_session.start()
		# Cannot get page directly - need to use events
		# page = await browser_session.get_current_page() - removed

		# Create HTML page with download link pointing to HTTP server
		base_url = f'http://{http_server.host}:{http_server.port}'
		html_content = f"""
		<!DOCTYPE html>
		<html>
		<body>
			<h1>Download Test</h1>
			<a id="download-link" href="{base_url}/download/test.txt">Download Test File</a>
		</body>
		</html>
		"""

		# Set content using CDP
		cdp_session = await browser_session.get_or_create_cdp_session()
		await cdp_session.cdp_client.send.Page.setDocumentContent(
			params={'frameId': cdp_session.cdp_client.page_frame_id, 'html': html_content}, session_id=cdp_session.session_id
		)

		# Wait a moment for DOM to be ready
		await asyncio.sleep(0.5)

		# Click the download link using events
		state = await browser_session.get_browser_state_summary()
		download_link = None
		for idx, element in state.dom_state.selector_map.items():
			if element.attributes.get('id') == 'download-link':
				download_link = element
				break

		assert download_link is not None, 'Download link not found'
		from browser_use.browser.events import ClickElementEvent

		click_event = browser_session.event_bus.dispatch(ClickElementEvent(node=download_link))
		await click_event

		# Wait for the DownloadsWatchdog to process the download by expecting the FileDownloadedEvent
		from browser_use.browser.events import FileDownloadedEvent

		try:
			download_event = await browser_session.event_bus.expect(FileDownloadedEvent, timeout=10.0)
			assert isinstance(download_event, FileDownloadedEvent)
			print(f'📁 Download completed: {download_event.file_name} ({download_event.file_size} bytes)')
		except TimeoutError:
			print('❌ Download did not complete within timeout')
			raise AssertionError('Download event not received within timeout')

		# Verify file exists in downloads directory
		expected_file = downloads_path / 'test.txt'
		assert expected_file.exists()
		assert expected_file.read_text() == 'Hello BrowserUse'

		print('✅ BrowserUse HTTP server download test passed!')

		# Check if browser_session sees the downloaded file
		downloaded_files = browser_session.downloaded_files
		print(f'Downloaded files seen by browser_session: {downloaded_files}')

		await browser_session.stop()


if __name__ == '__main__':
	import sys

	if len(sys.argv) > 1 and sys.argv[1] == 'playwright':
		asyncio.run(test_simple_playwright_download())
	elif len(sys.argv) > 1 and sys.argv[1] == 'browseruse':
		# Run the HTTP server test
		server = HTTPServer()
		server.start()
		server.expect_request('/download/test.txt').respond_with_data(
			'Hello BrowserUse', content_type='text/plain', headers={'Content-Disposition': 'attachment; filename="test.txt"'}
		)
		try:
			asyncio.run(test_browser_use_download_with_http_server(server))
		finally:
			server.stop()
	else:
		print('Usage: python test_browser_session_downloads_simple.py [playwright|browseruse]')
