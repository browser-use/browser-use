"""HAR Recording Watchdog for Browser-Use sessions.

Captures HTTPS network activity via CDP Network domain and writes a HAR 1.2
file on browser shutdown. Respects `record_har_content` (omit/embed/attach)
and `record_har_mode` (full/minimal).
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import ClassVar

from bubus import BaseEvent
from cdp_use.cdp.network.events import (
	DataReceivedEvent,
	LoadingFailedEvent,
	LoadingFinishedEvent,
	RequestWillBeSentEvent,
	ResponseReceivedEvent,
)
from cdp_use.cdp.page.events import FrameNavigatedEvent, LifecycleEventEvent

from browser_use.browser.events import BrowserConnectedEvent, BrowserStopEvent
from browser_use.browser.watchdog_base import BaseWatchdog


@dataclass
class _HarContent:
	mime_type: str | None = None
	text_b64: str | None = None  # for embed
	file_rel: str | None = None  # for attach
	size: int | None = None


@dataclass
class _HarEntryBuilder:
	request_id: str = ''
	frame_id: str | None = None
	document_url: str | None = None
	url: str | None = None
	method: str | None = None
	request_headers: dict = field(default_factory=dict)
	request_body: bytes | None = None
	post_data: str | None = None  # CDP postData field
	status: int | None = None
	status_text: str | None = None
	response_headers: dict = field(default_factory=dict)
	mime_type: str | None = None
	encoded_data: bytearray = field(default_factory=bytearray)
	failed: bool = False
	# timing info (CDP timestamps are monotonic seconds); wallTime is epoch seconds
	ts_request: float | None = None
	wall_time_request: float | None = None
	ts_response: float | None = None
	ts_finished: float | None = None
	encoded_data_length: int | None = None
	response_body: bytes | None = None
	content_length: int | None = None  # From Content-Length header


def _is_https(url: str | None) -> bool:
	return bool(url and url.lower().startswith('https://'))


def _origin(url: str) -> str:
	# Very small origin extractor, assumes https URLs
	# https://host[:port]/...
	if not url:
		return ''
	try:
		without_scheme = url.split('://', 1)[1]
		host_port = without_scheme.split('/', 1)[0]
		return f'https://{host_port}'
	except Exception:
		return ''


class HarRecordingWatchdog(BaseWatchdog):
	"""Collects HTTPS requests/responses and writes a HAR 1.2 file on stop."""

	LISTENS_TO: ClassVar[list[type[BaseEvent]]] = [BrowserConnectedEvent, BrowserStopEvent]
	EMITS: ClassVar[list[type[BaseEvent]]] = []

	def __init__(self, *args, **kwargs) -> None:
		super().__init__(*args, **kwargs)
		self._enabled: bool = False
		self._entries: dict[str, _HarEntryBuilder] = {}
		self._top_level_pages: dict[
			str, dict
		] = {}  # frameId -> {url, title, startedDateTime, monotonic_start, onContentLoad, onLoad}

	async def on_BrowserConnectedEvent(self, event: BrowserConnectedEvent) -> None:
		profile = self.browser_session.browser_profile
		if not profile.record_har_path:
			return

		# Normalize config
		self._content_mode = (profile.record_har_content or 'embed').lower()
		self._mode = (profile.record_har_mode or 'full').lower()
		self._har_path = Path(str(profile.record_har_path)).expanduser().resolve()
		self._har_dir = self._har_path.parent
		self._har_dir.mkdir(parents=True, exist_ok=True)

		try:
			# Enable Network and Page domains for events
			cdp_session = await self.browser_session.get_or_create_cdp_session()
			await cdp_session.cdp_client.send.Network.enable(session_id=cdp_session.session_id)
			await cdp_session.cdp_client.send.Page.enable(session_id=cdp_session.session_id)

			# Query browser version for HAR log.browser
			try:
				version_info = await self.browser_session.cdp_client.send.Browser.getVersion()
				self._browser_name = version_info.get('product') or 'Chromium'
				self._browser_version = version_info.get('jsVersion') or ''
			except Exception:
				self._browser_name = 'Chromium'
				self._browser_version = ''

			cdp = self.browser_session.cdp_client.register
			cdp.Network.requestWillBeSent(self._on_request_will_be_sent)
			cdp.Network.responseReceived(self._on_response_received)
			cdp.Network.dataReceived(self._on_data_received)
			cdp.Network.loadingFinished(self._on_loading_finished)
			cdp.Network.loadingFailed(self._on_loading_failed)
			cdp.Page.lifecycleEvent(self._on_lifecycle_event)
			cdp.Page.frameNavigated(self._on_frame_navigated)

			self._enabled = True
			self.logger.info(f'📊 Starting HAR recording to {self._har_path}')
		except Exception as e:
			self.logger.warning(f'Failed to enable HAR recording: {e}')
			self._enabled = False

	async def on_BrowserStopEvent(self, event: BrowserStopEvent) -> None:
		if not self._enabled:
			return
		try:
			await self._write_har()
			self.logger.info(f'📊 HAR file saved: {self._har_path}')
		except Exception as e:
			self.logger.warning(f'Failed to write HAR: {e}')

	# =============== CDP Event Handlers (sync) ==================
	def _on_request_will_be_sent(self, params: RequestWillBeSentEvent, session_id: str | None) -> None:
		try:
			req = params.get('request', {}) if hasattr(params, 'get') else getattr(params, 'request', {})
			url = req.get('url') if isinstance(req, dict) else getattr(req, 'url', None)
			if not _is_https(url):
				return  # HTTPS-only requirement (only HTTPS requests are recorded for now)

			request_id = params.get('requestId') if hasattr(params, 'get') else getattr(params, 'requestId', None)
			if not request_id:
				return

			entry = self._entries.setdefault(request_id, _HarEntryBuilder(request_id=request_id))
			entry.url = url
			entry.method = req.get('method') if isinstance(req, dict) else getattr(req, 'method', None)
			entry.post_data = req.get('postData') if isinstance(req, dict) else getattr(req, 'postData', None)

			# Convert headers to plain dict, handling various formats
			headers_raw = req.get('headers') if isinstance(req, dict) else getattr(req, 'headers', None)
			if headers_raw is None:
				entry.request_headers = {}
			elif isinstance(headers_raw, dict):
				entry.request_headers = {k.lower(): str(v) for k, v in headers_raw.items()}
			elif isinstance(headers_raw, list):
				entry.request_headers = {
					h.get('name', '').lower(): str(h.get('value') or '') for h in headers_raw if isinstance(h, dict)
				}
			else:
				# Handle Headers type or other formats - convert to dict
				try:
					headers_dict = dict(headers_raw) if hasattr(headers_raw, '__iter__') else {}
					entry.request_headers = {k.lower(): str(v) for k, v in headers_dict.items()}
				except Exception:
					entry.request_headers = {}

			entry.frame_id = params.get('frameId') if hasattr(params, 'get') else getattr(params, 'frameId', None)
			entry.document_url = (
				params.get('documentURL')
				if hasattr(params, 'get')
				else getattr(params, 'documentURL', None) or entry.document_url
			)

			# Timing anchors
			entry.ts_request = params.get('timestamp') if hasattr(params, 'get') else getattr(params, 'timestamp', None)
			entry.wall_time_request = params.get('wallTime') if hasattr(params, 'get') else getattr(params, 'wallTime', None)

			# Track top-level navigations for page context
			req_type = params.get('type') if hasattr(params, 'get') else getattr(params, 'type', None)
			is_same_doc = (
				params.get('isSameDocument', False) if hasattr(params, 'get') else getattr(params, 'isSameDocument', False)
			)
			if req_type == 'Document' and not is_same_doc:
				# best-effort: consider as navigation
				if entry.frame_id and url:
					if entry.frame_id not in self._top_level_pages:
						self._top_level_pages[entry.frame_id] = {
							'url': str(url),
							'title': str(url),  # Default to URL, will be updated from DOM
							'startedDateTime': entry.wall_time_request,
							'monotonic_start': entry.ts_request,  # Track monotonic start time for timing calculations
							'onContentLoad': -1,
							'onLoad': -1,
						}
					else:
						# Update startedDateTime and monotonic_start if this is earlier
						page_info = self._top_level_pages[entry.frame_id]
						if entry.wall_time_request and (
							page_info['startedDateTime'] is None or entry.wall_time_request < page_info['startedDateTime']
						):
							page_info['startedDateTime'] = entry.wall_time_request
							page_info['monotonic_start'] = entry.ts_request
		except Exception as e:
			self.logger.debug(f'requestWillBeSent handling error: {e}')

	def _on_response_received(self, params: ResponseReceivedEvent, session_id: str | None) -> None:
		try:
			request_id = params.get('requestId') if hasattr(params, 'get') else getattr(params, 'requestId', None)
			if not request_id or request_id not in self._entries:
				return
			response = params.get('response', {}) if hasattr(params, 'get') else getattr(params, 'response', {})
			entry = self._entries[request_id]
			entry.status = response.get('status') if isinstance(response, dict) else getattr(response, 'status', None)
			entry.status_text = (
				response.get('statusText') if isinstance(response, dict) else getattr(response, 'statusText', None)
			)

			# Extract Content-Length for compression calculation (before converting headers)
			headers_raw = response.get('headers') if isinstance(response, dict) else getattr(response, 'headers', None)
			if headers_raw:
				if isinstance(headers_raw, dict):
					cl_str = headers_raw.get('content-length') or headers_raw.get('Content-Length')
				elif isinstance(headers_raw, list):
					cl_header = next(
						(h for h in headers_raw if isinstance(h, dict) and h.get('name', '').lower() == 'content-length'), None
					)
					cl_str = cl_header.get('value') if cl_header else None
				else:
					cl_str = None
				if cl_str:
					try:
						entry.content_length = int(cl_str)
					except Exception:
						pass

			# Convert headers to plain dict, handling various formats
			if headers_raw is None:
				entry.response_headers = {}
			elif isinstance(headers_raw, dict):
				entry.response_headers = {k.lower(): str(v) for k, v in headers_raw.items()}
			elif isinstance(headers_raw, list):
				entry.response_headers = {
					h.get('name', '').lower(): str(h.get('value') or '') for h in headers_raw if isinstance(h, dict)
				}
			else:
				# Handle Headers type or other formats - convert to dict
				try:
					headers_dict = dict(headers_raw) if hasattr(headers_raw, '__iter__') else {}
					entry.response_headers = {k.lower(): str(v) for k, v in headers_dict.items()}
				except Exception:
					entry.response_headers = {}

			entry.mime_type = response.get('mimeType') if isinstance(response, dict) else getattr(response, 'mimeType', None)
			entry.ts_response = params.get('timestamp') if hasattr(params, 'get') else getattr(params, 'timestamp', None)
		except Exception as e:
			self.logger.debug(f'responseReceived handling error: {e}')

	def _on_data_received(self, params: DataReceivedEvent, session_id: str | None) -> None:
		try:
			request_id = params.get('requestId') if hasattr(params, 'get') else getattr(params, 'requestId', None)
			if not request_id or request_id not in self._entries:
				return
			data = params.get('data') if hasattr(params, 'get') else getattr(params, 'data', None)
			if isinstance(data, str):
				try:
					self._entries[request_id].encoded_data.extend(data.encode('latin1'))
				except Exception:
					pass
		except Exception as e:
			self.logger.debug(f'dataReceived handling error: {e}')

	def _on_loading_finished(self, params: LoadingFinishedEvent, session_id: str | None) -> None:
		try:
			request_id = params.get('requestId') if hasattr(params, 'get') else getattr(params, 'requestId', None)
			if not request_id or request_id not in self._entries:
				return
			entry = self._entries[request_id]
			entry.ts_finished = params.get('timestamp')
			# Fetch response body via CDP as dataReceived may be incomplete
			import asyncio as _asyncio

			async def _fetch_body(self_ref, req_id, sess_id):
				try:
					resp = await self_ref.browser_session.cdp_client.send.Network.getResponseBody(
						params={'requestId': req_id}, session_id=sess_id
					)
					data = resp.get('body', b'')
					if resp.get('base64Encoded'):
						import base64 as _b64

						data = _b64.b64decode(data)
					else:
						# Ensure data is bytes even if CDP returns a string
						if isinstance(data, str):
							data = data.encode('utf-8', errors='replace')
					# Ensure we always have bytes
					if not isinstance(data, bytes):
						data = bytes(data) if data else b''
					entry.response_body = data
				except Exception:
					pass

			# Always schedule the response body fetch task
			_asyncio.create_task(_fetch_body(self, request_id, session_id))

			encoded_length = (
				params.get('encodedDataLength') if hasattr(params, 'get') else getattr(params, 'encodedDataLength', None)
			)
			if encoded_length is not None:
				try:
					entry.encoded_data_length = int(encoded_length)
				except Exception:
					entry.encoded_data_length = None
		except Exception as e:
			self.logger.debug(f'loadingFinished handling error: {e}')

	def _on_loading_failed(self, params: LoadingFailedEvent, session_id: str | None) -> None:
		try:
			request_id = params.get('requestId') if hasattr(params, 'get') else getattr(params, 'requestId', None)
			if request_id and request_id in self._entries:
				self._entries[request_id].failed = True
		except Exception as e:
			self.logger.debug(f'loadingFailed handling error: {e}')

	# ===================== HAR Writing ==========================
	def _on_lifecycle_event(self, params: LifecycleEventEvent, session_id: str | None) -> None:
		"""Handle Page.lifecycleEvent for tracking page load timings."""
		try:
			frame_id = params.get('frameId') if hasattr(params, 'get') else getattr(params, 'frameId', None)
			name = params.get('name') if hasattr(params, 'get') else getattr(params, 'name', None)
			timestamp = params.get('timestamp') if hasattr(params, 'get') else getattr(params, 'timestamp', None)

			if not frame_id or not name or frame_id not in self._top_level_pages:
				return

			page_info = self._top_level_pages[frame_id]
			# Use monotonic_start instead of startedDateTime (wall-clock) for timing calculations
			monotonic_start = page_info.get('monotonic_start')

			if name == 'DOMContentLoaded' and monotonic_start is not None:
				# Calculate milliseconds since page start using monotonic timestamps
				try:
					elapsed_ms = int(round((timestamp - monotonic_start) * 1000))
					page_info['onContentLoad'] = max(0, elapsed_ms)
				except Exception:
					pass
			elif name == 'load' and monotonic_start is not None:
				try:
					elapsed_ms = int(round((timestamp - monotonic_start) * 1000))
					page_info['onLoad'] = max(0, elapsed_ms)
				except Exception:
					pass
		except Exception as e:
			self.logger.debug(f'lifecycleEvent handling error: {e}')

	def _on_frame_navigated(self, params: FrameNavigatedEvent, session_id: str | None) -> None:
		"""Handle Page.frameNavigated to update page title from DOM."""
		try:
			frame = params.get('frame') if hasattr(params, 'get') else getattr(params, 'frame', None)
			if not frame:
				return

			frame_id = frame.get('id') if isinstance(frame, dict) else getattr(frame, 'id', None)
			title = (
				frame.get('name') or frame.get('url')
				if isinstance(frame, dict)
				else getattr(frame, 'name', None) or getattr(frame, 'url', None)
			)

			if frame_id and frame_id in self._top_level_pages:
				# Try to get actual page title via Runtime.evaluate if possible
				# For now, use frame name or URL as fallback
				if title:
					self._top_level_pages[frame_id]['title'] = str(title)
		except Exception as e:
			self.logger.debug(f'frameNavigated handling error: {e}')

	# ===================== HAR Writing ==========================
	async def _write_har(self) -> None:
		# Filter by mode and HTTPS already respected at collection time
		entries = [e for e in self._entries.values() if self._include_entry(e)]

		har_entries = []
		sidecar_dir: Path | None = None
		if self._content_mode == 'attach':
			sidecar_dir = self._har_dir / f'{self._har_path.stem}_har_parts'
			sidecar_dir.mkdir(parents=True, exist_ok=True)

		for e in entries:
			content_obj: dict = {'mimeType': e.mime_type or ''}

			# Get body data, preferring response_body over encoded_data
			if e.response_body is not None:
				body_data = e.response_body
			else:
				body_data = e.encoded_data

			# Defensive conversion: ensure body_data is always bytes
			if isinstance(body_data, str):
				body_bytes = body_data.encode('utf-8', errors='replace')
			elif isinstance(body_data, bytearray):
				body_bytes = bytes(body_data)
			elif isinstance(body_data, bytes):
				body_bytes = body_data
			else:
				# Fallback: try to convert to bytes
				try:
					body_bytes = bytes(body_data) if body_data else b''
				except (TypeError, ValueError):
					body_bytes = b''

			content_size = len(body_bytes)

			# Calculate compression (bytes saved by compression)
			compression = 0
			if e.content_length is not None and e.encoded_data_length is not None:
				compression = max(0, e.content_length - e.encoded_data_length)

			if self._content_mode == 'embed' and content_size > 0:
				# Prefer plain text; fallback to base64 only if decoding fails
				try:
					text_decoded = body_bytes.decode('utf-8')
					content_obj['text'] = text_decoded
					content_obj['size'] = content_size
					if compression > 0:
						content_obj['compression'] = compression
				except UnicodeDecodeError:
					content_obj['text'] = base64.b64encode(body_bytes).decode('ascii')
					content_obj['encoding'] = 'base64'
					content_obj['size'] = content_size
					if compression > 0:
						content_obj['compression'] = compression
			elif self._content_mode == 'attach' and content_size > 0 and sidecar_dir is not None:
				# Use incremental index-based filenames for determinism
				rel_name = f'{len(har_entries):06d}.bin'
				(sidecar_dir / rel_name).write_bytes(body_bytes)
				content_obj['_file'] = str(Path(sidecar_dir.name) / rel_name)
				content_obj['size'] = content_size
				if compression > 0:
					content_obj['compression'] = compression
			else:
				# omit or empty
				content_obj['size'] = content_size
				if compression > 0:
					content_obj['compression'] = compression

			started_date_time, total_time_ms, timings = self._compute_timings(e)
			req_headers_list = [{'name': k, 'value': str(v)} for k, v in (e.request_headers or {}).items()]
			resp_headers_list = [{'name': k, 'value': str(v)} for k, v in (e.response_headers or {}).items()]
			request_headers_size = self._calc_headers_size(e.method or 'GET', e.url or '', req_headers_list)
			response_headers_size = self._calc_headers_size(None, None, resp_headers_list)
			request_body_size = self._calc_request_body_size(e)
			request_post_data = None
			if e.post_data and self._content_mode != 'omit':
				if self._content_mode == 'embed':
					request_post_data = {'mimeType': e.request_headers.get('content-type', ''), 'text': e.post_data}
				elif self._content_mode == 'attach' and sidecar_dir is not None:
					req_name = f'{len(har_entries):06d}_req.txt'
					(sidecar_dir / req_name).write_text(e.post_data)
					request_post_data = {
						'mimeType': e.request_headers.get('content-type', ''),
						'_file': str(Path(sidecar_dir.name) / req_name),
					}

			har_entries.append(
				{
					'startedDateTime': started_date_time,
					'time': total_time_ms,
					'request': {
						'method': e.method or 'GET',
						'url': e.url or '',
						'httpVersion': 'HTTP/1.1',
						'headers': req_headers_list,
						'queryString': [],
						'cookies': [],
						'headersSize': request_headers_size,
						'bodySize': request_body_size,
						'postData': request_post_data,
					},
					'response': {
						'status': e.status or 0,
						'statusText': e.status_text or '',
						'httpVersion': 'HTTP/1.1',
						'headers': resp_headers_list,
						'cookies': [],
						'content': content_obj,
						'redirectURL': '',
						'headersSize': response_headers_size,
						'bodySize': e.encoded_data_length
						if e.encoded_data_length is not None
						else (content_size if content_size > 0 else -1),
					},
					'cache': {},
					'timings': timings,
					'pageref': self._page_ref_for_entry(e),
				}
			)

		# Try to include our library version in creator
		try:
			bu_version = importlib_metadata.version('browser-use')
		except Exception:
			# Fallback when running from source without installed package metadata
			bu_version = 'dev'

		har_obj = {
			'log': {
				'version': '1.2',
				'creator': {'name': 'browser-use', 'version': bu_version},
				'browser': {'name': self._browser_name, 'version': self._browser_version},
				'pages': [
					{
						'id': pid,
						'title': page_info.get('title', page_info.get('url', '')),
						'startedDateTime': self._format_page_started_datetime(page_info.get('startedDateTime')),
						'pageTimings': (
							(lambda _ocl, _ol: ({k: v for k, v in (('onContentLoad', _ocl), ('onLoad', _ol)) if v is not None}))(
								(page_info.get('onContentLoad') if page_info.get('onContentLoad', -1) >= 0 else None),
								(page_info.get('onLoad') if page_info.get('onLoad', -1) >= 0 else None),
							)
						),
					}
					for pid, page_info in self._top_level_pages.items()
				],
				'entries': har_entries,
			}
		}

		tmp_path = self._har_path.with_suffix(self._har_path.suffix + '.tmp')
		# Write as bytes explicitly to avoid any text/binary mode confusion in different environments
		tmp_path.write_bytes(json.dumps(har_obj, indent=2).encode('utf-8'))
		tmp_path.replace(self._har_path)

	def _format_page_started_datetime(self, timestamp: float | None) -> str:
		"""Format page startedDateTime from timestamp."""
		if timestamp is None:
			return ''
		try:
			from datetime import datetime, timezone

			return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat().replace('+00:00', 'Z')
		except Exception:
			return ''

	def _page_ref_for_entry(self, e: _HarEntryBuilder) -> str | None:
		# Use frame_id as stable page id if known
		if e.frame_id and e.frame_id in self._top_level_pages:
			return e.frame_id
		return None

	def _include_entry(self, e: _HarEntryBuilder) -> bool:
		if not _is_https(e.url):
			return False
		if getattr(self, '_mode', 'full') == 'full':
			return True
		# minimal: include main document and same-origin subresources
		if e.frame_id and e.frame_id in self._top_level_pages:
			page_info = self._top_level_pages[e.frame_id]
			page_url = page_info.get('url') if isinstance(page_info, dict) else page_info
			return _origin(e.url or '') == _origin(page_url or '')
		return False

	# ===================== Helpers ==============================
	def _compute_timings(self, e: _HarEntryBuilder) -> tuple[str, int, dict]:
		# startedDateTime from wall_time_request in ISO8601 Z
		started = ''
		try:
			if e.wall_time_request is not None:
				from datetime import datetime, timezone

				started = datetime.fromtimestamp(e.wall_time_request, tz=timezone.utc).isoformat().replace('+00:00', 'Z')
		except Exception:
			started = ''

		send_ms = 0
		wait_ms = 0
		receive_ms = 0
		if e.ts_request is not None and e.ts_response is not None:
			wait_ms = max(0, int(round((e.ts_response - e.ts_request) * 1000)))
		if e.ts_response is not None and e.ts_finished is not None:
			receive_ms = max(0, int(round((e.ts_finished - e.ts_response) * 1000)))
		total = send_ms + wait_ms + receive_ms
		return started, total, {'send': send_ms, 'wait': wait_ms, 'receive': receive_ms}

	def _calc_headers_size(self, method: str | None, url: str | None, headers_list: list[dict]) -> int:
		try:
			# Approximate per RFC: sum of header lines + CRLF; include request/status line only for request
			size = 0
			if method and url:
				# Use HTTP/1.1 request line approximation
				size += len(f'{method} {url} HTTP/1.1\r\n'.encode('latin1'))
			for h in headers_list:
				size += len(f'{h.get("name", "")}: {h.get("value", "")}\r\n'.encode('latin1'))
			size += len(b'\r\n')
			return size
		except Exception:
			return -1

	def _calc_request_body_size(self, e: _HarEntryBuilder) -> int:
		# Try Content-Length header first; else post_data; else request_body; else 0 for GET/HEAD, -1 if unknown
		try:
			cl = None
			if e.request_headers:
				cl = e.request_headers.get('content-length') or e.request_headers.get('Content-Length')
			if cl is not None:
				return int(cl)
			if e.post_data:
				return len(e.post_data.encode('utf-8'))
			if e.request_body is not None:
				return len(e.request_body)
			# GET/HEAD requests typically have no body
			if e.method and e.method.upper() in ('GET', 'HEAD'):
				return 0
		except Exception:
			pass
		return -1
