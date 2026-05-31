"""Raw CDP helper methods for BrowserSession."""

from __future__ import annotations

import asyncio
from typing import Any

from cdp_use.cdp.network import Cookie
from cdp_use.cdp.target import TargetID
from cdp_use.cdp.target.commands import CreateTargetParameters

from browser_use.dom.views import TargetInfo
from browser_use.utils import is_new_tab_page


class BrowserSessionCDPMixin:
	"""Private CDP operations used by BrowserSession and compatibility APIs."""

	async def _cdp_get_all_pages(
		self: Any,
		include_http: bool = True,
		include_about: bool = True,
		include_pages: bool = True,
		include_iframes: bool = False,
		include_workers: bool = False,
		include_chrome: bool = False,
		include_chrome_extensions: bool = False,
		include_chrome_error: bool = False,
	) -> list[TargetInfo]:
		"""Get all browser pages/tabs using SessionManager as the source of truth."""
		if not self.session_manager:
			return []

		result = []
		for target in self.session_manager.get_all_targets().values():
			target_info: TargetInfo = {
				'targetId': target.target_id,
				'type': target.target_type,
				'title': target.title,
				'url': target.url,
				'attached': True,
				'canAccessOpener': False,
			}

			if self._is_valid_target(
				target_info,
				include_http=include_http,
				include_about=include_about,
				include_pages=include_pages,
				include_iframes=include_iframes,
				include_workers=include_workers,
				include_chrome=include_chrome,
				include_chrome_extensions=include_chrome_extensions,
				include_chrome_error=include_chrome_error,
			):
				result.append(target_info)

		return result

	async def _cdp_create_new_page(
		self: Any, url: str = 'about:blank', background: bool = False, new_window: bool = False
	) -> str:
		"""Create a new page/tab using CDP Target.createTarget."""
		params = CreateTargetParameters(url=url, background=background)
		if new_window:
			params['newWindow'] = True

		if self._cdp_client_root:
			result = await self._cdp_client_root.send.Target.createTarget(params=params)
		else:
			result = await self.cdp_client.send.Target.createTarget(params=params)
		return result['targetId']

	async def _cdp_close_page(self: Any, target_id: TargetID) -> None:
		"""Close a page/tab using CDP Target.closeTarget."""
		await self.cdp_client.send.Target.closeTarget(params={'targetId': target_id})

	async def _cdp_get_cookies(self: Any) -> list[Cookie]:
		"""Get cookies using CDP Storage.getCookies."""
		cdp_session = await self.get_or_create_cdp_session(target_id=None)
		result = await asyncio.wait_for(
			cdp_session.cdp_client.send.Storage.getCookies(session_id=cdp_session.session_id), timeout=8.0
		)
		return result.get('cookies', [])

	async def _cdp_set_cookies(self: Any, cookies: list[Cookie]) -> None:
		"""Set cookies using CDP Storage.setCookies."""
		if not self.agent_focus_target_id or not cookies:
			return

		cdp_session = await self.get_or_create_cdp_session(target_id=None)
		await cdp_session.cdp_client.send.Storage.setCookies(
			params={'cookies': cookies},  # type: ignore[arg-type]
			session_id=cdp_session.session_id,
		)

	async def _cdp_clear_cookies(self: Any) -> None:
		"""Clear all cookies using CDP Storage.clearCookies."""
		cdp_session = await self.get_or_create_cdp_session()
		await cdp_session.cdp_client.send.Storage.clearCookies(session_id=cdp_session.session_id)

	async def _cdp_grant_permissions(self: Any, permissions: list[str], origin: str | None = None) -> None:
		"""Grant permissions using CDP Browser.grantPermissions."""
		params = {'permissions': permissions}
		# if origin:
		# 	params['origin'] = origin
		cdp_session = await self.get_or_create_cdp_session()
		# await cdp_session.cdp_client.send.Browser.grantPermissions(params=params, session_id=cdp_session.session_id)
		raise NotImplementedError('Not implemented yet')

	async def _cdp_set_geolocation(self: Any, latitude: float, longitude: float, accuracy: float = 100) -> None:
		"""Set geolocation using CDP Emulation.setGeolocationOverride."""
		await self.cdp_client.send.Emulation.setGeolocationOverride(
			params={'latitude': latitude, 'longitude': longitude, 'accuracy': accuracy}
		)

	async def _cdp_clear_geolocation(self: Any) -> None:
		"""Clear geolocation override using CDP."""
		await self.cdp_client.send.Emulation.clearGeolocationOverride()

	async def _cdp_add_init_script(self: Any, script: str) -> str:
		"""Add script to evaluate on new document using CDP."""
		assert self._cdp_client_root is not None
		cdp_session = await self.get_or_create_cdp_session()

		result = await cdp_session.cdp_client.send.Page.addScriptToEvaluateOnNewDocument(
			params={'source': script, 'runImmediately': True}, session_id=cdp_session.session_id
		)
		return result['identifier']

	async def _cdp_remove_init_script(self: Any, identifier: str) -> None:
		"""Remove script added with addScriptToEvaluateOnNewDocument."""
		cdp_session = await self.get_or_create_cdp_session(target_id=None)
		await cdp_session.cdp_client.send.Page.removeScriptToEvaluateOnNewDocument(
			params={'identifier': identifier}, session_id=cdp_session.session_id
		)

	async def _cdp_set_viewport(
		self: Any,
		width: int,
		height: int,
		device_scale_factor: float = 1.0,
		mobile: bool = False,
		target_id: str | None = None,
	) -> None:
		"""Set viewport using CDP Emulation.setDeviceMetricsOverride."""
		if target_id:
			cdp_session = await self.get_or_create_cdp_session(target_id, focus=False)
		elif self.agent_focus_target_id:
			try:
				cdp_session = await self.get_or_create_cdp_session(self.agent_focus_target_id, focus=False)
			except ValueError:
				self.logger.warning('Cannot set viewport: focused target has no sessions')
				return
		else:
			self.logger.warning('Cannot set viewport: no target_id provided and agent_focus not initialized')
			return

		await cdp_session.cdp_client.send.Emulation.setDeviceMetricsOverride(
			params={'width': width, 'height': height, 'deviceScaleFactor': device_scale_factor, 'mobile': mobile},
			session_id=cdp_session.session_id,
		)

	async def _cdp_get_origins(self: Any) -> list[dict[str, Any]]:
		"""Get origins with localStorage and sessionStorage using CDP."""
		origins = []
		cdp_session = await self.get_or_create_cdp_session(target_id=None)

		try:
			await cdp_session.cdp_client.send.DOMStorage.enable(session_id=cdp_session.session_id)

			try:
				frames_result = await cdp_session.cdp_client.send.Page.getFrameTree(session_id=cdp_session.session_id)
				unique_origins = set()

				def _extract_origins(frame_tree: dict[str, Any]) -> None:
					frame = frame_tree.get('frame', {})
					origin = frame.get('securityOrigin')
					if origin and origin != 'null':
						unique_origins.add(origin)

					for child in frame_tree.get('childFrames', []):
						_extract_origins(child)

				async def _get_storage_items(origin: str, is_local_storage: bool) -> list[dict[str, str]] | None:
					storage_type = 'localStorage' if is_local_storage else 'sessionStorage'
					try:
						result = await cdp_session.cdp_client.send.DOMStorage.getDOMStorageItems(
							params={'storageId': {'securityOrigin': origin, 'isLocalStorage': is_local_storage}},
							session_id=cdp_session.session_id,
						)

						items = []
						for item in result.get('entries', []):
							if len(item) == 2:
								items.append({'name': item[0], 'value': item[1]})

						return items if items else None
					except Exception as e:
						self.logger.debug(f'Failed to get {storage_type} for {origin}: {e}')
						return None

				_extract_origins(frames_result.get('frameTree', {}))

				for origin in unique_origins:
					origin_data = {'origin': origin}

					local_storage = await _get_storage_items(origin, is_local_storage=True)
					if local_storage:
						origin_data['localStorage'] = local_storage

					session_storage = await _get_storage_items(origin, is_local_storage=False)
					if session_storage:
						origin_data['sessionStorage'] = session_storage

					if 'localStorage' in origin_data or 'sessionStorage' in origin_data:
						origins.append(origin_data)

			finally:
				await cdp_session.cdp_client.send.DOMStorage.disable(session_id=cdp_session.session_id)

		except Exception as e:
			self.logger.warning(f'Failed to get origins: {e}')

		return origins

	async def _cdp_get_storage_state(self: Any) -> dict[str, Any]:
		"""Get storage state using CDP."""
		return {
			'cookies': await self._cdp_get_cookies(),
			'origins': await self._cdp_get_origins(),
		}

	async def _cdp_navigate(self: Any, url: str, target_id: TargetID | None = None) -> None:
		"""Navigate to URL using CDP Page.navigate."""
		assert self._cdp_client_root is not None, 'CDP client not initialized - browser may not be connected yet'
		assert self.agent_focus_target_id is not None, 'Agent focus not initialized - browser may not be connected yet'

		target_id_to_use = target_id or self.agent_focus_target_id
		cdp_session = await self.get_or_create_cdp_session(target_id_to_use, focus=True)

		await cdp_session.cdp_client.send.Page.navigate(params={'url': url}, session_id=cdp_session.session_id)

	@staticmethod
	def _is_valid_target(
		target_info: TargetInfo,
		include_http: bool = True,
		include_chrome: bool = False,
		include_chrome_extensions: bool = False,
		include_chrome_error: bool = False,
		include_about: bool = True,
		include_iframes: bool = True,
		include_pages: bool = True,
		include_workers: bool = False,
	) -> bool:
		"""Check if a target should be processed."""
		target_type = target_info.get('type', '')
		url = target_info.get('url', '')

		url_allowed, type_allowed = False, False

		if is_new_tab_page(url):
			url_allowed = True

		if url.startswith('chrome-error://') and include_chrome_error:
			url_allowed = True

		if url.startswith('chrome://') and include_chrome:
			url_allowed = True

		if url.startswith('chrome-extension://') and include_chrome_extensions:
			url_allowed = True

		if url == 'about:blank' and include_about:
			url_allowed = True

		if (url.startswith('http://') or url.startswith('https://')) and include_http:
			url_allowed = True

		if target_type in ('service_worker', 'shared_worker', 'worker') and include_workers:
			type_allowed = True

		if target_type in ('page', 'tab') and include_pages:
			type_allowed = True

		if target_type in ('iframe', 'webview') and include_iframes:
			type_allowed = True
			if not url:
				url_allowed = True

		return url_allowed and type_allowed
