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


class NavigationService(BrowserService):
	"""Page navigation operations."""

	async def navigate(self, url: str, *, new_tab: bool = False, verify_not_empty: bool = True) -> None:
		self._ensure_url_allowed(url)
		target_id = await self._target_for_navigation(new_tab=new_tab)
		await self.browser_session._navigate_and_wait(url, target_id)
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
		await self.browser_session.get_or_create_cdp_session(target_id=target_id, focus=True)
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
		await self.browser_session._navigate_and_wait(url, target_id)
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
		await self.browser_session._cdp_close_page(target_id)


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

	async def export(self, output_path: str | None = None) -> dict[str, Any]:
		return await self.browser_session.export_storage_state(output_path=output_path)


class LifecycleService(BrowserService):
	"""Browser lifecycle operations."""

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
			actions=ActionService.from_session(browser_session),
			navigation=navigation,
			tabs=tabs,
			downloads=DownloadService(browser_session=browser_session),
			dialogs=DialogService(browser_session=browser_session),
			network=NetworkService(browser_session=browser_session),
			storage=StorageStateService(browser_session=browser_session),
			lifecycle=LifecycleService(browser_session=browser_session),
		)
