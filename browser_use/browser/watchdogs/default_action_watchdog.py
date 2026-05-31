"""Default browser action handlers using CDP."""

import asyncio
import json
from typing import Literal

from browser_use.browser.events import (
	ClickCoordinateEvent,
	ClickElementEvent,
	FileDownloadedEvent,
	GetDropdownOptionsEvent,
	GoBackEvent,
	GoForwardEvent,
	RefreshEvent,
	ScrollEvent,
	ScrollToTextEvent,
	SelectDropdownOptionEvent,
	SendKeysEvent,
	TypeTextEvent,
	UploadFileEvent,
	WaitEvent,
)
from browser_use.browser.views import BrowserError, URLNotAllowedError
from browser_use.browser.watchdog_base import BaseWatchdog
from browser_use.dom.service import EnhancedDOMTreeNode
from browser_use.observability import observe_debug

# Import EnhancedDOMTreeNode and rebuild event models that have forward references to it
# This must be done after all imports are complete
ClickCoordinateEvent.model_rebuild()
ClickElementEvent.model_rebuild()
GetDropdownOptionsEvent.model_rebuild()
SelectDropdownOptionEvent.model_rebuild()
TypeTextEvent.model_rebuild()
ScrollEvent.model_rebuild()
UploadFileEvent.model_rebuild()


class DefaultActionWatchdog(BaseWatchdog):
	"""Handles default browser actions like click, type, and scroll using CDP."""

	async def _execute_click_with_download_detection(
		self,
		click_coro,
		download_start_timeout: float = 0.5,
		download_complete_timeout: float = 30.0,
	) -> dict | None:
		"""Execute a click operation and automatically wait for any triggered download

		Args:
			click_coro: Coroutine that performs the click (should return click_metadata dict or None)
			download_start_timeout: Time to wait for download to start after click (seconds)
			download_complete_timeout: Time to wait for download to complete once started (seconds)

		Returns:
			Click metadata dict, potentially with 'download' key containing download info.
			If a download times out but is still in progress, includes 'download_in_progress' with status.
		"""
		import time

		download_started = asyncio.Event()
		download_completed = asyncio.Event()
		download_info: dict = {}
		progress_info: dict = {'last_update': 0.0, 'received_bytes': 0, 'total_bytes': 0, 'state': ''}

		def on_download_start(info: dict) -> None:
			"""Direct callback when download starts (called from CDP handler)."""
			if info.get('auto_download'):
				return  # ignore auto-downloads
			download_info['guid'] = info.get('guid', '')
			download_info['url'] = info.get('url', '')
			download_info['suggested_filename'] = info.get('suggested_filename', 'download')
			download_started.set()
			self.logger.debug(f'[ClickWithDownload] Download started: {download_info["suggested_filename"]}')

		def on_download_progress(info: dict) -> None:
			"""Direct callback when download progress updates (called from CDP handler)."""
			# Match by guid if available
			if download_info.get('guid') and info.get('guid') != download_info['guid']:
				return  # different download
			progress_info['last_update'] = time.time()
			progress_info['received_bytes'] = info.get('received_bytes', 0)
			progress_info['total_bytes'] = info.get('total_bytes', 0)
			progress_info['state'] = info.get('state', '')
			self.logger.debug(
				f'[ClickWithDownload] Progress: {progress_info["received_bytes"]}/{progress_info["total_bytes"]} bytes ({progress_info["state"]})'
			)

		def on_download_complete(info: dict) -> None:
			"""Direct callback when download completes (called from CDP handler)."""
			if info.get('auto_download'):
				return  # ignore auto-downloads
			# Match by guid if available, otherwise accept any non-auto download
			if download_info.get('guid') and info.get('guid') and info.get('guid') != download_info['guid']:
				return  # different download
			download_info['path'] = info.get('path', '')
			download_info['file_name'] = info.get('file_name', '')
			download_info['file_size'] = info.get('file_size', 0)
			download_info['file_type'] = info.get('file_type')
			download_info['mime_type'] = info.get('mime_type')
			download_completed.set()
			self.logger.debug(f'[ClickWithDownload] Download completed: {download_info["file_name"]}')

		# Get the downloads watchdog and register direct callbacks
		downloads_watchdog = self.browser_session._downloads_watchdog
		self.logger.debug(f'[ClickWithDownload] downloads_watchdog={downloads_watchdog is not None}')
		if downloads_watchdog:
			self.logger.debug('[ClickWithDownload] Registering download callbacks...')
			downloads_watchdog.register_download_callbacks(
				on_start=on_download_start,
				on_progress=on_download_progress,
				on_complete=on_download_complete,
			)
		else:
			self.logger.warning('[ClickWithDownload] No downloads_watchdog available!')

		try:
			# Perform the click
			click_metadata = await click_coro

			# Check for validation errors - return them immediately without waiting for downloads
			if isinstance(click_metadata, dict) and 'validation_error' in click_metadata:
				return click_metadata

			# Wait briefly to see if a download starts
			try:
				await asyncio.wait_for(download_started.wait(), timeout=download_start_timeout)

				# Download started!
				self.logger.info(f'📥 Download started: {download_info.get("suggested_filename", "unknown")}')

				# Now wait for it to complete with longer timeout
				try:
					await asyncio.wait_for(download_completed.wait(), timeout=download_complete_timeout)

					# Download completed successfully
					msg = f'Downloaded file: {download_info["file_name"]} ({download_info["file_size"]} bytes) saved to {download_info["path"]}'
					self.logger.info(f'💾 {msg}')

					# Merge download info into click_metadata
					if click_metadata is None:
						click_metadata = {}
					click_metadata['download'] = {
						'path': download_info['path'],
						'file_name': download_info['file_name'],
						'file_size': download_info['file_size'],
						'file_type': download_info.get('file_type'),
						'mime_type': download_info.get('mime_type'),
					}
				except TimeoutError:
					# Download timed out - check if it's still in progress
					if click_metadata is None:
						click_metadata = {}

					filename = download_info.get('suggested_filename', 'unknown')
					received = progress_info.get('received_bytes', 0)
					total = progress_info.get('total_bytes', 0)
					state = progress_info.get('state', 'unknown')
					last_update = progress_info.get('last_update', 0.0)
					time_since_update = time.time() - last_update if last_update > 0 else float('inf')

					# Check if download is still actively progressing (received update in last 5 seconds)
					is_still_active = time_since_update < 5.0 and state == 'inProgress'

					if is_still_active:
						# Download is still progressing - suggest waiting
						if total > 0:
							percent = (received / total) * 100
							progress_str = f'{percent:.1f}% ({received:,}/{total:,} bytes)'
						else:
							progress_str = f'{received:,} bytes downloaded (total size unknown)'

						msg = (
							f'Download timed out after {download_complete_timeout}s but is still in progress: '
							f'{filename} - {progress_str}. '
							f'The download appears to be progressing normally. Consider using the wait action '
							f'to allow more time for the download to complete.'
						)
						self.logger.warning(f'⏱️ {msg}')
						click_metadata['download_in_progress'] = {
							'file_name': filename,
							'received_bytes': received,
							'total_bytes': total,
							'state': state,
							'message': msg,
						}
					else:
						# Download may be stalled or completed
						if received > 0:
							msg = (
								f'Download timed out after {download_complete_timeout}s: {filename}. '
								f'Last progress: {received:,} bytes received. '
								f'The download may have stalled or completed - check the downloads folder.'
							)
						else:
							msg = (
								f'Download timed out after {download_complete_timeout}s: {filename}. '
								f'No progress data received - the download may have failed to start properly.'
							)
						self.logger.warning(f'⏱️ {msg}')
						click_metadata['download_timeout'] = {
							'file_name': filename,
							'received_bytes': received,
							'total_bytes': total,
							'message': msg,
						}
			except TimeoutError:
				# No download started within grace period
				pass

			return click_metadata if isinstance(click_metadata, dict) else None

		finally:
			# Unregister download callbacks
			if downloads_watchdog:
				downloads_watchdog.unregister_download_callbacks(
					on_start=on_download_start,
					on_progress=on_download_progress,
					on_complete=on_download_complete,
				)

	def _is_print_related_element(self, element_node: EnhancedDOMTreeNode) -> bool:
		"""Check if an element is related to printing (print buttons, print dialogs, etc.).

		Primary check: onclick attribute (most reliable for print detection)
		Fallback: button text/value (for cases without onclick)
		"""
		# Primary: Check onclick attribute for print-related functions (most reliable)
		onclick = element_node.attributes.get('onclick', '').lower() if element_node.attributes else ''
		if onclick and 'print' in onclick:
			# Matches: window.print(), PrintElem(), print(), etc.
			return True

		return False

	async def _handle_print_button_click(self, element_node: EnhancedDOMTreeNode) -> dict | None:
		"""Handle print button by directly generating PDF via CDP instead of opening dialog.

		Returns:
			Metadata dict with download path if successful, None otherwise
		"""
		try:
			import base64
			import os
			from pathlib import Path

			# Get CDP session
			cdp_session = await self.browser_session.get_or_create_cdp_session(focus=True)

			# Generate PDF using CDP Page.printToPDF
			result = await asyncio.wait_for(
				cdp_session.cdp_client.send.Page.printToPDF(
					params={
						'printBackground': True,
						'preferCSSPageSize': True,
					},
					session_id=cdp_session.session_id,
				),
				timeout=15.0,  # 15 second timeout for PDF generation
			)

			pdf_data = result.get('data')
			if not pdf_data:
				self.logger.warning('⚠️ PDF generation returned no data')
				return None

			# Decode base64 PDF data
			pdf_bytes = base64.b64decode(pdf_data)

			# Get downloads path
			downloads_path = self.browser_session.browser_profile.downloads_path
			if not downloads_path:
				self.logger.warning('⚠️ No downloads path configured, cannot save PDF')
				return None

			# Generate filename from page title or URL
			try:
				page_title = await asyncio.wait_for(self.browser_session.get_current_page_title(), timeout=2.0)
				# Sanitize title for filename
				import re

				safe_title = re.sub(r'[^\w\s-]', '', page_title)[:50]  # Max 50 chars
				filename = f'{safe_title}.pdf' if safe_title else 'print.pdf'
			except Exception:
				filename = 'print.pdf'

			# Ensure downloads directory exists
			downloads_dir = Path(downloads_path).expanduser().resolve()
			downloads_dir.mkdir(parents=True, exist_ok=True)

			# Generate unique filename if file exists
			final_path = downloads_dir / filename
			if final_path.exists():
				base, ext = os.path.splitext(filename)
				counter = 1
				while (downloads_dir / f'{base} ({counter}){ext}').exists():
					counter += 1
				final_path = downloads_dir / f'{base} ({counter}){ext}'

			# Write PDF to file
			import anyio

			async with await anyio.open_file(final_path, 'wb') as f:
				await f.write(pdf_bytes)

			file_size = final_path.stat().st_size
			self.logger.info(f'✅ Generated PDF via CDP: {final_path} ({file_size:,} bytes)')

			page_url = await self.browser_session.get_current_page_url()
			await self.browser_session.on_FileDownloadedEvent(
				FileDownloadedEvent(
					url=page_url,
					path=str(final_path),
					file_name=final_path.name,
					file_size=file_size,
					file_type='pdf',
					mime_type='application/pdf',
					auto_download=False,  # This was intentional (user clicked print)
				)
			)

			return {'pdf_generated': True, 'path': str(final_path)}

		except TimeoutError:
			self.logger.warning('⏱️ PDF generation timed out')
			return None
		except Exception as e:
			self.logger.warning(f'⚠️ Failed to generate PDF via CDP: {type(e).__name__}: {e}')
			return None

	@observe_debug(ignore_input=True, ignore_output=True, name='click_element_event')
	async def on_ClickElementEvent(self, event: ClickElementEvent) -> dict | None:
		"""Compatibility adapter for legacy event-based click dispatch."""
		return await self.click_element(event.node, button=event.button)

	async def click_element(
		self,
		element_node: EnhancedDOMTreeNode,
		*,
		button: Literal['left', 'right', 'middle'] = 'left',
	) -> dict | None:
		"""Compatibility adapter for direct click calls that still reference this handler."""
		from browser_use.browser.services import ClickService

		return await ClickService(browser_session=self.browser_session).click_node(element_node, button=button)

	async def on_ClickCoordinateEvent(self, event: ClickCoordinateEvent) -> dict | None:
		"""Compatibility adapter for legacy event-based coordinate click dispatch."""
		return await self.click_coordinates(
			event.coordinate_x,
			event.coordinate_y,
			button=event.button,
			force=event.force,
		)

	async def click_coordinates(
		self,
		coordinate_x: int,
		coordinate_y: int,
		*,
		button: Literal['left', 'right', 'middle'] = 'left',
		force: bool = False,
	) -> dict | None:
		"""Compatibility adapter for direct coordinate-click calls that still reference this handler."""
		from browser_use.browser.services import ClickService

		return await ClickService(browser_session=self.browser_session).click_coordinates(
			coordinate_x,
			coordinate_y,
			button=button,
			force=force,
		)

	async def on_TypeTextEvent(self, event: TypeTextEvent) -> dict | None:
		"""Compatibility adapter for legacy event-based text entry dispatch."""
		return await self.type_text(
			event.node,
			event.text,
			clear=event.clear,
			is_sensitive=event.is_sensitive,
			sensitive_key_name=event.sensitive_key_name,
		)

	async def type_text(
		self,
		element_node: EnhancedDOMTreeNode,
		text: str,
		*,
		clear: bool = True,
		is_sensitive: bool = False,
		sensitive_key_name: str | None = None,
	) -> dict | None:
		"""Compatibility adapter for direct text-entry calls that still reference this handler."""
		from browser_use.browser.services import TypeService

		return await TypeService(browser_session=self.browser_session).type_node(
			element_node,
			text,
			clear=clear,
			is_sensitive=is_sensitive,
			sensitive_key_name=sensitive_key_name,
		)

	async def on_ScrollEvent(self, event: ScrollEvent) -> None:
		"""Compatibility adapter for legacy event-based scroll requests."""
		from browser_use.browser.services import ScrollService

		await ScrollService(browser_session=self.browser_session).scroll_page(
			event.amount,
			direction=event.direction,
			node=event.node,
		)
		return None

	# ========== Implementation Methods ==========

	async def _check_element_occlusion(self, backend_node_id: int, x: float, y: float, cdp_session) -> bool:
		"""Check if an element is occluded by other elements at the given coordinates.

		Args:
			backend_node_id: The backend node ID of the target element
			x: X coordinate to check
			y: Y coordinate to check
			cdp_session: CDP session to use

		Returns:
			True if element is occluded, False if clickable
		"""
		try:
			session_id = cdp_session.session_id

			# Get target element info for comparison
			target_result = await cdp_session.cdp_client.send.DOM.resolveNode(
				params={'backendNodeId': backend_node_id}, session_id=session_id
			)

			if 'object' not in target_result:
				self.logger.debug('Could not resolve target element, assuming occluded')
				return True

			object_id = target_result['object']['objectId']

			# Get target element info
			target_info_result = await cdp_session.cdp_client.send.Runtime.callFunctionOn(
				params={
					'objectId': object_id,
					'functionDeclaration': """
					function() {
						const getElementInfo = (el) => {
							return {
								tagName: el.tagName,
								id: el.id || '',
								className: el.className || '',
								textContent: (el.textContent || '').substring(0, 100)
							};
						};


						const elementAtPoint = document.elementFromPoint(arguments[0], arguments[1]);
						if (!elementAtPoint) {
							return { targetInfo: getElementInfo(this), isClickable: false };
						}


						// Simple containment-based clickability logic
						let isClickable = this === elementAtPoint ||
							this.contains(elementAtPoint) ||
							elementAtPoint.contains(this);

						// Check label-input associations when containment check fails
						if (!isClickable) {
							const target = this;
							const atPoint = elementAtPoint;

							// Case 1: target is <input>, atPoint is its associated <label> (or child of that label)
							if (target.tagName === 'INPUT' && target.id) {
								const escapedId = CSS.escape(target.id);
								const assocLabel = document.querySelector('label[for="' + escapedId + '"]');
								if (assocLabel && (assocLabel === atPoint || assocLabel.contains(atPoint))) {
									isClickable = true;
								}
							}

							// Case 2: target is <input>, atPoint is inside a <label> ancestor that wraps the target
							if (!isClickable && target.tagName === 'INPUT') {
								let ancestor = atPoint;
								for (let i = 0; i < 3 && ancestor; i++) {
									if (ancestor.tagName === 'LABEL' && ancestor.contains(target)) {
										isClickable = true;
										break;
									}
									ancestor = ancestor.parentElement;
								}
							}

							// Case 3: target is <label>, atPoint is the associated <input>
							if (!isClickable && target.tagName === 'LABEL') {
								if (target.htmlFor && atPoint.tagName === 'INPUT' && atPoint.id === target.htmlFor) {
									isClickable = true;
								}
								// Also check if atPoint is an input inside the label
								if (!isClickable && atPoint.tagName === 'INPUT' && target.contains(atPoint)) {
									isClickable = true;
								}
							}
						}

						return {
							targetInfo: getElementInfo(this),
							elementAtPointInfo: getElementInfo(elementAtPoint),
							isClickable: isClickable
						};
					}
					""",
					'arguments': [{'value': x}, {'value': y}],
					'returnByValue': True,
				},
				session_id=session_id,
			)

			if 'result' not in target_info_result or 'value' not in target_info_result['result']:
				self.logger.debug('Could not get target element info, assuming occluded')
				return True

			target_data = target_info_result['result']['value']
			is_clickable = target_data.get('isClickable', False)

			if is_clickable:
				self.logger.debug('Element is clickable (target, contained, or semantically related)')
				return False
			else:
				target_info = target_data.get('targetInfo', {})
				element_at_point_info = target_data.get('elementAtPointInfo', {})
				self.logger.debug(
					f'Element is occluded. Target: {target_info.get("tagName", "unknown")} '
					f'(id={target_info.get("id", "none")}), '
					f'ElementAtPoint: {element_at_point_info.get("tagName", "unknown")} '
					f'(id={element_at_point_info.get("id", "none")})'
				)
				return True

		except Exception as e:
			self.logger.debug(f'Occlusion check failed: {e}, assuming not occluded')
			return False

	async def _click_element_node_impl(self, element_node) -> dict | None:
		"""
		Click an element using pure CDP with multiple fallback methods for getting element geometry.

		Args:
			element_node: The DOM element to click
		"""

		try:
			# Check if element is a file input or select dropdown - these should not be clicked
			tag_name = element_node.tag_name.lower() if element_node.tag_name else ''
			element_type = element_node.attributes.get('type', '').lower() if element_node.attributes else ''

			if tag_name == 'select':
				msg = f'Cannot click on <select> elements. Use dropdown_options(index={element_node.backend_node_id}) action instead.'
				# Return error dict instead of raising to avoid ERROR logs
				return {'validation_error': msg}

			if tag_name == 'input' and element_type == 'file':
				msg = f'Cannot click on file input element (index={element_node.backend_node_id}). File uploads must be handled using upload_file_to_element action.'
				# Return error dict instead of raising to avoid ERROR logs
				return {'validation_error': msg}

			# Get CDP client
			cdp_session = await self.browser_session.cdp_client_for_node(element_node)

			# Get the correct session ID for the element's frame
			session_id = cdp_session.session_id

			# Get element bounds
			backend_node_id = element_node.backend_node_id

			# For checkbox/radio: capture pre-click state to verify toggle worked
			is_toggle_element = tag_name == 'input' and element_type in ('checkbox', 'radio')
			pre_click_checked: bool | None = None
			checkbox_object_id: str | None = None
			if is_toggle_element and backend_node_id:
				try:
					resolve_res = await cdp_session.cdp_client.send.DOM.resolveNode(
						params={'backendNodeId': backend_node_id}, session_id=session_id
					)
					obj_info = resolve_res.get('object', {})
					checkbox_object_id = obj_info.get('objectId') if obj_info else None
					if not checkbox_object_id:
						raise Exception('Failed to resolve checkbox element objectId')
					state_res = await cdp_session.cdp_client.send.Runtime.callFunctionOn(
						params={
							'functionDeclaration': 'function() { return this.checked; }',
							'objectId': checkbox_object_id,
							'returnByValue': True,
						},
						session_id=session_id,
					)
					pre_click_checked = state_res.get('result', {}).get('value')
					self.logger.debug(f'Checkbox pre-click state: checked={pre_click_checked}')
				except Exception as e:
					self.logger.debug(f'Could not capture pre-click checkbox state: {e}')

			# Get viewport dimensions for visibility checks
			layout_metrics = await cdp_session.cdp_client.send.Page.getLayoutMetrics(session_id=session_id)
			viewport_width = layout_metrics['layoutViewport']['clientWidth']
			viewport_height = layout_metrics['layoutViewport']['clientHeight']

			# Scroll element into view FIRST before getting coordinates
			try:
				await cdp_session.cdp_client.send.DOM.scrollIntoViewIfNeeded(
					params={'backendNodeId': backend_node_id}, session_id=session_id
				)
				await asyncio.sleep(0.05)  # Wait for scroll to complete
				self.logger.debug('Scrolled element into view before getting coordinates')
			except Exception as e:
				self.logger.debug(f'Failed to scroll element into view: {e}')

			# Get element coordinates using the unified method AFTER scrolling
			element_rect = await self.browser_session.get_element_coordinates(backend_node_id, cdp_session)

			# Convert rect to quads format if we got coordinates
			quads = []
			if element_rect:
				# Convert DOMRect to quad format
				x, y, w, h = element_rect.x, element_rect.y, element_rect.width, element_rect.height
				quads = [
					[
						x,
						y,  # top-left
						x + w,
						y,  # top-right
						x + w,
						y + h,  # bottom-right
						x,
						y + h,  # bottom-left
					]
				]
				self.logger.debug(
					f'Got coordinates from unified method: {element_rect.x}, {element_rect.y}, {element_rect.width}x{element_rect.height}'
				)

			# If we still don't have quads, fall back to JS click
			if not quads:
				self.logger.warning('Could not get element geometry from any method, falling back to JavaScript click')
				try:
					result = await cdp_session.cdp_client.send.DOM.resolveNode(
						params={'backendNodeId': backend_node_id},
						session_id=session_id,
					)
					assert 'object' in result and 'objectId' in result['object'], (
						'Failed to find DOM element based on backendNodeId, maybe page content changed?'
					)
					object_id = result['object']['objectId']

					await cdp_session.cdp_client.send.Runtime.callFunctionOn(
						params={
							'functionDeclaration': 'function() { this.click(); }',
							'objectId': object_id,
						},
						session_id=session_id,
					)
					await asyncio.sleep(0.05)
					# Navigation is handled by BrowserSession via events
					return None
				except Exception as js_e:
					self.logger.warning(f'CDP JavaScript click also failed: {js_e}')
					if 'No node with given id found' in str(js_e):
						raise Exception('Element with given id not found')
					else:
						raise Exception(f'Failed to click element: {js_e}')

			# Find the largest visible quad within the viewport
			best_quad = None
			best_area = 0

			for quad in quads:
				if len(quad) < 8:
					continue

				# Calculate quad bounds
				xs = [quad[i] for i in range(0, 8, 2)]
				ys = [quad[i] for i in range(1, 8, 2)]
				min_x, max_x = min(xs), max(xs)
				min_y, max_y = min(ys), max(ys)

				# Check if quad intersects with viewport
				if max_x < 0 or max_y < 0 or min_x > viewport_width or min_y > viewport_height:
					continue  # Quad is completely outside viewport

				# Calculate visible area (intersection with viewport)
				visible_min_x = max(0, min_x)
				visible_max_x = min(viewport_width, max_x)
				visible_min_y = max(0, min_y)
				visible_max_y = min(viewport_height, max_y)

				visible_width = visible_max_x - visible_min_x
				visible_height = visible_max_y - visible_min_y
				visible_area = visible_width * visible_height

				if visible_area > best_area:
					best_area = visible_area
					best_quad = quad

			if not best_quad:
				# No visible quad found, use the first quad anyway
				best_quad = quads[0]
				self.logger.warning('No visible quad found, using first quad')

			# Calculate center point of the best quad
			center_x = sum(best_quad[i] for i in range(0, 8, 2)) / 4
			center_y = sum(best_quad[i] for i in range(1, 8, 2)) / 4

			# Ensure click point is within viewport bounds
			center_x = max(0, min(viewport_width - 1, center_x))
			center_y = max(0, min(viewport_height - 1, center_y))

			# Check for occlusion before attempting CDP click
			is_occluded = await self._check_element_occlusion(backend_node_id, center_x, center_y, cdp_session)

			if is_occluded:
				self.logger.debug('🚫 Element is occluded, falling back to JavaScript click')
				try:
					result = await cdp_session.cdp_client.send.DOM.resolveNode(
						params={'backendNodeId': backend_node_id},
						session_id=session_id,
					)
					assert 'object' in result and 'objectId' in result['object'], (
						'Failed to find DOM element based on backendNodeId'
					)
					object_id = result['object']['objectId']

					await cdp_session.cdp_client.send.Runtime.callFunctionOn(
						params={
							'functionDeclaration': 'function() { this.click(); }',
							'objectId': object_id,
						},
						session_id=session_id,
					)
					await asyncio.sleep(0.05)
					return None
				except Exception as js_e:
					self.logger.error(f'JavaScript click fallback failed: {js_e}')
					raise Exception(f'Failed to click occluded element: {js_e}')

			# Perform the click using CDP (element is not occluded)
			try:
				self.logger.debug(f'👆 Dragging mouse over element before clicking x: {center_x}px y: {center_y}px ...')
				# Move mouse to element
				await cdp_session.cdp_client.send.Input.dispatchMouseEvent(
					params={
						'type': 'mouseMoved',
						'x': center_x,
						'y': center_y,
					},
					session_id=session_id,
				)
				await asyncio.sleep(0.05)

				# Mouse down
				self.logger.debug(f'👆🏾 Clicking x: {center_x}px y: {center_y}px ...')
				try:
					await asyncio.wait_for(
						cdp_session.cdp_client.send.Input.dispatchMouseEvent(
							params={
								'type': 'mousePressed',
								'x': center_x,
								'y': center_y,
								'button': 'left',
								'clickCount': 1,
							},
							session_id=session_id,
						),
						timeout=3.0,  # 3 second timeout for mousePressed
					)
					await asyncio.sleep(0.08)
				except TimeoutError:
					self.logger.debug('⏱️ Mouse down timed out (likely due to dialog), continuing...')
					# Don't sleep if we timed out

				# Mouse up
				try:
					await asyncio.wait_for(
						cdp_session.cdp_client.send.Input.dispatchMouseEvent(
							params={
								'type': 'mouseReleased',
								'x': center_x,
								'y': center_y,
								'button': 'left',
								'clickCount': 1,
							},
							session_id=session_id,
						),
						timeout=5.0,  # 5 second timeout for mouseReleased
					)
				except TimeoutError:
					self.logger.debug('⏱️ Mouse up timed out (possibly due to lag or dialog popup), continuing...')

				self.logger.debug('🖱️ Clicked successfully using x,y coordinates')

				# For checkbox/radio: verify state toggled, fall back to JS element.click() if not
				if is_toggle_element and pre_click_checked is not None and checkbox_object_id:
					try:
						await asyncio.sleep(0.05)
						state_res = await cdp_session.cdp_client.send.Runtime.callFunctionOn(
							params={
								'functionDeclaration': 'function() { return this.checked; }',
								'objectId': checkbox_object_id,
								'returnByValue': True,
							},
							session_id=session_id,
						)
						post_click_checked = state_res.get('result', {}).get('value')
						if post_click_checked == pre_click_checked:
							# CDP mouse events didn't toggle the checkbox — try JS element.click()
							self.logger.debug(
								f'Checkbox state unchanged after CDP click (checked={pre_click_checked}), using JS fallback'
							)
							await cdp_session.cdp_client.send.Runtime.callFunctionOn(
								params={'functionDeclaration': 'function() { this.click(); }', 'objectId': checkbox_object_id},
								session_id=session_id,
							)
							await asyncio.sleep(0.05)
							final_res = await cdp_session.cdp_client.send.Runtime.callFunctionOn(
								params={
									'functionDeclaration': 'function() { return this.checked; }',
									'objectId': checkbox_object_id,
									'returnByValue': True,
								},
								session_id=session_id,
							)
							post_click_checked = final_res.get('result', {}).get('value')
						self.logger.debug(f'Checkbox post-click state: checked={post_click_checked}')
						return {'click_x': center_x, 'click_y': center_y, 'checked': post_click_checked}
					except Exception as e:
						self.logger.debug(f'Checkbox state verification failed (non-critical): {e}')

				# Return coordinates as dict for metadata
				return {'click_x': center_x, 'click_y': center_y}

			except Exception as e:
				self.logger.warning(f'CDP click failed: {type(e).__name__}: {e}')
				# Fall back to JavaScript click via CDP
				try:
					result = await cdp_session.cdp_client.send.DOM.resolveNode(
						params={'backendNodeId': backend_node_id},
						session_id=session_id,
					)
					assert 'object' in result and 'objectId' in result['object'], (
						'Failed to find DOM element based on backendNodeId, maybe page content changed?'
					)
					object_id = result['object']['objectId']

					await cdp_session.cdp_client.send.Runtime.callFunctionOn(
						params={
							'functionDeclaration': 'function() { this.click(); }',
							'objectId': object_id,
						},
						session_id=session_id,
					)

					# Small delay for dialog dismissal
					await asyncio.sleep(0.1)

					return None
				except Exception as js_e:
					self.logger.warning(f'CDP JavaScript click also failed: {js_e}')
					raise Exception(f'Failed to click element: {e}')
			finally:
				# Always re-focus back to original top-level page session context in case click opened a new tab/popup/window/dialog/etc.
				# Use timeout to prevent hanging if dialog is blocking
				try:
					cdp_session = await asyncio.wait_for(self.browser_session.get_or_create_cdp_session(focus=True), timeout=3.0)
					await asyncio.wait_for(
						cdp_session.cdp_client.send.Runtime.runIfWaitingForDebugger(session_id=cdp_session.session_id),
						timeout=2.0,
					)
				except TimeoutError:
					self.logger.debug('⏱️ Refocus after click timed out (page may be blocked by dialog). Continuing...')
				except Exception as e:
					self.logger.debug(f'⚠️ Refocus error (non-critical): {type(e).__name__}: {e}')

		except URLNotAllowedError as e:
			raise e
		except BrowserError as e:
			raise e
		except Exception as e:
			# Extract key element info for error message
			element_info = f'<{element_node.tag_name or "unknown"}'
			if element_node.backend_node_id:
				element_info += f' index={element_node.backend_node_id}'
			element_info += '>'

			# Create helpful error message based on context
			error_detail = f'Failed to click element {element_info}. The element may not be interactable or visible.'

			# Add hint if element has index (common in code-use mode)
			if element_node.backend_node_id:
				error_detail += f' If the page changed after navigation/interaction, the index [{element_node.backend_node_id}] may be stale. Get fresh browser state before retrying.'

			raise BrowserError(
				message=f'Failed to click element: {str(e)}',
				long_term_memory=error_detail,
			)

	async def _click_on_coordinate(
		self,
		coordinate_x: int,
		coordinate_y: int,
		force: bool = False,
		button: Literal['left', 'right', 'middle'] = 'left',
	) -> dict | None:
		"""
		Click directly at coordinates using CDP Input.dispatchMouseEvent.

		Args:
			coordinate_x: X coordinate in viewport
			coordinate_y: Y coordinate in viewport
			force: If True, skip all safety checks (used when force=True in event)

		Returns:
			Dict with click coordinates or None
		"""
		try:
			# Get CDP session
			cdp_session = await self.browser_session.get_or_create_cdp_session()
			session_id = cdp_session.session_id

			self.logger.debug(f'👆 Moving mouse to ({coordinate_x}, {coordinate_y})...')

			# Move mouse to coordinates
			await cdp_session.cdp_client.send.Input.dispatchMouseEvent(
				params={
					'type': 'mouseMoved',
					'x': coordinate_x,
					'y': coordinate_y,
				},
				session_id=session_id,
			)
			await asyncio.sleep(0.05)

			# Mouse down
			self.logger.debug(f'👆🏾 Clicking at ({coordinate_x}, {coordinate_y})...')
			try:
				await asyncio.wait_for(
					cdp_session.cdp_client.send.Input.dispatchMouseEvent(
						params={
							'type': 'mousePressed',
							'x': coordinate_x,
							'y': coordinate_y,
							'button': button,
							'clickCount': 1,
						},
						session_id=session_id,
					),
					timeout=3.0,
				)
				await asyncio.sleep(0.05)
			except TimeoutError:
				self.logger.debug('⏱️ Mouse down timed out (likely due to dialog), continuing...')

			# Mouse up
			try:
				await asyncio.wait_for(
					cdp_session.cdp_client.send.Input.dispatchMouseEvent(
						params={
							'type': 'mouseReleased',
							'x': coordinate_x,
							'y': coordinate_y,
							'button': button,
							'clickCount': 1,
						},
						session_id=session_id,
					),
					timeout=5.0,
				)
			except TimeoutError:
				self.logger.debug('⏱️ Mouse up timed out (possibly due to lag or dialog popup), continuing...')

			self.logger.debug(f'🖱️ Clicked successfully at ({coordinate_x}, {coordinate_y})')

			# Return coordinates as metadata
			return {'click_x': coordinate_x, 'click_y': coordinate_y}

		except Exception as e:
			self.logger.error(f'Failed to click at coordinates ({coordinate_x}, {coordinate_y}): {type(e).__name__}: {e}')
			raise BrowserError(
				message=f'Failed to click at coordinates: {e}',
				long_term_memory=f'Failed to click at coordinates ({coordinate_x}, {coordinate_y}). The coordinates may be outside viewport or the page may have changed.',
			)

	async def _type_to_page(self, text: str):
		"""
		Type text to the page (whatever element currently has focus).
		This is used when index is 0 or when an element can't be found.
		"""
		try:
			# Get CDP client and session
			cdp_session = await self.browser_session.get_or_create_cdp_session(target_id=None, focus=True)

			# Type the text character by character to the focused element
			for char in text:
				# Handle newline characters as Enter key
				if char == '\n':
					# Send proper Enter key sequence
					await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
						params={
							'type': 'keyDown',
							'key': 'Enter',
							'code': 'Enter',
							'windowsVirtualKeyCode': 13,
						},
						session_id=cdp_session.session_id,
					)
					# Send char event with carriage return
					await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
						params={
							'type': 'char',
							'text': '\r',
						},
						session_id=cdp_session.session_id,
					)
					# Send keyup
					await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
						params={
							'type': 'keyUp',
							'key': 'Enter',
							'code': 'Enter',
							'windowsVirtualKeyCode': 13,
						},
						session_id=cdp_session.session_id,
					)
				else:
					# Handle regular characters
					# Send keydown
					await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
						params={
							'type': 'keyDown',
							'key': char,
						},
						session_id=cdp_session.session_id,
					)
					# Send char for actual text input
					await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
						params={
							'type': 'char',
							'text': char,
						},
						session_id=cdp_session.session_id,
					)
					# Send keyup
					await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
						params={
							'type': 'keyUp',
							'key': char,
						},
						session_id=cdp_session.session_id,
					)
				# Add 10ms delay between keystrokes
				await asyncio.sleep(0.010)
		except Exception as e:
			raise Exception(f'Failed to type to page: {str(e)}')

	def _get_char_modifiers_and_vk(self, char: str) -> tuple[int, int, str]:
		"""Get modifiers, virtual key code, and base key for a character.

		Returns:
			(modifiers, windowsVirtualKeyCode, base_key)
		"""
		# Characters that require Shift modifier
		shift_chars = {
			'!': ('1', 49),
			'@': ('2', 50),
			'#': ('3', 51),
			'$': ('4', 52),
			'%': ('5', 53),
			'^': ('6', 54),
			'&': ('7', 55),
			'*': ('8', 56),
			'(': ('9', 57),
			')': ('0', 48),
			'_': ('-', 189),
			'+': ('=', 187),
			'{': ('[', 219),
			'}': (']', 221),
			'|': ('\\', 220),
			':': (';', 186),
			'"': ("'", 222),
			'<': (',', 188),
			'>': ('.', 190),
			'?': ('/', 191),
			'~': ('`', 192),
		}

		# Check if character requires Shift
		if char in shift_chars:
			base_key, vk_code = shift_chars[char]
			return (8, vk_code, base_key)  # Shift=8

		# Some Unicode characters' upper()/lower() expand to multiple code points
		# (e.g. 'ß'.upper() == 'SS', 'ﬃ'.upper() == 'FFI'). ord() rejects those,
		# so fall back to the original char's code point for the VK code.
		def _vk_from(c: str) -> int:
			up = c.upper()
			return ord(up) if len(up) == 1 else ord(c)

		# Uppercase letters require Shift
		if char.isupper():
			return (8, ord(char), char.lower()[:1] or char)  # Shift=8

		# Lowercase letters
		if char.islower():
			return (0, _vk_from(char), char)

		# Numbers
		if char.isdigit():
			return (0, ord(char), char)

		# Special characters without Shift
		no_shift_chars = {
			' ': 32,
			'-': 189,
			'=': 187,
			'[': 219,
			']': 221,
			'\\': 220,
			';': 186,
			"'": 222,
			',': 188,
			'.': 190,
			'/': 191,
			'`': 192,
		}

		if char in no_shift_chars:
			return (0, no_shift_chars[char], char)

		# Fallback
		return (0, _vk_from(char) if char.isalpha() else ord(char), char)

	def _get_key_code_for_char(self, char: str) -> str:
		"""Get the proper key code for a character (like Playwright does)."""
		# Key code mapping for common characters (using proper base keys + modifiers)
		key_codes = {
			' ': 'Space',
			'.': 'Period',
			',': 'Comma',
			'-': 'Minus',
			'_': 'Minus',  # Underscore uses Minus with Shift
			'@': 'Digit2',  # @ uses Digit2 with Shift
			'!': 'Digit1',  # ! uses Digit1 with Shift (not 'Exclamation')
			'?': 'Slash',  # ? uses Slash with Shift
			':': 'Semicolon',  # : uses Semicolon with Shift
			';': 'Semicolon',
			'(': 'Digit9',  # ( uses Digit9 with Shift
			')': 'Digit0',  # ) uses Digit0 with Shift
			'[': 'BracketLeft',
			']': 'BracketRight',
			'{': 'BracketLeft',  # { uses BracketLeft with Shift
			'}': 'BracketRight',  # } uses BracketRight with Shift
			'/': 'Slash',
			'\\': 'Backslash',
			'=': 'Equal',
			'+': 'Equal',  # + uses Equal with Shift
			'*': 'Digit8',  # * uses Digit8 with Shift
			'&': 'Digit7',  # & uses Digit7 with Shift
			'%': 'Digit5',  # % uses Digit5 with Shift
			'$': 'Digit4',  # $ uses Digit4 with Shift
			'#': 'Digit3',  # # uses Digit3 with Shift
			'^': 'Digit6',  # ^ uses Digit6 with Shift
			'~': 'Backquote',  # ~ uses Backquote with Shift
			'`': 'Backquote',
			"'": 'Quote',
			'"': 'Quote',  # " uses Quote with Shift
		}

		# Numbers
		if char.isdigit():
			return f'Digit{char}'

		# Letters
		if char.isalpha():
			return f'Key{char.upper()}'

		# Special characters
		if char in key_codes:
			return key_codes[char]

		# Fallback for unknown characters
		return f'Key{char.upper()}'

	async def _clear_text_field(self, object_id: str, cdp_session) -> bool:
		"""Clear text field using multiple strategies, starting with the most reliable."""
		try:
			# Strategy 1: Direct JavaScript value/content setting (handles both inputs and contenteditable)
			self.logger.debug('🧹 Clearing text field using JavaScript value setting')

			clear_result = await cdp_session.cdp_client.send.Runtime.callFunctionOn(
				params={
					'functionDeclaration': """
						function() {
							// Check if it's a contenteditable element
							const hasContentEditable = this.getAttribute('contenteditable') === 'true' ||
													this.getAttribute('contenteditable') === '' ||
													this.isContentEditable === true;

							if (hasContentEditable) {
								// For contenteditable elements, clear all content
								while (this.firstChild) {
									this.removeChild(this.firstChild);
								}
								this.textContent = "";
								this.innerHTML = "";

								// Focus and position cursor at the beginning
								this.focus();
								const selection = window.getSelection();
								const range = document.createRange();
								range.setStart(this, 0);
								range.setEnd(this, 0);
								selection.removeAllRanges();
								selection.addRange(range);

								// Dispatch events
								this.dispatchEvent(new Event("input", { bubbles: true }));
								this.dispatchEvent(new Event("change", { bubbles: true }));

								return {cleared: true, method: 'contenteditable', finalText: this.textContent};
							} else if (this.value !== undefined) {
								// For regular inputs with value property
								try {
									this.select();
								} catch (e) {
									// ignore
								}
								this.value = "";
								this.dispatchEvent(new Event("input", { bubbles: true }));
								this.dispatchEvent(new Event("change", { bubbles: true }));
								return {cleared: true, method: 'value', finalText: this.value};
							} else {
								return {cleared: false, method: 'none', error: 'Not a supported input type'};
							}
						}
					""",
					'objectId': object_id,
					'returnByValue': True,
				},
				session_id=cdp_session.session_id,
			)

			# Check the clear result
			clear_info = clear_result.get('result', {}).get('value', {})
			self.logger.debug(f'Clear result: {clear_info}')

			if clear_info.get('cleared'):
				final_text = clear_info.get('finalText', '')
				if not final_text or not final_text.strip():
					self.logger.debug(f'✅ Text field cleared successfully using {clear_info.get("method")}')
					return True
				else:
					self.logger.debug(f'⚠️ JavaScript clear partially failed, field still contains: "{final_text}"')
			else:
				self.logger.debug(f'❌ JavaScript clear failed: {clear_info.get("error", "Unknown error")}')

		except Exception as e:
			self.logger.debug(f'JavaScript clear failed with exception: {e}')
			return False

		# Strategy 2: Triple-click + Delete (fallback for stubborn fields)
		try:
			self.logger.debug('🧹 Fallback: Clearing using triple-click + Delete')

			# Get element center coordinates for triple-click
			bounds_result = await cdp_session.cdp_client.send.Runtime.callFunctionOn(
				params={
					'functionDeclaration': 'function() { return this.getBoundingClientRect(); }',
					'objectId': object_id,
					'returnByValue': True,
				},
				session_id=cdp_session.session_id,
			)

			if bounds_result.get('result', {}).get('value'):
				bounds = bounds_result['result']['value']
				center_x = bounds['x'] + bounds['width'] / 2
				center_y = bounds['y'] + bounds['height'] / 2

				# Triple-click to select all text
				await cdp_session.cdp_client.send.Input.dispatchMouseEvent(
					params={
						'type': 'mousePressed',
						'x': center_x,
						'y': center_y,
						'button': 'left',
						'clickCount': 3,
					},
					session_id=cdp_session.session_id,
				)
				await cdp_session.cdp_client.send.Input.dispatchMouseEvent(
					params={
						'type': 'mouseReleased',
						'x': center_x,
						'y': center_y,
						'button': 'left',
						'clickCount': 3,
					},
					session_id=cdp_session.session_id,
				)

				# Delete selected text
				await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
					params={
						'type': 'keyDown',
						'key': 'Delete',
						'code': 'Delete',
					},
					session_id=cdp_session.session_id,
				)
				await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
					params={
						'type': 'keyUp',
						'key': 'Delete',
						'code': 'Delete',
					},
					session_id=cdp_session.session_id,
				)

				self.logger.debug('✅ Text field cleared using triple-click + Delete')
				return True

		except Exception as e:
			self.logger.debug(f'Triple-click clear failed: {e}')

		# Strategy 3: Keyboard shortcuts (last resort)
		try:
			import platform

			is_macos = platform.system() == 'Darwin'
			select_all_modifier = 4 if is_macos else 2  # Meta=4 (Cmd), Ctrl=2
			modifier_name = 'Cmd' if is_macos else 'Ctrl'

			self.logger.debug(f'🧹 Last resort: Clearing using {modifier_name}+A + Backspace')

			# Select all text (Ctrl/Cmd+A)
			await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
				params={
					'type': 'keyDown',
					'key': 'a',
					'code': 'KeyA',
					'modifiers': select_all_modifier,
				},
				session_id=cdp_session.session_id,
			)
			await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
				params={
					'type': 'keyUp',
					'key': 'a',
					'code': 'KeyA',
					'modifiers': select_all_modifier,
				},
				session_id=cdp_session.session_id,
			)

			# Delete selected text (Backspace)
			await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
				params={
					'type': 'keyDown',
					'key': 'Backspace',
					'code': 'Backspace',
				},
				session_id=cdp_session.session_id,
			)
			await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
				params={
					'type': 'keyUp',
					'key': 'Backspace',
					'code': 'Backspace',
				},
				session_id=cdp_session.session_id,
			)

			self.logger.debug('✅ Text field cleared using keyboard shortcuts')
			return True

		except Exception as e:
			self.logger.debug(f'All clearing strategies failed: {e}')
			return False

	async def _focus_element_simple(
		self, backend_node_id: int, object_id: str, cdp_session, input_coordinates: dict | None = None
	) -> bool:
		"""Simple focus strategy: CDP first, then click if failed."""

		# Strategy 1: Try CDP DOM.focus first
		try:
			result = await cdp_session.cdp_client.send.DOM.focus(
				params={'backendNodeId': backend_node_id},
				session_id=cdp_session.session_id,
			)
			self.logger.debug(f'Element focused using CDP DOM.focus (result: {result})')
			return True

		except Exception as e:
			self.logger.debug(f'❌ CDP DOM.focus threw exception: {type(e).__name__}: {e}')

		# Strategy 2: Try click to focus if CDP failed
		if input_coordinates and 'input_x' in input_coordinates and 'input_y' in input_coordinates:
			try:
				click_x = input_coordinates['input_x']
				click_y = input_coordinates['input_y']

				self.logger.debug(f'🎯 Attempting click-to-focus at ({click_x:.1f}, {click_y:.1f})')

				# Click to focus
				await cdp_session.cdp_client.send.Input.dispatchMouseEvent(
					params={
						'type': 'mousePressed',
						'x': click_x,
						'y': click_y,
						'button': 'left',
						'clickCount': 1,
					},
					session_id=cdp_session.session_id,
				)
				await cdp_session.cdp_client.send.Input.dispatchMouseEvent(
					params={
						'type': 'mouseReleased',
						'x': click_x,
						'y': click_y,
						'button': 'left',
						'clickCount': 1,
					},
					session_id=cdp_session.session_id,
				)

				self.logger.debug('✅ Element focused using click method')
				return True

			except Exception as e:
				self.logger.debug(f'Click focus failed: {e}')

		# Both strategies failed
		self.logger.debug('Focus strategies failed, will attempt typing anyway')
		return False

	def _requires_direct_value_assignment(self, element_node: EnhancedDOMTreeNode) -> bool:
		"""
		Check if an element requires direct value assignment instead of character-by-character typing.

		Certain input types have compound components, custom plugins, or special requirements
		that make character-by-character typing unreliable. These need direct .value assignment:

		Native HTML5:
		- date, time, datetime-local: Have spinbutton components (ISO format required)
		- month, week: Similar compound structure
		- color: Expects hex format #RRGGBB
		- range: Needs numeric value within min/max

		jQuery/Bootstrap Datepickers:
		- Detected by class names or data attributes
		- Often expect specific date formats (MM/DD/YYYY, DD/MM/YYYY, etc.)

		Note: We use direct assignment because:
		1. Typing triggers intermediate validation that might reject partial values
		2. Compound components (like date spinbuttons) don't work with sequential typing
		3. It's much faster and more reliable
		4. We dispatch proper input/change events afterward to trigger listeners
		"""
		if not element_node.tag_name or not element_node.attributes:
			return False

		tag_name = element_node.tag_name.lower()

		# Check for native HTML5 inputs that need direct assignment
		if tag_name == 'input':
			input_type = element_node.attributes.get('type', '').lower()

			# Native HTML5 inputs with compound components or strict formats
			if input_type in {'date', 'time', 'datetime-local', 'month', 'week', 'color', 'range'}:
				return True

			# Detect jQuery/Bootstrap datepickers (text inputs with datepicker plugins)
			if input_type in {'text', ''}:
				# Check for common datepicker indicators
				class_attr = element_node.attributes.get('class', '').lower()
				if any(
					indicator in class_attr
					for indicator in ['datepicker', 'daterangepicker', 'datetimepicker', 'bootstrap-datepicker']
				):
					return True

				# Check for data attributes indicating datepickers
				if any(attr in element_node.attributes for attr in ['data-datepicker', 'data-date-format', 'data-provide']):
					return True

		return False

	async def _set_value_directly(self, element_node: EnhancedDOMTreeNode, text: str, object_id: str, cdp_session) -> None:
		"""
		Set element value directly using JavaScript for inputs that don't support typing.

		This is used for:
		- Date/time inputs where character-by-character typing doesn't work
		- jQuery datepickers that need direct value assignment
		- Color/range inputs that need specific formats
		- Any input with custom plugins that intercept typing

		After setting the value, we dispatch comprehensive events to ensure all frameworks
		and plugins recognize the change (React, Vue, Angular, jQuery, etc.)
		"""
		try:
			# Set the value using JavaScript with comprehensive event dispatching
			# callFunctionOn expects a function body (not a self-invoking function)
			set_value_js = f"""
			function() {{
				// Store old value for comparison
				const oldValue = this.value;

				// REACT-COMPATIBLE VALUE SETTING:
				// React uses Object.getOwnPropertyDescriptor to track input changes
				// We need to use the native setter to bypass React's tracking and then trigger events
				const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
					window.HTMLInputElement.prototype,
					'value'
				).set;

				// Set the value using the native setter (bypasses React's control)
				nativeInputValueSetter.call(this, {json.dumps(text)});

				// Dispatch comprehensive events to ensure all frameworks detect the change
				// Order matters: focus -> input -> change -> blur (mimics user interaction)

				// 1. Focus event (in case element isn't focused)
				this.dispatchEvent(new FocusEvent('focus', {{ bubbles: true }}));

				// 2. Input event (CRITICAL for React onChange)
				// React listens to 'input' events on the document and checks for value changes
				const inputEvent = new Event('input', {{ bubbles: true, cancelable: true }});
				this.dispatchEvent(inputEvent);

				// 3. Change event (for form handling, traditional listeners)
				const changeEvent = new Event('change', {{ bubbles: true, cancelable: true }});
				this.dispatchEvent(changeEvent);

				// 4. Blur event (triggers final validation in some libraries)
				this.dispatchEvent(new FocusEvent('blur', {{ bubbles: true }}));

				// 5. jQuery-specific events (if jQuery is present)
				if (typeof jQuery !== 'undefined' && jQuery.fn) {{
					try {{
						jQuery(this).trigger('change');
						// Trigger datepicker-specific events if it's a datepicker
						if (jQuery(this).data('datepicker')) {{
							jQuery(this).datepicker('update');
						}}
					}} catch (e) {{
						// jQuery not available or error, continue anyway
					}}
				}}

				return this.value;
			}}
			"""

			result = await cdp_session.cdp_client.send.Runtime.callFunctionOn(
				params={
					'objectId': object_id,
					'functionDeclaration': set_value_js,
					'returnByValue': True,
				},
				session_id=cdp_session.session_id,
			)

			# Verify the value was set correctly
			if 'result' in result and 'value' in result['result']:
				actual_value = result['result']['value']
				self.logger.debug(f'✅ Value set directly to: "{actual_value}"')
			else:
				self.logger.warning('⚠️ Could not verify value was set correctly')

		except Exception as e:
			self.logger.error(f'❌ Failed to set value directly: {e}')
			raise

	async def _input_text_element_node_impl(
		self, element_node: EnhancedDOMTreeNode, text: str, clear: bool = True, is_sensitive: bool = False
	) -> dict | None:
		"""
		Input text into an element using pure CDP with improved focus fallbacks.

		For date/time inputs, uses direct value assignment instead of typing.
		"""

		try:
			# Get CDP client
			cdp_client = self.browser_session.cdp_client

			# Get the correct session ID for the element's iframe
			# session_id = await self._get_session_id_for_element(element_node)

			# cdp_session = await self.browser_session.get_or_create_cdp_session(target_id=element_node.target_id, focus=True)
			cdp_session = await self.browser_session.cdp_client_for_node(element_node)

			# Get element info
			backend_node_id = element_node.backend_node_id

			# Track coordinates for metadata
			input_coordinates = None

			# Scroll element into view
			try:
				await cdp_session.cdp_client.send.DOM.scrollIntoViewIfNeeded(
					params={'backendNodeId': backend_node_id}, session_id=cdp_session.session_id
				)
				await asyncio.sleep(0.01)
			except Exception as e:
				# Node detached errors are common with shadow DOM and dynamic content
				# The element can still be interacted with even if scrolling fails
				error_str = str(e)
				if 'Node is detached from document' in error_str or 'detached from document' in error_str:
					self.logger.debug(
						f'Element node temporarily detached during scroll (common with shadow DOM), continuing: {element_node}'
					)
				else:
					self.logger.debug(f'Failed to scroll element {element_node} into view before typing: {type(e).__name__}: {e}')

			# Get object ID for the element
			result = await cdp_client.send.DOM.resolveNode(
				params={'backendNodeId': backend_node_id},
				session_id=cdp_session.session_id,
			)
			assert 'object' in result and 'objectId' in result['object'], (
				'Failed to find DOM element based on backendNodeId, maybe page content changed?'
			)
			object_id = result['object']['objectId']

			# Get current coordinates using unified method
			coords = await self.browser_session.get_element_coordinates(backend_node_id, cdp_session)
			if coords:
				center_x = coords.x + coords.width / 2
				center_y = coords.y + coords.height / 2

				# Check for occlusion before using coordinates for focus
				is_occluded = await self._check_element_occlusion(backend_node_id, center_x, center_y, cdp_session)

				if is_occluded:
					self.logger.debug('🚫 Input element is occluded, skipping coordinate-based focus')
					input_coordinates = None  # Force fallback to CDP-only focus
				else:
					input_coordinates = {'input_x': center_x, 'input_y': center_y}
					self.logger.debug(f'Using unified coordinates: x={center_x:.1f}, y={center_y:.1f}')
			else:
				input_coordinates = None
				self.logger.debug('No coordinates found for element')

			# Ensure we have a valid object_id before proceeding
			if not object_id:
				raise ValueError('Could not get object_id for element')

			# Step 1: Focus the element using simple strategy
			focused_successfully = await self._focus_element_simple(
				backend_node_id=backend_node_id, object_id=object_id, cdp_session=cdp_session, input_coordinates=input_coordinates
			)

			# Step 2: Check if this element requires direct value assignment (date/time inputs)
			requires_direct_assignment = self._requires_direct_value_assignment(element_node)

			if requires_direct_assignment:
				# Date/time inputs: use direct value assignment instead of typing
				self.logger.debug(
					f'🎯 Element type={element_node.attributes.get("type")} requires direct value assignment, setting value directly'
				)
				await self._set_value_directly(element_node, text, object_id, cdp_session)

				# Return input coordinates for metadata
				return input_coordinates

			# Step 3: Clear existing text if requested (only for regular inputs that support typing)
			if clear:
				cleared_successfully = await self._clear_text_field(object_id=object_id, cdp_session=cdp_session)
				if not cleared_successfully:
					self.logger.warning('⚠️ Text field clearing failed, typing may append to existing text')

			# Step 4: Type the text character by character using proper human-like key events
			# This emulates exactly how a human would type, which modern websites expect
			if is_sensitive:
				# Note: sensitive_key_name is not passed to this low-level method,
				# but we could extend the signature if needed for more granular logging
				self.logger.debug('🎯 Typing <sensitive> character by character')
			else:
				self.logger.debug(f'🎯 Typing text character by character: "{text}"')

			# Detect contenteditable elements (may have leaf-start bug where first char is dropped)
			_attrs = element_node.attributes or {}
			_is_contenteditable = _attrs.get('contenteditable') in ('true', '') or (
				_attrs.get('role') == 'textbox' and element_node.tag_name not in ('input', 'textarea')
			)

			# For contenteditable: after typing first char, check if dropped and retype if needed
			_check_first_char = _is_contenteditable and len(text) > 0 and clear
			_first_char = text[0] if _check_first_char else None

			for i, char in enumerate(text):
				# Handle newline characters as Enter key
				if char == '\n':
					# Send proper Enter key sequence
					await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
						params={
							'type': 'keyDown',
							'key': 'Enter',
							'code': 'Enter',
							'windowsVirtualKeyCode': 13,
						},
						session_id=cdp_session.session_id,
					)

					# Small delay to emulate human typing speed
					await asyncio.sleep(0.001)

					# Send char event with carriage return
					await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
						params={
							'type': 'char',
							'text': '\r',
							'key': 'Enter',
						},
						session_id=cdp_session.session_id,
					)

					# Send keyUp event
					await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
						params={
							'type': 'keyUp',
							'key': 'Enter',
							'code': 'Enter',
							'windowsVirtualKeyCode': 13,
						},
						session_id=cdp_session.session_id,
					)
				else:
					# Handle regular characters
					# Get proper modifiers, VK code, and base key for the character
					modifiers, vk_code, base_key = self._get_char_modifiers_and_vk(char)
					key_code = self._get_key_code_for_char(base_key)

					# self.logger.debug(f'🎯 Typing character {i + 1}/{len(text)}: "{char}" (base_key: {base_key}, code: {key_code}, modifiers: {modifiers}, vk: {vk_code})')

					# Step 1: Send keyDown event (NO text parameter)
					await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
						params={
							'type': 'keyDown',
							'key': base_key,
							'code': key_code,
							'modifiers': modifiers,
							'windowsVirtualKeyCode': vk_code,
						},
						session_id=cdp_session.session_id,
					)

					# Small delay to emulate human typing speed
					await asyncio.sleep(0.005)

					# Step 2: Send char event (WITH text parameter) - this is crucial for text input
					await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
						params={
							'type': 'char',
							'text': char,
							'key': char,
						},
						session_id=cdp_session.session_id,
					)

					# Step 3: Send keyUp event (NO text parameter)
					await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
						params={
							'type': 'keyUp',
							'key': base_key,
							'code': key_code,
							'modifiers': modifiers,
							'windowsVirtualKeyCode': vk_code,
						},
						session_id=cdp_session.session_id,
					)

				# After first char on contenteditable: check if dropped and retype if needed
				if i == 0 and _check_first_char and _first_char:
					check_result = await cdp_session.cdp_client.send.Runtime.evaluate(
						params={'expression': 'document.activeElement.textContent'},
						session_id=cdp_session.session_id,
					)
					content = check_result.get('result', {}).get('value', '')
					if _first_char not in content:
						self.logger.debug(f'🎯 First char "{_first_char}" was dropped (leaf-start bug), retyping')
						# Retype the first character - cursor now past leaf-start
						modifiers, vk_code, base_key = self._get_char_modifiers_and_vk(_first_char)
						key_code = self._get_key_code_for_char(base_key)
						await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
							params={
								'type': 'keyDown',
								'key': base_key,
								'code': key_code,
								'modifiers': modifiers,
								'windowsVirtualKeyCode': vk_code,
							},
							session_id=cdp_session.session_id,
						)
						await asyncio.sleep(0.005)
						await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
							params={'type': 'char', 'text': _first_char, 'key': _first_char},
							session_id=cdp_session.session_id,
						)
						await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
							params={
								'type': 'keyUp',
								'key': base_key,
								'code': key_code,
								'modifiers': modifiers,
								'windowsVirtualKeyCode': vk_code,
							},
							session_id=cdp_session.session_id,
						)

				# Small delay between characters to look human (realistic typing speed)
				await asyncio.sleep(0.001)

			# Step 4: Trigger framework-aware DOM events after typing completion
			# Modern JavaScript frameworks (React, Vue, Angular) rely on these events
			# to update their internal state and trigger re-renders
			await self._trigger_framework_events(object_id=object_id, cdp_session=cdp_session)

			# Step 5: Read back actual value for verification (skip for sensitive data)
			if not is_sensitive:
				try:
					await asyncio.sleep(0.05)  # let autocomplete/formatter JS settle
					readback_result = await cdp_session.cdp_client.send.Runtime.callFunctionOn(
						params={
							'objectId': object_id,
							'functionDeclaration': 'function() { return this.value !== undefined ? this.value : this.textContent; }',
							'returnByValue': True,
						},
						session_id=cdp_session.session_id,
					)
					actual_value = readback_result.get('result', {}).get('value')
					if actual_value is not None:
						if input_coordinates is None:
							input_coordinates = {}
						input_coordinates['actual_value'] = actual_value
				except Exception as e:
					self.logger.debug(f'Value readback failed (non-critical): {e}')

			# Step 6: Auto-retry on concatenation mismatch (only when clear was requested)
			# If we asked to clear but the readback value contains the typed text as a substring
			# yet is longer, the field had pre-existing text that wasn't cleared. Set directly.
			if clear and not is_sensitive and input_coordinates and 'actual_value' in input_coordinates:
				actual_value = input_coordinates['actual_value']
				if (
					isinstance(actual_value, str)
					and actual_value != text
					and len(actual_value) > len(text)
					and (actual_value.endswith(text) or actual_value.startswith(text))
				):
					self.logger.info(f'🔄 Concatenation detected: got "{actual_value}", expected "{text}" — auto-retrying')
					try:
						# Clear + set value via native setter in one JS call (works with React/Vue)
						retry_result = await cdp_session.cdp_client.send.Runtime.callFunctionOn(
							params={
								'objectId': object_id,
								'functionDeclaration': """
									function(newValue) {
										if (this.value !== undefined) {
											var desc = Object.getOwnPropertyDescriptor(
												HTMLInputElement.prototype, 'value'
											) || Object.getOwnPropertyDescriptor(
												HTMLTextAreaElement.prototype, 'value'
											);
											if (desc && desc.set) {
												desc.set.call(this, newValue);
											} else {
												this.value = newValue;
											}
										} else if (this.isContentEditable) {
											this.textContent = newValue;
										}
										this.dispatchEvent(new Event('input', { bubbles: true }));
										this.dispatchEvent(new Event('change', { bubbles: true }));
										return this.value !== undefined ? this.value : this.textContent;
									}
								""",
								'arguments': [{'value': text}],
								'returnByValue': True,
							},
							session_id=cdp_session.session_id,
						)
						retry_value = retry_result.get('result', {}).get('value')
						if retry_value is not None:
							input_coordinates['actual_value'] = retry_value
							if retry_value == text:
								self.logger.info('✅ Auto-retry fixed concatenation')
							else:
								self.logger.warning(f'⚠️ Auto-retry value still differs: "{retry_value}"')
					except Exception as e:
						self.logger.debug(f'Auto-retry failed (non-critical): {e}')

			# Return coordinates metadata if available
			return input_coordinates

		except Exception as e:
			self.logger.error(f'Failed to input text via CDP: {type(e).__name__}: {e}')
			raise BrowserError(f'Failed to input text into element: {repr(element_node)}')

	async def _trigger_framework_events(self, object_id: str, cdp_session) -> None:
		"""
		Trigger framework-aware DOM events after text input completion.

		This is critical for modern JavaScript frameworks (React, Vue, Angular, etc.)
		that rely on DOM events to update their internal state and trigger re-renders.

		Args:
			object_id: CDP object ID of the input element
			cdp_session: CDP session for the element's context
		"""
		try:
			# Execute JavaScript to trigger comprehensive event sequence
			framework_events_script = """
			function() {
				// Find the target element (available as 'this' when using objectId)
				const element = this;
				if (!element) return false;

				// Ensure element is focused
				element.focus();

				// Comprehensive event sequence for maximum framework compatibility
				const events = [
					// Input event - primary event for React controlled components
					{ type: 'input', bubbles: true, cancelable: true },
					// Change event - important for form validation and Vue v-model
					{ type: 'change', bubbles: true, cancelable: true },
					// Blur event - triggers validation in many frameworks
					{ type: 'blur', bubbles: true, cancelable: true }
				];

				let success = true;

				events.forEach(eventConfig => {
					try {
						const event = new Event(eventConfig.type, {
							bubbles: eventConfig.bubbles,
							cancelable: eventConfig.cancelable
						});

						// Special handling for InputEvent (more specific than Event)
						if (eventConfig.type === 'input') {
							const inputEvent = new InputEvent('input', {
								bubbles: true,
								cancelable: true,
								data: element.value,
								inputType: 'insertText'
							});
							element.dispatchEvent(inputEvent);
						} else {
							element.dispatchEvent(event);
						}
					} catch (e) {
						success = false;
						console.warn('Framework event dispatch failed:', eventConfig.type, e);
					}
				});

				// Special React synthetic event handling
				// React uses internal fiber properties for event system
				if (element._reactInternalFiber || element._reactInternalInstance || element.__reactInternalInstance) {
					try {
						// Trigger React's synthetic event system
						const syntheticInputEvent = new InputEvent('input', {
							bubbles: true,
							cancelable: true,
							data: element.value
						});

						// Force React to process this as a synthetic event
						Object.defineProperty(syntheticInputEvent, 'isTrusted', { value: true });
						element.dispatchEvent(syntheticInputEvent);
					} catch (e) {
						console.warn('React synthetic event failed:', e);
					}
				}

				// Special Vue reactivity trigger
				// Vue uses __vueParentComponent or __vue__ for component access
				if (element.__vue__ || element._vnode || element.__vueParentComponent) {
					try {
						// Vue often needs explicit input event with proper timing
						const vueEvent = new Event('input', { bubbles: true });
						setTimeout(() => element.dispatchEvent(vueEvent), 0);
					} catch (e) {
						console.warn('Vue reactivity trigger failed:', e);
					}
				}

				return success;
			}
			"""

			# Execute the framework events script
			result = await cdp_session.cdp_client.send.Runtime.callFunctionOn(
				params={
					'objectId': object_id,
					'functionDeclaration': framework_events_script,
					'returnByValue': True,
				},
				session_id=cdp_session.session_id,
			)

			success = result.get('result', {}).get('value', False)
			if success:
				self.logger.debug('✅ Framework events triggered successfully')
			else:
				self.logger.warning('⚠️ Failed to trigger framework events')

		except Exception as e:
			self.logger.warning(f'⚠️ Failed to trigger framework events: {type(e).__name__}: {e}')
			# Don't raise - framework events are a best-effort enhancement

	async def _scroll_with_cdp_gesture(self, pixels: int) -> bool:
		"""
		Scroll using CDP Input.synthesizeScrollGesture to simulate realistic scroll gesture.

		Args:
			pixels: Number of pixels to scroll (positive = down, negative = up)

		Returns:
			True if successful, False if failed
		"""
		try:
			# Get focused CDP session using public API (validates and waits for recovery if needed)
			cdp_session = await self.browser_session.get_or_create_cdp_session()
			cdp_client = cdp_session.cdp_client
			session_id = cdp_session.session_id

			# Get viewport dimensions from cached value if available
			if self.browser_session._original_viewport_size:
				viewport_width, viewport_height = self.browser_session._original_viewport_size
			else:
				# Fallback: query layout metrics
				layout_metrics = await cdp_client.send.Page.getLayoutMetrics(session_id=session_id)
				viewport_width = layout_metrics['layoutViewport']['clientWidth']
				viewport_height = layout_metrics['layoutViewport']['clientHeight']

			# Calculate center of viewport
			center_x = viewport_width / 2
			center_y = viewport_height / 2

			# For scroll gesture, positive yDistance scrolls up, negative scrolls down
			# (opposite of mouseWheel deltaY convention)
			y_distance = -pixels

			# Synthesize scroll gesture - use very high speed for near-instant scrolling
			await cdp_client.send.Input.synthesizeScrollGesture(
				params={
					'x': center_x,
					'y': center_y,
					'xDistance': 0,
					'yDistance': y_distance,
					'speed': 50000,  # pixels per second (high = near-instant scroll)
				},
				session_id=session_id,
			)

			self.logger.debug(f'📄 Scrolled via CDP gesture: {pixels}px')
			return True

		except Exception as e:
			# Not critical - JavaScript fallback will handle scrolling
			self.logger.debug(f'CDP gesture scroll failed ({type(e).__name__}: {e}), falling back to JS')
			return False

	async def _scroll_element_container(self, element_node, pixels: int) -> bool:
		"""Try to scroll an element's container using CDP."""
		try:
			cdp_session = await self.browser_session.cdp_client_for_node(element_node)

			# Check if this is an iframe - if so, scroll its content directly
			if element_node.tag_name and element_node.tag_name.upper() == 'IFRAME':
				# For iframes, we need to scroll the content document, not the iframe element itself
				# Use JavaScript to directly scroll the iframe's content
				backend_node_id = element_node.backend_node_id

				# Resolve the node to get an object ID
				result = await cdp_session.cdp_client.send.DOM.resolveNode(
					params={'backendNodeId': backend_node_id},
					session_id=cdp_session.session_id,
				)

				if 'object' in result and 'objectId' in result['object']:
					object_id = result['object']['objectId']

					# Scroll the iframe's content directly
					scroll_result = await cdp_session.cdp_client.send.Runtime.callFunctionOn(
						params={
							'functionDeclaration': f"""
								function() {{
									try {{
										const doc = this.contentDocument || this.contentWindow.document;
										if (doc) {{
											const scrollElement = doc.documentElement || doc.body;
											if (scrollElement) {{
												const oldScrollTop = scrollElement.scrollTop;
												scrollElement.scrollTop += {pixels};
												const newScrollTop = scrollElement.scrollTop;
												return {{
													success: true,
													oldScrollTop: oldScrollTop,
													newScrollTop: newScrollTop,
													scrolled: newScrollTop - oldScrollTop
												}};
											}}
										}}
										return {{success: false, error: 'Could not access iframe content'}};
									}} catch (e) {{
										return {{success: false, error: e.toString()}};
									}}
								}}
							""",
							'objectId': object_id,
							'returnByValue': True,
						},
						session_id=cdp_session.session_id,
					)

					if scroll_result and 'result' in scroll_result and 'value' in scroll_result['result']:
						result_value = scroll_result['result']['value']
						if result_value.get('success'):
							self.logger.debug(f'Successfully scrolled iframe content by {result_value.get("scrolled", 0)}px')
							return True
						else:
							self.logger.debug(f'Failed to scroll iframe: {result_value.get("error", "Unknown error")}')

			# For non-iframe elements, use the standard mouse wheel approach
			# Get element bounds to know where to scroll
			backend_node_id = element_node.backend_node_id
			box_model = await cdp_session.cdp_client.send.DOM.getBoxModel(
				params={'backendNodeId': backend_node_id}, session_id=cdp_session.session_id
			)
			content_quad = box_model['model']['content']

			# Calculate center point
			center_x = (content_quad[0] + content_quad[2] + content_quad[4] + content_quad[6]) / 4
			center_y = (content_quad[1] + content_quad[3] + content_quad[5] + content_quad[7]) / 4

			# Dispatch mouse wheel event at element location
			await cdp_session.cdp_client.send.Input.dispatchMouseEvent(
				params={
					'type': 'mouseWheel',
					'x': center_x,
					'y': center_y,
					'deltaX': 0,
					'deltaY': pixels,
				},
				session_id=cdp_session.session_id,
			)

			return True
		except Exception as e:
			self.logger.debug(f'Failed to scroll element container via CDP: {e}')
			return False

	async def _get_session_id_for_element(self, element_node: EnhancedDOMTreeNode) -> str | None:
		"""Get the appropriate CDP session ID for an element based on its frame."""
		if element_node.frame_id:
			# Element is in an iframe, need to get session for that frame
			try:
				all_targets = self.browser_session.session_manager.get_all_targets()

				# Find the target for this frame
				for target_id, target in all_targets.items():
					if target.target_type == 'iframe' and element_node.frame_id in str(target_id):
						# Create temporary session for iframe target without switching focus
						temp_session = await self.browser_session.get_or_create_cdp_session(target_id, focus=False)
						return temp_session.session_id

				# If frame not found in targets, use main target session
				self.logger.debug(f'Frame {element_node.frame_id} not found in targets, using main session')
			except Exception as e:
				self.logger.debug(f'Error getting frame session: {e}, using main session')

		# Use main target session - get_or_create_cdp_session validates focus automatically
		cdp_session = await self.browser_session.get_or_create_cdp_session()
		return cdp_session.session_id

	async def on_GoBackEvent(self, event: GoBackEvent) -> None:
		"""Compatibility adapter for legacy event-based back navigation."""
		from browser_use.browser.services import NavigationService

		url = await NavigationService(browser_session=self.browser_session).go_back()
		if url is None:
			self.logger.warning('⚠️ Cannot go back - no previous entry in history')
			return
		self.logger.info(f'🔙 Navigated back to {url}')

	async def on_GoForwardEvent(self, event: GoForwardEvent) -> None:
		"""Compatibility adapter for legacy event-based forward navigation."""
		from browser_use.browser.services import NavigationService

		url = await NavigationService(browser_session=self.browser_session).go_forward()
		if url is None:
			self.logger.warning('⚠️ Cannot go forward - no next entry in history')
			return
		self.logger.info(f'🔜 Navigated forward to {url}')

	async def on_RefreshEvent(self, event: RefreshEvent) -> None:
		"""Compatibility adapter for legacy event-based refresh requests."""
		from browser_use.browser.services import NavigationService

		await NavigationService(browser_session=self.browser_session).refresh()
		self.logger.info('🔄 Target refreshed')

	@observe_debug(ignore_input=True, ignore_output=True, name='wait_event_handler')
	async def on_WaitEvent(self, event: WaitEvent) -> None:
		"""Handle wait request."""
		try:
			# Cap wait time at maximum
			actual_seconds = min(max(event.seconds, 0), event.max_seconds)
			if actual_seconds != event.seconds:
				self.logger.info(f'🕒 Waiting for {actual_seconds} seconds (capped from {event.seconds}s)')
			else:
				self.logger.info(f'🕒 Waiting for {actual_seconds} seconds')

			await asyncio.sleep(actual_seconds)
		except Exception as e:
			raise

	async def on_SendKeysEvent(self, event: SendKeysEvent) -> None:
		"""Compatibility adapter for legacy event-based keyboard requests."""
		from browser_use.browser.services import KeyboardService

		await KeyboardService(browser_session=self.browser_session).send_keys(event.keys)

	async def on_UploadFileEvent(self, event: UploadFileEvent) -> None:
		"""Compatibility adapter for legacy event-based upload requests."""
		from browser_use.browser.services import UploadService

		await UploadService(browser_session=self.browser_session).upload_file(event.node, event.file_path)

	async def on_ScrollToTextEvent(self, event: ScrollToTextEvent) -> None:
		"""Compatibility adapter for legacy event-based scroll-to-text requests."""
		from browser_use.browser.services import ScrollService

		await ScrollService(browser_session=self.browser_session).scroll_to_text(event.text)
		return None

	async def on_GetDropdownOptionsEvent(self, event: GetDropdownOptionsEvent) -> dict[str, str]:
		"""Compatibility adapter for legacy event-based dropdown option requests."""
		return await self.get_dropdown_options(event.node)

	async def get_dropdown_options(self, element_node: EnhancedDOMTreeNode) -> dict[str, str]:
		"""Compatibility adapter for direct dropdown option calls that still reference this handler."""
		from browser_use.browser.services import DropdownService

		return await DropdownService(browser_session=self.browser_session).get_dropdown_options(element_node)

	async def on_SelectDropdownOptionEvent(self, event: SelectDropdownOptionEvent) -> dict[str, str]:
		"""Compatibility adapter for legacy event-based dropdown selection requests."""
		return await self.select_dropdown_option(event.node, event.text)

	async def select_dropdown_option(self, element_node: EnhancedDOMTreeNode, target_text: str) -> dict[str, str]:
		"""Compatibility adapter for direct dropdown selection calls that still reference this handler."""
		from browser_use.browser.services import DropdownService

		return await DropdownService(browser_session=self.browser_session).select_dropdown_option(element_node, target_text)
