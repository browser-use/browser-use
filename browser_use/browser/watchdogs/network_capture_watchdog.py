"""Watchdog for agent-controlled network response capture via CDP.

Captures API responses matching URL patterns, stores them in IndexedDB,
supports JS-based transformation, and syncs results to FileSystem.
"""

import asyncio
import json
import logging
from fnmatch import fnmatch
from typing import Any, ClassVar
from urllib.parse import urlparse

from bubus import BaseEvent
from cdp_use.cdp.network import ResponseReceivedEvent
from pydantic import PrivateAttr

from browser_use.browser.events import (
	BrowserStoppedEvent,
	NavigationCompleteEvent,
	NetworkCaptureStartedEvent,
	NetworkCaptureStoppedEvent,
	TabCreatedEvent,
)
from browser_use.browser.watchdog_base import BaseWatchdog
from browser_use.filesystem.file_system import FileSystem
from browser_use.utils import create_task_with_error_handling

logger = logging.getLogger(__name__)

# JS to initialize the IndexedDB schema
_INDEXEDDB_INIT_JS = """\
(async () => {
	return new Promise((resolve, reject) => {
		const req = indexedDB.open('__bu_capture', 1);
		req.onupgradeneeded = (e) => {
			const db = e.target.result;
			if (!db.objectStoreNames.contains('responses')) {
				db.createObjectStore('responses', { keyPath: 'id', autoIncrement: true });
			}
			if (!db.objectStoreNames.contains('results')) {
				db.createObjectStore('results', { keyPath: 'id', autoIncrement: true });
			}
		};
		req.onsuccess = () => { req.result.close(); resolve({ok: true}); };
		req.onerror = () => reject(req.error);
	});
})()
"""

# JS template to store a captured response into IndexedDB
_STORE_RESPONSE_JS = """\
(async () => {
	return new Promise((resolve, reject) => {
		const req = indexedDB.open('__bu_capture', 1);
		req.onsuccess = () => {
			const db = req.result;
			const tx = db.transaction('responses', 'readwrite');
			const store = tx.objectStore('responses');
			store.add(RECORD);
			tx.oncomplete = () => { db.close(); resolve({ok: true}); };
			tx.onerror = () => { db.close(); reject(tx.error); };
		};
		req.onerror = () => reject(req.error);
	});
})()
"""

# JS template to read all records from an IndexedDB store
_READ_STORE_JS = """\
(async () => {
	return new Promise((resolve, reject) => {
		const req = indexedDB.open('__bu_capture', 1);
		req.onsuccess = () => {
			const db = req.result;
			const tx = db.transaction(STORE_NAME, 'readonly');
			const store = tx.objectStore(STORE_NAME);
			const getAll = store.getAll();
			getAll.onsuccess = () => { db.close(); resolve(getAll.result); };
			getAll.onerror = () => { db.close(); reject(getAll.error); };
		};
		req.onerror = () => reject(req.error);
	});
})()
"""

# JS harness that wraps user transform code with helpers
_TRANSFORM_HARNESS_JS = """\
(async () => {
	try {
		const dbOpen = () => new Promise((resolve, reject) => {
			const req = indexedDB.open('__bu_capture', 1);
			req.onupgradeneeded = (e) => {
				const db = e.target.result;
				if (!db.objectStoreNames.contains('responses')) {
					db.createObjectStore('responses', { keyPath: 'id', autoIncrement: true });
				}
				if (!db.objectStoreNames.contains('results')) {
					db.createObjectStore('results', { keyPath: 'id', autoIncrement: true });
				}
			};
			req.onsuccess = () => resolve(req.result);
			req.onerror = () => reject(req.error || new Error('IndexedDB open failed'));
		});

		const _readAll = async (storeName) => {
			const db = await dbOpen();
			return new Promise((resolve, reject) => {
				const tx = db.transaction(storeName, 'readonly');
				const store = tx.objectStore(storeName);
				const getAll = store.getAll();
				getAll.onsuccess = () => { db.close(); resolve(getAll.result); };
				getAll.onerror = () => { db.close(); reject(getAll.error || new Error('getAll failed')); };
			});
		};

		const _writeResults = async (db, items) => {
			return new Promise((resolve, reject) => {
				const tx = db.transaction('results', 'readwrite');
				const store = tx.objectStore('results');
				store.clear();
				let idx = 0;
				for (const item of items) {
					idx++;
					const record = Object.assign({}, item);
					record.id = idx;
					store.put(record);
				}
				tx.oncomplete = () => resolve(items.length);
				tx.onerror = () => reject(tx.error || new Error('write failed'));
			});
		};

		const responses = await _readAll('responses');
		const db = await dbOpen();

		USER_CODE_HERE

		db.close();
		return {ok: true, count: typeof __result_count !== 'undefined' ? __result_count : null};
	} catch (e) {
		return {ok: false, error: (e && e.message) ? e.message : String(e || 'Unknown error')};
	}
})()
"""


class NetworkCaptureWatchdog(BaseWatchdog):
	"""Manages CDP Network.responseReceived interception and IndexedDB storage.

	Conditionally active — only captures when the agent calls start_capture.
	"""

	LISTENS_TO: ClassVar[list[type[BaseEvent[Any]]]] = [
		TabCreatedEvent,
		BrowserStoppedEvent,
		NavigationCompleteEvent,
	]
	EMITS: ClassVar[list[type[BaseEvent[Any]]]] = [
		NetworkCaptureStartedEvent,
		NetworkCaptureStoppedEvent,
	]

	# Private state
	_capture_active: bool = PrivateAttr(default=False)
	_session_name: str = PrivateAttr(default='default')
	_url_patterns: list[str] = PrivateAttr(default_factory=list)
	_capture_origin: str | None = PrivateAttr(default=None)
	_network_callback_registered: bool = PrivateAttr(default=False)
	_network_enabled_targets: set[str] = PrivateAttr(default_factory=set)
	_captured_count: int = PrivateAttr(default=0)
	_indexeddb_initialized: bool = PrivateAttr(default=False)
	_cdp_event_tasks: set[asyncio.Task[Any]] = PrivateAttr(default_factory=set)

	# --- Event handlers ---

	async def on_TabCreatedEvent(self, event: TabCreatedEvent) -> None:
		"""Enable Network domain on new tabs when capture is active."""
		if not self._capture_active:
			return
		target_id = event.target_id
		if target_id in self._network_enabled_targets:
			return
		try:
			await self._enable_network_for_target(target_id)
		except Exception as e:
			self.logger.warning(f'[NetworkCaptureWatchdog] Failed to enable network for new tab {target_id[-4:]}: {e}')

	async def on_BrowserStoppedEvent(self, event: BrowserStoppedEvent) -> None:
		"""Reset all state when browser stops."""
		self._capture_active = False
		self._session_name = 'default'
		self._url_patterns = []
		self._capture_origin = None
		self._network_callback_registered = False
		self._network_enabled_targets.clear()
		self._captured_count = 0
		self._indexeddb_initialized = False

	async def on_NavigationCompleteEvent(self, event: NavigationCompleteEvent) -> None:
		"""Check if origin changed during capture, re-init IndexedDB if so."""
		if not self._capture_active:
			return
		new_origin = self._extract_origin(event.url)
		if self._capture_origin and new_origin and new_origin != self._capture_origin:
			self.logger.warning(
				f'[NetworkCaptureWatchdog] Origin changed from {self._capture_origin} to {new_origin}. '
				f'Old captured data is no longer accessible from this origin.'
			)
			self._capture_origin = new_origin
			self._indexeddb_initialized = False
			try:
				await self._init_indexeddb()
			except Exception as e:
				self.logger.warning(f'[NetworkCaptureWatchdog] Failed to re-init IndexedDB on new origin: {e}')

	# --- Public methods (called by tool actions) ---

	async def start_capture(self, session_name: str, url_patterns: list[str]) -> dict[str, Any]:
		"""Activate network capture for matching URL patterns."""
		assert url_patterns, 'url_patterns must not be empty'

		self._session_name = session_name
		self._url_patterns = url_patterns
		self._captured_count = 0
		self._capture_active = True

		# Determine origin from current page
		try:
			current_url = await self.browser_session.get_current_page_url()
			self._capture_origin = self._extract_origin(current_url)
		except Exception:
			self._capture_origin = None

		# Initialize IndexedDB schema
		await self._init_indexeddb()

		# Register CDP callback + enable Network domain on current target
		await self._ensure_network_monitoring()

		# Dispatch informational event
		self.event_bus.dispatch(
			NetworkCaptureStartedEvent(
				session_name=session_name,
				url_patterns=url_patterns,
				origin=self._capture_origin or 'unknown',
			)
		)

		return {
			'session_name': session_name,
			'url_patterns': url_patterns,
			'origin': self._capture_origin or 'unknown',
		}

	async def stop_capture(self) -> dict[str, Any]:
		"""Deactivate network capture and return summary."""
		was_active = self._capture_active
		count = self._captured_count
		name = self._session_name

		self._capture_active = False

		if was_active:
			self.event_bus.dispatch(
				NetworkCaptureStoppedEvent(
					session_name=name,
					responses_captured=count,
				)
			)

		return {
			'session_name': name,
			'responses_captured': count,
			'was_active': was_active,
		}

	async def run_js_transform(self, js_code: str) -> dict[str, Any]:
		"""Execute user JS transform code inside the browser sandbox.

		The JS code has access to:
		- responses: array of captured response objects
		- db: open IndexedDB handle
		- _writeResults(db, items): helper to write transformed results

		User code should call: const __result_count = await _writeResults(db, transformedItems);
		"""
		# Build the full JS by inserting user code into the harness
		full_js = _TRANSFORM_HARNESS_JS.replace('USER_CODE_HERE', js_code)

		cdp_session = await self.browser_session.get_or_create_cdp_session()
		try:
			result = await asyncio.wait_for(
				cdp_session.cdp_client.send.Runtime.evaluate(
					params={
						'expression': full_js,
						'returnByValue': True,
						'awaitPromise': True,
					},
					session_id=cdp_session.session_id,
				),
				timeout=30.0,
			)
		except asyncio.TimeoutError:
			return {'ok': False, 'error': 'Transform timed out after 30s'}

		if result.get('exceptionDetails'):
			error_text = result['exceptionDetails'].get('text', 'Unknown JS error')
			return {'ok': False, 'error': error_text}

		value = result.get('result', {}).get('value')
		if isinstance(value, dict):
			return value
		return {'ok': False, 'error': f'Unexpected result: {value}'}

	async def sync_to_filesystem(self, file_system: FileSystem, file_name: str, source: str = 'results') -> str:
		"""Read from IndexedDB store and write to FileSystem.

		Args:
			file_system: The FileSystem instance to write to.
			file_name: Output filename (e.g. "products.json").
			source: "responses" for raw captured data, "results" for transformed data.
		"""
		assert source in ('responses', 'results'), f'source must be "responses" or "results", got "{source}"'

		# Read all records from the specified store
		read_js = _READ_STORE_JS.replace('STORE_NAME', json.dumps(source))

		cdp_session = await self.browser_session.get_or_create_cdp_session()
		result = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={
				'expression': read_js,
				'returnByValue': True,
				'awaitPromise': True,
			},
			session_id=cdp_session.session_id,
		)

		if result.get('exceptionDetails'):
			error_text = result['exceptionDetails'].get('text', 'Unknown JS error')
			raise RuntimeError(f'Failed to read from IndexedDB store "{source}": {error_text}')

		records = result.get('result', {}).get('value', [])
		if not isinstance(records, list):
			records = []

		# Format based on file extension
		ext = file_name.rsplit('.', 1)[-1].lower() if '.' in file_name else 'json'

		if ext == 'jsonl':
			content = '\n'.join(json.dumps(r, ensure_ascii=False) for r in records)
		elif ext == 'csv':
			content = self._records_to_csv(records)
		else:
			# Default to JSON
			content = json.dumps(records, ensure_ascii=False, indent=2)

		await file_system.write_file(file_name, content)
		return f'Written to {file_name} ({len(records)} records)'

	# --- Internal helpers ---

	async def _init_indexeddb(self) -> None:
		"""Initialize the __bu_capture IndexedDB on the current page."""
		cdp_session = await self.browser_session.get_or_create_cdp_session()
		result = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={
				'expression': _INDEXEDDB_INIT_JS,
				'returnByValue': True,
				'awaitPromise': True,
			},
			session_id=cdp_session.session_id,
		)
		if result.get('exceptionDetails'):
			error_text = result['exceptionDetails'].get('text', 'Unknown JS error')
			raise RuntimeError(f'Failed to init IndexedDB: {error_text}')
		self._indexeddb_initialized = True
		self.logger.debug('[NetworkCaptureWatchdog] IndexedDB initialized')

	async def _ensure_network_monitoring(self) -> None:
		"""Register the CDP callback globally (once) and enable Network domain on current target."""
		cdp_client = self.browser_session.cdp_client

		if not self._network_callback_registered:

			def on_response_received(event: ResponseReceivedEvent, session_id: str | None) -> None:
				"""Handle Network.responseReceived to capture matching responses."""
				if not self._capture_active:
					return
				try:
					response = event.get('response', {})
					url = response.get('url', '')
					request_id = event.get('requestId') or event.get('request_id')

					if not url or not request_id:
						return

					# Check if URL matches any pattern
					if not any(fnmatch(url, pattern) for pattern in self._url_patterns):
						return

					mime_type = response.get('mimeType', '')

					# Fetch body and store in background
					async def _fetch_and_store():
						try:
							# Resolve the session_id to use for getResponseBody
							target_session_id = session_id
							if not target_session_id and self.browser_session.session_manager:
								# Fallback: try to use the default session
								cdp_sess = await self.browser_session.get_or_create_cdp_session()
								target_session_id = cdp_sess.session_id

							body_result = await cdp_client.send.Network.getResponseBody(
								params={'requestId': request_id},
								session_id=target_session_id,
							)
							body = body_result.get('body', '')
							base64_encoded = body_result.get('base64Encoded', False)

							# Build record for IndexedDB
							record = {
								'session': self._session_name,
								'url': url,
								'body': body,
								'mime': mime_type,
								'timestamp': int(asyncio.get_event_loop().time() * 1000),
								'_raw_length': len(body),
								'base64Encoded': base64_encoded,
							}

							record_json = json.dumps(record, ensure_ascii=False)
							store_js = _STORE_RESPONSE_JS.replace('RECORD', record_json)

							cdp_sess = await self.browser_session.get_or_create_cdp_session()
							await cdp_sess.cdp_client.send.Runtime.evaluate(
								params={
									'expression': store_js,
									'returnByValue': True,
									'awaitPromise': True,
								},
								session_id=cdp_sess.session_id,
							)
							self._captured_count += 1
							self.logger.debug(f'[NetworkCaptureWatchdog] Captured #{self._captured_count}: {url[:80]}')
						except Exception as e:
							# Non-critical: skip silently (redirects, CORS, evicted body)
							self.logger.debug(f'[NetworkCaptureWatchdog] Failed to capture {url[:60]}: {e}')

					task = create_task_with_error_handling(
						_fetch_and_store(),
						name='network_capture_store',
						logger_instance=self.logger,
						suppress_exceptions=True,
					)
					self._cdp_event_tasks.add(task)
					task.add_done_callback(lambda t: self._cdp_event_tasks.discard(t))

				except Exception as e:
					self.logger.error(f'[NetworkCaptureWatchdog] Error in response handler: {type(e).__name__}: {e}')

			cdp_client.register.Network.responseReceived(on_response_received)
			self._network_callback_registered = True
			self.logger.debug('[NetworkCaptureWatchdog] Registered global network response callback')

		# Enable Network domain on current target
		try:
			cdp_session = await self.browser_session.get_or_create_cdp_session()
			target_id = cdp_session.target_id
			if target_id and target_id not in self._network_enabled_targets:
				await self._enable_network_for_target(target_id)
		except Exception as e:
			self.logger.warning(f'[NetworkCaptureWatchdog] Failed to enable network on current target: {e}')

	async def _enable_network_for_target(self, target_id: str) -> None:
		"""Enable the Network CDP domain for a specific target."""
		cdp_client = self.browser_session.cdp_client
		cdp_session = await self.browser_session.get_or_create_cdp_session(target_id, focus=False)
		await cdp_client.send.Network.enable(session_id=cdp_session.session_id)
		self._network_enabled_targets.add(target_id)
		self.logger.debug(f'[NetworkCaptureWatchdog] Network enabled for target {target_id[-4:]}')

	@staticmethod
	def _extract_origin(url: str) -> str | None:
		"""Extract origin (scheme + host + port) from a URL."""
		try:
			parsed = urlparse(url)
			if parsed.scheme and parsed.netloc:
				return f'{parsed.scheme}://{parsed.netloc}'
		except Exception:
			pass
		return None

	@staticmethod
	def _records_to_csv(records: list[dict[str, Any]]) -> str:
		"""Convert a list of dicts to CSV string."""
		if not records:
			return ''

		# Collect all keys across records
		all_keys: list[str] = []
		seen: set[str] = set()
		for r in records:
			for k in r:
				if k not in seen:
					all_keys.append(k)
					seen.add(k)

		def escape_csv(val: Any) -> str:
			s = str(val) if val is not None else ''
			if ',' in s or '"' in s or '\n' in s:
				return '"' + s.replace('"', '""') + '"'
			return s

		lines = [','.join(escape_csv(k) for k in all_keys)]
		for r in records:
			lines.append(','.join(escape_csv(r.get(k)) for k in all_keys))
		return '\n'.join(lines)
