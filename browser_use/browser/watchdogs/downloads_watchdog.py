"""Downloads watchdog for monitoring and handling file downloads."""

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar
from urllib.parse import urlparse

import anyio
from bubus import BaseEvent
from cdp_use.cdp.browser import DownloadProgressEvent, DownloadWillBeginEvent
from cdp_use.cdp.network import ResponseReceivedEvent
from cdp_use.cdp.target import SessionID, TargetID
from pydantic import PrivateAttr

from browser_use.browser.events import (
	BrowserLaunchEvent,
	BrowserStateRequestEvent,
	BrowserStoppedEvent,
	FileDownloadedEvent,
	NavigationCompleteEvent,
	TabClosedEvent,
	TabCreatedEvent,
)
from browser_use.browser.watchdog_base import BaseWatchdog
from browser_use.utils import create_task_with_error_handling

if TYPE_CHECKING:
	pass


class DownloadsWatchdog(BaseWatchdog):
	"""Monitors downloads and handles file download events."""

	# Events this watchdog listens to (for documentation)
	LISTENS_TO: ClassVar[list[type[BaseEvent[Any]]]] = [
		BrowserLaunchEvent,
		BrowserStateRequestEvent,
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
	_cdp_downloads_info: dict[str, dict[str, Any]] = PrivateAttr(default_factory=dict)  # Map guid -> info
	_use_js_fetch_for_local: bool = PrivateAttr(default=False)  # Guard JS fetch path for local regular downloads
	_session_pdf_urls: dict[str, str] = PrivateAttr(default_factory=dict)  # URL -> path for PDFs downloaded this session
	_network_monitored_targets: set[str] = PrivateAttr(default_factory=set)  # Track targets with network monitoring enabled
	_detected_downloads: set[str] = PrivateAttr(default_factory=set)  # Track detected download URLs to avoid duplicates
	_network_callback_registered: bool = PrivateAttr(default=False)  # Track if global network callback is registered

	async def on_BrowserLaunchEvent(self, event: BrowserLaunchEvent) -> None:
		self.logger.debug(f'[DownloadsWatchdog] Received BrowserLaunchEvent, EventBus ID: {id(self.event_bus)}')
		# Ensure downloads directory exists
		downloads_path = self.browser_session.browser_profile.downloads_path
		if downloads_path:
			expanded_path = Path(downloads_path).expanduser().resolve()
			expanded_path.mkdir(parents=True, exist_ok=True)
			self.logger.debug(f'[DownloadsWatchdog] Ensured downloads directory exists: {expanded_path}')

	async def on_TabCreatedEvent(self, event: TabCreatedEvent) -> None:
		"""Monitor new tabs for downloads."""
		# logger.info(f'[DownloadsWatchdog] TabCreatedEvent received for tab {event.target_id[-4:]}: {event.url}')

		# Assert downloads path is configured (should always be set by BrowserProfile default)
		assert self.browser_session.browser_profile.downloads_path is not None, 'Downloads path must be configured'

		if event.target_id:
			# logger.info(f'[DownloadsWatchdog] Found target for tab {event.target_id}, calling attach_to_target')
			await self.attach_to_target(event.target_id)
		else:
			self.logger.warning(f'[DownloadsWatchdog] No target found for tab {event.target_id}')

	async def on_TabClosedEvent(self, event: TabClosedEvent) -> None:
		"""Stop monitoring closed tabs."""
		pass  # No cleanup needed, browser context handles target lifecycle

	async def on_BrowserStateRequestEvent(self, event: BrowserStateRequestEvent) -> None:
		"""Handle browser state request events."""
		# Use public API - automatically validates and waits for recovery if needed
		self.logger.debug(f'[DownloadsWatchdog] on_BrowserStateRequestEvent started, event_id={event.event_id[-4:]}')
		try:
			cdp_session = await self.browser_session.get_or_create_cdp_session()
		except ValueError:
			self.logger.warning(f'[DownloadsWatchdog] No valid focus, skipping BrowserStateRequestEvent {event.event_id[-4:]}')
			return  # No valid focus, skip

		self.logger.debug(
			f'[DownloadsWatchdog] About to call get_current_page_url(), target_id={cdp_session.target_id[-4:] if cdp_session.target_id else "None"}'
		)
		url = await self.browser_session.get_current_page_url()
		self.logger.debug(f'[DownloadsWatchdog] Got URL: {url[:80] if url else "None"}')

		if not url:
			self.logger.warning(f'[DownloadsWatchdog] No URL found for BrowserStateRequestEvent {event.event_id[-4:]}')
			return

		target_id = cdp_session.target_id
		self.logger.debug(f'[DownloadsWatchdog] About to dispatch NavigationCompleteEvent for target {target_id[-4:]}')
		self.event_bus.dispatch(
			NavigationCompleteEvent(
				event_type='NavigationCompleteEvent',
				url=url,
				target_id=target_id,
				event_parent_id=event.event_id,
			)
		)
		self.logger.debug('[DownloadsWatchdog] Successfully completed BrowserStateRequestEvent')

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
		self._session_pdf_urls.clear()
		self._network_monitored_targets.clear()
		self._detected_downloads.clear()
		self._network_callback_registered = False

	async def on_NavigationCompleteEvent(self, event: NavigationCompleteEvent) -> None:
		"""Check for PDFs after navigation completes."""
		self.logger.debug(f'[DownloadsWatchdog] NavigationCompleteEvent received for {event.url}, tab #{event.target_id[-4:]}')

		# Clear PDF cache for the navigated URL since content may have changed
		if event.url in self._pdf_viewer_cache:
			del self._pdf_viewer_cache[event.url]

		# Check if auto-download is enabled
		auto_download_enabled = self._is_auto_download_enabled()
		if not auto_download_enabled:
			return

		# Note: Using network-based PDF detection that doesn't require JavaScript

		target_id = event.target_id
		self.logger.debug(f'[DownloadsWatchdog] Got target_id={target_id} for tab #{event.target_id[-4:]}')

		is_pdf = await self.check_for_pdf_viewer(target_id)

		if is_pdf:
			self.logger.debug(f'[DownloadsWatchdog] 📄 PDF detected at {event.url}, triggering auto-download...')
			download_path = await self.trigger_pdf_download(target_id)
			if not download_path:
				self.logger.warning(f'[DownloadsWatchdog] ⚠️ PDF download failed for {event.url}')

	def _is_auto_download_enabled(self) -> bool:
		"""Check if auto-download PDFs is enabled in browser profile."""
		return self.browser_session.browser_profile.auto_download_pdfs

	async def attach_to_target(self, target_id: TargetID) -> None:
		"""Set up download monitoring for a specific target."""

		# Define CDP event handlers outside of try to avoid indentation/scope issues
		def download_will_begin_handler(event: DownloadWillBeginEvent, session_id: SessionID | None) -> None:
			self.logger.debug(f'[DownloadsWatchdog] Download will begin: {event}')
			# Cache info for later completion event handling (esp. remote browsers)
			guid = event.get('guid', '')
			try:
				suggested_filename = event.get('suggestedFilename')
				assert suggested_filename, 'CDP DownloadWillBegin missing suggestedFilename'
				self._cdp_downloads_info[guid] = {
					'url': event.get('url', ''),
					'suggested_filename': suggested_filename,
					'handled': False,
				}
			except (AssertionError, KeyError):
				pass
			# Create and track the task
			task = create_task_with_error_handling(
				self._handle_cdp_download(event, target_id, session_id),
				name='handle_cdp_download',
				logger_instance=self.logger,
				suppress_exceptions=True,
			)
			self._cdp_event_tasks.add(task)
			# Remove from set when done
			task.add_done_callback(lambda t: self._cdp_event_tasks.discard(t))

		def download_progress_handler(event: DownloadProgressEvent, session_id: SessionID | None) -> None:
			# Check if download is complete
			if event.get('state') == 'completed':
				file_path = event.get('filePath')
				guid = event.get('guid', '')
				if self.browser_session.is_local:
					if file_path:
						self.logger.debug(f'[DownloadsWatchdog] Download completed: {file_path}')
						# Track the download
						self._track_download(file_path)
						# Mark as handled to prevent fallback duplicate dispatch
						try:
							if guid in self._cdp_downloads_info:
								self._cdp_downloads_info[guid]['handled'] = True
						except (KeyError, AttributeError):
							pass
					else:
						# No local file path provided, local polling in _handle_cdp_download will handle it
						self.logger.debug(
							'[DownloadsWatchdog] No filePath in progress event (local); polling will handle detection'
						)
				else:
					# Remote browser: do not touch local filesystem. Fallback to downloadPath+suggestedFilename
					info = self._cdp_downloads_info.get(guid, {})
					try:
						suggested_filename = info.get('suggested_filename') or (Path(file_path).name if file_path else 'download')
						downloads_path = str(self.browser_session.browser_profile.downloads_path or '')
						effective_path = file_path or str(Path(downloads_path) / suggested_filename)
						file_name = Path(effective_path).name
						file_ext = Path(file_name).suffix.lower().lstrip('.')
						self.event_bus.dispatch(
							FileDownloadedEvent(
								url=info.get('url', ''),
								path=str(effective_path),
								file_name=file_name,
								file_size=0,
								file_type=file_ext if file_ext else None,
							)
						)
						self.logger.debug(f'[DownloadsWatchdog] ✅ (remote) Download completed: {effective_path}')
					finally:
						if guid in self._cdp_downloads_info:
							del self._cdp_downloads_info[guid]

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
				if not downloads_path:
					self.logger.warning('[DownloadsWatchdog] No downloads path configured, skipping CDP download setup')
					return
				# Ensure path is properly expanded (~ -> absolute path)
				expanded_downloads_path = Path(downloads_path).expanduser().resolve()
				await cdp_client.send.Browser.setDownloadBehavior(
					params={
						'behavior': 'allow',
						'downloadPath': str(expanded_downloads_path),  # Use expanded absolute path
						'eventsEnabled': True,
					}
				)

				# Register the handlers with CDP
				cdp_client.register.Browser.downloadWillBegin(download_will_begin_handler)  # type: ignore[arg-type]
				cdp_client.register.Browser.downloadProgress(download_progress_handler)  # type: ignore[arg-type]

				self._download_cdp_session_setup = True
				self.logger.debug('[DownloadsWatchdog] Set up CDP download listeners')

			# No need to track individual targets since download listener is browser-level
			# logger.debug(f'[DownloadsWatchdog] Successfully set up CDP download listener for target: {target_id}')

		except Exception as e:
			self.logger.warning(f'[DownloadsWatchdog] Failed to set up CDP download listener for target {target_id}: {e}')

		# Set up network monitoring for this target (catches ALL download variants)
		await self._setup_network_monitoring(target_id)

	async def _setup_network_monitoring(self, target_id: TargetID) -> None:
		"""Set up network monitoring to detect PDFs and downloads from ALL sources.

		This catches:
		- Direct PDF navigation
		- PDFs in iframes
		- PDFs with embed/object tags
		- JavaScript-triggered downloads
		- Any Content-Disposition: attachment headers
		"""
		# Skip if already monitoring this target
		if target_id in self._network_monitored_targets:
			self.logger.debug(f'[DownloadsWatchdog] Network monitoring already enabled for target {target_id[-4:]}')
			return

		# Check if auto-download is enabled
		if not self._is_auto_download_enabled():
			self.logger.debug('[DownloadsWatchdog] Auto-download disabled, skipping network monitoring')
			return

		try:
			cdp_client = self.browser_session.cdp_client

			# Register the global callback once
			if not self._network_callback_registered:

				def on_response_received(event: ResponseReceivedEvent, session_id: str | None) -> None:
					"""Handle Network.responseReceived event to detect downloadable content.

					This callback is registered globally and uses session_id to determine the correct target.
					"""
					try:
						# Check if session_manager exists (may be None during browser shutdown)
						if not self.browser_session.session_manager:
							self.logger.warning('[DownloadsWatchdog] Session manager not found, skipping network monitoring')
							return

						# Look up target_id from session_id
						event_target_id = self.browser_session.session_manager.get_target_id_from_session_id(session_id)
						if not event_target_id:
							# Session not in pool - might be a stale session or not yet tracked
							return

						# Only process events for targets we're monitoring
						if event_target_id not in self._network_monitored_targets:
							return

						response = event.get('response', {})
						url = response.get('url', '')
						content_type = response.get('mimeType', '').lower()
						headers = response.get('headers', {})

						# Skip non-HTTP URLs (data:, about:, chrome-extension:, etc.)
						if not url.startswith('http'):
							return

						# Check if it's a PDF
						is_pdf = 'application/pdf' in content_type

						# Check if it's marked as download via Content-Disposition header
						content_disposition = headers.get('content-disposition', '').lower()
						is_download_attachment = 'attachment' in content_disposition

						# Filter out image/video/audio files even if marked as attachment
						# These are likely resources, not intentional downloads
						unwanted_content_types = [
							'image/',
							'video/',
							'audio/',
							'text/css',
							'text/javascript',
							'application/javascript',
							'application/x-javascript',
							'text/html',
							'application/json',
							'font/',
							'application/font',
							'application/x-font',
						]
						is_unwanted_type = any(content_type.startswith(prefix) for prefix in unwanted_content_types)
						if is_unwanted_type:
							return

						# Check URL extension to filter out obvious images/resources
						url_lower = url.lower().split('?')[0]  # Remove query params
						unwanted_extensions = [
							'.jpg',
							'.jpeg',
							'.png',
							'.gif',
							'.webp',
							'.svg',
							'.ico',
							'.css',
							'.js',
							'.woff',
							'.woff2',
							'.ttf',
							'.eot',
							'.mp4',
							'.webm',
							'.mp3',
							'.wav',
							'.ogg',
						]
						if any(url_lower.endswith(ext) for ext in unwanted_extensions):
							return

						# Only process if it's a PDF or download
						if not (is_pdf or is_download_attachment):
							return

						# Check if we've already processed this URL in this session
						if url in self._detected_downloads:
							self.logger.debug(f'[DownloadsWatchdog] Already detected download: {url[:80]}...')
							return

						# Mark as detected to avoid duplicates
						self._detected_downloads.add(url)

						# Extract filename from Content-Disposition if available
						suggested_filename = None
						if 'filename=' in content_disposition:
							# Parse filename from Content-Disposition header
							import re

							filename_match = re.search(r'filename[^;=\n]*=(([\'"]).*?\2|[^;\n]*)', content_disposition)
							if filename_match:
								suggested_filename = filename_match.group(1).strip('\'"')

						self.logger.info(f'[DownloadsWatchdog] 🔍 Detected downloadable content via network: {url[:80]}...')
						self.logger.debug(
							f'[DownloadsWatchdog]   Content-Type: {content_type}, Is PDF: {is_pdf}, Is Attachment: {is_download_attachment}'
						)

						# Trigger download asynchronously in background (don't block event handler)
						async def download_in_background():
							try:
								download_path = await self.download_file_from_url(
									url=url,
									target_id=event_target_id,  # Use target_id from session_id lookup
									content_type=content_type,
									suggested_filename=suggested_filename,
								)

								if download_path:
									self.logger.info(f'[DownloadsWatchdog] ✅ Successfully downloaded: {download_path}')
								else:
									self.logger.warning(f'[DownloadsWatchdog] ⚠️  Failed to download: {url[:80]}...')
							except Exception as e:
								self.logger.error(f'[DownloadsWatchdog] Error downloading in background: {type(e).__name__}: {e}')

						# Create background task
						task = create_task_with_error_handling(
							download_in_background(),
							name='download_in_background',
							logger_instance=self.logger,
							suppress_exceptions=True,
						)
						self._cdp_event_tasks.add(task)
						task.add_done_callback(lambda t: self._cdp_event_tasks.discard(t))

					except Exception as e:
						self.logger.error(f'[DownloadsWatchdog] Error in network response handler: {type(e).__name__}: {e}')

				# Register the callback globally (once)
				cdp_client.register.Network.responseReceived(on_response_received)
				self._network_callback_registered = True
				self.logger.debug('[DownloadsWatchdog] ✅ Registered global network response callback')

			# Get or create CDP session for this target
			cdp_session = await self.browser_session.get_or_create_cdp_session(target_id, focus=False)

			# Enable Network domain to monitor HTTP responses (per-target/per-session)
			await cdp_client.send.Network.enable(session_id=cdp_session.session_id)
			self.logger.debug(f'[DownloadsWatchdog] Enabled Network domain for target {target_id[-4:]}')

			# Mark this target as monitored
			self._network_monitored_targets.add(target_id)
			self.logger.debug(f'[DownloadsWatchdog] ✅ Network monitoring enabled for target {target_id[-4:]}')

		except Exception as e:
			self.logger.warning(f'[DownloadsWatchdog] Failed to set up network monitoring for target {target_id}: {e}')

	async def download_file_from_url(
		self, url: str, target_id: TargetID, content_type: str | None = None, suggested_filename: str | None = None
	) -> str | None:
		"""Generic method to download any file from a URL.

		Args:
			url: The URL to download
			target_id: The target ID for CDP session
			content_type: Optional content type (e.g., 'application/pdf')
			suggested_filename: Optional filename from Content-Disposition header

		Returns:
			Path to downloaded file, or None if download failed
		"""
		if not self.browser_session.browser_profile.downloads_path:
			self.logger.warning('[DownloadsWatchdog] No downloads path configured')
			return None

		# Check if already downloaded in this session
		if url in self._session_pdf_urls:
			existing_path = self._session_pdf_urls[url]
			self.logger.debug(f'[DownloadsWatchdog] File already downloaded in session: {existing_path}')
			return existing_path

		try:
			# Get or create CDP session for this target
			temp_session = await self.browser_session.get_or_create_cdp_session(target_id, focus=False)

			# Determine filename
			if suggested_filename:
				filename = suggested_filename
			else:
				# Extract from URL
				filename = os.path.basename(url.split('?')[0])  # Remove query params
				if not filename or '.' not in filename:
					# Fallback: use content type to determine extension
					if content_type and 'pdf' in content_type:
						filename = 'document.pdf'
					else:
						filename = 'download'

			# Ensure downloads directory exists
			downloads_dir = str(self.browser_session.browser_profile.downloads_path)
			os.makedirs(downloads_dir, exist_ok=True)

			# Generate unique filename if file exists
			final_filename = filename
			existing_files = os.listdir(downloads_dir)
			if filename in existing_files:
				base, ext = os.path.splitext(filename)
				counter = 1
				while f'{base} ({counter}){ext}' in existing_files:
					counter += 1
				final_filename = f'{base} ({counter}){ext}'
				self.logger.debug(f'[DownloadsWatchdog] File exists, using: {final_filename}')

			self.logger.debug(f'[DownloadsWatchdog] Downloading from: {url[:100]}...')

			# Download using JavaScript fetch to leverage browser cache
			escaped_url = json.dumps(url)

			result = await asyncio.wait_for(
				temp_session.cdp_client.send.Runtime.evaluate(
					params={
						'expression': f"""
				(async () => {{
					try {{
						const response = await fetch({escaped_url}, {{
							cache: 'force-cache'
						}});
						if (!response.ok) {{
							throw new Error(`HTTP error! status: ${{response.status}}`);
						}}
						const blob = await response.blob();
						const arrayBuffer = await blob.arrayBuffer();
						const uint8Array = new Uint8Array(arrayBuffer);

						return {{
							data: Array.from(uint8Array),
							responseSize: uint8Array.length
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
				timeout=15.0,  # 15 second timeout
			)

			download_result = result.get('result', {}).get('value', {})

			if download_result and download_result.get('data') and len(download_result['data']) > 0:
				download_path = os.path.join(downloads_dir, final_filename)

				# Save the file asynchronously
				async with await anyio.open_file(download_path, 'wb') as f:
					await f.write(bytes(download_result['data']))

				# Verify file was written successfully
				if os.path.exists(download_path):
					actual_size = os.path.getsize(download_path)
					self.logger.debug(f'[DownloadsWatchdog] File written: {download_path} ({actual_size} bytes)')

					# Determine file type
					file_ext = Path(final_filename).suffix.lower().lstrip('.')
					mime_type = content_type or f'application/{file_ext}'

					# Store URL->path mapping for this session
					self._session_pdf_urls[url] = download_path

					# Emit file downloaded event
					self.logger.debug(f'[DownloadsWatchdog] Dispatching FileDownloadedEvent for {final_filename}')
					self.event_bus.dispatch(
						FileDownloadedEvent(
							url=url,
							path=download_path,
							file_name=final_filename,
							file_size=actual_size,
							file_type=file_ext if file_ext else None,
							mime_type=mime_type,
							auto_download=True,
						)
					)

					return download_path
				else:
					self.logger.error(f'[DownloadsWatchdog] Failed to write file: {download_path}')
					return None
			else:
				self.logger.warning(f'[DownloadsWatchdog] No data received when downloading from {url}')
				return None

		except TimeoutError:
			self.logger.warning(f'[DownloadsWatchdog] Download timed out: {url[:80]}...')
			return None
		except Exception as e:
			self.logger.warning(f'[DownloadsWatchdog] Download failed: {type(e).__name__}: {e}')
			return None

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
				self.logger.debug(f'[DownloadsWatchdog] Tracked download: {path.name} ({file_size} bytes)')

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

	async def _handle_cdp_download(
		self, event: DownloadWillBeginEvent, target_id: TargetID, session_id: SessionID | None
	) -> None:
		"""Handle a CDP Page.downloadWillBegin event."""
		downloads_dir = (
			Path(
				self.browser_session.browser_profile.downloads_path
				or f'{tempfile.gettempdir()}/browser_use_downloads.{str(self.browser_session.id)[-4:]}'
			)
			.expanduser()
			.resolve()
		)  # Ensure path is properly expanded

		# Initialize variables that may be used outside try blocks
		unique_filename = None
		file_size = 0
		expected_path = None
		download_result = None
		download_url = event.get('url', '')
		suggested_filename = event.get('suggestedFilename', 'download')
		guid = event.get('guid', '')

		try:
			self.logger.debug(f'[DownloadsWatchdog] ⬇️ File download starting: {suggested_filename} from {download_url[:100]}...')
			self.logger.debug(f'[DownloadsWatchdog] Full CDP event: {event}')

			# Since Browser.setDownloadBehavior is already configured, the browser will download the file
			# We just need to wait for it to appear in the downloads directory
			expected_path = downloads_dir / suggested_filename

			# Debug: List current directory contents
			self.logger.debug(f'[DownloadsWatchdog] Downloads directory: {downloads_dir}')
			if downloads_dir.exists():
				files_before = list(downloads_dir.iterdir())
				self.logger.debug(f'[DownloadsWatchdog] Files before download: {[f.name for f in files_before]}')

			# Try manual JavaScript fetch as a fallback for local browsers (disabled for regular local downloads)
			if self.browser_session.is_local and self._use_js_fetch_for_local:
				self.logger.debug(f'[DownloadsWatchdog] Attempting JS fetch fallback for {download_url}')

				unique_filename = None
				file_size = None
				download_result = None
				try:
					# Escape the URL for JavaScript
					import json

					escaped_url = json.dumps(download_url)

					# Get the proper session for the frame that initiated the download
					cdp_session = await self.browser_session.cdp_client_for_frame(event.get('frameId'))
					assert cdp_session

					result = await cdp_session.cdp_client.send.Runtime.evaluate(
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
						session_id=cdp_session.session_id,
					)
					download_result = result.get('result', {}).get('value')

					if download_result and download_result.get('data'):
						# Save the file
						file_data = bytes(download_result['data'])
						file_size = len(file_data)

						# Ensure unique filename
						unique_filename = await self._get_unique_filename(str(downloads_dir), suggested_filename)
						final_path = downloads_dir / unique_filename

						# Write the file
						import anyio

						async with await anyio.open_file(final_path, 'wb') as f:
							await f.write(file_data)

						self.logger.debug(f'[DownloadsWatchdog] ✅ Downloaded and saved file: {final_path} ({file_size} bytes)')
						expected_path = final_path
						# Emit download event immediately
						file_ext = expected_path.suffix.lower().lstrip('.')
						file_type = file_ext if file_ext else None
						self.event_bus.dispatch(
							FileDownloadedEvent(
								url=download_url,
								path=str(expected_path),
								file_name=unique_filename or expected_path.name,
								file_size=file_size or 0,
								file_type=file_type,
								mime_type=(download_result.get('contentType') if download_result else None),
								from_cache=False,
								auto_download=False,
							)
						)
						# Mark as handled to prevent duplicate dispatch from progress/polling paths
						try:
							if guid in self._cdp_downloads_info:
								self._cdp_downloads_info[guid]['handled'] = True
						except (KeyError, AttributeError):
							pass
						self.logger.debug(
							f'[DownloadsWatchdog] ✅ File download completed via CDP: {suggested_filename} ({file_size} bytes) saved to {expected_path}'
						)
						return
					else:
						self.logger.error('[DownloadsWatchdog] ❌ No data received from fetch')

				except Exception as fetch_error:
					self.logger.error(f'[DownloadsWatchdog] ❌ Failed to download file via fetch: {fetch_error}')

			# For remote browsers, don't poll local filesystem; downloadProgress handler will emit the event
			if not self.browser_session.is_local:
				return
		except Exception as e:
			self.logger.error(f'[DownloadsWatchdog] ❌ Error handling CDP download: {type(e).__name__} {e}')

		# If we reach here, the fetch method failed, so wait for native download
		# Poll the downloads directory for new files
		self.logger.debug(f'[DownloadsWatchdog] Checking if browser auto-download saved the file for us: {suggested_filename}')

		# Get initial list of files in downloads directory
		initial_files = set()
		if Path(downloads_dir).exists():
			for f in Path(downloads_dir).iterdir():
				if f.is_file() and not f.name.startswith('.'):
					initial_files.add(f.name)

		# Poll for new files
		max_wait = 20  # seconds
		start_time = asyncio.get_event_loop().time()

		while asyncio.get_event_loop().time() - start_time < max_wait:
			await asyncio.sleep(5.0)  # Check every 5 seconds

			if Path(downloads_dir).exists():
				for file_path in Path(downloads_dir).iterdir():
					# Skip hidden files and files that were already there
					if file_path.is_file() and not file_path.name.startswith('.') and file_path.name not in initial_files:
						# Check if file has content (> 4 bytes)
						try:
							file_size = file_path.stat().st_size
							if file_size > 4:
								# Found a new download!
								self.logger.debug(
									f'[DownloadsWatchdog] ✅ Found downloaded file: {file_path} ({file_size} bytes)'
								)

								# Determine file type from extension
								file_ext = file_path.suffix.lower().lstrip('.')
								file_type = file_ext if file_ext else None

								# Dispatch download event
								# Skip if already handled by progress/JS fetch
								info = self._cdp_downloads_info.get(guid, {})
								if info.get('handled'):
									return
								self.event_bus.dispatch(
									FileDownloadedEvent(
										url=download_url,
										path=str(file_path),
										file_name=file_path.name,
										file_size=file_size,
										file_type=file_type,
									)
								)
								# Mark as handled after dispatch
								try:
									if guid in self._cdp_downloads_info:
										self._cdp_downloads_info[guid]['handled'] = True
								except (KeyError, AttributeError):
									pass
								return
						except Exception as e:
							self.logger.debug(f'[DownloadsWatchdog] Error checking file {file_path}: {e}')

		self.logger.warning(f'[DownloadsWatchdog] Download did not complete within {max_wait} seconds')

	async def _handle_download(self, download: Any) -> None:
		"""Handle a download event."""
		download_id = f'{id(download)}'
		self._active_downloads[download_id] = download
		self.logger.debug(f'[DownloadsWatchdog] ⬇️ Handling download: {download.suggested_filename} from {download.url[:100]}...')

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
				self.logger.debug(
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

				self.logger.debug(f'[DownloadsWatchdog] Download started: {unique_filename} from {url[:100]}...')

				current_step = 'calling_save_as'
				# Save the download using Playwright's save_as method
				self.logger.debug(f'[DownloadsWatchdog] Saving download to: {download_path}')
				self.logger.debug(f'[DownloadsWatchdog] Download path exists: {download_path.parent.exists()}')
				self.logger.debug(f'[DownloadsWatchdog] Download path writable: {os.access(download_path.parent, os.W_OK)}')

				try:
					self.logger.debug('[DownloadsWatchdog] About to call download.save_as()...')
					await download.save_as(str(download_path))
					self.logger.debug(f'[DownloadsWatchdog] Successfully saved download to: {download_path}')
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

			self.logger.debug(
				f'[DownloadsWatchdog] ✅ Download completed: {suggested_filename} ({file_size} bytes) saved to {download_path}'
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

	async def check_for_pdf_viewer(self, target_id: TargetID) -> bool:
		"""Check if the current target is a PDF using network-based detection.

		This method avoids JavaScript execution that can crash WebSocket connections.
		Returns True if a PDF is detected and should be downloaded.
		"""
		self.logger.debug(f'[DownloadsWatchdog] Checking if target {target_id} is PDF viewer...')

		# Use safe API - focus=False to avoid changing focus during PDF check
		try:
			session = await self.browser_session.get_or_create_cdp_session(target_id, focus=False)
		except ValueError as e:
			self.logger.warning(f'[DownloadsWatchdog] No session found for {target_id}: {e}')
			return False

		# Get URL from target
		target = self.browser_session.session_manager.get_target(target_id)
		if not target:
			self.logger.warning(f'[DownloadsWatchdog] No target found for {target_id}')
			return False
		page_url = target.url

		# Check cache first
		if page_url in self._pdf_viewer_cache:
			cached_result = self._pdf_viewer_cache[page_url]
			self.logger.debug(f'[DownloadsWatchdog] Using cached PDF check result for {page_url}: {cached_result}')
			return cached_result

		try:
			# Method 1: Check URL patterns (fastest, most reliable)
			url_is_pdf = self._check_url_for_pdf(page_url)
			if url_is_pdf:
				self.logger.debug(f'[DownloadsWatchdog] PDF detected via URL pattern: {page_url}')
				self._pdf_viewer_cache[page_url] = True
				return True
			chrome_pdf_viewer = self._is_chrome_pdf_viewer_url(page_url)
			if chrome_pdf_viewer:
				self.logger.debug(f'[DownloadsWatchdog] Chrome PDF viewer detected: {page_url}')
				self._pdf_viewer_cache[page_url] = True
				return True

			# Not a PDF
			self._pdf_viewer_cache[page_url] = False
			return False

		except Exception as e:
			self.logger.warning(f'[DownloadsWatchdog] ❌ Error checking for PDF viewer: {e}')
			self._pdf_viewer_cache[page_url] = False
			return False

	def _check_url_for_pdf(self, url: str) -> bool:
		"""Check if URL indicates a PDF file."""
		if not url:
			return False

		url_lower = url.lower()

		# Direct PDF file extensions
		if url_lower.endswith('.pdf'):
			return True

		# PDF in path
		if '.pdf' in url_lower:
			return True

		# PDF MIME type in URL parameters
		if any(
			param in url_lower
			for param in [
				'content-type=application/pdf',
				'content-type=application%2fpdf',
				'mimetype=application/pdf',
				'type=application/pdf',
			]
		):
			return True

		return False

	def _is_chrome_pdf_viewer_url(self, url: str) -> bool:
		"""Check if this is Chrome's internal PDF viewer URL."""
		if not url:
			return False

		url_lower = url.lower()

		# Chrome PDF viewer uses chrome-extension:// URLs
		if 'chrome-extension://' in url_lower and 'pdf' in url_lower:
			return True

		# Chrome PDF viewer internal URLs
		if url_lower.startswith('chrome://') and 'pdf' in url_lower:
			return True

		return False

	async def _check_network_headers_for_pdf(self, target_id: TargetID) -> bool:
		"""Infer PDF via navigation history/URL; headers are not available post-navigation in this context."""
		try:
			import asyncio

			# Get CDP session
			temp_session = await self.browser_session.get_or_create_cdp_session(target_id, focus=False)

			# Get navigation history to find the main resource
			history = await asyncio.wait_for(
				temp_session.cdp_client.send.Page.getNavigationHistory(session_id=temp_session.session_id), timeout=3.0
			)

			current_entry = history.get('entries', [])
			if current_entry:
				current_index = history.get('currentIndex', 0)
				if 0 <= current_index < len(current_entry):
					current_url = current_entry[current_index].get('url', '')

					# Check if the URL itself suggests PDF
					if self._check_url_for_pdf(current_url):
						return True

			# Note: CDP doesn't easily expose response headers for completed navigations
			# For more complex cases, we'd need to set up Network.responseReceived listeners
			# before navigation, but that's overkill for most PDF detection cases

			return False

		except Exception as e:
			self.logger.debug(f'[DownloadsWatchdog] Network headers check failed (non-critical): {e}')
			return False

	async def trigger_pdf_download(self, target_id: TargetID) -> str | None:
		"""Trigger download of a PDF from Chrome's PDF viewer.

		Returns the download path if successful, None otherwise.
		"""
		self.logger.debug(f'[DownloadsWatchdog] trigger_pdf_download called for target_id={target_id}')

		if not self.browser_session.browser_profile.downloads_path:
			self.logger.warning('[DownloadsWatchdog] ❌ No downloads path configured, cannot save PDF download')
			return None

		downloads_path = self.browser_session.browser_profile.downloads_path
		self.logger.debug(f'[DownloadsWatchdog] Downloads path: {downloads_path}')

		try:
			# Create a temporary CDP session for this target without switching focus
			import asyncio

			self.logger.debug(f'[DownloadsWatchdog] Creating CDP session for PDF download from target {target_id}')
			temp_session = await self.browser_session.get_or_create_cdp_session(target_id, focus=False)

			# Try to get the PDF URL with timeout
			result = await asyncio.wait_for(
				temp_session.cdp_client.send.Runtime.evaluate(
					params={
						'expression': """
				(() => {
					// For Chrome's PDF viewer, the actual URL is in window.location.href
					// The embed element's src is often "about:blank"
					const embedElement = document.querySelector('embed[type="application/x-google-chrome-pdf"]') ||
										document.querySelector('embed[type="application/pdf"]');
					if (embedElement) {
						// Chrome PDF viewer detected - use the page URL
						return { url: window.location.href };
					}
					// Fallback to window.location.href anyway
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

			self.logger.debug(f'[DownloadsWatchdog] Generated filename: {pdf_filename}')

			# Check if already downloaded in this session
			self.logger.debug(f'[DownloadsWatchdog] PDF_URL: {pdf_url}, session_pdf_urls: {self._session_pdf_urls}')
			if pdf_url in self._session_pdf_urls:
				existing_path = self._session_pdf_urls[pdf_url]
				self.logger.debug(f'[DownloadsWatchdog] PDF already downloaded in session: {existing_path}')
				return existing_path

			# Generate unique filename if file exists from previous run
			downloads_dir = str(self.browser_session.browser_profile.downloads_path)
			os.makedirs(downloads_dir, exist_ok=True)
			final_filename = pdf_filename
			existing_files = os.listdir(downloads_dir)
			if pdf_filename in existing_files:
				# Generate unique name with (1), (2), etc.
				base, ext = os.path.splitext(pdf_filename)
				counter = 1
				while f'{base} ({counter}){ext}' in existing_files:
					counter += 1
				final_filename = f'{base} ({counter}){ext}'
				self.logger.debug(f'[DownloadsWatchdog] File exists, using: {final_filename}')

			self.logger.debug(f'[DownloadsWatchdog] Starting PDF download from: {pdf_url[:100]}...')

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
											 !response.headers.has('date');
											 
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
					# Ensure downloads directory exists
					downloads_dir = str(self.browser_session.browser_profile.downloads_path)
					os.makedirs(downloads_dir, exist_ok=True)
					download_path = os.path.join(downloads_dir, final_filename)

					# Save the PDF asynchronously
					async with await anyio.open_file(download_path, 'wb') as f:
						await f.write(bytes(download_result['data']))

					# Verify file was written successfully
					if os.path.exists(download_path):
						actual_size = os.path.getsize(download_path)
						self.logger.debug(
							f'[DownloadsWatchdog] PDF file written successfully: {download_path} ({actual_size} bytes)'
						)
					else:
						self.logger.error(f'[DownloadsWatchdog] ❌ Failed to write PDF file to: {download_path}')
						return None

					# Log cache information
					cache_status = 'from cache' if download_result.get('fromCache') else 'from network'
					response_size = download_result.get('responseSize', 0)
					self.logger.debug(
						f'[DownloadsWatchdog] ✅ Auto-downloaded PDF ({cache_status}, {response_size:,} bytes): {download_path}'
					)

					# Store URL->path mapping for this session
					self._session_pdf_urls[pdf_url] = download_path

					# Emit file downloaded event
					self.logger.debug(f'[DownloadsWatchdog] Dispatching FileDownloadedEvent for {final_filename}')
					self.event_bus.dispatch(
						FileDownloadedEvent(
							url=pdf_url,
							path=download_path,
							file_name=final_filename,
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
