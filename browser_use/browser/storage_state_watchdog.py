"""Storage state watchdog for managing browser cookies and storage persistence."""

import asyncio
import json
import os
from pathlib import Path
from typing import Any, ClassVar

from bubus import BaseEvent
from playwright.async_api import Cookie, Page, StorageStateCookie
from pydantic import Field, PrivateAttr

from browser_use.browser.events import (
	BrowserStartedEvent,
	BrowserStoppedEvent,
	LoadStorageStateEvent,
	SaveStorageStateEvent,
	StorageStateLoadedEvent,
	StorageStateSavedEvent,
)
from browser_use.browser.watchdog_base import BaseWatchdog
from browser_use.utils import logger


class StorageStateWatchdog(BaseWatchdog):
	"""Monitors and persists browser storage state including cookies and localStorage."""

	# Event contracts
	LISTENS_TO: ClassVar[list[type[BaseEvent]]] = [
		BrowserStartedEvent,
		BrowserStoppedEvent,
		SaveStorageStateEvent,
		LoadStorageStateEvent,
	]
	EMITS: ClassVar[list[type[BaseEvent]]] = [
		StorageStateSavedEvent,
		StorageStateLoadedEvent,
	]

	# Configuration
	auto_save_interval: float = Field(default=30.0)  # Auto-save every 30 seconds
	save_on_change: bool = Field(default=True)  # Save immediately when cookies change

	# Private state
	_monitoring_task: asyncio.Task | None = PrivateAttr(default=None)
	_last_cookie_state: list[StorageStateCookie] = PrivateAttr(default_factory=list)
	_save_lock: asyncio.Lock = PrivateAttr(default_factory=asyncio.Lock)

	async def on_BrowserStartedEvent(self, event: BrowserStartedEvent) -> None:
		"""Start monitoring when browser starts."""
		logger.info('[StorageStateWatchdog] Browser started, initializing storage monitoring')

		# Start monitoring
		await self._start_monitoring()

		# Automatically load storage state after browser start
		self.event_bus.dispatch(LoadStorageStateEvent())

	async def on_BrowserStoppedEvent(self, event: BrowserStoppedEvent) -> None:
		"""Stop monitoring and save state when browser stops."""
		logger.info('[StorageStateWatchdog] Browser stopping, saving final storage state')

		# Save storage state before stopping and wait for completion
		save_event = self.event_bus.dispatch(SaveStorageStateEvent())
		await save_event

		# Stop monitoring
		await self._stop_monitoring()
		# No cleanup needed - browser context is managed by session

	async def on_SaveStorageStateEvent(self, event: SaveStorageStateEvent) -> None:
		"""Handle storage state save request."""
		# Use provided path or fall back to profile default
		path = event.path
		if path is None:
			# Use profile default path if available
			if self.browser_session.browser_profile.storage_state:
				path = str(self.browser_session.browser_profile.storage_state)
			else:
				path = None  # Skip saving if no path available
		await self._save_storage_state(path)

	async def on_LoadStorageStateEvent(self, event: LoadStorageStateEvent) -> None:
		"""Handle storage state load request."""
		# Use provided path or fall back to profile default
		path = event.path
		if path is None:
			# Use profile default path if available
			if self.browser_session.browser_profile.storage_state:
				path = str(self.browser_session.browser_profile.storage_state)
			else:
				path = None  # Skip loading if no path available
		await self._load_storage_state(path)

	async def _start_monitoring(self) -> None:
		"""Start the monitoring task."""
		if self._monitoring_task and not self._monitoring_task.done():
			return

		self._monitoring_task = asyncio.create_task(self._monitor_storage_changes())
		logger.info('[StorageStateWatchdog] Started storage monitoring task')

		# Set up page monitoring for existing pages
		if self.browser_session._browser_context:
			for page in self.browser_session._browser_context.pages:
				self._setup_page_monitoring(page)

	async def _stop_monitoring(self) -> None:
		"""Stop the monitoring task."""
		if self._monitoring_task and not self._monitoring_task.done():
			self._monitoring_task.cancel()
			try:
				await self._monitoring_task
			except asyncio.CancelledError:
				pass
			logger.info('[StorageStateWatchdog] Stopped storage monitoring task')

	def _setup_page_monitoring(self, page: Page) -> None:
		"""Set up storage change monitoring for a page."""
		# Monitor for cookie changes via response headers
		page.on('response', lambda response: asyncio.create_task(self._check_for_cookie_changes(response)))

		logger.debug(f'[StorageStateWatchdog] Set up monitoring for page: {page.url}')

	async def _check_for_cookie_changes(self, response) -> None:
		"""Check if a response set any cookies."""
		try:
			# Check for Set-Cookie headers
			headers = response.headers
			if 'set-cookie' in headers:
				logger.debug(f'[StorageStateWatchdog] Cookie change detected from: {response.url}')

				# If save on change is enabled, trigger save immediately
				if self.save_on_change:
					await self._save_storage_state()
		except Exception as e:
			logger.debug(f'[StorageStateWatchdog] Error checking for cookie changes: {e}')

	async def _monitor_storage_changes(self) -> None:
		"""Periodically check for storage changes and auto-save."""
		while True:
			try:
				await asyncio.sleep(self.auto_save_interval)

				# Check if cookies have changed
				if await self._have_cookies_changed():
					logger.info('[StorageStateWatchdog] Detected cookie changes during periodic check')
					await self._save_storage_state()

			except asyncio.CancelledError:
				break
			except Exception as e:
				logger.error(f'[StorageStateWatchdog] Error in monitoring loop: {e}')

	async def _have_cookies_changed(self) -> bool:
		"""Check if cookies have changed since last save."""
		if not self.browser_session._browser_context:
			return False

		try:
			# Get current storage state cookies (not Cookie API objects)
			storage_state = await self.browser_session._browser_context.storage_state()
			current_cookies = storage_state.get('cookies', [])

			# Convert to comparable format, using .get() for optional fields
			current_cookie_set = {
				(c.get('name', ''), c.get('domain', ''), c.get('path', '')): c.get('value', '') for c in current_cookies
			}

			last_cookie_set = {
				(c.get('name', ''), c.get('domain', ''), c.get('path', '')): c.get('value', '') for c in self._last_cookie_state
			}

			return current_cookie_set != last_cookie_set
		except Exception as e:
			logger.debug(f'[StorageStateWatchdog] Error comparing cookies: {e}')
			return False

	async def _save_storage_state(self, path: str | None = None) -> None:
		"""Save browser storage state to file."""
		async with self._save_lock:
			if not self.browser_session._browser_context:
				logger.warning('[StorageStateWatchdog] No browser context available for saving')
				return

			save_path = path or self.browser_session.browser_profile.storage_state
			if not save_path:
				return

			# Skip saving if the storage state is already a dict (indicates it was loaded from memory)
			# We only save to file if it started as a file path
			if isinstance(save_path, dict):
				logger.debug('[StorageStateWatchdog] Storage state is already a dict, skipping file save')
				return

			try:
				# Get current storage state
				storage_state = await self.browser_session._browser_context.storage_state()

				# Update our last known state
				self._last_cookie_state = storage_state.get('cookies', []).copy()

				# Convert path to Path object
				json_path = Path(save_path).expanduser().resolve()
				json_path.parent.mkdir(parents=True, exist_ok=True)

				# Merge with existing state if file exists
				merged_state = storage_state
				if json_path.exists():
					try:
						existing_state = json.loads(json_path.read_text())
						merged_state = self._merge_storage_states(existing_state, dict(storage_state))
					except Exception as e:
						logger.error(f'[StorageStateWatchdog] Failed to merge with existing state: {e}')

				# Write atomically
				temp_path = json_path.with_suffix('.json.tmp')
				temp_path.write_text(json.dumps(merged_state, indent=4))

				# Backup existing file
				if json_path.exists():
					backup_path = json_path.with_suffix('.json.bak')
					json_path.replace(backup_path)

				# Move temp to final
				temp_path.replace(json_path)

				# Emit success event
				self.event_bus.dispatch(
					StorageStateSavedEvent(
						path=str(json_path),
						cookies_count=len(merged_state.get('cookies', [])),
						origins_count=len(merged_state.get('origins', [])),
					)
				)

				logger.info(
					f'[StorageStateWatchdog] Saved storage state to {json_path} '
					f'({len(merged_state.get("cookies", []))} cookies, '
					f'{len(merged_state.get("origins", []))} origins)'
				)

			except Exception as e:
				logger.error(f'[StorageStateWatchdog] Failed to save storage state: {e}')

	async def _load_storage_state(self, path: str | None = None) -> None:
		"""Load browser storage state from file."""
		if not self.browser_session._browser_context:
			logger.warning('[StorageStateWatchdog] No browser context available for loading')
			return

		load_path = path or self.browser_session.browser_profile.storage_state
		if not load_path or not os.path.exists(str(load_path)):
			return

		try:
			# Read the storage state file asynchronously
			import anyio

			content = await anyio.Path(str(load_path)).read_text()
			storage = json.loads(content)

			# Apply cookies if present
			if 'cookies' in storage and storage['cookies']:
				await self.browser_session._browser_context.add_cookies(storage['cookies'])
				self._last_cookie_state = storage['cookies'].copy()
				logger.info(f'[StorageStateWatchdog] Added {len(storage["cookies"])} cookies from storage state')

			# Apply origins (localStorage/sessionStorage) if present
			if 'origins' in storage and storage['origins']:
				for origin in storage['origins']:
					if 'localStorage' in origin:
						for item in origin['localStorage']:
							await self.browser_session._browser_context.add_init_script(f"""
								window.localStorage.setItem({json.dumps(item['name'])}, {json.dumps(item['value'])});
							""")
					if 'sessionStorage' in origin:
						for item in origin['sessionStorage']:
							await self.browser_session._browser_context.add_init_script(f"""
								window.sessionStorage.setItem({json.dumps(item['name'])}, {json.dumps(item['value'])});
							""")
				logger.info(f'[StorageStateWatchdog] Applied localStorage/sessionStorage from {len(storage["origins"])} origins')

			self.event_bus.dispatch(
				StorageStateLoadedEvent(
					path=str(load_path),
					cookies_count=len(storage.get('cookies', [])),
					origins_count=len(storage.get('origins', [])),
				)
			)

			logger.info(f'[StorageStateWatchdog] Loaded storage state from: {load_path}')

		except Exception as e:
			logger.error(f'[StorageStateWatchdog] Failed to load storage state: {e}')

	@staticmethod
	def _merge_storage_states(existing: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
		"""Merge two storage states, with new values taking precedence."""
		merged = existing.copy()

		# Merge cookies
		existing_cookies = {(c['name'], c['domain'], c['path']): c for c in existing.get('cookies', [])}

		for cookie in new.get('cookies', []):
			key = (cookie['name'], cookie['domain'], cookie['path'])
			existing_cookies[key] = cookie

		merged['cookies'] = list(existing_cookies.values())

		# Merge origins
		existing_origins = {origin['origin']: origin for origin in existing.get('origins', [])}

		for origin in new.get('origins', []):
			existing_origins[origin['origin']] = origin

		merged['origins'] = list(existing_origins.values())

		return merged

	async def get_current_cookies(self) -> list[Cookie]:
		"""Get current cookies from browser context."""
		if not self.browser_session._browser_context:
			return []

		try:
			return await self.browser_session._browser_context.cookies()
		except Exception as e:
			logger.error(f'[StorageStateWatchdog] Failed to get cookies: {e}')
			return []

	async def add_cookies(self, cookies: list[Cookie]) -> None:
		"""Add cookies to browser context."""
		if not self.browser_session._browser_context:
			logger.warning('[StorageStateWatchdog] No browser context available for adding cookies')
			return

		try:
			# Convert Cookie objects to format required by add_cookies()
			# add_cookies() requires 'url' field that Cookie doesn't have
			cookie_params = []
			for cookie in cookies:
				# Build the required URL from cookie domain and path
				domain = cookie.get('domain', 'localhost')
				path = cookie.get('path', '/')
				secure = cookie.get('secure', False)
				url = f'http{"s" if secure else ""}://{domain.lstrip(".")}{path}'

				# Create cookie param dict with required fields
				param = {'name': cookie.get('name', ''), 'value': cookie.get('value', ''), 'url': url}

				# Add optional fields that both types support
				if 'domain' in cookie and cookie['domain']:
					param['domain'] = cookie['domain']
				if 'path' in cookie and cookie['path']:
					param['path'] = cookie['path']
				if 'expires' in cookie and cookie['expires'] is not None:
					param['expires'] = cookie['expires']  # type: ignore
				if 'httpOnly' in cookie and cookie['httpOnly'] is not None:
					param['httpOnly'] = cookie['httpOnly']  # type: ignore
				if 'secure' in cookie and cookie['secure'] is not None:
					param['secure'] = cookie['secure']  # type: ignore
				if 'sameSite' in cookie and cookie['sameSite']:
					param['sameSite'] = cookie['sameSite']

				cookie_params.append(param)

			await self.browser_session._browser_context.add_cookies(cookie_params)  # type: ignore
			logger.info(f'[StorageStateWatchdog] Added {len(cookies)} cookies')
		except Exception as e:
			logger.error(f'[StorageStateWatchdog] Failed to add cookies: {e}')


# Fix Pydantic circular dependency - this will be called from session.py after BrowserSession is defined
