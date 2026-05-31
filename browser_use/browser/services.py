from __future__ import annotations

import asyncio
import json
import mimetypes
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from cdp_use.cdp.target import TargetID
from pydantic import BaseModel, ConfigDict

from browser_use.browser.events import (
	FileDownloadedEvent,
)
from browser_use.browser.interaction_services import (
	ClickService,
	DropdownService,
	KeyboardService,
	ScrollService,
	TypeService,
	UploadService,
)
from browser_use.browser.service_base import BrowserService
from browser_use.browser.session import BrowserSession
from browser_use.browser.views import BrowserStateSummary, TabInfo


class BrowserStateService(BrowserService):
	"""Fresh browser state capture."""

	async def get_state(
		self,
		*,
		include_screenshot: bool = True,
		cached: bool = False,
		include_recent_events: bool = False,
	) -> BrowserStateSummary:
		return await self.browser_session.get_browser_state_summary(
			include_screenshot=include_screenshot,
			cached=cached,
			include_recent_events=include_recent_events,
		)

	async def get_text(self) -> str:
		return await self.browser_session.get_state_as_text()


class PageReadinessService(BrowserService):
	"""Navigation readiness policy backed by CDP lifecycle events."""

	async def navigate_and_wait(
		self,
		url: str,
		target_id: str,
		*,
		timeout: float | None = None,
		wait_until: str = 'load',
		nav_timeout: float | None = None,
	) -> None:
		cdp_session = await self.browser_session.get_or_create_cdp_session(target_id, focus=False)

		if timeout is None:
			target = self.browser_session.session_manager.get_target(target_id)
			current_url = target.url
			same_domain = (
				url.split('/')[2] == current_url.split('/')[2]
				if url.startswith('http') and current_url.startswith('http')
				else False
			)
			timeout = 3.0 if same_domain else 8.0

		nav_start_time = asyncio.get_event_loop().time()

		if nav_timeout is None:
			nav_timeout = 20.0
		try:
			nav_result = await asyncio.wait_for(
				cdp_session.cdp_client.send.Page.navigate(
					params={'url': url, 'transitionType': 'address_bar'},
					session_id=cdp_session.session_id,
				),
				timeout=nav_timeout,
			)
		except TimeoutError:
			duration_ms = (asyncio.get_event_loop().time() - nav_start_time) * 1000
			raise RuntimeError(f'Page.navigate() timed out after {nav_timeout}s ({duration_ms:.0f}ms) for {url}')

		if nav_result.get('errorText'):
			raise RuntimeError(f'Navigation failed: {nav_result["errorText"]}')

		if wait_until == 'commit':
			duration_ms = (asyncio.get_event_loop().time() - nav_start_time) * 1000
			self.logger.debug(f'✅ Page ready for {url} (commit, {duration_ms:.0f}ms)')
			return

		navigation_id = nav_result.get('loaderId')
		start_time = asyncio.get_event_loop().time()
		seen_events = []

		if not hasattr(cdp_session, '_lifecycle_events'):
			raise RuntimeError(
				f'❌ Lifecycle monitoring not enabled for {cdp_session.target_id[:8]}! '
				f'This is a bug - SessionManager should have initialized it. '
				f'Session: {cdp_session}'
			)

		acceptable_events: set[str] = {'networkIdle'}
		if wait_until in ('load', 'domcontentloaded'):
			acceptable_events.add('load')
		if wait_until == 'domcontentloaded':
			acceptable_events.add('DOMContentLoaded')

		poll_interval = 0.05
		while (asyncio.get_event_loop().time() - start_time) < timeout:
			try:
				for event_data in list(cdp_session._lifecycle_events):
					event_name = event_data.get('name')
					event_loader_id = event_data.get('loaderId')

					event_str = f'{event_name}(loader={event_loader_id[:8] if event_loader_id else "none"})'
					if event_str not in seen_events:
						seen_events.append(event_str)

					if event_loader_id and navigation_id and event_loader_id != navigation_id:
						continue

					if event_name in acceptable_events:
						duration_ms = (asyncio.get_event_loop().time() - nav_start_time) * 1000
						self.logger.debug(f'✅ Page ready for {url} ({event_name}, {duration_ms:.0f}ms)')
						return

			except Exception as exc:
				self.logger.debug(f'Error polling lifecycle events: {exc}')

			await asyncio.sleep(poll_interval)

		duration_ms = (asyncio.get_event_loop().time() - nav_start_time) * 1000
		if not seen_events:
			self.logger.error(
				f'❌ No lifecycle events received for {url} after {duration_ms:.0f}ms! '
				f'Monitoring may have failed. Target: {cdp_session.target_id[:8]}'
			)
		else:
			self.logger.warning(f'⚠️ Page readiness timeout ({timeout}s, {duration_ms:.0f}ms) for {url}')


class NavigationService(BrowserService):
	"""Page navigation operations."""

	async def navigate(self, url: str, *, new_tab: bool = False, verify_not_empty: bool = True) -> None:
		self._ensure_url_allowed(url)
		self.browser_session._clear_browser_state_cache_direct(reason='navigation requested')
		target_id = await self._target_for_navigation(new_tab=new_tab)
		await PageReadinessService(browser_session=self.browser_session).navigate_and_wait(url, target_id)
		await self.browser_session._set_agent_focus_direct(target_id=target_id, url=url, emit_event=False)
		await self.browser_session._close_extension_options_pages()
		if verify_not_empty and not new_tab:
			await self._ensure_page_not_empty(url)

	async def go_back(self) -> str | None:
		cdp_session = await self.browser_session.get_or_create_cdp_session(target_id=None, focus=True)
		history = await cdp_session.cdp_client.send.Page.getNavigationHistory(session_id=cdp_session.session_id)
		current_index = history['currentIndex']
		entries = history['entries']
		if current_index <= 0:
			return None

		previous_entry = entries[current_index - 1]
		await cdp_session.cdp_client.send.Page.navigateToHistoryEntry(
			params={'entryId': previous_entry['id']},
			session_id=cdp_session.session_id,
		)
		await asyncio.sleep(0.5)
		return str(previous_entry.get('url', ''))

	async def go_forward(self) -> str | None:
		cdp_session = await self.browser_session.get_or_create_cdp_session(target_id=None, focus=True)
		history = await cdp_session.cdp_client.send.Page.getNavigationHistory(session_id=cdp_session.session_id)
		current_index = history['currentIndex']
		entries = history['entries']
		if current_index >= len(entries) - 1:
			return None

		next_entry = entries[current_index + 1]
		await cdp_session.cdp_client.send.Page.navigateToHistoryEntry(
			params={'entryId': next_entry['id']},
			session_id=cdp_session.session_id,
		)
		await asyncio.sleep(0.5)
		return str(next_entry.get('url', ''))

	async def refresh(self) -> None:
		cdp_session = await self.browser_session.get_or_create_cdp_session(target_id=None, focus=True)
		await cdp_session.cdp_client.send.Page.reload(session_id=cdp_session.session_id)
		await asyncio.sleep(1.0)

	async def current_url(self) -> str:
		return await self.browser_session.get_current_page_url()

	async def current_title(self) -> str:
		return await self.browser_session.get_current_page_title()

	async def _target_for_navigation(self, *, new_tab: bool) -> TargetID:
		if self.browser_session.agent_focus_target_id is None:
			cdp_session = await self.browser_session.get_or_create_cdp_session(target_id=None, focus=True)
			return cdp_session.target_id

		if not new_tab:
			return self.browser_session.agent_focus_target_id

		target_id = await self.browser_session._cdp_create_new_page('about:blank')
		await self.browser_session.get_or_create_cdp_session(target_id=target_id, focus=False)
		await self.browser_session._initialize_target_services_direct(target_id, 'about:blank')
		await self.browser_session._notify_tab_created_compatibility(target_id, 'about:blank')
		await self.browser_session._set_agent_focus_direct(target_id=target_id, url='about:blank', emit_event=False)
		return target_id

	def _ensure_url_allowed(self, url: str) -> None:
		security_watchdog = getattr(self.browser_session, '_security_watchdog', None)
		if security_watchdog is not None and not security_watchdog._is_url_allowed(url):
			raise ValueError(f'Navigation to {url} blocked by security policy')

	async def _ensure_page_not_empty(self, url: str) -> None:
		state = await self.browser_session.get_browser_state_summary(include_screenshot=False)
		url_is_http = state.url.lower().startswith(('http://', 'https://'))
		if not url_is_http or not _page_appears_empty(state):
			return

		self.browser_session.logger.warning(f'⚠️ Empty DOM detected after navigation to {url}, waiting 3s and rechecking...')
		await asyncio.sleep(3.0)
		state = await self.browser_session.get_browser_state_summary(include_screenshot=False)
		if not state.url.lower().startswith(('http://', 'https://')) or not _page_appears_empty(state):
			return

		self.browser_session.logger.warning(f'⚠️ Still empty after 3s, attempting page reload for {url}...')
		target_id = self.browser_session.agent_focus_target_id
		if target_id is None:
			cdp_session = await self.browser_session.get_or_create_cdp_session(target_id=None, focus=True)
			target_id = cdp_session.target_id
		await PageReadinessService(browser_session=self.browser_session).navigate_and_wait(url, target_id)
		await asyncio.sleep(5.0)
		state = await self.browser_session.get_browser_state_summary(include_screenshot=False)
		if state.url.lower().startswith(('http://', 'https://')) and state.dom_state._root is None:
			raise RuntimeError(
				f'Page loaded but returned empty content for {url}. '
				f'The page may require JavaScript that failed to render, use anti-bot measures, '
				f'or have a connection issue (e.g. tunnel/proxy error). Try a different URL or approach.'
			)


class TabService(BrowserService):
	"""Tab listing and focus operations."""

	async def list_tabs(self) -> list[TabInfo]:
		return await self.browser_session.get_tabs()

	async def switch(self, target_id: TargetID | None = None) -> TargetID:
		return await self.browser_session.switch_tab_direct(target_id)

	async def close(self, target_id: TargetID) -> None:
		next_focus = None
		if target_id == self.browser_session.agent_focus_target_id:
			page_targets = [
				target.target_id
				for target in self.browser_session.session_manager.get_all_page_targets()
				if target.target_id != target_id
			]
			next_focus = page_targets[-1] if page_targets else None

		await self.browser_session._cdp_close_page(target_id)
		self.browser_session._clear_browser_state_cache_direct(reason='tab closed')

		if target_id != self.browser_session.agent_focus_target_id:
			return

		if next_focus is None:
			next_focus = await self.browser_session._cdp_create_new_page('about:blank')
			await self.browser_session.get_or_create_cdp_session(target_id=next_focus, focus=False)
			await self.browser_session._initialize_target_services_direct(next_focus, 'about:blank')
			await self.browser_session._notify_tab_created_compatibility(next_focus, 'about:blank')

		await self.browser_session.switch_tab_direct(next_focus)


def _page_appears_empty(state: BrowserStateSummary) -> bool:
	return state.dom_state._root is None or not state.dom_state.llm_representation().strip()


def _download_filename(url: str, *, content_type: str | None, suggested_filename: str | None) -> str:
	if suggested_filename:
		return _sanitize_download_filename(suggested_filename)

	parsed = urlparse(url)
	filename = _sanitize_download_filename(os.path.basename(parsed.path))
	if filename != 'download' and '.' in filename:
		return filename
	if content_type and 'pdf' in content_type:
		return 'document.pdf'
	return filename


def _sanitize_download_filename(name: str | None) -> str:
	if not name:
		return 'download'
	name = name.replace('\x00', '')
	name = name.replace('\\', '/')
	name = os.path.basename(name.rsplit('/', 1)[-1])
	if name in ('', '.', '..'):
		return 'download'
	return name


def _unique_download_destination(downloads_dir: Path, filename: str) -> Path:
	destination = downloads_dir / filename
	if not destination.exists():
		return destination

	base = destination.stem
	ext = destination.suffix
	counter = 1
	while True:
		candidate = downloads_dir / f'{base} ({counter}){ext}'
		if not candidate.exists():
			return candidate
		counter += 1


def _is_path_contained(path: str | Path, directory: str | Path) -> bool:
	real_path = os.path.realpath(str(path))
	real_dir = os.path.realpath(str(directory))
	return real_path == real_dir or real_path.startswith(real_dir + os.sep)


class DownloadService(BrowserService):
	"""Downloaded file access."""

	async def prepare_directory(self) -> None:
		downloads_watchdog = getattr(self.browser_session, '_downloads_watchdog', None)
		if downloads_watchdog is not None:
			await downloads_watchdog.initialize_downloads_directory()

	async def attach_to_target(self, target_id: TargetID) -> None:
		downloads_watchdog = getattr(self.browser_session, '_downloads_watchdog', None)
		if downloads_watchdog is not None:
			await downloads_watchdog.attach_to_target(target_id)

	async def cleanup(self) -> None:
		downloads_watchdog = getattr(self.browser_session, '_downloads_watchdog', None)
		if downloads_watchdog is not None:
			await downloads_watchdog.cleanup_after_stop()

	def list_downloads(self) -> list[str]:
		return self.browser_session.downloaded_files

	async def download_url(
		self,
		url: str,
		*,
		target_id: TargetID | None = None,
		content_type: str | None = None,
		suggested_filename: str | None = None,
		timeout_s: float = 15.0,
	) -> dict[str, Any] | None:
		"""Download a URL through the browser context and track it without the event bus."""

		downloads_path = self.browser_session.browser_profile.downloads_path
		if not downloads_path:
			self.browser_session.logger.warning('[DownloadService] No downloads path configured')
			return None

		downloads_dir = Path(downloads_path).expanduser().resolve()
		downloads_dir.mkdir(parents=True, exist_ok=True)
		filename = _download_filename(url, content_type=content_type, suggested_filename=suggested_filename)
		destination = _unique_download_destination(downloads_dir, filename)
		if not _is_path_contained(destination, downloads_dir):
			self.browser_session.logger.error(
				f'[DownloadService] Refusing to write download outside downloads_dir: {destination}'
			)
			return None

		if target_id is None:
			if self.browser_session.agent_focus_target_id is None:
				cdp_session = await self.browser_session.get_or_create_cdp_session(target_id=None, focus=True)
			else:
				cdp_session = await self.browser_session.get_or_create_cdp_session(
					target_id=self.browser_session.agent_focus_target_id, focus=False
				)
		else:
			cdp_session = await self.browser_session.get_or_create_cdp_session(target_id=target_id, focus=False)

		result = await asyncio.wait_for(
			cdp_session.cdp_client.send.Runtime.evaluate(
				params={
					'expression': f"""
(async () => {{
	const response = await fetch({json.dumps(url)}, {{ cache: 'force-cache' }});
	if (!response.ok) {{
		throw new Error(`HTTP error! status: ${{response.status}}`);
	}}
	const blob = await response.blob();
	const arrayBuffer = await blob.arrayBuffer();
	const uint8Array = new Uint8Array(arrayBuffer);
	return {{ data: Array.from(uint8Array), responseSize: uint8Array.length }};
}})()
""",
					'awaitPromise': True,
					'returnByValue': True,
				},
				session_id=cdp_session.session_id,
			),
			timeout=timeout_s,
		)
		download_result = result.get('result', {}).get('value') or {}
		data = download_result.get('data') or []
		if not data:
			self.browser_session.logger.warning(f'[DownloadService] No data received when downloading from {url}')
			return None

		payload = bytes(data)
		await asyncio.to_thread(destination.write_bytes, payload)
		file_size = destination.stat().st_size
		resolved_content_type = content_type or mimetypes.guess_type(destination.name)[0]
		file_ext = destination.suffix.lower().lstrip('.') or None
		event = FileDownloadedEvent(
			url=url,
			path=str(destination),
			file_name=destination.name,
			file_size=file_size,
			file_type=file_ext,
			mime_type=resolved_content_type,
			auto_download=True,
		)
		await self.browser_session.on_FileDownloadedEvent(event)
		return {
			'url': url,
			'path': str(destination),
			'file_name': destination.name,
			'file_size': file_size,
			'file_type': file_ext,
			'mime_type': resolved_content_type,
		}


class DialogService(BrowserService):
	"""Dialog state captured by popup handling."""

	async def register_handlers(self, target_id: TargetID) -> None:
		if target_id in self.browser_session._dialog_listeners_registered:
			self.logger.debug(f'Already registered dialog handlers for target {target_id}')
			return

		self.logger.debug(f'📌 Starting dialog handler setup for target {target_id}')
		try:
			cdp_session = await self.browser_session.get_or_create_cdp_session(target_id, focus=False)

			try:
				await cdp_session.cdp_client.send.Page.enable(session_id=cdp_session.session_id)
				self.logger.debug(f'✅ Enabled Page domain for session {cdp_session.session_id[-8:]}')
			except Exception as exc:
				self.logger.debug(f'Failed to enable Page domain: {exc}')

			if self.browser_session._cdp_client_root:
				self.logger.debug('📌 Also registering handler on root CDP client')
				try:
					await self.browser_session._cdp_client_root.send.Page.enable()
					self.logger.debug('✅ Enabled Page domain on root CDP client')
				except Exception as exc:
					self.logger.debug(f'Failed to enable Page domain on root: {exc}')

			async def handle_dialog(event_data, session_id: str | None = None):
				try:
					dialog_type = event_data.get('type', 'alert')
					message = event_data.get('message', '')

					if message:
						formatted_message = f'[{dialog_type}] {message}'
						self.browser_session._closed_popup_messages.append(formatted_message)
						self.logger.debug(f'📝 Stored popup message: {formatted_message[:100]}')

					should_accept = dialog_type in ('alert', 'confirm', 'beforeunload')
					action_str = 'accepting (OK)' if should_accept else 'dismissing (Cancel)'
					self.logger.info(f"🔔 JavaScript {dialog_type} dialog: '{message[:100]}' - {action_str}...")

					dismissed = False
					if self.browser_session._cdp_client_root and session_id:
						try:
							self.logger.debug(f'🔄 Approach 1: Using detecting session {session_id[-8:]}')
							await asyncio.wait_for(
								self.browser_session._cdp_client_root.send.Page.handleJavaScriptDialog(
									params={'accept': should_accept},
									session_id=session_id,
								),
								timeout=0.5,
							)
							dismissed = True
							self.logger.info('✅ Dialog handled successfully via detecting session')
						except (TimeoutError, Exception) as exc:
							self.logger.debug(f'Approach 1 failed: {type(exc).__name__}')

					if not dismissed and self.browser_session._cdp_client_root and self.browser_session.agent_focus_target_id:
						try:
							focused_session = await self.browser_session.get_or_create_cdp_session(
								self.browser_session.agent_focus_target_id,
								focus=False,
							)
							self.logger.debug(f'🔄 Approach 2: Using agent focus session {focused_session.session_id[-8:]}')
							await asyncio.wait_for(
								self.browser_session._cdp_client_root.send.Page.handleJavaScriptDialog(
									params={'accept': should_accept},
									session_id=focused_session.session_id,
								),
								timeout=0.5,
							)
							self.logger.info('✅ Dialog handled successfully via agent focus session')
						except (TimeoutError, Exception) as exc:
							self.logger.debug(f'Approach 2 failed: {type(exc).__name__}')

				except Exception as exc:
					self.logger.error(f'❌ Critical error in dialog handler: {type(exc).__name__}: {exc}')

			cdp_session.cdp_client.register.Page.javascriptDialogOpening(handle_dialog)  # type: ignore[arg-type]
			self.logger.debug(
				f'Successfully registered Page.javascriptDialogOpening handler for session {cdp_session.session_id}'
			)

			if hasattr(self.browser_session._cdp_client_root, 'register'):
				try:
					self.browser_session._cdp_client_root.register.Page.javascriptDialogOpening(handle_dialog)  # type: ignore[arg-type]
					self.logger.debug('Successfully registered dialog handler on root CDP client for all frames')
				except Exception as root_error:
					self.logger.warning(f'Failed to register on root CDP client: {root_error}')

			self.browser_session._dialog_listeners_registered.add(target_id)
			self.logger.debug(f'Set up JavaScript dialog handling for tab {target_id}')

		except Exception as exc:
			self.logger.warning(f'Failed to set up popup handling for tab {target_id}: {exc}')

	def closed_messages(self) -> list[str]:
		return list(self.browser_session._closed_popup_messages)

	def clear_closed_messages(self) -> None:
		self.browser_session._closed_popup_messages.clear()


class NetworkService(BrowserService):
	"""Network configuration helpers."""

	async def set_extra_headers(self, headers: dict[str, str], *, target_id: TargetID | None = None) -> None:
		await self.browser_session.set_extra_headers(headers, target_id=target_id)


class StorageStateService(BrowserService):
	"""Storage state import/export helpers."""

	async def initialize(self) -> None:
		storage_state_watchdog = getattr(self.browser_session, '_storage_state_watchdog', None)
		if storage_state_watchdog is not None:
			await storage_state_watchdog.initialize_storage_state()

	async def save(self, path: str | None = None) -> None:
		storage_state_watchdog = getattr(self.browser_session, '_storage_state_watchdog', None)
		if storage_state_watchdog is not None:
			if path is None:
				await storage_state_watchdog.save_storage_state()
			else:
				await storage_state_watchdog.save_storage_state(path)

	async def load(self, path: str | None = None) -> None:
		storage_state_watchdog = getattr(self.browser_session, '_storage_state_watchdog', None)
		if storage_state_watchdog is not None:
			if path is None:
				await storage_state_watchdog.load_storage_state()
			else:
				await storage_state_watchdog.load_storage_state(path)

	async def stop_monitoring(self) -> None:
		storage_state_watchdog = getattr(self.browser_session, '_storage_state_watchdog', None)
		if storage_state_watchdog is not None:
			await storage_state_watchdog.stop_monitoring()

	async def export(self, output_path: str | None = None) -> dict[str, Any]:
		return await self.browser_session.export_storage_state(output_path=output_path)


class LifecycleService(BrowserService):
	"""Browser lifecycle operations."""

	async def initialize_connected_services(self) -> None:
		await DownloadService(browser_session=self.browser_session).prepare_directory()
		await StorageStateService(browser_session=self.browser_session).initialize()

		permissions_watchdog = getattr(self.browser_session, '_permissions_watchdog', None)
		if permissions_watchdog is not None:
			await permissions_watchdog.grant_permissions()

		recording_watchdog = getattr(self.browser_session, '_recording_watchdog', None)
		if recording_watchdog is not None:
			await recording_watchdog.start_configured_recording()

		har_recording_watchdog = getattr(self.browser_session, '_har_recording_watchdog', None)
		if har_recording_watchdog is not None:
			await har_recording_watchdog.start_configured_recording()

		captcha_watchdog = getattr(self.browser_session, '_captcha_watchdog', None)
		if captcha_watchdog is not None:
			await captcha_watchdog.register_cdp_handlers()

	async def initialize_target_services(self, target_id: TargetID, url: str = '') -> None:
		await self.browser_session._apply_viewport_to_target(target_id)

		security_watchdog = getattr(self.browser_session, '_security_watchdog', None)
		if security_watchdog is not None:
			target_allowed = await security_watchdog.validate_new_tab(url, target_id)
			if not target_allowed:
				return

		aboutblank_watchdog = getattr(self.browser_session, '_aboutblank_watchdog', None)
		if aboutblank_watchdog is not None:
			await aboutblank_watchdog.handle_tab_created(target_id=target_id, url=url)

		await DownloadService(browser_session=self.browser_session).attach_to_target(target_id)
		await DialogService(browser_session=self.browser_session).register_handlers(target_id)

		crash_watchdog = getattr(self.browser_session, '_crash_watchdog', None)
		if crash_watchdog is not None:
			await crash_watchdog.attach_to_target(target_id)

	async def finalize_before_stop(self) -> None:
		aboutblank_watchdog = getattr(self.browser_session, '_aboutblank_watchdog', None)
		if aboutblank_watchdog is not None:
			aboutblank_watchdog.mark_stopping()

		await DownloadService(browser_session=self.browser_session).cleanup()
		await StorageStateService(browser_session=self.browser_session).stop_monitoring()

		recording_watchdog = getattr(self.browser_session, '_recording_watchdog', None)
		if recording_watchdog is not None:
			await recording_watchdog.stop_recording()

		har_recording_watchdog = getattr(self.browser_session, '_har_recording_watchdog', None)
		if har_recording_watchdog is not None:
			await har_recording_watchdog.save_har()

		captcha_watchdog = getattr(self.browser_session, '_captcha_watchdog', None)
		if captcha_watchdog is not None:
			captcha_watchdog.reset_state()

	async def start(self) -> None:
		await self.browser_session.start()

	async def stop(self) -> None:
		await self.browser_session.stop()

	async def kill(self) -> None:
		await self.browser_session.kill()


class ActionService(BaseModel):
	"""Grouped browser action services."""

	model_config = ConfigDict(arbitrary_types_allowed=True)

	click: ClickService
	type: TypeService
	scroll: ScrollService
	keyboard: KeyboardService
	upload: UploadService
	dropdown: DropdownService
	navigation: NavigationService
	tabs: TabService

	@classmethod
	def from_session(cls, browser_session: BrowserSession) -> ActionService:
		return cls(
			click=ClickService(browser_session=browser_session),
			type=TypeService(browser_session=browser_session),
			scroll=ScrollService(browser_session=browser_session),
			keyboard=KeyboardService(browser_session=browser_session),
			upload=UploadService(browser_session=browser_session),
			dropdown=DropdownService(browser_session=browser_session),
			navigation=NavigationService(browser_session=browser_session),
			tabs=TabService(browser_session=browser_session),
		)


class BrowserServiceBundle(BaseModel):
	"""Explicit service bundle for browser runtime operations."""

	model_config = ConfigDict(arbitrary_types_allowed=True)

	state: BrowserStateService
	readiness: PageReadinessService
	actions: ActionService
	navigation: NavigationService
	tabs: TabService
	downloads: DownloadService
	dialogs: DialogService
	network: NetworkService
	storage: StorageStateService
	lifecycle: LifecycleService

	@classmethod
	def from_session(cls, browser_session: BrowserSession) -> BrowserServiceBundle:
		navigation = NavigationService(browser_session=browser_session)
		tabs = TabService(browser_session=browser_session)
		return cls(
			state=BrowserStateService(browser_session=browser_session),
			readiness=PageReadinessService(browser_session=browser_session),
			actions=ActionService.from_session(browser_session),
			navigation=navigation,
			tabs=tabs,
			downloads=DownloadService(browser_session=browser_session),
			dialogs=DialogService(browser_session=browser_session),
			network=NetworkService(browser_session=browser_session),
			storage=StorageStateService(browser_session=browser_session),
			lifecycle=LifecycleService(browser_session=browser_session),
		)
