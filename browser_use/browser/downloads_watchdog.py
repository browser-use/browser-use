"""Downloads watchdog for monitoring and handling file downloads."""

import asyncio
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar
from urllib.parse import urlparse

import anyio
from bubus import BaseEvent
from pydantic import PrivateAttr

from browser_use.browser.events import (
	BrowserLaunchEvent,
	BrowserStoppedEvent,
	FileDownloadedEvent,
	NavigationCompleteEvent,
	TabClosedEvent,
	TabCreatedEvent,
)
from browser_use.browser.watchdog_base import BaseWatchdog
from cdp_use.cdp.browser import DownloadProgressEvent, DownloadWillBeginEvent

if TYPE_CHECKING:
	pass


class DownloadsWatchdog(BaseWatchdog):
	"""Monitors downloads and handles file download events."""

	# Events this watchdog listens to (for documentation)
	LISTENS_TO: ClassVar[list[type[BaseEvent[Any]]]] = [
		BrowserLaunchEvent,
		BrowserStoppedEvent,
		TabCreatedEvent,
		TabClosedEvent,
		NavigationCompleteEvent,
	]

	# Events this watchdog emits
	EMITS: ClassVar[list[type[BaseEvent[Any]]]] = [
		FileDownloadedEvent,
	]

	# Private state
	_sessions_with_listeners: set[str] = PrivateAttr(default_factory=set)  # Track sessions that already have download listeners
	_active_downloads: dict[str, Any] = PrivateAttr(default_factory=dict)
	_pdf_viewer_cache: dict[str, bool] = PrivateAttr(default_factory=dict)  # Cache PDF viewer status by target URL
	_download_cdp_session_setup: bool = PrivateAttr(default=False)  # Track if CDP session is set up
	_download_cdp_session: Any = PrivateAttr(default=None)  # Store CDP session reference
	_cdp_event_tasks: set[asyncio.Task] = PrivateAttr(default_factory=set)  # Track CDP event handler tasks

	async def on_BrowserLaunchEvent(self, event: BrowserLaunchEvent) -> None:
		self.logger.info(f'[DownloadsWatchdog] Received BrowserLaunchEvent, EventBus ID: {id(self.event_bus)}')
		# Ensure downloads directory exists
		downloads_path = self.browser_session.browser_profile.downloads_path
		if downloads_path:
			Path(downloads_path).mkdir(parents=True, exist_ok=True)
			self.logger.info(f'[DownloadsWatchdog] Ensured downloads directory exists: {downloads_path}')

	async def on_TabCreatedEvent(self, event: TabCreatedEvent) -> None:
		"""Monitor new tabs for downloads."""
		# logger.info(f'[DownloadsWatchdog] TabCreatedEvent received for tab {event.tab_index}: {event.url}')

		# Assert downloads path is configured (should always be set by BrowserProfile default)
		assert self.browser_session.browser_profile.downloads_path is not None, 'Downloads path must be configured'

		target_id = await self.browser_session.get_target_id_by_tab_index(event.tab_index)
		if target_id:
			# logger.info(f'[DownloadsWatchdog] Found target for tab {event.tab_index}, calling attach_to_target')
			await self.attach_to_target(target_id)
		else:
			self.logger.warning(f'[DownloadsWatchdog] No target found for tab {event.tab_index}')

	async def on_TabClosedEvent(self, event: TabClosedEvent) -> None:
		"""Stop monitoring closed tabs."""
		pass  # No cleanup needed, browser context handles target lifecycle

	async def on_BrowserStoppedEvent(self, event: BrowserStoppedEvent) -> None:
		"""Clean up when browser stops."""
		# Cancel all CDP event handler tasks
		for task in list(self._cdp_event_tasks):
			if not task.done():
				task.cancel()
		# Wait for all tasks to complete cancellation
		if self._cdp_event_tasks:
			await asyncio.gather(*self._cdp_event_tasks, return_exceptions=True)
		self._cdp_event_tasks.clear()

		# Clean up CDP session
		# CDP sessions are now cached and managed by BrowserSession
		self._download_cdp_session = None
		self._download_cdp_session_setup = False

		# Clear other state
		self._sessions_with_listeners.clear()
		self._active_downloads.clear()
		self._pdf_viewer_cache.clear()

	async def on_NavigationCompleteEvent(self, event: NavigationCompleteEvent) -> None:
		"""Check for PDFs after navigation completes."""
		# Clear PDF cache for the navigated URL since content may have changed
		if event.url in self._pdf_viewer_cache:
			del self._pdf_viewer_cache[event.url]

		# Check if auto-download is enabled
		if not self._is_auto_download_enabled():
			return

		target_id = await self.browser_session.get_target_id_by_tab_index(event.tab_index)
		if target_id and await self.check_for_pdf_viewer(target_id):
			self.logger.info(f'[DownloadsWatchdog] PDF detected after navigation to {event.url}')
			await self.trigger_pdf_download(target_id)

	def _is_auto_download_enabled(self) -> bool:
		return True  # TODO: move this to browser_profile config option

	async def attach_to_target(self, target_id: str) -> None:
		"""Set up download monitoring for a specific target."""
		try:
			downloads_path_raw = self.browser_session.browser_profile.downloads_path
			if not downloads_path_raw:
				# logger.info(f'[DownloadsWatchdog] No downloads path configured, skipping target: {target_id}')
				return  # No downloads path configured

			# Check if we already have a download listener on this session
			# to prevent duplicate listeners from being added
			# Note: Since download listeners are set up once per browser session, not per target,
			# we just track if we've set up the browser-level listener
			if self._download_cdp_session_setup:
				self.logger.debug('[DownloadsWatchdog] Download listener already set up for browser session')
				return

			# logger.debug(f'[DownloadsWatchdog] Setting up CDP download listener for target: {target_id}')

			# Use CDP session for download events but store reference in watchdog
			if not self._download_cdp_session_setup:
				# Set up CDP session for downloads (only once per browser session)
				cdp_client = self.browser_session.cdp_client

				# Set download behavior to allow downloads and enable events
				downloads_path = self.browser_session.browser_profile.downloads_path
				await cdp_client.send.Browser.setDownloadBehavior(
					params={
						'behavior': 'allow',
						'downloadPath': str(downloads_path),  # Convert Path to string
						'eventsEnabled': True,
					}
				)

				# Register download event handlers
				def download_will_begin_handler(event: DownloadWillBeginEvent, session_id: str | None):
					self.logger.info(f'[DownloadsWatchdog] Download will begin: {event}')
					# Create and track the task
					task = asyncio.create_task(self._handle_cdp_download(event, target_id, session_id))
					self._cdp_event_tasks.add(task)
					# Remove from set when done
					task.add_done_callback(lambda t: self._cdp_event_tasks.discard(t))

				def download_progress_handler(event: DownloadProgressEvent, session_id: str | None):
					# Check if download is complete
					if event.get('state') == 'completed':
						file_path = event.get('filePath')
						if file_path:
							self.logger.info(f'[DownloadsWatchdog] Download completed: {file_path}')
							# Track the download
							self._track_download(file_path)

				# Register the handlers with CDP
				cdp_client.register.Browser.downloadWillBegin(download_will_begin_handler)
				cdp_client.register.Browser.downloadProgress(download_progress_handler)

				self._download_cdp_session_setup = True
				self.logger.debug('[DownloadsWatchdog] Set up CDP download listeners')

			# No need to track individual targets since download listener is browser-level
			# logger.debug(f'[DownloadsWatchdog] Successfully set up CDP download listener for target: {target_id}')

		except Exception as e:
			self.logger.warning(f'[DownloadsWatchdog] Failed to set up CDP download listener for target {target_id}: {e}')

	def _track_download(self, file_path: str) -> None:
		"""Track a completed download and dispatch the appropriate event.

		Args:
			file_path: The path to the downloaded file
		"""
		try:
			# Get file info
			path = Path(file_path)
			if path.exists():
				file_size = path.stat().st_size
				self.logger.info(f'[DownloadsWatchdog] Tracked download: {path.name} ({file_size} bytes)')

				# Dispatch download event
				from browser_use.browser.events import FileDownloadedEvent

				self.event_bus.dispatch(
					FileDownloadedEvent(
						url=str(path),  # Use the file path as URL for local files
						path=str(path),
						file_name=path.name,
						file_size=file_size,
					)
				)
			else:
				self.logger.warning(f'[DownloadsWatchdog] Downloaded file not found: {file_path}')
		except Exception as e:
			self.logger.error(f'[DownloadsWatchdog] Error tracking download: {e}')

	async def _handle_cdp_download(self, event: DownloadWillBeginEvent, target_id: str, session_id: str | None) -> None:
		"""Handle a CDP Page.downloadWillBegin event."""
		try:
			download_url = event.get('url', '')
			suggested_filename = event.get('suggestedFilename', 'download')
			guid = event.get('guid', '')

			self.logger.info(f'[DownloadsWatchdog] ⬇️ File download starting: {suggested_filename} from {download_url[:100]}...')
			self.logger.debug(f'[DownloadsWatchdog] Full CDP event: {event}')

			# Get download directory
			downloads_dir = self.browser_session.browser_profile.downloads_path
			if not downloads_dir:
				downloads_dir = str(Path.home() / 'Downloads')
			else:
				downloads_dir = str(downloads_dir)

			# Since Browser.setDownloadBehavior is already configured, the browser will download the file
			# We just need to wait for it to appear in the downloads directory
			expected_path = Path(downloads_dir) / suggested_filename

			# Debug: List current directory contents
			self.logger.info(f'[DownloadsWatchdog] Downloads directory: {downloads_dir}')
			if Path(downloads_dir).exists():
				files_before = list(Path(downloads_dir).iterdir())
				self.logger.info(f'[DownloadsWatchdog] Files before download: {[f.name for f in files_before]}')

			# Browser.setDownloadBehavior doesn't work reliably with CDP connections
			# So we'll download the file manually using JavaScript fetch
			self.logger.info(f'[DownloadsWatchdog] Downloading file manually via fetch: {download_url}')

			try:
				# Escape the URL for JavaScript
				import json

				escaped_url = json.dumps(download_url)
				cdp_client = self.browser_session.cdp_client

				result = await cdp_client.send.Runtime.evaluate(
					params={
						'expression': f"""
						(async () => {{
							try {{
								const response = await fetch({escaped_url});
								if (!response.ok) {{
									throw new Error(`HTTP error! status: ${{response.status}}`);
								}}
								const blob = await response.blob();
								const arrayBuffer = await blob.arrayBuffer();
								const uint8Array = new Uint8Array(arrayBuffer);
								return {{
									data: Array.from(uint8Array),
									size: uint8Array.length,
									contentType: response.headers.get('content-type') || 'application/octet-stream'
								}};
							}} catch (error) {{
								throw new Error(`Fetch failed: ${{error.message}}`);
							}}
						}})()
						""",
						'awaitPromise': True,
						'returnByValue': True,
					},
					session_id=session_id if session_id else None,
				)
				download_result = result.get('result', {}).get('value')

				if download_result and download_result.get('data'):
					# Save the file
					file_data = bytes(download_result['data'])
					file_size = len(file_data)

					# Ensure unique filename
					unique_filename = await self._get_unique_filename(downloads_dir, suggested_filename)
					final_path = Path(downloads_dir) / unique_filename

					# Write the file
					import anyio

					async with await anyio.open_file(final_path, 'wb') as f:
						await f.write(file_data)

					self.logger.info(f'[DownloadsWatchdog] ✅ Downloaded and saved file: {final_path} ({file_size} bytes)')
					expected_path = final_path
				else:
					self.logger.error('[DownloadsWatchdog] ❌ No data received from fetch')
					return

			except Exception as fetch_error:
				self.logger.error(f'[DownloadsWatchdog] ❌ Failed to download file via fetch: {fetch_error}')
				return

			# Determine file type from extension
			file_ext = expected_path.suffix.lower().lstrip('.')
			file_type = file_ext if file_ext else None

			# Emit download event
			self.event_bus.dispatch(
				FileDownloadedEvent(
					url=download_url,
					path=str(expected_path),
					file_name=unique_filename,
					file_size=file_size,
					file_type=file_type,
					mime_type=download_result.get('contentType'),
					from_cache=False,
					auto_download=False,
				)
			)

			self.logger.info(
				f'[DownloadsWatchdog] ✅ File download completed via CDP: {suggested_filename} ({file_size} bytes) saved to {expected_path}'
			)

		except Exception as e:
			self.logger.error(f'[DownloadsWatchdog] ❌ Error handling CDP download: {e}')

	async def _handle_download(self, download: Any) -> None:
		"""Handle a download event."""
		download_id = f'{id(download)}'
		self._active_downloads[download_id] = download
		self.logger.info(f'[DownloadsWatchdog] ⬇️ Handling download: {download.suggested_filename} from {download.url[:100]}...')

		# Debug: Check if download is already being handled elsewhere
		failure = (
			await download.failure()
		)  # TODO: it always fails for some reason, figure out why connect_over_cdp makes accept_downloads not work
		self.logger.warning(f'[DownloadsWatchdog] ❌ Download state - canceled: {failure}, url: {download.url}')
		# logger.info(f'[DownloadsWatchdog] Active downloads count: {len(self._active_downloads)}')

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

			# Check if Playwright already auto-downloaded the file (due to CDP setup)
			original_path = Path(downloads_dir) / suggested_filename
			if original_path.exists() and original_path.stat().st_size > 0:
				self.logger.info(
					f'[DownloadsWatchdog] File already downloaded by Playwright: {original_path} ({original_path.stat().st_size} bytes)'
				)

				# Use the existing file instead of creating a duplicate
				download_path = original_path
				file_size = original_path.stat().st_size
				unique_filename = suggested_filename
			else:
				current_step = 'generating_unique_filename'
				# Ensure unique filename
				unique_filename = await self._get_unique_filename(downloads_dir, suggested_filename)
				download_path = Path(downloads_dir) / unique_filename

				self.logger.info(f'[DownloadsWatchdog] Download started: {unique_filename} from {url[:100]}...')

				current_step = 'calling_save_as'
				# Save the download using Playwright's save_as method
				self.logger.info(f'[DownloadsWatchdog] Saving download to: {download_path}')
				self.logger.info(f'[DownloadsWatchdog] Download path exists: {download_path.parent.exists()}')
				self.logger.info(f'[DownloadsWatchdog] Download path writable: {os.access(download_path.parent, os.W_OK)}')

				try:
					self.logger.info('[DownloadsWatchdog] About to call download.save_as()...')
					await download.save_as(str(download_path))
					self.logger.info(f'[DownloadsWatchdog] Successfully saved download to: {download_path}')
					current_step = 'save_as_completed'
				except Exception as save_error:
					self.logger.error(f'[DownloadsWatchdog] save_as() failed with error: {save_error}')
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

			self.logger.info(
				f'[DownloadsWatchdog] Download completed: {suggested_filename} ({file_size} bytes) saved to {download_path}'
			)

			# File is now tracked on filesystem, no need to track in memory

		except Exception as e:
			self.logger.error(
				f'[DownloadsWatchdog] Error handling download at step "{locals().get("current_step", "unknown")}", error: {e}'
			)
			self.logger.error(
				f'[DownloadsWatchdog] Download state - URL: {download.url}, filename: {download.suggested_filename}'
			)
		finally:
			# Clean up tracking
			if download_id in self._active_downloads:
				del self._active_downloads[download_id]

	async def check_for_pdf_viewer(self, target_id: str) -> bool:
		"""Check if the current target is Chrome's built-in PDF viewer.

		Returns True if a PDF is detected and should be downloaded.
		"""
		# Get target info to get URL
		cdp_client = self.browser_session.cdp_client
		targets = await cdp_client.send.Target.getTargets()
		target_info = next((t for t in targets['targetInfos'] if t['targetId'] == target_id), None)
		if not target_info:
			return False

		page_url = target_info.get('url', '')

		# Check cache first
		if page_url in self._pdf_viewer_cache:
			return self._pdf_viewer_cache[page_url]

		try:
			# Create a temporary CDP session for this target without switching focus
			import asyncio
			
			temp_session = await self.browser_session.get_or_create_cdp_session(target_id, focus=False)

			result = await asyncio.wait_for(
				temp_session.cdp_client.send.Runtime.evaluate(
					params={
						'expression': """
				(() => {
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
				})()
				""",
						'returnByValue': True,
					},
					session_id=temp_session.session_id,
				),
				timeout=5.0,  # 5 second timeout to prevent hanging
			)

			# No need to detach - session is cached
			is_pdf_viewer = result.get('result', {}).get('value', {})

			if is_pdf_viewer.get('isPdf', False):
				self.logger.info(
					f'[DownloadsWatchdog] 📄 PDF detected: {is_pdf_viewer.get("url", "unknown")} '
					f'(type: {"Chrome viewer" if is_pdf_viewer.get("isChromePdfViewer") else "direct PDF"})'
				)
				self._pdf_viewer_cache[page_url] = True
				return True

			self._pdf_viewer_cache[page_url] = False
			return False

		except TimeoutError:
			self.logger.warning(f'[DownloadsWatchdog] ❌ PDF check timed out for target: {page_url}')
			self._pdf_viewer_cache[page_url] = False
			return False
		except Exception as e:
			self.logger.warning(f'[DownloadsWatchdog] ❌ Error checking for PDF viewer: {e}')
			self._pdf_viewer_cache[page_url] = False
			return False

	async def trigger_pdf_download(self, target_id: str) -> str | None:
		"""Trigger download of a PDF from Chrome's PDF viewer.

		Returns the download path if successful, None otherwise.
		"""
		if not self.browser_session.browser_profile.downloads_path:
			self.logger.warning('[DownloadsWatchdog] ❌ No downloads path configured, cannot save PDF download')
			return None

		try:
			# Create a temporary CDP session for this target without switching focus
			import asyncio
			
			temp_session = await self.browser_session.get_or_create_cdp_session(target_id, focus=False)

			# Try to get the PDF URL with timeout
			result = await asyncio.wait_for(
				temp_session.cdp_client.send.Runtime.evaluate(
					params={
						'expression': """
				(() => {
					const embedElement = document.querySelector('embed[type="application/x-google-chrome-pdf"]') ||
										document.querySelector('embed[type="application/pdf"]');
					if (embedElement && embedElement.src) {
						return { url: embedElement.src };
					}
					return { url: window.location.href };
				})()
				""",
						'returnByValue': True,
					},
					session_id=temp_session.session_id,
				),
				timeout=5.0,  # 5 second timeout to prevent hanging
			)
			pdf_info = result.get('result', {}).get('value', {})

			pdf_url = pdf_info.get('url', '')
			if not pdf_url:
				self.logger.warning(f'[DownloadsWatchdog] ❌ Could not determine PDF URL for download {pdf_info}')
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
					self.logger.debug(f'[DownloadsWatchdog] ✅ PDF already downloaded: {pdf_filename}')
					return None

			self.logger.info(f'[DownloadsWatchdog] ⬇️ Downloading PDF file from: {pdf_url[:100]}...')

			# Download using JavaScript fetch to leverage browser cache
			try:
				# Properly escape the URL to prevent JavaScript injection
				escaped_pdf_url = json.dumps(pdf_url)

				result = await asyncio.wait_for(
					temp_session.cdp_client.send.Runtime.evaluate(
						params={
							'expression': f"""
					(async () => {{
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
					}})()
					""",
							'awaitPromise': True,
							'returnByValue': True,
						},
						session_id=temp_session.session_id,
					),
					timeout=10.0,  # 10 second timeout for download operation
				)
				download_result = result.get('result', {}).get('value', {})

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
					self.logger.info(
						f'[DownloadsWatchdog] ✅ Auto-downloaded PDF ({cache_status}, {response_size:,} bytes): {download_path}'
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

					# No need to detach - session is cached
					return download_path
				else:
					self.logger.warning(f'[DownloadsWatchdog] No data received when downloading PDF from {pdf_url}')
					return None

			except Exception as e:
				self.logger.warning(f'[DownloadsWatchdog] Failed to auto-download PDF from {pdf_url}: {type(e).__name__}: {e}')
				return None

		except TimeoutError:
			self.logger.debug('[DownloadsWatchdog] PDF download operation timed out')
			return None
		except Exception as e:
			self.logger.error(f'[DownloadsWatchdog] Error in PDF download: {type(e).__name__}: {e}')
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
