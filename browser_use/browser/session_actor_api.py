"""BrowserSession actor-style page and storage helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cdp_use import CDPClient
from cdp_use.cdp.network import Cookie

if TYPE_CHECKING:
	from browser_use.actor.page import Page
	from browser_use.browser.session import Target


class BrowserSessionActorAPIMixin:
	"""Actor-style page APIs exposed by BrowserSession."""

	@property
	def cdp_client(self: Any) -> CDPClient:
		"""Get the cached root CDP client."""
		assert self._cdp_client_root is not None, 'CDP client not initialized - browser may not be connected yet'
		return self._cdp_client_root

	async def new_page(self: Any, url: str | None = None) -> Page:
		"""Create a new page (tab)."""
		from cdp_use.cdp.target.commands import CreateTargetParameters

		params: CreateTargetParameters = {'url': url or 'about:blank'}
		result = await self.cdp_client.send.Target.createTarget(params)

		from browser_use.actor.page import Page as Target

		return Target(self, result['targetId'])

	async def get_current_page(self: Any) -> Page | None:
		"""Get the current page as an actor Page."""
		target_info = await self.get_current_target_info()

		if not target_info:
			return None

		from browser_use.actor.page import Page as Target

		return Target(self, target_info['targetId'])

	async def must_get_current_page(self: Any) -> Page:
		"""Get the current page as an actor Page."""
		page = await self.get_current_page()
		if not page:
			raise RuntimeError('No current target found')

		return page

	async def get_pages(self: Any) -> list[Page]:
		"""Get all available pages using SessionManager."""
		from browser_use.actor.page import Page as PageActor

		page_targets = self.session_manager.get_all_page_targets() if self.session_manager else []

		return [PageActor(self, target.target_id) for target in page_targets]

	def get_focused_target(self: Any) -> Target | None:
		"""Get the target that currently has agent focus."""
		if not self.session_manager:
			return None
		return self.session_manager.get_focused_target()

	def get_page_targets(self: Any) -> list[Target]:
		"""Get all page/tab targets."""
		if not self.session_manager:
			return []
		return self.session_manager.get_all_page_targets()

	async def close_page(self: Any, page: Page | str) -> None:
		"""Close a page by Page object or target ID."""
		from cdp_use.cdp.target.commands import CloseTargetParameters

		from browser_use.actor.page import Page as Target

		if isinstance(page, Target):
			target_id = page._target_id
		else:
			target_id = str(page)

		params: CloseTargetParameters = {'targetId': target_id}
		await self.cdp_client.send.Target.closeTarget(params)

	async def cookies(self: Any) -> list[Cookie]:
		"""Get cookies."""
		result = await self.cdp_client.send.Storage.getCookies()
		return result['cookies']

	async def clear_cookies(self: Any) -> None:
		"""Clear all cookies."""
		await self.cdp_client.send.Network.clearBrowserCookies()

	async def export_storage_state(self: Any, output_path: str | Path | None = None) -> dict[str, Any]:
		"""Export all browser cookies and storage to storage_state format."""
		cookies = await self._cdp_get_cookies()

		storage_state = {
			'cookies': [
				{
					'name': c['name'],
					'value': c['value'],
					'domain': c['domain'],
					'path': c['path'],
					'expires': c.get('expires', -1),
					'httpOnly': c.get('httpOnly', False),
					'secure': c.get('secure', False),
					'sameSite': c.get('sameSite', 'Lax'),
				}
				for c in cookies
			],
			'origins': [],
		}

		if output_path:
			output_file = Path(output_path).expanduser().resolve()
			output_file.parent.mkdir(parents=True, exist_ok=True)
			output_file.write_text(json.dumps(storage_state, indent=2, ensure_ascii=False), encoding='utf-8')
			self.logger.info(f'Exported {len(cookies)} cookies to {output_file}')

		return storage_state
