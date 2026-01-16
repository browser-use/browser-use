"""
Download Manager for browser-use library.

Handles file downloads through two strategies:
1. JavaScript fetch via browser (default) - preserves authentication, handles PDFs
2. Direct HTTP downloads (download_from_remote_browser flag) - transfers files from remote browsers

Features: deduplication, progress tracking, session context preservation.
"""

import asyncio
import json
import os
import time
from pathlib import Path

import anyio
import httpx

from browser_use.browser.events import FileDownloadedEvent


class DownloadManager:
	"""
	Manages file downloads for browser automation.

	Supports JavaScript fetch (default) and HTTP downloads (download_from_remote_browser flag).
	Handles authentication, progress tracking, and file deduplication.
	"""

	def __init__(self, browser_session):
		"""Initialize with browser session for CDP access, cookies, and configuration."""
		self.session = browser_session

	# PUBLIC METHODS
	async def download_via_browser_fetch(
		self,
		target_id: str,
		url: str | None = None,
		filename: str | None = None,
		use_cache: bool = True,
		avoid_duplicates: bool = False,
		timeout: float = 10.0,
	) -> str | None:
		"""Unified browser fetch download method (refactored)."""
		self.session.logger.info('🔧 [DownloadManager] Executing download_via_browser_fetch')
		if not self.session.browser_profile.downloads_path:
			self.session.logger.warning('❌ No downloads path configured')
			return None

		try:
			# Create CDP session
			temp_session = await self.session.get_or_create_cdp_session(target_id, focus=False)

			# 1. Resolve URL
			resolved_url = await self._resolve_download_url(temp_session, url)
			if not resolved_url:
				return None

			# 2. Generate filename
			final_filename = self._generate_download_filename(resolved_url, filename)

			# 3. Check cache/duplicates
			existing_path = self._check_existing_download(resolved_url, final_filename, use_cache, avoid_duplicates)
			if existing_path:
				return existing_path

			# Use the final filename determined by duplicate checking
			final_filename = getattr(self.session, '_temp_final_filename', final_filename)

			# 4. Execute download
			download_data = await self._execute_browser_fetch(temp_session, resolved_url, use_cache, timeout)
			if not download_data:
				return None

			# 5. Save file
			return await self._save_download_file(final_filename, download_data, resolved_url, avoid_duplicates)

		except Exception as e:
			self.session.logger.error(f'❌ Browser fetch download failed: {e}')
			return None

	async def download_via_direct_http_with_tracking(self, url: str, filename: str) -> None:
		"""Download file via direct HTTP with automatic state tracking."""
		self.session.logger.info('🔧 [DownloadManager] Executing download_via_direct_http_with_tracking')
		try:
			self.add_active_download(url, filename)
			await self._download_via_http(url)
		finally:
			self.remove_active_download(url)

	def add_active_download(self, url: str, filename: str):
		"""Track a new active download."""
		self.session._active_downloads[url] = {'filename': filename, 'start_time': time.time()}
		self.session.logger.info(
			f'📥 Added 1 active download: {filename} (total: {len(self.session._active_downloads)} active downloads)'
		)

	def remove_active_download(self, url: str):
		"""Remove completed download from tracking."""
		if url in self.session._active_downloads:
			filename = self.session._active_downloads[url]['filename']
			self.session._active_downloads.pop(url, None)
			self.session.logger.info(
				f'✅ Removed 1 active download: {filename} (total: {len(self.session._active_downloads)} active downloads)'
			)

	def add_failed_download(self, url: str, filename: str, error: str):
		"""Track a failed download."""
		self.session._failed_downloads.append({'url': url, 'filename': filename, 'error': str(error), 'timestamp': time.time()})
		self.session.logger.info(
			f'❌ Added 1 failed download: {filename} (total: {len(self.session._failed_downloads)} failed downloads)'
		)
		self.session.logger.error(f'❌ Download failed: {filename} - {error}')

	# PUBLIC PROPERTIES
	@property
	def active_downloads(self) -> list[dict]:
		"""Get list of currently active downloads."""
		return [self._format_download_info(url, info) for url, info in self.session._active_downloads.items()]

	@property
	def failed_downloads(self) -> list[dict]:
		"""Get all failed downloads with age info for LLM context."""
		current_time = time.time()
		return [
			{
				'filename': failure['filename'],
				'error': failure['error'],
				'age_minutes': int((current_time - failure['timestamp']) / 60),
			}
			for failure in self.session._failed_downloads
		]

	# PRIVATE HELPER METHODS
	async def _resolve_download_url(self, session, url: str | None) -> str | None:
		"""Get URL from page if None, otherwise return provided URL."""
		if url is not None:
			return url

		# Get URL from current page (PDF case)
		try:
			result = await asyncio.wait_for(
				session.cdp_client.send.Runtime.evaluate(
					params={
						'expression': """
                        (() => {
                            // For Chrome's PDF viewer, the actual URL is in window.location.href
                            const embedElement = document.querySelector('embed[type="application/x-google-chrome-pdf"]') ||
                                                document.querySelector('embed[type="application/pdf"]');
                            if (embedElement) {
                                return { url: window.location.href };
                            }
                            return { url: window.location.href };
                        })()
                        """,
						'returnByValue': True,
					},
					session_id=session.session_id,
				),
				timeout=5.0,
			)
			url_info = result.get('result', {}).get('value', {})
			resolved_url = url_info.get('url', '')
			if not resolved_url:
				self.session.logger.warning('❌ Could not determine URL for download')
				return None
			return resolved_url
		except Exception as e:
			self.session.logger.error(f'❌ Failed to get page URL: {e}')
			return None

	def _generate_download_filename(self, url: str, filename: str | None) -> str:
		"""Generate filename from URL or use provided filename."""
		if filename is not None:
			return filename

		# Extract filename from URL
		parsed_filename = os.path.basename(url.split('?')[0])
		if not parsed_filename:
			from urllib.parse import urlparse

			parsed = urlparse(url)
			parsed_filename = os.path.basename(parsed.path) or 'document'
			if url.lower().endswith('.pdf') or 'pdf' in url.lower():
				if not parsed_filename.endswith('.pdf'):
					parsed_filename += '.pdf'
		return parsed_filename

	def _check_existing_download(self, url: str, filename: str, use_cache: bool, avoid_duplicates: bool) -> str | None:
		"""Check for existing cached/duplicate files."""
		downloads_dir = str(self.session.browser_profile.downloads_path)

		# Check session tracking for duplicates (PDF case)
		if avoid_duplicates:
			if not hasattr(self.session, '_session_pdf_urls'):
				self.session._session_pdf_urls = {}
			if url in self.session._session_pdf_urls:
				existing_path = self.session._session_pdf_urls[url]
				self.session.logger.debug(f'File already downloaded in session: {existing_path}')
				return existing_path

		# Handle duplicate filenames
		os.makedirs(downloads_dir, exist_ok=True)
		final_filename = filename

		if avoid_duplicates:
			existing_files = os.listdir(downloads_dir)
			if filename in existing_files:
				base, ext = os.path.splitext(filename)
				counter = 1
				while f'{base} ({counter}){ext}' in existing_files:
					counter += 1
				final_filename = f'{base} ({counter}){ext}'

		# Store final filename for later use
		self.session._temp_final_filename = final_filename
		return None

	async def _execute_browser_fetch(self, session, url: str, use_cache: bool, timeout: float) -> dict | None:
		"""Execute JavaScript fetch and return download result."""
		escaped_url = json.dumps(url)
		cache_option = ', { cache: "force-cache" }' if use_cache else ''

		try:
			result = await asyncio.wait_for(
				session.cdp_client.send.Runtime.evaluate(
					params={
						'expression': f"""
                    (async () => {{
                        try {{
                            const response = await fetch({escaped_url}{cache_option});
                            if (!response.ok) {{
                                return {{ error: `HTTP error! status: ${{response.status}}` }};
                            }}
                            const blob = await response.blob();
                            const arrayBuffer = await blob.arrayBuffer();
                            const uint8Array = new Uint8Array(arrayBuffer);
                            
                            return {{ 
                                data: Array.from(uint8Array),
                                responseSize: uint8Array.length
                            }};
                        }} catch (error) {{
                            return {{ error: `Fetch failed: ${{error.message}}` }};
                        }}
                    }})()
                    """,
						'awaitPromise': True,
						'returnByValue': True,
					},
					session_id=session.session_id,
				),
				timeout=timeout,
			)

			download_result = result.get('result', {}).get('value', {})

			if download_result.get('error'):
				self.session.logger.error(f'Browser fetch error: {download_result["error"]}')
				return None

			return download_result

		except Exception as e:
			self.session.logger.error(f'❌ Browser fetch execution failed: {e}')
			return None

	async def _save_download_file(self, filename: str, download_data: dict, url: str, avoid_duplicates: bool) -> str | None:
		"""Save download data to file and handle tracking."""
		if not download_data or not download_data.get('data') or len(download_data['data']) == 0:
			self.session.logger.warning('No file data received from browser fetch')
			return None

		downloads_dir = str(self.session.browser_profile.downloads_path)
		download_path = os.path.join(downloads_dir, filename)

		try:
			# Save file
			async with await anyio.open_file(download_path, 'wb') as f:
				await f.write(bytes(download_data['data']))

			if os.path.exists(download_path):
				actual_size = os.path.getsize(download_path)
				self.session.logger.info(f'✅ Browser fetch download complete: {download_path} ({actual_size} bytes)')

				# Track in session if needed
				if avoid_duplicates:
					if not hasattr(self.session, '_session_pdf_urls'):
						self.session._session_pdf_urls = {}
					self.session._session_pdf_urls[url] = download_path

				return download_path
			else:
				self.session.logger.error('❌ File was not created successfully')
				return None

		except Exception as e:
			self.session.logger.error(f'❌ Failed to save download file: {e}')
			return None

	async def _download_via_http(self, url: str):
		"""Download file directly via HTTP client with browser session data."""
		try:
			self.session.logger.info(f'🌐 Direct HTTP download: {url[:100]}...')

			# Extract cookies from browser session
			cookies = {}
			try:
				if hasattr(self.session, '_storage_state_watchdog') and self.session._storage_state_watchdog:
					cookies_list = await self.session._storage_state_watchdog.get_current_cookies()
					cookies = {cookie['name']: cookie['value'] for cookie in cookies_list}
					self.session.logger.debug(f'🍪 Using {len(cookies)} cookies for authenticated download')
				else:
					# Fallback to direct CDP cookie extraction
					cookies_list = await self.session._cdp_get_cookies()
					cookies = {cookie['name']: cookie['value'] for cookie in cookies_list}
					self.session.logger.debug(f'🍪 Using {len(cookies)} cookies via CDP for download')
			except Exception as e:
				self.session.logger.debug(f'⚠️ Could not extract cookies: {e}')

			# Get headers from browser profile
			headers = (self.session.browser_profile.headers or {}).copy()
			if not headers.get('User-Agent'):
				headers['User-Agent'] = 'Mozilla/5.0 (compatible; browser-use)'

			async with httpx.AsyncClient(timeout=300, cookies=cookies, headers=headers, follow_redirects=True) as client:
				async with client.stream('GET', url) as response:
					response.raise_for_status()

					local_downloads_dir = Path('./downloads')
					local_downloads_dir.mkdir(exist_ok=True)

					filename = url.split('/')[-1].split('?')[0] or 'download.dat'
					local_path = local_downloads_dir / filename

					# Get total size from headers for progress tracking
					total_size = int(response.headers.get('content-length', 0))
					downloaded = 0

					async with await anyio.open_file(local_path, 'wb') as f:
						async for chunk in response.aiter_bytes():
							await f.write(chunk)

							# Track progress
							downloaded += len(chunk)
							if url in self.session._active_downloads:
								self.session._active_downloads[url]['downloaded'] = downloaded
								self.session._active_downloads[url]['total_size'] = total_size

					file_size = local_path.stat().st_size
					self.session.logger.info(f'✅ HTTP download complete: {file_size} bytes saved to {local_path}')

					# Emit FileDownloadedEvent to integrate with existing download tracking
					self.session.event_bus.dispatch(
						FileDownloadedEvent(
							url=url,
							path=str(local_path),
							file_name=filename,
							file_size=file_size,
							file_type=filename.split('.')[-1] if '.' in filename else None,
							mime_type=response.headers.get('content-type'),
							auto_download=False,
							from_cache=False,
						)
					)

		except Exception as e:
			self.session.logger.error(f'❌ HTTP download failed: {e}')

			# Track the failed download
			filename = url.split('/')[-1].split('?')[0] or 'download.dat'
			self.add_failed_download(url, filename, str(e))

	def _format_download_info(self, url: str, info: dict) -> dict:
		"""Format single download with progress info."""
		download_info = {'url': url, 'filename': info['filename'], 'duration': int(time.time() - info['start_time'])}

		# Add progress information if available
		if 'downloaded' in info and 'total_size' in info:
			downloaded = info['downloaded']
			total_size = info['total_size']
			if total_size > 0:
				progress_percent = int((downloaded / total_size) * 100)
				downloaded_mb = downloaded / (1024 * 1024)
				total_mb = total_size / (1024 * 1024)
				download_info['progress'] = f'{downloaded_mb:.1f}MB / {total_mb:.1f}MB ({progress_percent}%)'
			else:
				downloaded_mb = downloaded / (1024 * 1024)
				download_info['progress'] = f'{downloaded_mb:.1f}MB'

		return download_info
