"""
Chrome Extension Bridge for browser-use.

This module provides a bridge to communicate with a Chrome extension
that exposes chrome.* APIs via JSON-RPC.
"""

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
	from cdp_use import CDPClient

logger = logging.getLogger(__name__)


class ExtensionBridge:
	"""Bridge to communicate with Chrome extension APIs via CDP."""

	def __init__(self, cdp_client: 'CDPClient', extension_id: str | None = None):
		self.cdp_client = cdp_client
		self.extension_id = extension_id
		self._request_id = 0
		self._service_worker_target_id = None
		self._session_id = None
		self._pending_requests = {}
		self._event_listeners = {}

	async def initialize(self):
		"""Find and connect to the extension's service worker."""
		if not self.extension_id:
			# Try to auto-detect the extension
			await self._detect_extension()

		if not self.extension_id:
			raise RuntimeError('Extension ID not provided and could not be auto-detected')

		# Find the service worker target
		targets = await self.cdp_client.send.Target.getTargets()

		for target in targets['targetInfos']:
			if target['type'] == 'service_worker' and self.extension_id in target['url']:
				self._service_worker_target_id = target['targetId']
				break

		if not self._service_worker_target_id:
			raise RuntimeError(f'Could not find service worker for extension {self.extension_id}')

		# Attach to the service worker
		result = await self.cdp_client.send.Target.attachToTarget(
			params={'targetId': self._service_worker_target_id, 'flatten': True}
		)
		self._session_id = result['sessionId']

		logger.info(f'Connected to extension {self.extension_id} (session: {self._session_id})')

	async def _detect_extension(self):
		"""Try to detect the Browser Use extension."""
		targets = await self.cdp_client.send.Target.getTargets()

		logger.debug(f'Looking for extension among {len(targets["targetInfos"])} targets')
		for target in targets['targetInfos']:
			logger.debug(f'Target: type={target["type"]}, url={target["url"]}, title={target.get("title", "")}')
			if target['type'] == 'service_worker' and target['url'].endswith('/service_worker.js'):
				# Extract extension ID from URL
				url = target['url']
				if url.startswith('chrome-extension://'):
					self.extension_id = url.split('/')[2]
					logger.info(f'Auto-detected extension ID: {self.extension_id}')
					return

	async def call(self, method: str, params: list | None = None) -> Any:
		"""
		Call a Chrome API method via JSON-RPC.

		Examples:
		    # Get all tabs
		    tabs = await bridge.call('chrome.tabs.query', [{}])

		    # Create a new tab
		    tab = await bridge.call('chrome.tabs.create', [{'url': 'https://example.com'}])

		    # Switch to a tab
		    await bridge.call('chrome.tabs.update', [tab_id, {'active': True}])
		"""
		if not self._session_id:
			await self.initialize()

		self._request_id += 1
		request_id = self._request_id

		# Create JSON-RPC request
		request = {'jsonrpc': '2.0', 'id': request_id, 'method': method, 'params': params or []}

		# Send the request directly to the service worker via Runtime.evaluate
		# We need to handle the JSON-RPC request directly in the service worker context
		js_code = f"""
        (async () => {{
            const request = {json.dumps(request)};
            // Call handleJsonRpc directly in the service worker context
            const response = await handleJsonRpc(request);
            response.jsonrpc = '2.0';
            return response;
        }})()
        """

		result = await self.cdp_client.send.Runtime.evaluate(
			params={'expression': js_code, 'awaitPromise': True, 'returnByValue': True}, session_id=self._session_id
		)

		if 'exceptionDetails' in result:
			raise RuntimeError(f'Extension call failed: {result["exceptionDetails"]}')

		# Debug logging
		logger.debug(f'Runtime.evaluate result: {result}')

		# The result might be in different formats depending on the response
		if 'result' in result and 'value' in result['result']:
			response = result['result']['value']
		else:
			# Handle the case where the response is not wrapped
			response = result.get('result', {})

		if isinstance(response, dict) and 'error' in response:
			raise RuntimeError(f'Extension API error: {response["error"]["message"]}')

		# If response is a dict with 'result' key, return that, otherwise return the response itself
		if isinstance(response, dict) and 'result' in response:
			return response['result']
		else:
			return response

	async def add_listener(self, event_path: str) -> int:
		"""
		Add an event listener to a Chrome API event.

		Example:
		    listener_id = await bridge.add_listener('tabs.onCreated')
		"""
		return await self.call('addListener', [event_path])

	async def remove_listener(self, listener_id: int) -> bool:
		"""Remove a previously added event listener."""
		return await self.call('removeListener', [listener_id])

	async def get_property(self, property_path: str) -> Any:
		"""
		Get a Chrome API property value.

		Example:
		    extension_id = await bridge.get_property('runtime.id')
		"""
		return await self.call(f'get:chrome.{property_path}')

	# Convenience methods for tab management
	async def get_tabs(self, query: dict | None = None) -> list[dict]:
		"""Get all tabs matching the query."""
		return await self.call('chrome.tabs.query', [query or {}])

	async def get_tab(self, tab_id: int) -> dict:
		"""Get a specific tab by ID."""
		return await self.call('chrome.tabs.get', [tab_id])

	async def create_tab(self, url: str | None = None, **options) -> dict:
		"""Create a new tab."""
		if url:
			options['url'] = url
		return await self.call('chrome.tabs.create', [options])

	async def update_tab(self, tab_id: int, **update_info) -> dict:
		"""Update a tab's properties."""
		return await self.call('chrome.tabs.update', [tab_id, update_info])

	async def close_tab(self, tab_id: int):
		"""Close a tab."""
		return await self.call('chrome.tabs.remove', [tab_id])

	async def switch_to_tab(self, tab_id: int) -> dict:
		"""Switch to a specific tab (make it active)."""
		return await self.update_tab(tab_id, active=True)

	async def get_current_tab(self) -> dict | None:
		"""Get the currently active tab."""
		query_options = {'active': True, 'lastFocusedWindow': True}
		tabs = await self.call('chrome.tabs.query', [query_options])
		return tabs[0] if tabs else None


def get_extension_path() -> Path:
	"""Get the path to the Browser Use extension."""
	# Get the path relative to this file
	return Path(__file__).parent.parent.parent / 'extension'
