"""Downloads watchdog for monitoring and handling file downloads."""

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import urlparse
from weakref import WeakSet

import anyio
from bubus import BaseEvent
from playwright.async_api import Download, Page
from pydantic import PrivateAttr

from browser_use.browser.events import (
	FileDownloadedEvent,
	NavigationCompleteEvent,
	TabClosedEvent,
	TabCreatedEvent,
)
from browser_use.browser.watchdog_base import BaseWatchdog
from browser_use.utils import logger

if TYPE_CHECKING:
	pass


class DownloadsWatchdog(BaseWatchdog):
	"""Monitors downloads and handles file download events."""

	# Events this watchdog listens to (for documentation)
	LISTENS_TO: ClassVar[list[type[BaseEvent]]] = [
		TabCreatedEvent,
		TabClosedEvent,
		NavigationCompleteEvent,
	]

	# Events this watchdog emits
	EMITS: ClassVar[list[type[BaseEvent]]] = [
		FileDownloadedEvent,
	]

	# Private state
	_pages_with_listeners: WeakSet[Page] = PrivateAttr(
		default_factory=WeakSet
	)  # Track pages that already have download listeners
	_active_downloads: dict[str, Download] = PrivateAttr(default_factory=dict)
	_pdf_viewer_cache: dict[str, bool] = PrivateAttr(default_factory=dict)  # Cache PDF viewer status by page URL

	async def attach_to_session(self) -> None:
		"""Attach to browser session and ensure downloads directory exists."""
		await super().attach_to_session()

		# Ensure downloads directory exists
		downloads_path = self.browser_session.browser_profile.downloads_path
		if downloads_path:
			Path(downloads_path).mkdir(parents=True, exist_ok=True)
			logger.info(f'[DownloadsWatchdog] Ensured downloads directory exists: {downloads_path}')

	async def on_TabCreatedEvent(self, event: TabCreatedEvent) -> None:
		"""Monitor new tabs for downloads."""
		logger.info(f'[DownloadsWatchdog] TabCreatedEvent received for tab {event.tab_index}: {event.url}')

		# Assert downloads path is configured (should always be set by BrowserProfile default)
		assert self.browser_session.browser_profile.downloads_path is not None, 'Downloads path must be configured'

		page = self.browser_session.get_page_by_tab_index(event.tab_index)
		if page:
			logger.info(f'[DownloadsWatchdog] Found page for tab {event.tab_index}, calling attach_to_page')
			await self.attach_to_page(page)
		else:
			logger.warning(f'[DownloadsWatchdog] No page found for tab {event.tab_index}')

	async def on_TabClosedEvent(self, event: TabClosedEvent) -> None:
		"""Stop monitoring closed tabs."""
		pass  # No cleanup needed, browser context handles page lifecycle

	async def on_NavigationCompleteEvent(self, event: NavigationCompleteEvent) -> None:
		"""Check for PDFs after navigation completes."""
		# Clear PDF cache for the navigated URL since content may have changed
		if event.url in self._pdf_viewer_cache:
			del self._pdf_viewer_cache[event.url]

		# Check if auto-download is enabled
		if not self._is_auto_download_enabled():
			return

		page = self.browser_session.get_page_by_tab_index(event.tab_index)
		if page and await self.check_for_pdf_viewer(page):
			logger.info(f'[DownloadsWatchdog] PDF detected after navigation to {event.url}')
			await self.trigger_pdf_download(page)

	def _is_auto_download_enabled(self) -> bool:
		"""Check if PDF auto-download is enabled."""
		return getattr(self.browser_session, '_auto_download_pdfs', True)

	async def attach_to_page(self, page: Page) -> None:
		"""Set up download monitoring for a specific page."""
		try:
			downloads_path_raw = self.browser_session.browser_profile.downloads_path
			if not downloads_path_raw:
				logger.info(f'[DownloadsWatchdog] No downloads path configured, skipping page: {page.url}')
				return  # No downloads path configured

			# Check if we already have a download listener on this page
			# to prevent duplicate listeners from being added
			if page in self._pages_with_listeners:
				logger.debug(f'[DownloadsWatchdog] Download listener already exists for page: {page.url}')
				return

			logger.info(f'[DownloadsWatchdog] Setting up download listener for page: {page.url}')
			# Set up Playwright download event listener
			page.on('download', self._handle_download)
			# Track that we've added a listener to prevent duplicates
			self._pages_with_listeners.add(page)
			logger.info(f'[DownloadsWatchdog] Successfully set up download listener for page: {page.url}')

		except Exception as e:
			logger.warning(f'[DownloadsWatchdog] Failed to set up download listener for page {page.url}: {e}')

	async def _handle_download(self, download: Download) -> None:
		"""Handle a download event."""
		download_id = f'{id(download)}'
		self._active_downloads[download_id] = download
		logger.info(f'[DownloadsWatchdog] Handling download: {download.suggested_filename} from {download.url[:100]}...')

		# Debug: Check if download is already being handled elsewhere
		failure = await download.failure()
		logger.info(f'[DownloadsWatchdog] Download state - canceled: {failure}, url: {download.url}')
		logger.info(f'[DownloadsWatchdog] Active downloads count: {len(self._active_downloads)}')

		try:
			current_step = 'getting_download_info'
			# Get download info immediately
			url = download.url
			suggested_filename = download.suggested_filename

			current_step = 'determining_download_directory'
			# Determine download directory from browser profile
			downloads_dir = self.browser_session.browser_profile.downloads_path
			if not downloads_dir:
				downloads_dir = str(Path.home() / 'Downloads')
			else:
				downloads_dir = str(downloads_dir)  # Ensure it's a string

			current_step = 'generating_unique_filename'
			# Ensure unique filename
			unique_filename = await self._get_unique_filename(downloads_dir, suggested_filename)
			download_path = Path(downloads_dir) / unique_filename

			logger.info(f'[DownloadsWatchdog] Download started: {unique_filename} from {url[:100]}...')

			current_step = 'calling_save_as'
			# Save the download using Playwright's save_as method
			logger.info(f'[DownloadsWatchdog] Saving download to: {download_path}')
			logger.info(f'[DownloadsWatchdog] Download path exists: {download_path.parent.exists()}')
			logger.info(f'[DownloadsWatchdog] Download path writable: {os.access(download_path.parent, os.W_OK)}')

			try:
				logger.info('[DownloadsWatchdog] About to call download.save_as()...')
				await download.save_as(str(download_path))
				logger.info(f'[DownloadsWatchdog] Successfully saved download to: {download_path}')
				current_step = 'save_as_completed'
			except Exception as save_error:
				logger.error(f'[DownloadsWatchdog] save_as() failed with error: {save_error}')
				if 'canceled' in str(save_error).lower():
					# Download was canceled - try using the path method as fallback
					logger.warning(f'[DownloadsWatchdog] save_as() was canceled, trying path() method: {save_error}')
					current_step = 'using_path_fallback'
					try:
						# Use download.path() to access the file that was already downloaded
						source_path = await download.path()
						if source_path and Path(source_path).exists():
							# Move the file from the temporary location to our desired location
							import shutil

							shutil.move(str(source_path), str(download_path))
							logger.info(f'[DownloadsWatchdog] Successfully moved download from {source_path} to: {download_path}')
							current_step = 'path_fallback_completed'
						else:
							raise Exception(f'Downloaded file not found at path: {source_path}')
					except Exception as path_error:
						logger.error(f'[DownloadsWatchdog] Path fallback also failed: {path_error}')
						raise save_error  # Re-raise the original error
				else:
					# Some other save error
					raise save_error

			# Get file info
			file_size = download_path.stat().st_size if download_path.exists() else 0

			# Determine file type from extension
			file_ext = download_path.suffix.lower().lstrip('.')
			file_type = file_ext if file_ext else None

			# Try to get MIME type from response headers if available
			mime_type = None
			# Note: Playwright doesn't expose response headers directly from Download object

			# Check if this was a PDF auto-download
			auto_download = False
			if file_type == 'pdf':
				auto_download = self._is_auto_download_enabled()

			# Emit download event
			self.event_bus.dispatch(
				FileDownloadedEvent(
					url=url,
					path=str(download_path),
					file_name=suggested_filename,
					file_size=file_size,
					file_type=file_type,
					mime_type=mime_type,
					from_cache=False,
					auto_download=auto_download,
				)
			)

			logger.info(
				f'[DownloadsWatchdog] Download completed: {suggested_filename} ({file_size} bytes) saved to {download_path}'
			)

			# File is now tracked on filesystem, no need to track in memory

		except Exception as e:
			logger.error(
				f'[DownloadsWatchdog] Error handling download at step "{locals().get("current_step", "unknown")}", error: {e}'
			)
			logger.error(f'[DownloadsWatchdog] Download state - URL: {download.url}, filename: {download.suggested_filename}')
		finally:
			# Clean up tracking
			if download_id in self._active_downloads:
				del self._active_downloads[download_id]

	async def check_for_pdf_viewer(self, page: Page) -> bool:
		"""Check if the current page is Chrome's built-in PDF viewer.

		Returns True if a PDF is detected and should be downloaded.
		"""
		# Check cache first
		page_url = page.url
		if page_url in self._pdf_viewer_cache:
			return self._pdf_viewer_cache[page_url]

		try:
			# Check if page is still valid before evaluation
			if page.is_closed():
				logger.debug(f'[DownloadsWatchdog] Page is closed, cannot check for PDF: {page_url}')
				self._pdf_viewer_cache[page_url] = False
				return False

			# Add timeout to prevent hanging on unresponsive pages
			import asyncio

			is_pdf_viewer = await asyncio.wait_for(
				page.evaluate("""
				() => {
					// Check for Chrome's built-in PDF viewer (both old and new selectors)
					const pdfEmbed = document.querySelector('embed[type="application/x-google-chrome-pdf"]') ||
									 document.querySelector('embed[type="application/pdf"]');
					if (pdfEmbed && pdfEmbed.src) {
						return {
							isPdf: true,
							url: pdfEmbed.src,
							isChromePdfViewer: true
						};
					}
					
					// Check for direct PDF navigation
					if (document.contentType === 'application/pdf') {
						return {
							isPdf: true,
							url: window.location.href,
							isDirectPdf: true
						};
					}
					
					// Also check if the URL ends with .pdf or has PDF in it
					const url = window.location.href;
					const isPdfUrl = url.toLowerCase().includes('.pdf');
					if (isPdfUrl) {
						return {
							isPdf: true,
							url: url,
							isPdfUrl: true
						};
					}
					
					// Check for PDF in iframe
					const iframes = document.querySelectorAll('iframe');
					for (const iframe of iframes) {
						try {
							const iframeDoc = iframe.contentDocument || iframe.contentWindow.document;
							if (iframeDoc.contentType === 'application/pdf') {
								return {
									isPdf: true,
									url: iframe.src,
									isIframePdf: true
								};
							}
						} catch (e) {
							// Cross-origin iframe, skip
						}
					}
					
					return { isPdf: false };
				}
				"""),
				timeout=5.0,  # 5 second timeout to prevent hanging
			)

			if is_pdf_viewer.get('isPdf', False):
				logger.info(
					f'[DownloadsWatchdog] PDF detected: {is_pdf_viewer.get("url", "unknown")} '
					f'(type: {"Chrome viewer" if is_pdf_viewer.get("isChromePdfViewer") else "direct PDF"})'
				)
				self._pdf_viewer_cache[page_url] = True
				return True

			self._pdf_viewer_cache[page_url] = False
			return False

		except TimeoutError:
			logger.debug(f'[DownloadsWatchdog] PDF check timed out for page: {page_url}')
			self._pdf_viewer_cache[page_url] = False
			return False
		except Exception as e:
			logger.debug(f'[DownloadsWatchdog] Error checking for PDF viewer: {e}')
			self._pdf_viewer_cache[page_url] = False
			return False

	async def trigger_pdf_download(self, page: Page) -> str | None:
		"""Trigger download of a PDF from Chrome's PDF viewer.

		Returns the download path if successful, None otherwise.
		"""
		if not self.browser_session.browser_profile.downloads_path:
			logger.warning('[DownloadsWatchdog] No downloads path configured')
			return None

		try:
			# Check if page is still valid before evaluation
			if page.is_closed():
				logger.debug('[DownloadsWatchdog] Page is closed, cannot trigger PDF download')
				return None

			# Try to get the PDF URL with timeout
			import asyncio

			pdf_info = await asyncio.wait_for(
				page.evaluate("""
				() => {
					const embedElement = document.querySelector('embed[type="application/x-google-chrome-pdf"]') ||
									   document.querySelector('embed[type="application/pdf"]');
					if (embedElement && embedElement.src) {
						return { url: embedElement.src };
					}
					return { url: window.location.href };
				}
				"""),
				timeout=5.0,  # 5 second timeout to prevent hanging
			)

			pdf_url = pdf_info.get('url', '')
			if not pdf_url:
				logger.warning('[DownloadsWatchdog] Could not determine PDF URL for download')
				return None

			# Generate filename from URL
			pdf_filename = os.path.basename(pdf_url.split('?')[0])  # Remove query params
			if not pdf_filename or not pdf_filename.endswith('.pdf'):
				parsed = urlparse(pdf_url)
				pdf_filename = os.path.basename(parsed.path) or 'document.pdf'
				if not pdf_filename.endswith('.pdf'):
					pdf_filename += '.pdf'

			# Check if already downloaded by looking in the downloads directory
			downloads_dir = str(self.browser_session.browser_profile.downloads_path)
			if os.path.exists(downloads_dir):
				existing_files = os.listdir(downloads_dir)
				if pdf_filename in existing_files:
					logger.debug(f'[DownloadsWatchdog] PDF already downloaded: {pdf_filename}')
					return None

			logger.info(f'[DownloadsWatchdog] Auto-downloading PDF from: {pdf_url[:100]}...')

			# Download using JavaScript fetch to leverage browser cache
			try:
				# Properly escape the URL to prevent JavaScript injection
				escaped_pdf_url = json.dumps(pdf_url)

				download_result = await asyncio.wait_for(
					page.evaluate(f"""
					async () => {{
						try {{
							// Use fetch with cache: 'force-cache' to prioritize cached version
							const response = await fetch({escaped_pdf_url}, {{
								cache: 'force-cache'
							}});
							if (!response.ok) {{
								throw new Error(`HTTP error! status: ${{response.status}}`);
							}}
							const blob = await response.blob();
							const arrayBuffer = await blob.arrayBuffer();
							const uint8Array = new Uint8Array(arrayBuffer);
							
							// Check if served from cache
							const fromCache = response.headers.has('age') || 
											 !response.headers.has('date') ||
											 performance.getEntriesByName({escaped_pdf_url}).some(entry => 
												 entry.transferSize === 0 || entry.transferSize < entry.encodedBodySize
											 );
											 
							return {{ 
								data: Array.from(uint8Array),
								fromCache: fromCache,
								responseSize: uint8Array.length,
								transferSize: response.headers.get('content-length') || 'unknown'
							}};
						}} catch (error) {{
							throw new Error(`Fetch failed: ${{error.message}}`);
						}}
					}}
					"""),
					timeout=10.0,  # 10 second timeout for download operation
				)

				if download_result and download_result.get('data') and len(download_result['data']) > 0:
					# Ensure unique filename
					downloads_dir = str(self.browser_session.browser_profile.downloads_path)
					unique_filename = await self._get_unique_filename(downloads_dir, pdf_filename)
					download_path = os.path.join(downloads_dir, unique_filename)

					# Save the PDF asynchronously
					async with await anyio.open_file(download_path, 'wb') as f:
						await f.write(bytes(download_result['data']))

					# File is now tracked on filesystem, no need to track in memory

					# Log cache information
					cache_status = 'from cache' if download_result.get('fromCache') else 'from network'
					response_size = download_result.get('responseSize', 0)
					logger.info(
						f'[DownloadsWatchdog] Auto-downloaded PDF ({cache_status}, {response_size:,} bytes): {download_path}'
					)

					# Emit file downloaded event
					self.event_bus.dispatch(
						FileDownloadedEvent(
							url=pdf_url,
							path=download_path,
							file_name=unique_filename,
							file_size=response_size,
							file_type='pdf',
							mime_type='application/pdf',
							from_cache=download_result.get('fromCache', False),
							auto_download=True,
						)
					)

					return download_path
				else:
					logger.warning(f'[DownloadsWatchdog] No data received when downloading PDF from {pdf_url}')
					return None

			except Exception as e:
				logger.warning(f'[DownloadsWatchdog] Failed to auto-download PDF from {pdf_url}: {type(e).__name__}: {e}')
				return None

		except TimeoutError:
			logger.debug('[DownloadsWatchdog] PDF download operation timed out')
			return None
		except Exception as e:
			logger.error(f'[DownloadsWatchdog] Error in PDF download: {type(e).__name__}: {e}')
			return None

	@staticmethod
	async def _get_unique_filename(directory: str, filename: str) -> str:
		"""Generate a unique filename for downloads by appending (1), (2), etc., if a file already exists."""
		base, ext = os.path.splitext(filename)
		counter = 1
		new_filename = filename
		while os.path.exists(os.path.join(directory, new_filename)):
			new_filename = f'{base} ({counter}){ext}'
			counter += 1
		return new_filename


# Fix Pydantic circular dependency - this will be called from session.py after BrowserSession is defined
