"""Test DownloadsWatchdog functionality."""

import asyncio
import os
import time
from pathlib import Path

import pytest
from werkzeug.wrappers import Response

from browser_use.browser.events import (
	BrowserConnectedEvent,
	BrowserStartEvent,
	BrowserStopEvent,
	BrowserStoppedEvent,
	ClickElementEvent,
	FileDownloadedEvent,
)
from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession


@pytest.fixture(scope='function')
async def download_test_server(httpserver):
	"""Setup test HTTP server with download endpoints."""
	html_content = """
	<!DOCTYPE html>
	<html>
	<head>
		<title>Download Test Page</title>
	</head>
	<body>
		<h1>Download Test</h1>
		<a href="/download/test.pdf" download>Download PDF</a>
		<a href="/download/test.txt" download>Download Text</a>
	</body>
	</html>
	"""
	httpserver.expect_request('/').respond_with_data(html_content, content_type='text/html')

	# Set up PDF download with proper headers to force download
	def pdf_handler(request):
		return Response(
			b'%PDF-1.4 fake pdf content',
			content_type='application/pdf',
			headers={'Content-Disposition': 'attachment; filename="test.pdf"', 'Content-Length': '25'},
		)

	def txt_handler(request):
		return Response(
			b'Test text file content',
			content_type='text/plain',
			headers={'Content-Disposition': 'attachment; filename="test.txt"', 'Content-Length': '23'},
		)

	httpserver.expect_request('/download/test.pdf').respond_with_handler(pdf_handler)
	httpserver.expect_request('/download/test.txt').respond_with_handler(txt_handler)
	return httpserver


@pytest.mark.asyncio
async def test_downloads_watchdog_lifecycle():
	"""Test that DownloadsWatchdog starts and stops with browser session."""
	# Use temp directory for downloads
	import tempfile

	with tempfile.TemporaryDirectory() as temp_dir:
		downloads_path = Path(temp_dir)

		profile = BrowserProfile(headless=True, downloads_path=downloads_path)
		session = BrowserSession(browser_profile=profile)

		try:
			# Start browser
			session.event_bus.dispatch(BrowserStartEvent())
			await session.event_bus.expect(BrowserConnectedEvent, timeout=5.0)

			# Verify downloads watchdog was created
			assert hasattr(session, '_downloads_watchdog'), 'DownloadsWatchdog should be created'
			assert session._downloads_watchdog is not None, 'DownloadsWatchdog should not be None'

			# Verify downloads path is configured
			assert session.browser_profile.downloads_path == downloads_path

		finally:
			# Clean shutdown
			try:
				session.event_bus.dispatch(BrowserStopEvent())
				await session.event_bus.expect(BrowserStoppedEvent, timeout=3.0)
			except Exception:
				# If graceful shutdown fails, force cleanup
				await session.kill()
			# Always stop event bus to prevent hanging
			await session.event_bus.stop(clear=True, timeout=5)


@pytest.mark.asyncio
async def test_downloads_watchdog_file_detection(download_test_server):
	"""Test that DownloadsWatchdog detects file downloads."""
	# Use temp directory for downloads
	import tempfile

	with tempfile.TemporaryDirectory() as temp_dir:
		downloads_path = Path(temp_dir)

		profile = BrowserProfile(headless=True, downloads_path=downloads_path)
		session = BrowserSession(browser_profile=profile)

		# Track FileDownloadedEvents
		download_events = []
		session.event_bus.on(FileDownloadedEvent, lambda e: download_events.append(e))

		try:
			# Start browser
			session.event_bus.dispatch(BrowserStartEvent())
			await session.event_bus.expect(BrowserConnectedEvent, timeout=5.0)

			# Navigate to test page
			test_url = download_test_server.url_for('/')
			await session.event_bus.dispatch(NavigateToUrlEvent(url=test_url))

			# Click download link to trigger download
			await session.event_bus.dispatch(
				ClickElementEvent(element_node=session.get_element_node('a[href="/download/test.pdf"]'))
			)

			# Wait for download to complete
			await asyncio.sleep(2.0)

			# Verify file was downloaded with correct content
			downloaded_files = list(downloads_path.glob('*.pdf'))
			assert len(downloaded_files) > 0, 'PDF download must succeed - no files downloaded is not acceptable'

			downloaded_file = downloaded_files[0]
			assert downloaded_file.exists(), f'Downloaded PDF file must exist: {downloaded_file}'

			# Verify file size and content (we sent 'fake pdf content' which is 25 bytes)
			file_size = downloaded_file.stat().st_size
			assert file_size == 25, f'Downloaded PDF must be 25 bytes (fake pdf content), got {file_size} bytes'

			file_content = downloaded_file.read_bytes()
			expected_content = b'%PDF-1.4 fake pdf content'
			assert file_content == expected_content, (
				f'Downloaded PDF content must match. Expected: {expected_content!r}, got: {file_content!r}'
			)

			# Verify FileDownloadedEvent was emitted
			pdf_events = [e for e in download_events if 'pdf' in e.path.lower()]
			assert len(pdf_events) > 0, 'FileDownloadedEvent must be dispatched for PDF download'

			print(f'✅ PDF download successful: {downloaded_file} ({file_size} bytes) with correct content')

		finally:
			# Clean shutdown
			try:
				session.event_bus.dispatch(BrowserStopEvent())
				await session.event_bus.expect(BrowserStoppedEvent, timeout=3.0)
			except Exception:
				# If graceful shutdown fails, force cleanup
				await session.kill()
			# Always stop event bus to prevent hanging
			await session.event_bus.stop(clear=True, timeout=5)


@pytest.mark.asyncio
async def test_downloads_watchdog_page_attachment():
	"""Test that DownloadsWatchdog attaches to pages properly."""
	# Use temp directory for downloads
	import tempfile

	with tempfile.TemporaryDirectory() as temp_dir:
		downloads_path = Path(temp_dir)

		profile = BrowserProfile(headless=True, downloads_path=downloads_path)
		session = BrowserSession(browser_profile=profile)

		try:
			# Start browser
			session.event_bus.dispatch(BrowserStartEvent())
			await session.event_bus.expect(BrowserConnectedEvent, timeout=5.0)

			# Get downloads watchdog
			downloads_watchdog = session._downloads_watchdog
			assert downloads_watchdog is not None

			# Navigate to create a new page
			await session.navigate('data:text/html,<h1>Test Page</h1>')

			# Verify watchdog has pages with listeners
			assert hasattr(downloads_watchdog, '_pages_with_listeners')

			# Give it a moment for page attachment
			await asyncio.sleep(0.2)

			# The watchdog should have attached to at least one page
			# Note: We can't easily verify the internal WeakSet without accessing private attrs

		finally:
			# Clean shutdown
			try:
				session.event_bus.dispatch(BrowserStopEvent())
				await session.event_bus.expect(BrowserStoppedEvent, timeout=3.0)
			except Exception:
				# If graceful shutdown fails, force cleanup
				await session.kill()
			# Always stop event bus to prevent hanging
			await session.event_bus.stop(clear=True, timeout=5)


@pytest.mark.asyncio
async def test_downloads_watchdog_default_downloads_path():
	"""Test that DownloadsWatchdog works with default downloads path."""
	# Don't specify downloads_path - should use default
	profile = BrowserProfile(headless=True)
	session = BrowserSession(browser_profile=profile)

	try:
		# Start browser
		session.event_bus.dispatch(BrowserStartEvent())
		await session.event_bus.expect(BrowserConnectedEvent, timeout=5.0)

		# Verify downloads watchdog was created
		assert hasattr(session, '_downloads_watchdog'), 'DownloadsWatchdog should be created'
		assert session._downloads_watchdog is not None, 'DownloadsWatchdog should not be None'

		# Verify default downloads path was set by BrowserProfile
		assert session.browser_profile.downloads_path is not None
		assert Path(session.browser_profile.downloads_path).exists()

	finally:
		# Clean shutdown
		try:
			session.event_bus.dispatch(BrowserStopEvent())
			await session.event_bus.expect(BrowserStoppedEvent, timeout=3.0)
		except Exception:
			# If graceful shutdown fails, force cleanup
			await session.kill()
		# Always stop event bus to prevent hanging
		await session.event_bus.stop(clear=True, timeout=5)


@pytest.mark.asyncio
async def test_unique_downloads_directories():
	"""Test that different browser profiles get unique downloads directories."""
	# Create two profiles without specifying downloads_path
	profile1 = BrowserProfile(headless=True)
	profile2 = BrowserProfile(headless=True)

	# Ensure they have different downloads paths
	assert profile1.downloads_path != profile2.downloads_path
	assert profile1.downloads_path is not None
	assert profile2.downloads_path is not None

	# Ensure both directories exist
	assert Path(profile1.downloads_path).exists()
	assert Path(profile2.downloads_path).exists()

	# Ensure they are both under the temp directory with the correct prefix
	import tempfile

	temp_dir = Path(tempfile.gettempdir())
	assert Path(profile1.downloads_path).parent == temp_dir
	assert Path(profile2.downloads_path).parent == temp_dir
	assert 'browser-use-downloads-' in str(profile1.downloads_path)
	assert 'browser-use-downloads-' in str(profile2.downloads_path)

	print(f'✅ Profile 1 downloads path: {profile1.downloads_path}')
	print(f'✅ Profile 2 downloads path: {profile2.downloads_path}')

	# Test that explicit downloads_path is preserved
	with tempfile.TemporaryDirectory() as tmpdir:
		explicit_path = Path(tmpdir) / 'custom-downloads'
		explicit_path.mkdir()

		profile3 = BrowserProfile(headless=True, downloads_path=str(explicit_path))
		assert profile3.downloads_path and Path(profile3.downloads_path) == explicit_path
		print(f'✅ Explicit downloads path preserved: {profile3.downloads_path}')


@pytest.fixture(scope='function')
async def comprehensive_download_test_server(httpserver):
	"""Setup test HTTP server with comprehensive download test page."""
	html_content = """
	<!DOCTYPE html>
	<html>
	<head>
		<title>Test Page</title>
	</head>
	<body>
		<h1>Test Page</h1>
		<button id="test-button" onclick="document.getElementById('result').innerText = 'Clicked!'">
			Click Me
		</button>
		<p id="result"></p>
		<a href="/download/test.pdf" download>Download PDF</a>
	</body>
	</html>
	"""
	httpserver.expect_request('/').respond_with_data(html_content, content_type='text/html')

	# Set up PDF download with proper headers to force download
	def pdf_handler(request):
		return Response(
			b'PDF content',
			content_type='application/pdf',
			headers={'Content-Disposition': 'attachment; filename="test.pdf"', 'Content-Length': '11'},
		)

	httpserver.expect_request('/download/test.pdf').respond_with_handler(pdf_handler)
	return httpserver


@pytest.mark.asyncio
async def test_downloads_watchdog_detection_timing(comprehensive_download_test_server, tmp_path):
	"""Test that download detection adds appropriate delay to clicks when downloads_dir is set."""

	# Test 1: With downloads_dir set (default behavior)
	browser_with_downloads = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			downloads_path=str(tmp_path / 'downloads'),
			user_data_dir=None,
		)
	)

	await browser_with_downloads.start()
	page = await browser_with_downloads.get_current_page()
	await page.goto(comprehensive_download_test_server.url_for('/'))

	# Get the actual DOM state to find the button
	state = await browser_with_downloads.get_browser_state_summary()

	# Find the button element
	button_node = None
	for elem in state.selector_map.values():
		if elem.tag_name == 'button' and elem.attributes.get('id') == 'test-button':
			button_node = elem
			break

	if button_node is None:
		# Try alternative approach - find by text content or use Playwright directly
		await page.wait_for_selector('#test-button', timeout=5000)
		# Use a simpler approach with playwright locator for timing test
		start_time = time.time()
		await page.click('#test-button')
		duration_with_downloads = time.time() - start_time

		# Verify click worked
		result_text = await page.locator('#result').text_content()
		assert result_text == 'Clicked!'
	else:
		# Time the click using browser session method
		start_time = time.time()
		event = browser_with_downloads.event_bus.dispatch(ClickElementEvent(element_node=button_node))
		await event
		result = await event.event_result()
		result = result.get('download_path') if result else None
		duration_with_downloads = time.time() - start_time

		# Verify click worked
		result_text = await page.locator('#result').text_content()
		assert result_text == 'Clicked!'
		assert result is None  # No download happened

	await browser_with_downloads.close()
	await browser_with_downloads.event_bus.stop(clear=True, timeout=5)

	# Test 2: With downloads_dir set to None (disables download detection)
	browser_no_downloads = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			downloads_path=None,
			user_data_dir=None,
		)
	)

	await browser_no_downloads.start()
	page = await browser_no_downloads.get_current_page()
	await page.goto(comprehensive_download_test_server.url_for('/'))

	# Clear previous result
	await page.evaluate('document.getElementById("result").innerText = ""')

	# Get the DOM state again for the new browser session
	state = await browser_no_downloads.get_browser_state_summary()

	# Find the button element again
	button_node = None
	for elem in state.selector_map.values():
		if elem.tag_name == 'button' and elem.attributes.get('id') == 'test-button':
			button_node = elem
			break

	if button_node is None:
		# Use Playwright directly as fallback
		await page.wait_for_selector('#test-button', timeout=5000)
		start_time = time.time()
		await page.click('#test-button')
		duration_no_downloads = time.time() - start_time
	else:
		# Time the click using browser session method
		start_time = time.time()
		event = browser_no_downloads.event_bus.dispatch(ClickElementEvent(element_node=button_node))
		await event
		result = await event.event_result()
		result = result.get('download_path') if result else None
		duration_no_downloads = time.time() - start_time

	# Verify click worked
	result_text = await page.locator('#result').text_content()
	assert result_text == 'Clicked!'

	await browser_no_downloads.close()
	await browser_no_downloads.event_bus.stop(clear=True, timeout=5)

	# Check timing differences
	print(f'Click with downloads_dir: {duration_with_downloads:.2f}s')
	print(f'Click without downloads_dir: {duration_no_downloads:.2f}s')
	print(f'Difference: {duration_with_downloads - duration_no_downloads:.2f}s')

	# Both should be fast now since we're clicking a button (not a download link)
	assert duration_with_downloads < 8, f'Expected <8s with downloads_dir, got {duration_with_downloads:.2f}s'
	assert duration_no_downloads < 3, f'Expected <3s without downloads_dir, got {duration_no_downloads:.2f}s'


@pytest.mark.asyncio
async def test_downloads_watchdog_actual_download_detection(comprehensive_download_test_server, tmp_path):
	"""Test that DownloadsWatchdog detects actual downloads correctly."""

	downloads_path = tmp_path / 'downloads'
	downloads_path.mkdir()

	# Don't use user_data_dir - it seems to complicate downloads
	browser_session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			downloads_path=str(downloads_path),
			user_data_dir=None,  # Use temporary context
		)
	)

	await browser_session.start()
	page = await browser_session.get_current_page()
	await page.goto(comprehensive_download_test_server.url_for('/'))

	# Get the DOM state to find the download link
	state = await browser_session.get_browser_state_summary()

	# Find the download link element
	download_node = None
	for elem in state.selector_map.values():
		if elem.tag_name == 'a' and 'download' in elem.attributes:
			download_node = elem
			break

	assert download_node is not None, 'Could not find download link element'

	# Debug: Log what we're about to click
	print(f'Clicking download link with href: {download_node.attributes.get("href")}')
	print(f'Download link has download attribute: {"download" in download_node.attributes}')

	# Since the link has a download attribute, it will trigger a download, not navigation
	# The downloads watchdog will handle the download automatically
	start_time = time.time()

	# We don't need our own download handler - let the downloads watchdog handle it

	# Click the download link with expect_download=True
	event = browser_session.event_bus.dispatch(ClickElementEvent(element_node=download_node))
	await event
	duration = time.time() - start_time

	print(f'Click completed in {duration:.2f}s')

	# Wait for download to be processed
	await asyncio.sleep(2.0)

	# Check if we're still on the same page (download attribute prevents navigation)
	current_url = page.url
	print(f'Current URL after click: {current_url}')
	print('Download was handled by downloads watchdog')

	# Wait a bit more
	await asyncio.sleep(1.0)

	# Check the downloaded files using the browser_session property
	downloaded_files = browser_session.downloaded_files

	# Debug: check the downloads directory
	print(f'Downloads directory: {downloads_path}')
	print(f'Directory exists: {os.path.exists(downloads_path)}')
	if os.path.exists(downloads_path):
		files = os.listdir(downloads_path)
		print(f'Files in downloads directory: {files}')

	# Verify files were actually downloaded with correct content
	assert len(downloaded_files) > 0, 'Download must succeed - no files downloaded is not acceptable'

	# Check the most recent download
	latest_download = downloaded_files[0]  # Files are sorted by newest first
	assert 'test.pdf' in latest_download, f'Downloaded file should be named test.pdf, got: {latest_download}'
	assert os.path.exists(latest_download), f'Downloaded file must exist on disk: {latest_download}'

	# Verify the file has the correct content and size
	file_size = os.path.getsize(latest_download)
	assert file_size == 11, f'Downloaded file must be 11 bytes (PDF content), got {file_size} bytes'

	# Verify the actual file content matches what the server sent
	file_content = Path(latest_download).read_bytes()
	expected_content = b'PDF content'
	assert file_content == expected_content, (
		f'Downloaded file content must match. Expected: {expected_content!r}, got: {file_content!r}'
	)

	print(f'✅ Download successful: {latest_download} ({file_size} bytes) with correct content: {file_content!r}')

	await browser_session.close()
	await browser_session.event_bus.stop(clear=True, timeout=5)


@pytest.mark.asyncio
async def test_downloads_watchdog_event_dispatching(comprehensive_download_test_server, tmp_path):
	"""Test that FileDownloadedEvent is properly dispatched by DownloadsWatchdog."""
	downloads_path = tmp_path / 'downloads'
	downloads_path.mkdir()

	browser_session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			downloads_path=str(downloads_path),
			user_data_dir=None,
		)
	)

	try:
		await browser_session.start()
		page = await browser_session.get_current_page()
		await page.goto(comprehensive_download_test_server.url_for('/'))

		# Get initial event history count
		initial_history_count = len(browser_session.event_bus.event_history)

		# Click download link - this should trigger FileDownloadedEvent
		download_link = page.locator('a[download]')
		await download_link.click()

		# Wait for download to complete and event to be dispatched
		await asyncio.sleep(3.0)

		# Check that FileDownloadedEvent was dispatched
		event_history = list(browser_session.event_bus.event_history.values())
		download_events = [e for e in event_history if isinstance(e, FileDownloadedEvent)]

		# FileDownloadedEvent must be dispatched - no failures accepted
		assert len(download_events) >= 1, 'FileDownloadedEvent must be dispatched when download succeeds - no failures acceptable'

		# Verify the event contains correct information
		latest_download_event = download_events[-1]
		assert latest_download_event.path is not None, 'FileDownloadedEvent must have a valid path'
		assert 'test.pdf' in latest_download_event.path, (
			f'FileDownloadedEvent path should contain test.pdf, got: {latest_download_event.path}'
		)
		assert os.path.exists(latest_download_event.path), (
			f'FileDownloadedEvent path must exist on disk: {latest_download_event.path}'
		)

		# Verify the downloaded file has correct content and size
		file_size = os.path.getsize(latest_download_event.path)
		assert file_size == 11, f'Downloaded file from event must be 11 bytes (PDF content), got {file_size} bytes'

		file_content = Path(latest_download_event.path).read_bytes()
		expected_content = b'PDF content'
		assert file_content == expected_content, (
			f'Downloaded file content must match. Expected: {expected_content!r}, got: {file_content!r}'
		)

		print(
			f'✅ FileDownloadedEvent dispatched correctly for: {latest_download_event.path} ({file_size} bytes) with correct content: {file_content!r}'
		)

	finally:
		await browser_session.kill()
		await browser_session.event_bus.stop(clear=True, timeout=5)
