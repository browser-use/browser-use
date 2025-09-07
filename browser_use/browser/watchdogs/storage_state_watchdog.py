"""Storage state watchdog for managing browser cookies and storage persistence."""

import asyncio
import json
import os
from pathlib import Path
from typing import Any, ClassVar

from bubus import BaseEvent
from cdp_use.cdp.network import Cookie
from pydantic import Field, PrivateAttr

from browser_use.browser.events import (
	BrowserConnectedEvent,
	BrowserStopEvent,
	LoadStorageStateEvent,
	SaveStorageStateEvent,
	StorageStateLoadedEvent,
	StorageStateSavedEvent,
)
from browser_use.browser.watchdog_base import BaseWatchdog


class StorageStateWatchdog(BaseWatchdog):
	"""Monitors and persists browser storage state including cookies and localStorage."""

	# Event contracts
	LISTENS_TO: ClassVar[list[type[BaseEvent]]] = [
		BrowserConnectedEvent,
		BrowserStopEvent,
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
	_last_cookie_state: list[dict] = PrivateAttr(default_factory=list)
	_save_lock: asyncio.Lock = PrivateAttr(default_factory=asyncio.Lock)

	async def on_BrowserConnectedEvent(self, event: BrowserConnectedEvent) -> None:
		"""Start monitoring when browser starts."""
		self.logger.debug('[StorageStateWatchdog] 🍪 Initializing auth/cookies sync <-> with storage_state.json file')

		# Start monitoring
		await self._start_monitoring()

		# Automatically load storage state after browser start
		await self.event_bus.dispatch(LoadStorageStateEvent())

	async def on_BrowserStopEvent(self, event: BrowserStopEvent) -> None:
		"""Stop monitoring when browser stops."""
		self.logger.debug('[StorageStateWatchdog] Stopping storage_state monitoring')
		await self._stop_monitoring()

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

		assert self.browser_session.cdp_client is not None

		self._monitoring_task = asyncio.create_task(self._monitor_storage_changes())
		# self.logger'[StorageStateWatchdog] Started storage monitoring task')

	async def _stop_monitoring(self) -> None:
		"""Stop the monitoring task."""
		if self._monitoring_task and not self._monitoring_task.done():
			self._monitoring_task.cancel()
			try:
				await self._monitoring_task
			except asyncio.CancelledError:
				pass
			# self.logger.debug('[StorageStateWatchdog] Stopped storage monitoring task')

	async def _check_for_cookie_changes_cdp(self, event: dict) -> None:
		"""Check if a CDP network event indicates cookie changes.

		This would be called by Network.responseReceivedExtraInfo events
		if we set up CDP event listeners.
		"""
		try:
			# Check for Set-Cookie headers in the response
			headers = event.get('headers', {})
			if 'set-cookie' in headers or 'Set-Cookie' in headers:
				self.logger.debug('[StorageStateWatchdog] Cookie change detected via CDP')

				# If save on change is enabled, trigger save immediately
				if self.save_on_change:
					await self._save_storage_state()
		except Exception as e:
			self.logger.warning(f'[StorageStateWatchdog] Error checking for cookie changes: {e}')

	async def _monitor_storage_changes(self) -> None:
		"""Periodically check for storage changes and auto-save."""
		while True:
			try:
				await asyncio.sleep(self.auto_save_interval)

				# Check if cookies have changed
				if await self._have_cookies_changed():
					self.logger.debug('[StorageStateWatchdog] Detected changes to sync with storage_state.json')
					await self._save_storage_state()

			except asyncio.CancelledError:
				break
			except Exception as e:
				self.logger.error(f'[StorageStateWatchdog] Error in monitoring loop: {e}')

	async def _have_cookies_changed(self) -> bool:
		"""Check if cookies have changed since last save."""
		if not self.browser_session.cdp_client:
			return False

		try:
			# Get current cookies using CDP
			current_cookies = await self.browser_session._cdp_get_cookies()

			# Convert to comparable format, using .get() for optional fields
			current_cookie_set = {
				(c.get('name', ''), c.get('domain', ''), c.get('path', '')): c.get('value', '') for c in current_cookies
			}

			last_cookie_set = {
				(c.get('name', ''), c.get('domain', ''), c.get('path', '')): c.get('value', '') for c in self._last_cookie_state
			}

			return current_cookie_set != last_cookie_set
		except Exception as e:
			self.logger.debug(f'[StorageStateWatchdog] Error comparing cookies: {e}')
			return False

	async def _save_storage_state(self, path: str | None = None) -> None:
		"""Save browser storage state to file."""
		async with self._save_lock:
			# Check if CDP client is available
			assert await self.browser_session.get_or_create_cdp_session(target_id=None, new_socket=False)

			save_path = path or self.browser_session.browser_profile.storage_state
			if not save_path:
				return

			# Skip saving if the storage state is already a dict (indicates it was loaded from memory)
			# We only save to file if it started as a file path
			if isinstance(save_path, dict):
				self.logger.debug('[StorageStateWatchdog] Storage state is already a dict, skipping file save')
				return

			try:
				# Get current storage state using CDP
				storage_state = await self.browser_session._cdp_get_storage_state()

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
						self.logger.error(f'[StorageStateWatchdog] Failed to merge with existing state: {e}')

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

				self.logger.debug(
					f'[StorageStateWatchdog] Saved storage state to {json_path} '
					f'({len(merged_state.get("cookies", []))} cookies, '
					f'{len(merged_state.get("origins", []))} origins)'
				)

			except Exception as e:
				self.logger.error(f'[StorageStateWatchdog] Failed to save storage state: {e}')

	async def _load_storage_state(self, path: str | None = None) -> None:
		"""Load browser storage state from file."""
		if not self.browser_session.cdp_client:
			self.logger.warning('[StorageStateWatchdog] No CDP client available for loading')
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
				await self.browser_session._cdp_set_cookies(storage['cookies'])
				self._last_cookie_state = storage['cookies'].copy()
				self.logger.debug(f'[StorageStateWatchdog] Added {len(storage["cookies"])} cookies from storage state')

			# Apply origins (localStorage/sessionStorage) if present
			if 'origins' in storage and storage['origins']:
				for origin in storage['origins']:
					if 'localStorage' in origin:
						for item in origin['localStorage']:
							script = f"""
								window.localStorage.setItem({json.dumps(item['name'])}, {json.dumps(item['value'])});
							"""
							await self.browser_session._cdp_add_init_script(script)
					if 'sessionStorage' in origin:
						for item in origin['sessionStorage']:
							script = f"""
								window.sessionStorage.setItem({json.dumps(item['name'])}, {json.dumps(item['value'])});
							"""
							await self.browser_session._cdp_add_init_script(script)
				self.logger.debug(
					f'[StorageStateWatchdog] Applied localStorage/sessionStorage from {len(storage["origins"])} origins'
				)

			self.event_bus.dispatch(
				StorageStateLoadedEvent(
					path=str(load_path),
					cookies_count=len(storage.get('cookies', [])),
					origins_count=len(storage.get('origins', [])),
				)
			)

			self.logger.debug(f'[StorageStateWatchdog] Loaded storage state from: {load_path}')

		except Exception as e:
			self.logger.error(f'[StorageStateWatchdog] Failed to load storage state: {e}')

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

	async def get_current_cookies(self) -> list[dict[str, Any]]:
		"""Get current cookies using CDP."""
		if not self.browser_session.cdp_client:
			return []

		try:
			cookies = await self.browser_session._cdp_get_cookies()
			# Cookie is a TypedDict, cast to dict for compatibility
			return [dict(cookie) for cookie in cookies]
		except Exception as e:
			self.logger.error(f'[StorageStateWatchdog] Failed to get cookies: {e}')
			return []

	async def add_cookies(self, cookies: list[dict[str, Any]]) -> None:
		"""Add cookies using CDP."""
		if not self.browser_session.cdp_client:
			self.logger.warning('[StorageStateWatchdog] No CDP client available for adding cookies')
			return

		try:
			# Convert dicts to Cookie objects
			cookie_objects = [Cookie(**cookie_dict) if isinstance(cookie_dict, dict) else cookie_dict for cookie_dict in cookies]
			# Set cookies using CDP
			await self.browser_session._cdp_set_cookies(cookie_objects)
			self.logger.debug(f'[StorageStateWatchdog] Added {len(cookies)} cookies')
		except Exception as e:
			self.logger.error(f'[StorageStateWatchdog] Failed to add cookies: {e}')
