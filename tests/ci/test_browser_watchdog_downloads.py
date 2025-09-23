"""Test downloads watchdog functionality."""

import asyncio
import tempfile
from pathlib import Path

import pytest
from pytest_httpserver import HTTPServer

from browser_use.browser import BrowserSession
from browser_use.browser.events import (
	BrowserConnectedEvent,
	BrowserStartEvent,
	BrowserStopEvent,
	BrowserStoppedEvent,
	NavigateToUrlEvent,
)
from browser_use.browser.profile import BrowserProfile


@pytest.mark.skip(reason='TODO: fix')
async def test_downloads_watchdog_lifecycle():
	"""Test that DownloadsWatchdog starts and stops with browser session."""

	# Create temp directory for downloads
	with tempfile.TemporaryDirectory() as temp_dir:
		downloads_path = Path(temp_dir)

		profile = BrowserProfile(headless=True, downloads_path=downloads_path)
		session = BrowserSession(browser_profile=profile)

		# Check that downloads watchdog is None initially
		assert session._downloads_watchdog is None

		try:
			# Start browser
			session.event_bus.dispatch(BrowserStartEvent())
			await session.event_bus.expect(BrowserConnectedEvent, timeout=5.0)

			# Check that downloads watchdog is attached
			assert session._downloads_watchdog is not None

			# Verify watchdog has proper session reference
			assert session._downloads_watchdog.browser_session is session

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


@pytest.mark.skip(reason='TODO: fix')
async def test_downloads_watchdog_file_detection(download_test_server):
	"""Test that DownloadsWatchdog detects file downloads."""

	# Create temp directory for downloads
	with tempfile.TemporaryDirectory() as temp_dir:
		downloads_path = Path(temp_dir)

		profile = BrowserProfile(headless=True, downloads_path=downloads_path)
		session = BrowserSession(browser_profile=profile)

		try:
			# Start browser
			session.event_bus.dispatch(BrowserStartEvent())
			await session.event_bus.expect(BrowserConnectedEvent, timeout=5.0)

			# Navigate to test page
			test_url = download_test_server.url_for('/')
			await session.event_bus.dispatch(NavigateToUrlEvent(url=test_url))

			# Skip complex element selection for now - would need to implement selector-to-index conversion
			pytest.skip('Complex element selection needs refactoring for CDP events')

			# Wait for download to complete
			await asyncio.sleep(2.0)

			# Verify file was downloaded
			downloaded_files = list(downloads_path.glob('*'))
			assert len(downloaded_files) == 1, f'Expected 1 file, got {len(downloaded_files)}: {downloaded_files}'

			# Verify file content
			downloaded_file = downloaded_files[0]
			assert downloaded_file.name == 'test.pdf'
			assert downloaded_file.read_bytes() == b'PDF content'

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


@pytest.fixture
def comprehensive_download_test_server():
	"""Create a test server with downloadable files."""
	httpserver = HTTPServer(host='127.0.0.1', port=0)
	httpserver.start()

	# Serve a main page with download links
	main_page_html = """
	<!DOCTYPE html>
	<html>
	<head>
		<title>Download Test Page</title>
	</head>
	<body>
		<h1>Download Test Page</h1>
		<a href="/download/test.pdf" download="test.pdf">Download PDF</a>
		<br>
		<a href="/download/test.txt" download="test.txt">Download Text</a>
	</body>
	</html>
	"""

	httpserver.expect_request('/').respond_with_data(main_page_html, content_type='text/html')

	# PDF handler
	httpserver.expect_request('/download/test.pdf').respond_with_data(
		b'PDF content', status=200, headers={'Content-Type': 'application/pdf'}
	)

	# Text handler
	httpserver.expect_request('/download/test.txt').respond_with_data(
		b'Text content', status=200, headers={'Content-Type': 'text/plain'}
	)

	yield httpserver
	httpserver.stop()


# @pytest.mark.asyncio
# async def test_downloads_watchdog_page_attachment():
# 	"""Test that DownloadsWatchdog attaches to pages properly."""

# 	# Create temp directory for downloads
# 	with tempfile.TemporaryDirectory() as temp_dir:
# 		downloads_path = Path(temp_dir)

# 		profile = BrowserProfile(headless=True, downloads_path=downloads_path)
# 		session = BrowserSession(browser_profile=profile)

# 		try:
# 			# Start browser
# 			session.event_bus.dispatch(BrowserStartEvent())
# 			await session.event_bus.expect(BrowserConnectedEvent, timeout=5.0)

# 			# Get downloads watchdog
# 			downloads_watchdog = session._downloads_watchdog
# 			assert downloads_watchdog is not None

# 			# Navigate to create a new page
# 			event = session.event_bus.dispatch(NavigateToUrlEvent(url='data:text/html,<h1>Test Page</h1>'))
# 			await event
# 			await event.event_result(raise_if_any=True, raise_if_none=False)

# 			# Verify watchdog has pages with listeners
# 			assert hasattr(downloads_watchdog, '_pages_with_listeners')

# 			# Give it a moment for page attachment
# 			await asyncio.sleep(0.2)

# 			# The watchdog should have attached to at least one page
# 			# Note: We can't easily verify the internal WeakSet without accessing private attrs

# 		finally:
# 			# Clean shutdown
# 			try:
# 				session.event_bus.dispatch(BrowserStopEvent())
# 				await session.event_bus.expect(BrowserStoppedEvent, timeout=3.0)
# 			except Exception:
# 				# If graceful shutdown fails, force cleanup
# 				await session.kill()
# 			# Always stop event bus to prevent hanging
# 			await session.event_bus.stop(clear=True, timeout=5)


# @pytest.mark.asyncio
# async def test_downloads_watchdog_default_downloads_path():
# 	"""Test that DownloadsWatchdog works with default downloads path."""

# 	# Don't specify downloads path - should use default
# 	profile = BrowserProfile(headless=True)
# 	session = BrowserSession(browser_profile=profile)

# 	try:
# 		# Start browser
# 		session.event_bus.dispatch(BrowserStartEvent())
# 		await session.event_bus.expect(BrowserConnectedEvent, timeout=5.0)

# 		# Verify downloads watchdog is attached
# 		assert session._downloads_watchdog is not None

# 		# The default downloads path should be set
# 		# Note: We can't easily test the actual download without complex setup

# 	finally:
# 		# Clean shutdown
# 		try:
# 			session.event_bus.dispatch(BrowserStopEvent())
# 			await session.event_bus.expect(BrowserStoppedEvent, timeout=3.0)
# 		except Exception:
# 			# If graceful shutdown fails, force cleanup
# 			await session.kill()
# 		# Always stop event bus to prevent hanging
# 		await session.event_bus.stop(clear=True, timeout=5)


# @pytest.mark.asyncio
# async def test_unique_downloads_directories():
# 	"""Test that different browser profiles get unique downloads directories."""

# 	# Create temp directory for downloads
# 	with tempfile.TemporaryDirectory() as temp_dir:
# 		downloads_path_1 = Path(temp_dir) / 'downloads1'
# 		downloads_path_2 = Path(temp_dir) / 'downloads2'
# 		downloads_path_1.mkdir()
# 		downloads_path_2.mkdir()

# 		profile1 = BrowserProfile(headless=True, downloads_path=downloads_path_1)
# 		profile2 = BrowserProfile(headless=True, downloads_path=downloads_path_2)

# 		session1 = BrowserSession(browser_profile=profile1)
# 		session2 = BrowserSession(browser_profile=profile2)

# 		try:
# 			# Start both browsers
# 			session1.event_bus.dispatch(BrowserStartEvent())
# 			await session1.event_bus.expect(BrowserConnectedEvent, timeout=5.0)

# 			session2.event_bus.dispatch(BrowserStartEvent())
# 			await session2.event_bus.expect(BrowserConnectedEvent, timeout=5.0)

# 			# Verify downloads watchdogs are attached
# 			assert session1._downloads_watchdog is not None
# 			assert session2._downloads_watchdog is not None

# 			# Verify they have different downloads paths
# 			assert session1.browser_profile.downloads_path != session2.browser_profile.downloads_path

# 		finally:
# 			# Clean shutdown both sessions
# 			for session in [session1, session2]:
# 				try:
# 					session.event_bus.dispatch(BrowserStopEvent())
# 					await session.event_bus.expect(BrowserStoppedEvent, timeout=3.0)
# 				except Exception:
# 					# If graceful shutdown fails, force cleanup
# 					await session.kill()
# 				# Always stop event bus to prevent hanging
# 				await session.event_bus.stop(clear=True, timeout=5)


# Removed test_downloads_watchdog_actual_download_detection - complex Playwright patterns not suitable for CDP
